// API-слой терминала — контракт как у оригинального index.html:
//   GET  /api/dashboard?token=..&force=1
//   GET  /api/analyze?ticker=..&tf=..&token=..
//   POST /api/action            (JSON, токен в теле + заголовок)
//   GET  /api/backtest?days=..&token=..
// Анти-лаг: единый AbortController на запрос, таймауты, отмена устаревших запросов.

import type { AnalyzeData, BacktestResult, DashboardData } from "./types";
import { demoAnalyze, demoDashboard } from "./demo";

const SECRET_KEY = "moex_web_secret";

export const getSecret = (): string => {
  try {
    return localStorage.getItem(SECRET_KEY) ?? "0000";
  } catch {
    return "0000";
  }
};

export const setSecret = (s: string) => {
  try {
    if (s) localStorage.setItem(SECRET_KEY, s);
    else localStorage.removeItem(SECRET_KEY);
  } catch {
    /* ignore */
  }
};

export interface ApiResult<T> {
  data: T;
  isDemo: boolean;
}

async function fetchJson<T>(url: string, opts: RequestInit = {}, timeoutMs = 12000): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      ...opts,
      signal: ctrl.signal,
      headers: { "X-Web-Secret": getSecret(), ...(opts.headers || {}) },
    });
    if (res.status === 401) throw new ApiAuthError();
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

export class ApiAuthError extends Error {
  constructor() {
    super("unauthorized");
    this.name = "ApiAuthError";
  }
}

export async function apiDashboard(force = false): Promise<ApiResult<DashboardData>> {
  const token = encodeURIComponent(getSecret());
  try {
    const data = await fetchJson<DashboardData>(
      `/api/dashboard?token=${token}${force ? "&force=1" : ""}`,
      {},
      15000
    );
    return { data, isDemo: false };
  } catch (e) {
    if (e instanceof ApiAuthError) throw e;
    return { data: demoDashboard(), isDemo: true };
  }
}

export async function apiAnalyze(ticker: string, tf: string): Promise<ApiResult<AnalyzeData>> {
  const token = encodeURIComponent(getSecret());
  try {
    const data = await fetchJson<AnalyzeData>(
      `/api/analyze?ticker=${encodeURIComponent(ticker)}&tf=${encodeURIComponent(tf)}&token=${token}`,
      {},
      15000
    );
    return { data, isDemo: false };
  } catch (e) {
    if (e instanceof ApiAuthError) throw e;
    return { data: demoAnalyze(ticker), isDemo: true };
  }
}

export async function apiAction(body: Record<string, unknown>): Promise<{ ok: boolean; message?: string; error?: string }> {
  const token = encodeURIComponent(getSecret());
  return fetchJson(`/api/action?token=${token}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, token: getSecret() }),
  });
}

export async function apiBacktest(days: number): Promise<BacktestResult> {
  const token = encodeURIComponent(getSecret());
  return fetchJson<BacktestResult>(`/api/backtest?days=${days}&token=${token}`, {}, 120000);
}
