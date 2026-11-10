import { memo, useState } from "react";
import {
  Target,
  ShieldCheck,
  AlertOctagon,
  Crosshair,
  Timer,
  Percent,
  Gauge,
  CheckCheck,
  Loader2,
  Ban,
  ArrowUpRight,
  ArrowDownRight,
  Scale3d,
} from "lucide-react";
import type { AnalyzeData } from "../types";
import { apiAction } from "../api";
import { fmtPrice, parseNum, verdictColor } from "../utils";

interface Props {
  ticker: string;
  tf: string;
  analysis: AnalyzeData | null;
  loading: boolean;
  trackedTickers: Set<string>;
  onActionDone: (msg: string, ok: boolean) => void;
}

function ScoreRing({ score, color }: { score: number; color: string }) {
  const abs = Math.min(10, Math.abs(score));
  const R = 30;
  const C = 2 * Math.PI * R;
  return (
    <div className="relative h-[74px] w-[74px]">
      <svg viewBox="0 0 74 74" className="h-full w-full -rotate-90">
        <circle cx="37" cy="37" r={R} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="6" />
        <circle
          cx="37"
          cy="37"
          r={R}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={C}
          strokeDashoffset={C * (1 - abs / 10)}
          style={{ transition: "stroke-dashoffset 0.7s cubic-bezier(0.22,1,0.36,1)", filter: `drop-shadow(0 0 6px ${color})` }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center leading-none">
          <div className="font-mono text-[17px] font-800 text-white">{abs}</div>
          <div className="mt-0.5 font-mono text-[7.5px] uppercase tracking-[0.14em] text-smoke">/ 10</div>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="flex items-center justify-between rounded-md bg-white/[0.03] px-2.5 py-1.5">
      <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-smoke">{label}</span>
      <span className={`font-mono text-[11px] font-600 ${cls ?? "text-white"}`}>{value}</span>
    </div>
  );
}

function Detail({ ticker, tf, analysis, loading, trackedTickers, onActionDone }: Props) {
  const sig = analysis?.signal ?? null;
  const [depPct, setDepPct] = useState(20);
  const [useLev, setUseLev] = useState(true);
  const [autoPartial, setAutoPartial] = useState(true);
  const [customTp, setCustomTp] = useState("");
  const [customSl, setCustomSl] = useState("");
  const [maxGap, setMaxGap] = useState("1.0");
  const [busy, setBusy] = useState<string | null>(null);

  const tracked = trackedTickers.has(ticker);

  const doAction = async (label: string, body: Record<string, unknown>) => {
    setBusy(label);
    try {
      const res = await apiAction(body);
      onActionDone(res.message || (res.ok ? "Готово" : res.error || "Ошибка"), Boolean(res.ok));
    } catch {
      onActionDone("Нет связи с ботом", false);
    } finally {
      setBusy(null);
    }
  };

  const take = (side: "LONG" | "SHORT") =>
    doAction(side, {
      action: "track_manual",
      ticker,
      side,
      dep_pct: depPct,
      use_leverage: useLev,
      auto_partial: autoPartial,
      custom_tp: parseNum(customTp) || 0,
      custom_sl: parseNum(customSl) || 0,
      max_gap_pct: parseNum(maxGap) || 1,
    });

  const queueOrder = () =>
    doAction("queue", {
      action: "queue_open_order",
      ticker,
      side: sig?.verdict === "SHORT" ? "SHORT" : "LONG",
      dep_pct: depPct,
      use_leverage: useLev,
      auto_partial: autoPartial,
      custom_tp: parseNum(customTp) || 0,
      custom_sl: parseNum(customSl) || 0,
      max_gap_pct: parseNum(maxGap) || 1,
      ref_price: sig?.price || 0,
    });

  const vc = verdictColor(sig?.verdict);
  const m = analysis?.margin;
  const cvd = sig?.cvd_data;
  const sr = sig?.sr_levels;

  return (
    <div className="glass relative overflow-hidden rounded-xl">
      {/* header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-3">
          <ScoreRing score={sig?.score ?? 0} color={vc} />
          <div>
            <div className="flex items-center gap-2">
              <span className="font-display text-[16px] font-800 text-white">{ticker}</span>
              <span className="text-[11px] text-smoke">{sig?.name ?? ""}</span>
              <span className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[8.5px] uppercase tracking-wider text-fog">
                {tf}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span
                className="rounded-md px-2 py-0.5 font-mono text-[10px] font-800 tracking-[0.14em]"
                style={{ color: vc, background: `${vc}1f`, border: `1px solid ${vc}55` }}
              >
                {loading ? "…" : sig?.verdict ?? "—"}
              </span>
              <span className="font-mono text-[13px] font-700 text-white">{fmtPrice(sig?.price)} ₽</span>
              {sig?.change != null && (
                <span className={`flex items-center font-mono text-[10.5px] ${sig.change >= 0 ? "text-bull" : "text-bear"}`}>
                  {sig.change >= 0 ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                  {sig.change >= 0 ? "+" : ""}
                  {sig.change.toFixed(2)}%
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 font-mono text-[9px] text-smoke">
          {loading && <Loader2 size={12} className="animate-spin text-neon" />}
          {tracked && (
            <span className="flex items-center gap-1 rounded border border-bull/30 bg-bull/10 px-2 py-1 text-[9px] uppercase tracking-wider text-bull">
              <CheckCheck size={10} /> в сделке
            </span>
          )}
        </div>
      </div>

      <div className="grid gap-3 p-3.5 sm:grid-cols-2">
        {/* уровни */}
        <div className="flex flex-col gap-1.5">
          <div className="mb-0.5 flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.22em] text-smoke">
            <Target size={10} />
            уровни · r/r 1:{sig?.rr_ratio ?? "—"}
          </div>
          <Row label="точка входа" value={`${fmtPrice(sig?.entry)} ₽`} />
          <Row
            label="take-profit"
            value={`${fmtPrice(sig?.tp)} ₽  (+${sig?.profit_pct ?? 0}%)`}
            cls="text-bull"
          />
          <Row label="stop-loss" value={`${fmtPrice(sig?.sl)} ₽  (−${sig?.risk_pct ?? 0}%)`} cls="text-bear" />
          <Row
            label="poc / sup1"
            value={`${fmtPrice(sr?.poc)} / ${fmtPrice(sr?.sup1_price)} ₽`}
            cls="text-gold"
          />
          <Row label="res1" value={`${fmtPrice(sr?.res1_price)} ₽ (+${sr?.res1_dist_pct ?? 0}%)`} cls="text-neon" />
          {m && (
            <Row
              label="плечо L/S"
              value={`×${m.leverage_long} / ×${m.leverage_short}`}
              cls="text-violet"
            />
          )}
        </div>

        {/* CVD */}
        <div className="flex flex-col gap-1.5">
          <div className="mb-0.5 flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.22em] text-smoke">
            <Gauge size={10} />
            ордерфлоу · покрытие ленты {analysis?.tape_cov_pct ?? 0}%
          </div>
          <Row label="delta бара" value={`${(cvd?.bar_delta ?? 0) > 0 ? "+" : ""}${fmtPrice(cvd?.bar_delta as number)}`} cls={(cvd?.bar_delta ?? 0) >= 0 ? "text-bull" : "text-bear"} />
          <Row label="cvd за день" value={`${(cvd?.cvd_today ?? 0) > 0 ? "+" : ""}${fmtPrice(cvd?.cvd_today as number)}`} cls={(cvd?.cvd_today ?? 0) >= 0 ? "text-bull" : "text-bear"} />
          <Row label="Δ 6 свечей" value={`${fmtPrice(cvd?.cum_delta_change_6 as number)}%`} />
          {analysis && (
            <Row
              label="стакан L2"
              value={`${analysis.orderbook.bids.length}×${analysis.orderbook.asks.length}`}
              cls="text-neon"
            />
          )}
          <div className="mt-auto rounded-md border border-line bg-abyss/60 px-2.5 py-2">
            <div className="flex items-center gap-1.5 font-mono text-[8.5px] uppercase tracking-[0.18em] text-smoke">
              <Timer size={9} />
              {sig?.is_live_market === false ? "рынок закрыт — цены справочные" : "данные live · обновление после скана"}
            </div>
          </div>
        </div>
      </div>

      {/* факторы и причины блокировки */}
      <div className="border-t border-line px-4 py-3">
        <div className="mb-2 flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.22em] text-smoke">
          <Scale3d size={10} />
          факторы решения
        </div>
        {sig?.factors?.length ? (
          <ul className="flex flex-col gap-1">
            {sig.factors.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-[11.5px] leading-snug text-fog">
                <ShieldCheck size={11} className="mt-0.5 shrink-0 text-bull" />
                {f}
              </li>
            ))}
          </ul>
        ) : (
          <div className="font-mono text-[10px] text-smoke">{loading ? "считаем…" : "факторов нет"}</div>
        )}
        {sig?.block_reasons?.length ? (
          <ul className="mt-2 flex flex-col gap-1">
            {sig.block_reasons.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-[11.5px] leading-snug text-[#ffb3c1]">
                <AlertOctagon size={11} className="mt-0.5 shrink-0 text-bear" />
                {f}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {/* Форма входа */}
      <div className="border-t border-line bg-abyss/40 px-4 py-3.5">
        <div className="mb-2.5 flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.22em] text-smoke">
          <Crosshair size={10} />
          взять в сделку · {ticker}
        </div>

        <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <label className="col-span-2 rounded-lg border border-line bg-panel px-3 py-2">
            <span className="flex items-center gap-1 font-mono text-[8.5px] uppercase tracking-[0.16em] text-smoke">
              <Percent size={9} />
              объём · {depPct}% депо
            </span>
            <input
              type="range"
              min={5}
              max={100}
              step={5}
              value={depPct}
              onChange={(e) => setDepPct(+e.target.value)}
              className="mt-1.5 w-full accent-[#00f076]"
            />
          </label>
          {[
            { label: "custom TP ₽", v: customTp, set: setCustomTp, ph: sig?.tp?.toFixed(2) },
            { label: "custom SL ₽", v: customSl, set: setCustomSl, ph: sig?.sl?.toFixed(2) },
          ].map((f) => (
            <label key={f.label} className="rounded-lg border border-line bg-panel px-3 py-2">
              <span className="font-mono text-[8.5px] uppercase tracking-[0.16em] text-smoke">{f.label}</span>
              <input
                value={f.v}
                onChange={(e) => f.set(e.target.value.replace(/[^\d.,]/g, ""))}
                placeholder={f.ph}
                inputMode="decimal"
                className="mt-1 w-full bg-transparent font-mono text-[12px] text-white outline-none placeholder:text-smoke/50"
              />
            </label>
          ))}
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-4 font-mono text-[10px] text-fog">
          <label className="flex cursor-pointer items-center gap-2">
            <input type="checkbox" checked={useLev} onChange={(e) => setUseLev(e.target.checked)} className="accent-[#00f076]" />
            плечо ×{m?.leverage_long ?? 1}
          </label>
          <label className="flex cursor-pointer items-center gap-2">
            <input type="checkbox" checked={autoPartial} onChange={(e) => setAutoPartial(e.target.checked)} className="accent-[#00f076]" />
            автопартиал
          </label>
          <label className="flex items-center gap-1.5 text-smoke">
            макс. гэп
            <input
              value={maxGap}
              onChange={(e) => setMaxGap(e.target.value.replace(/[^\d.,]/g, ""))}
              className="w-10 rounded border border-line bg-panel px-1.5 py-0.5 text-center text-white outline-none"
            />
            %
          </label>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <button
            onClick={() => take("LONG")}
            disabled={busy !== null}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-bull px-3 py-2.5 font-display text-[10.5px] font-700 uppercase tracking-wider text-abyss transition-all hover:shadow-[0_0_24px_-4px_rgba(0,240,118,0.7)] disabled:opacity-50"
          >
            {busy === "LONG" ? <Loader2 size={13} className="animate-spin" /> : <ArrowUpRight size={13} />}
            long
          </button>
          <button
            onClick={() => take("SHORT")}
            disabled={busy !== null}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-bear px-3 py-2.5 font-display text-[10.5px] font-700 uppercase tracking-wider text-white transition-all hover:shadow-[0_0_24px_-4px_rgba(255,51,88,0.7)] disabled:opacity-50"
          >
            {busy === "SHORT" ? <Loader2 size={13} className="animate-spin" /> : <ArrowDownRight size={13} />}
            short
          </button>
          <button
            onClick={queueOrder}
            disabled={busy !== null}
            className="flex items-center justify-center gap-1.5 rounded-lg border border-neon/40 bg-neon/10 px-3 py-2.5 font-display text-[10.5px] font-700 uppercase tracking-wider text-neon transition-all hover:bg-neon/20 disabled:opacity-50"
            title="Отложенный ордер: бот дождётся цены без гэпа"
          >
            {busy === "queue" ? <Loader2 size={13} className="animate-spin" /> : <Timer size={13} />}
            в очередь
          </button>
        </div>

        {tracked && (
          <button
            onClick={() => doAction("untrack", { action: "untrack", ticker })}
            disabled={busy !== null}
            className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-bear/35 bg-bear/[0.08] px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-bear transition-all hover:bg-bear/15 disabled:opacity-50"
          >
            <Ban size={11} />
            {busy === "untrack" ? "закрываем…" : "закрыть позицию по рынку"}
          </button>
        )}
      </div>
    </div>
  );
}

export default memo(Detail);
