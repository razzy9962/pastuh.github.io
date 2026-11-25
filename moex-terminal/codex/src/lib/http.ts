import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";

/**
 * JSON-ответ с gzip, ETag и 304 — экономит исходящий трафик Render
 * (на бесплатном тарифе он общий на все сервисы рабочего пространства).
 * Next.js сжимает HTML, но потоковые JSON-ответы API уходят несжатыми,
 * поэтому сжатие делаем здесь.
 */
export function jsonWithCache(request: Request, data: unknown, ttlSeconds: number): Response {
  const body = JSON.stringify(data);
  const etag = `W/"${createHash("sha1").update(body).digest("base64url")}"`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": `public, max-age=${ttlSeconds}, stale-while-revalidate=${ttlSeconds * 2}`,
    ETag: etag,
    Vary: "Accept-Encoding",
  };
  // Клиент уже имеет актуальную копию — отдаём пустой 304, экономя почти весь трафик.
  // 304 обязан нести те же заголовки кеширования, но без тела и Content-Encoding.
  const ifNoneMatch = request.headers.get("if-none-match");
  if (ifNoneMatch && ifNoneMatch.split(",").some(tag => tag.trim().replace(/^W\//, "") === etag.replace(/^W\//, ""))) return new Response(null, { status: 304, headers });
  const acceptsGzip = /\bgzip\b/i.test(request.headers.get("accept-encoding") ?? "");
  if (acceptsGzip && body.length > 512) {
    headers["Content-Encoding"] = "gzip";
    return new Response(new Uint8Array(gzipSync(Buffer.from(body), { level: 6 })), { status: 200, headers });
  }
  return new Response(body, { status: 200, headers });
}
