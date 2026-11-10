import { memo, useMemo, useState } from "react";
import {
  Waves,
  Newspaper,
  CalendarDays,
  Trophy,
  Percent,
  Crosshair,
  Activity,
  ExternalLink,
  Layers3,
  ToggleLeft,
  ToggleRight,
  Loader2,
} from "lucide-react";
import type { DashboardData, Stock } from "../types";
import { apiAction } from "../api";
import { fmtPct, fmtRub, historyToEquity, kvFmt } from "../utils";

/* ---------------- ЛЕНТА КОТИРОВОК (по данным dashboard) ---------------- */

export const MarketTape = memo(function MarketTape({
  stocks,
  onSelect,
}: {
  stocks: Stock[];
  onSelect: (t: string) => void;
}) {
  const items = stocks.filter((s) => s.price > 0);
  if (!items.length) return null;
  const row = (k: string) => (
    <div key={k} className="flex shrink-0">
      {items.map((s) => {
        const up = (s.change ?? 0) >= 0;
        return (
          <button
            key={k + s.ticker}
            onClick={() => onSelect(s.ticker)}
            className="flex items-center gap-2 border-r border-line px-5 py-2 transition-colors hover:bg-white/[0.04]"
          >
            <span className="font-mono text-[10.5px] font-700 text-white">{s.ticker}</span>
            <span className="font-mono text-[10.5px] text-fog">{s.price.toLocaleString("ru-RU")}</span>
            <span className={`font-mono text-[9.5px] ${up ? "text-bull" : "text-bear"}`}>
              {up ? "+" : ""}
              {(s.change ?? 0).toFixed(2)}%
            </span>
          </button>
        );
      })}
    </div>
  );
  return (
    <div className="ticker-mask overflow-hidden border-b border-line bg-abyss/70">
      <div className="flex w-max animate-tape">
        {row("t1")}
        {row("t2")}
      </div>
    </div>
  );
});

/* ---------------- KPI ПОЛОСА ---------------- */

export const KpiStrip = memo(function KpiStrip({ data }: { data: DashboardData }) {
  const st = data.stats;
  const sniperCnt = data.stocks.filter((s) => s.verdict === "LONG" || s.verdict === "SHORT").length;
  const cvdCnt = data.stocks.filter((s) =>
    Object.values(s.mtf_cvd || {}).some((v) => v.absorption_side || v.pressure_side)
  ).length;
  const kpis = [
    { icon: Trophy, label: "винрейт", value: `${st.winrate}%`, sub: `${st.wins}В · ${st.losses}С`, color: "#00f076" },
    { icon: Percent, label: "чистый PnL", value: fmtPct(st.net_pct), sub: "compound", color: st.net_pct >= 0 ? "#00f076" : "#ff3358" },
    { icon: Crosshair, label: "сетапы снайпера", value: String(sniperCnt), sub: `порог ${data.min_score}/10`, color: "#38bdf8" },
    { icon: Activity, label: "cvd-алерты", value: String(cvdCnt), sub: `${data.active_count} в скане`, color: "#c084fc" },
    { icon: Waves, label: "крупняк 5мин", value: String(data.whales.length), sub: "принты · twap", color: "#fbbf24" },
  ];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
      {kpis.map((k) => (
        <div key={k.label} className="glass card-hover rounded-xl px-4 py-3">
          <div className="flex items-center gap-1.5">
            <k.icon size={11} style={{ color: k.color }} />
            <span className="font-mono text-[8.5px] uppercase tracking-[0.2em] text-smoke">{k.label}</span>
          </div>
          <div className="mt-1.5 font-mono text-[19px] font-800 leading-none" style={{ color: k.color }}>
            {k.value}
          </div>
          <div className="mt-1 font-mono text-[8.5px] text-smoke">{k.sub}</div>
        </div>
      ))}
    </div>
  );
});

/* ---------------- ЭКВИТИ ИЗ ИСТОРИИ ---------------- */

