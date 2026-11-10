import { memo, useMemo, useState } from "react";
import { Search, Crosshair, Waves, Droplets, TriangleAlert, LayoutGrid } from "lucide-react";
import type { ScannerFilter, Stock } from "../types";
import { hasCvdAlert } from "../utils";

const FILTERS: { key: ScannerFilter; label: string; icon: typeof Crosshair }[] = [
  { key: "ALL", label: "Все", icon: LayoutGrid },
  { key: "SNIPER", label: "Снайпер", icon: Crosshair },
  { key: "WHALE", label: "Крупняк", icon: Waves },
  { key: "CVD", label: "CVD", icon: Droplets },
  { key: "DIV", label: "Диверг.", icon: TriangleAlert },
];

const sideOf = (s: Stock) => (s.verdict === "SHORT" || s.verdict === "LONG" ? s.verdict : s.calc_side) as "LONG" | "SHORT";

export function matchesFilter(s: Stock, f: ScannerFilter) {
  if (f === "SNIPER") return s.verdict === "LONG" || s.verdict === "SHORT";
  if (f === "WHALE") return (s.whale_kinds?.length ?? 0) > 0 || (s.robots?.length ?? 0) > 0;
  if (f === "CVD") return hasCvdAlert(s);
  if (f === "DIV")
    return Boolean(s.short_proposal || s.cvd_data?.pivot_bearish_div || s.cvd_data?.pivot_bullish_div);
  return true;
}

interface RowProps {
  s: Stock;
  active: boolean;
  onSelect: (t: string) => void;
}

const StockRow = memo(function StockRow({ s, active, onSelect }: RowProps) {
  const isLong = s.verdict === "LONG";
  const isShort = s.verdict === "SHORT";
  const hasSig = isLong || isShort;
  const side = sideOf(s);
  const up = (s.change ?? 0) >= 0;
  const scoreAbs = Math.abs(s.score ?? 0);
  const whales = (s.whale_kinds?.length ?? 0) + (s.robots?.length ?? 0);

  return (
    <button
      onClick={() => onSelect(s.ticker)}
      className={`group w-full rounded-lg border px-3 py-2.5 text-left transition-colors duration-200 ${
        active
          ? "border-neon/45 bg-neon/[0.07]"
          : hasSig
            ? isLong
              ? "border-bull/25 bg-bull/[0.045] hover:border-bull/45"
              : "border-bear/25 bg-bear/[0.045] hover:border-bear/45"
            : "border-transparent hover:border-line-2 hover:bg-white/[0.03]"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="font-mono text-[12px] font-700 text-white">{s.ticker}</span>
          <span className="truncate text-[10.5px] text-smoke">{s.name}</span>
          {whales > 0 && <Waves size={11} className="shrink-0 text-gold" />}
          {s.short_proposal ? <TriangleAlert size={11} className="shrink-0 text-bear" /> : null}
        </div>
        <span
          className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[9px] font-700 tracking-wider ${
            hasSig
              ? isLong
                ? "bg-bull/15 text-bull"
                : "bg-bear/15 text-bear"
              : "bg-white/[0.05] text-smoke"
          }`}
        >
          {hasSig ? s.verdict : "WAIT"}
        </span>
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2">
        <div className="flex items-baseline gap-2 font-mono">
          <span className="text-[12px] font-600 text-white">{(s.price ?? 0).toLocaleString("ru-RU")}</span>
          <span className={`text-[10px] ${up ? "text-bull" : "text-bear"}`}>
            {up ? "+" : ""}
            {(s.change ?? 0).toFixed(2)}%
          </span>
        </div>
        {/* score bars */}
        <div className="flex items-center gap-[3px]">
          {Array.from({ length: 10 }).map((_, i) => (
            <span
              key={i}
              className={`h-[5px] w-[7px] rounded-[2px] ${
                i < scoreAbs ? (side === "LONG" ? "bg-bull" : "bg-bear") : "bg-white/[0.08]"
              }`}
            />
          ))}
          <span className={`ml-1 font-mono text-[10px] font-700 ${hasSig ? (isLong ? "text-bull" : "text-bear") : "text-smoke"}`}>
            {scoreAbs}
          </span>
        </div>
      </div>

      {(s.entry ?? 0) > 0 && (
        <div className="mt-1 flex items-center gap-3 font-mono text-[9.5px] text-smoke">
          <span>
            вх <span className="text-fog">{Number(s.entry).toFixed(2)}</span>
          </span>
          <span>
            tp <span className="text-bull">{Number(s.tp).toFixed(2)}</span>
          </span>
          <span>
            sl <span className="text-bear">{Number(s.sl).toFixed(2)}</span>
          </span>
          {typeof s.last_activity_age_min_now === "number" && s.last_activity_age_min_now < 9000 && (
            <span className="ml-auto text-smoke/70">{s.last_activity_age_min_now.toFixed(0)}м назад</span>
          )}
        </div>
      )}
    </button>
  );
});

interface Props {
  stocks: Stock[];
  activeTicker: string | null;
  onSelect: (t: string) => void;
  loading?: boolean;
}

export default function Scanner({ stocks, activeTicker, onSelect, loading }: Props) {
  const [filter, setFilter] = useState<ScannerFilter>("ALL");
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    const query = q.trim().toUpperCase();
    return stocks.filter((s) => {
      if (query && !s.ticker.toUpperCase().includes(query) && !(s.name || "").toUpperCase().includes(query))
        return false;
      return matchesFilter(s, filter);
    });
  }, [stocks, filter, q]);

  const counts = useMemo(() => {
    const c: Record<ScannerFilter, number> = { ALL: stocks.length, SNIPER: 0, WHALE: 0, CVD: 0, DIV: 0 };
    for (const s of stocks) {
      for (const f of FILTERS) {
        if (f.key !== "ALL" && matchesFilter(s, f.key)) c[f.key]++;
      }
    }
    return c;
  }, [stocks]);

  return (
    <div className="glass flex h-full flex-col overflow-hidden rounded-xl">
      <div className="border-b border-line px-3 pb-0 pt-3">
        <div className="relative mb-2.5">
          <Search size={12} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-smoke" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск: SBER, Газпром…"
            className="w-full rounded-lg border border-line bg-abyss/70 py-2 pl-8 pr-3 font-mono text-[11px] text-white outline-none transition-colors placeholder:text-smoke/60 focus:border-neon/40"
          />
        </div>
        <div className="flex gap-0.5 overflow-x-auto pb-0">
          {FILTERS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`flex shrink-0 items-center gap-1.5 rounded-t-lg border-b-2 px-2.5 py-1.5 font-mono text-[9.5px] uppercase tracking-wider transition-colors ${
                filter === key
                  ? "border-bull bg-bull/[0.08] text-bull"
                  : "border-transparent text-smoke hover:text-fog"
              }`}
            >
              <Icon size={11} />
              {label}
              <span className="rounded bg-white/[0.06] px-1 text-[8.5px]">{counts[key]}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex min-h-[240px] flex-1 flex-col gap-1.5 overflow-y-auto p-2.5">
        {filtered.map((s) => (
          <StockRow key={s.ticker} s={s} active={activeTicker === s.ticker} onSelect={onSelect} />
        ))}
        {!filtered.length && (
          <div className="flex flex-1 items-center justify-center py-10 font-mono text-[10px] text-smoke">
            {loading ? "загрузка сканера…" : "ничего не найдено по фильтру"}
          </div>
        )}
      </div>
    </div>
  );
}
