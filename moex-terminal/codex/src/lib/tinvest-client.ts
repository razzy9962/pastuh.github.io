import "server-only";
import { Agent, request } from "node:https";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { rootCertificates } from "node:tls";
import { X509Certificate } from "node:crypto";

// Official public Russian Trusted Root CA, downloaded over verified HTTPS from:
// https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
// This CA is scoped to T-Invest requests; global TLS verification is unchanged.
const EXPECTED_CA_FINGERPRINT = "D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31";
let agent: Agent | undefined;
function getAgent() {
  if (agent) return agent;
  const ca = readFileSync(join(process.cwd(), "certs", "russian-trusted-root-ca.pem"), "utf8");
  if (new X509Certificate(ca).fingerprint256 !== EXPECTED_CA_FINGERPRINT) throw new Error("Unexpected T-Invest CA certificate");
  agent = new Agent({ keepAlive: true, maxSockets: 6, ca: [...rootCertificates, ca], rejectUnauthorized: true });
  return agent;
}

// Каталог акций Т-Инвест весит около 3 МБ: на медленном канале общий таймаут в 8 секунд
// обрывал загрузку, и все котировки молча уходили в демо-режим. Теперь таймаут
// считается от активности: пока данные идут, соединение не разрывается.
const IDLE_TIMEOUT_MS = 12000;
const TOTAL_TIMEOUT_MS = 25000;
function send<T>(service: string, method: string, body: unknown, token: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const controller = new AbortController();
    let idle = setTimeout(() => controller.abort(), IDLE_TIMEOUT_MS);
    const hard = setTimeout(() => controller.abort(), TOTAL_TIMEOUT_MS);
    const finish = () => { clearTimeout(idle); clearTimeout(hard); };
    const touch = () => { clearTimeout(idle); idle = setTimeout(() => controller.abort(), IDLE_TIMEOUT_MS); };
    const req = request(`https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1.${service}/${method}`, {
      method: "POST", agent: getAgent(), signal: controller.signal,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload), "x-app-name": "moex.terminal" },
    }, response => {
      if (response.statusCode !== 200) { finish(); response.resume(); reject(new Error(`Market provider status ${response.statusCode}`)); return; }
      response.setEncoding("utf8");
      const chunks: string[] = [];
      let bytes = 0;
      response.on("data", (chunk: string) => {
        touch();
        bytes += Buffer.byteLength(chunk);
        if (bytes > 16 * 1024 * 1024) { req.destroy(new Error("Market response too large")); return; }
        chunks.push(chunk);
      });
      response.on("end", () => { finish(); try { resolve(JSON.parse(chunks.join("")) as T); } catch { reject(new Error("Invalid market response")); } });
      response.on("error", () => { finish(); reject(new Error("Market response interrupted")); });
    });
    req.on("error", error => {
      // Код ошибки (ECONNRESET, ETIMEDOUT, сертификат и т. п.) нужен в логах Render.
      finish();
      const code = (error as NodeJS.ErrnoException).code ?? (error as Error).message;
      reject(new Error(`Secure T-Invest connection unavailable (${code})`));
    });
    req.end(payload);
  });
}

const RETRYABLE = /status (404|408|425|429|5\d\d)/;
const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Запрос к Т-Инвест. Шлюз провайдера иногда отвечает 404 на одиночные запросы,
 * поэтому такие ответы (а также 429/5xx) повторяются — данные от этого не меняются.
 */
export async function tInvestRequest<T>(service: string, method: string, body: unknown, token: string, attempts = 3): Promise<T> {
  let lastError: Error = new Error("Market provider unavailable");
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await send<T>(service, method, body, token);
    } catch (error) {
      lastError = error instanceof Error ? error : lastError;
      if (!RETRYABLE.test(lastError.message) || attempt === attempts - 1) throw lastError;
      await pause(220 * (attempt + 1));
    }
  }
  throw lastError;
}
