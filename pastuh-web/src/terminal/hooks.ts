import { useCallback, useEffect, useRef, useState } from "react";
import { ApiAuthError, apiAnalyze, apiDashboard } from "./api";
import type { AnalyzeData, DashboardData } from "./types";

export interface Toast {
  id: number;
  text: string;
  kind: "ok" | "err" | "info";
}

let toastId = 0;

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = ++toastId;
    setToasts((t) => [...t.slice(-3), { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);
  return { toasts, push };
}

/** Дашборд: опрос каждые `intervalMs`, пауза когда вкладка скрыта. */
export function useDashboard(intervalMs = 15000) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [isDemo, setIsDemo] = useState(false);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(false);
  const [lastOk, setLastOk] = useState<number | null>(null);
  const busy = useRef(false);
  const gen = useRef(0);

  const load = useCallback(async (force = false) => {
    if (busy.current) return;
    busy.current = true;
    const g = ++gen.current;
    try {
      const res = await apiDashboard(force);
      if (g !== gen.current) return; // устаревший ответ
      setData(res.data);
      setIsDemo(res.isDemo);
      setAuthError(false);
      setLastOk(Date.now());
    } catch (e) {
      if (e instanceof ApiAuthError) setAuthError(true);
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(true);
    const id = setInterval(() => {
      if (!document.hidden) load(false);
    }, intervalMs);
    const onVis = () => {
      if (!document.hidden) load(false);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [load, intervalMs]);

  return { data, isDemo, loading, authError, lastOk, reload: load };
}

/** Анализ тикера: отмена предыдущего запроса при смене тикера/ТФ. */
export function useAnalysis(ticker: string | null, tf: string) {
  const [data, setData] = useState<AnalyzeData | null>(null);
  const [loading, setLoading] = useState(false);
  const gen = useRef(0);

  useEffect(() => {
    if (!ticker) {
      setData(null);
      return;
    }
    const g = ++gen.current;
    setLoading(true);
    apiAnalyze(ticker, tf)
      .then((res) => {
        if (gen.current === g) setData(res.data);
      })
      .catch(() => {})
      .finally(() => {
        if (gen.current === g) setLoading(false);
      });
  }, [ticker, tf]);

  return { data, loading };
}

/** Локальные часы, подстроенные под server_time. */
export function useClock(serverTime?: string) {
  const [now, setNow] = useState(() => new Date());
  const offset = useRef(0);

  useEffect(() => {
    if (!serverTime) return;
    const m = serverTime.match(/(\d{2}):(\d{2}):(\d{2})/);
    if (!m) return;
    const srv = new Date();
    srv.setHours(+m[1], +m[2], +m[3], 0);
    offset.current = srv.getTime() - Date.now();
  }, [serverTime]);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date(Date.now() + offset.current)), 1000);
    return () => clearInterval(id);
  }, []);

  return now.toLocaleTimeString("ru-RU");
}