export const EquitySpark = memo(function EquitySpark({ history }: { history: string[] }) {
  const { points, wins, losses } = useMemo(() => historyToEquity(history || []), [history]);
  if (points.length < 2) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-[9.5px] text-smoke">
        эквити появится после закрытых сделок
      </div>
    );
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const W = 300;
  const H = 100;
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${(i / (points.length - 1)) * W},${H - 12 - ((p - min) / span) * (H - 26)}`)
    .join(" ");
  const last = points[points.length - 1];
  const totalRet = last - 100;
  return (
    <div className="flex h-full flex-col px-2 pb-1 pt-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="min-h-0 w-full flex-1" preserveAspectRatio="none">
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(0,240,118,0.28)" />
            <stop offset="100%" stopColor="rgba(0,240,118,0)" />
          </linearGradient>
        </defs>
        <path d={`${path} L ${W},${H} L 0,${H} Z`} fill="url(#eqFill)" />
        <path d={path} fill="none" stroke="#00f076" strokeWidth="1.8" />
        <circle cx={W} cy={H - 12 - ((last - min) / span) * (H - 26)} r="3" fill="#00f076" />
      </svg>
      <div className="flex items-center justify-between px-2 pb-1 font-mono text-[9px] text-smoke">
        <span>
          {wins}в / {losses}с · {points.length} сделок
        </span>
        <span className={totalRet >= 0 ? "text-bull" : "text-bear"}>
          {totalRet >= 0 ? "+" : ""}
          {totalRet.toFixed(1)}%
        </span>
      </div>
    </div>
  );
});

/* ---------------- ЛЕНТЫ: КРУПНЯК / НОВОСТИ / ДИВИДЕНДЫ ---------------- */

export const FeedsTabs = memo(function FeedsTabs({
  data,
  onSelect,
}: {
  data: DashboardData;
  onSelect: (t: string) => void;
}) {
  const [tab, setTab] = useState<"whales" | "news" | "divs">("whales");
  const divs = data.dividend_calendar ?? [];
  const tabs = [
    { key: "whales" as const, label: "Крупняк", icon: Waves, n: data.whales.length },
    { key: "news" as const, label: "Новости", icon: Newspaper, n: data.news.length },
    { key: "divs" as const, label: "Дивиденды", icon: CalendarDays, n: divs.length },
  ];

  return (
    <div className="glass flex h-full flex-col overflow-hidden rounded-xl">
      <div className="flex border-b border-line px-2 pt-2">
        {tabs.map(({ key, label, icon: Icon, n }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-t-lg border-b-2 px-2 py-2 font-mono text-[9px] uppercase tracking-wider transition-colors ${
              tab === key ? "border-neon bg-neon/[0.07] text-neon" : "border-transparent text-smoke hover:text-fog"
            }`}
          >
            <Icon size={11} />
            {label}
            <span className="rounded bg-white/[0.06] px-1 text-[8.5px]">{n}</span>
          </button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto p-2.5">
        {tab === "whales" &&
          (data.whales.length ? (
            data.whales.map((w) => (
              <button
                key={w.ticker}
                onClick={() => onSelect(w.ticker)}
                className="rounded-lg border border-line bg-panel-2/60 p-2.5 text-left transition-colors hover:border-gold/35"
              >
                <div className="flex items-center justify-between font-mono text-[11px]">
                  <span className="font-700 text-white">
                    {w.ticker} <span className="font-400 text-smoke">{w.name}</span>
                  </span>
                  <span className={w.change >= 0 ? "text-bull" : "text-bear"}>
                    {w.price.toFixed(2)} ₽ {w.change >= 0 ? "+" : ""}
                    {w.change.toFixed(2)}%
                  </span>
                </div>
                {(w.events || []).map((ev, i) => (
                  <div key={i} className="mt-1 flex items-start gap-1.5 text-[10.5px] leading-snug text-fog">
                    <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-gold" />
                    {ev}
                  </div>
                ))}
              </button>
            ))
          ) : (
            <Empty text="за 5 минут крупных принтов не было" />
          ))}
        {tab === "news" &&
          (data.news.length ? (
            data.news.map((n, i) => (
              <a
                key={i}
                href={n.url || undefined}
                target="_blank"
                rel="noreferrer"
                className={`group rounded-lg border border-line bg-panel-2/60 p-2.5 ${n.url ? "cursor-pointer transition-colors hover:border-neon/35" : "cursor-default"}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5">
                    <span
                      className={`rounded px-1.5 py-0.5 font-mono text-[8px] font-700 tracking-wider ${
                        n.source === "MOEX" ? "bg-neon/12 text-neon" : "bg-amberx/12 text-amberx"
                      }`}
                    >
                      {n.source || "FEED"}
                    </span>
                    {n.important && (
                      <span className="rounded bg-bear/15 px-1.5 py-0.5 font-mono text-[8px] font-700 text-bear">ВАЖНО</span>
                    )}
                  </span>
                  <span className="flex items-center gap-1 font-mono text-[9px] text-smoke">
                    {n.time} {n.date}
                    {n.url && <ExternalLink size={9} className="opacity-0 transition-opacity group-hover:opacity-100" />}
                  </span>
                </div>
                <div className="mt-1.5 text-[11px] leading-snug text-white">{n.title}</div>
              </a>
            ))
          ) : (
            <Empty text="лента новостей пуста" />
          ))}
        {tab === "divs" &&
          (divs.length ? (
            divs.map((d) => (
              <div key={d.ticker} className="flex items-center justify-between rounded-lg border border-line bg-panel-2/60 px-3 py-2 font-mono text-[10.5px]">
                <span className="flex items-center gap-2">
                  <button onClick={() => onSelect(d.ticker)} className="font-700 text-white hover:text-neon">
                    {d.ticker}
                  </button>
                  <span className="text-smoke">
                    {d.date} · {d.days_left}дн
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  <span className="font-700 text-bull">
                    {d.div_rub} ₽ ({d.yield_pct}%)
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[8px] font-700 ${
                      d.cutoff_soon ? "bg-bear/15 text-bear" : d.days_left <= 10 ? "bg-amberx/15 text-amberx" : "bg-white/[0.06] text-smoke"
                    }`}
                  >
                    {d.risk}
                  </span>
                </span>
              </div>
            ))
          ) : (
            <Empty text="ближайших отсечек нет" />
          ))}
      </div>
    </div>
  );
});

