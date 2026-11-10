import type { Stock } from "./types";

/** Аналог hasCvdAlert из оригинального index.html: поглощение/давление в MTF-CVD. */
export function hasCvdAlert(s: Stock): boolean {
  const mtf = s.mtf_cvd || {};
  return Object.values(mtf).some((v) => Boolean(v?.absorption_side) || Boolean(v?.pressure_side));
}

export const fmtPrice = (v: number | undefined | null) =>
  v == null || !isFinite(v) ? "—" : v.toLocaleString("ru-RU", { maximumFractionDigits: 4 });

export const fmtRub = (v: number | undefined | null) =>
  v == null || !isFinite(v) ? "—" : `${Math.round(v).toLocaleString("ru-RU")} ₽`;

export const fmtPct = (v: number | undefined | null, signed = true) => {
  if (v == null || !isFinite(v)) return "—";
  const s = signed && v > 0 ? "+" : "";
  return `${s}${v.toFixed(2)}%`;
};

export const kvFmt = (v: number | undefined | null) => {
  if (v == null || !isFinite(v)) return "0";
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (a >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
};

/** Парсинг процентов из текстовой истории сделок, как в оригинале ("+1.84%"). */
export function historyToEquity(history: string[]): { points: number[]; wins: number; losses: number } {
  const pts: number[] = [];
  let eq = 100;
  let wins = 0;
  let losses = 0;
  const reg = /([+-]\d+[.,]?\d*)\s*%/;
  for (const raw of [...history].reverse()) {
    const m = raw.match(reg);
    if (!m) continue;
    const val = parseFloat(m[1].replace(",", "."));
    if (!isFinite(val)) continue;
    eq *= 1 + val / 100;
    pts.push(eq);
    if (val >= 0) wins++;
    else losses++;
  }
  return { points: pts, wins, losses };
}

export const parseNum = (v: string): number => {
  const n = parseFloat(v.replace(",", "."));
  return isFinite(n) ? n : 0;
};

export const verdictColor = (v: string | undefined) =>
  v === "LONG" ? "#00f076" : v === "SHORT" ? "#ff3358" : "#94a3b8";

export const stratLabel = (key?: string) =>
  key === "cvd_flow" ? "Поток CVD" : key === "divergence" ? "Дивергенция" : key === "news" ? "Новости" : key || "Ручная";