const Empty = ({ text }: { text: string }) => (
  <div className="flex flex-1 items-center justify-center py-8 text-center font-mono text-[9.5px] text-smoke">{text}</div>
);

/* ---------------- УПРАВЛЕНИЕ ЭШЕЛОНАМИ ---------------- */

export const TiersPanel = memo(function TiersPanel({
  tiers,
  activeCount,
  onChanged,
}: {
  tiers: DashboardData["tiers"];
  activeCount: number;
  onChanged: (msg: string, ok: boolean) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const toggle = async (ticker: string) => {
    setBusy(ticker);
    try {
      const res = await apiAction({ action: "toggle_ticker", ticker });
      const active = (res as { active?: boolean }).active;
      onChanged(res.ok ? `${ticker}: ${active ? "включён" : "выключен"}` : "Ошибка", Boolean(res.ok));
    } catch {
      onChanged("Нет связи с ботом", false);
    } finally {
      setBusy(null);
    }
  };

  const setTier = async (tier: number, on: boolean) => {
    setBusy(`tier${tier}`);
    try {
      const res = await apiAction({ action: "tier_set", tier, on });
      onChanged(res.ok ? `Эшелон ${tier}: ${on ? "включён" : "выключен"}` : "Ошибка", Boolean(res.ok));
    } catch {
      onChanged("Нет связи с ботом", false);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="glass overflow-hidden rounded-xl">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="flex items-center gap-2 font-mono text-[9.5px] uppercase tracking-[0.22em] text-smoke">
          <Layers3 size={11} />
          универсум сканера · активно {activeCount}
        </span>
      </div>
      <div className="flex max-h-[300px] flex-col gap-3 overflow-y-auto p-3.5">
        {Object.entries(tiers || {}).map(([tier, list]) => (
          <div key={tier}>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-smoke">эшелон {tier}</span>
              <span className="flex gap-1">
                <button
                  onClick={() => setTier(+tier, true)}
                  className="rounded border border-bull/30 bg-bull/10 px-2 py-0.5 font-mono text-[8.5px] text-bull"
                >
                  все вкл
                </button>
                <button
                  onClick={() => setTier(+tier, false)}
                  className="rounded border border-bear/30 bg-bear/10 px-2 py-0.5 font-mono text-[8.5px] text-bear"
                >
                  все выкл
                </button>
              </span>
            </div>
            <div className="grid grid-cols-2 gap-1">
              {list.map((e) => (
                <button
                  key={e.ticker}
                  onClick={() => toggle(e.ticker)}
                  disabled={busy === e.ticker}
                  className={`flex items-center justify-between rounded-lg border px-2.5 py-1.5 font-mono text-[10px] transition-colors disabled:opacity-50 ${
                    e.active
                      ? "border-bull/25 bg-bull/[0.06] text-white"
                      : "border-line bg-abyss/50 text-smoke"
                  }`}
                >
                  <span className="flex items-center gap-1.5">
                    <b>{e.ticker}</b>
                    <span className="hidden text-[8.5px] opacity-60 sm:inline">{e.name}</span>
                  </span>
                  {busy === e.ticker ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : e.active ? (
                    <ToggleRight size={13} className="text-bull" />
                  ) : (
                    <ToggleLeft size={13} className="text-smoke" />
                  )}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

export { kvFmt, fmtRub };
