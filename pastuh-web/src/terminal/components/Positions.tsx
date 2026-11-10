import { memo, useState } from "react";
import {
  Briefcase,
  Loader2,
  X,
  ShieldAlert,
  Eraser,
  RotateCcw,
  Timer,
  TrendingUp,
  Save,
  Layers3,
} from "lucide-react";
import type { PendingOrder, Strat, TrackedPos } from "../types";
import { apiAction } from "../api";
import { fmtPrice, fmtPct, parseNum, stratLabel } from "../utils";

interface Props {
  tracked: TrackedPos[];
  pending: PendingOrder[];
  strats: Strat[];
  onActionDone: (msg: string, ok: boolean) => void;
  onSelect: (t: string) => void;
}

function PositionCard({
  p,
  onActionDone,
  onSelect,
}: {
  p: TrackedPos;
  onActionDone: (m: string, ok: boolean) => void;
  onSelect: (t: string) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [edit, setEdit] = useState(false);
  const [tp, setTp] = useState(String(p.tp ?? ""));
  const [sl, setSl] = useState(String(p.sl ?? ""));
  const isLong = p.side === "LONG";
  const pnl = p.pnl_pct ?? 0;

  const act = async (label: string, body: Record<string, unknown>) => {
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

  return (
    <div className="rounded-lg border border-line bg-panel-2/70 p-3">
      <div className="flex items-center justify-between gap-2">
        <button onClick={() => onSelect(p.ticker)} className="flex min-w-0 items-center gap-2 text-left">
          <span className={`rounded px-1.5 py-0.5 font-mono text-[8.5px] font-800 ${isLong ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"}`}>
            {p.side}
          </span>
          <span className="font-mono text-[12px] font-700 text-white">{p.ticker}</span>
          {p.strategy && (
            <span className="rounded border border-violet/35 bg-violet/10 px-1.5 py-0.5 font-mono text-[8px] text-violet">
              {stratLabel(p.strategy)}
            </span>
          )}
          {p.is_be && (
            <span className="rounded border border-gold/35 bg-gold/10 px-1.5 py-0.5 font-mono text-[8px] text-gold">Б/У</span>
          )}
          {typeof p.leverage === "number" && p.leverage > 1 && (
            <span className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[8px] text-fog">×{p.leverage}</span>
          )}
        </button>
        <span className={`flex items-center gap-1 font-mono text-[12px] font-800 ${pnl >= 0 ? "text-bull" : "text-bear"}`}>
          <TrendingUp size={11} className={pnl >= 0 ? "" : "rotate-180"} />
          {fmtPct(pnl)}
        </span>
      </div>

      <div className="mt-2 grid grid-cols-4 gap-1.5 font-mono text-[9px]">
        {[
          { l: "вход", v: fmtPrice(p.entry), c: "text-fog" },
          { l: "сейчас", v: fmtPrice(p.current_price), c: "text-white" },
          { l: "tp", v: fmtPrice(p.tp), c: "text-bull" },
          { l: "sl", v: fmtPrice(p.sl), c: "text-bear" },
        ].map((x) => (
          <div key={x.l} className="rounded bg-abyss/70 px-1.5 py-1.5 text-center">
            <div className="text-[7.5px] uppercase tracking-[0.14em] text-smoke">{x.l}</div>
            <div className={`mt-0.5 text-[10px] font-600 ${x.c}`}>{x.v}</div>
          </div>
        ))}
      </div>

      {p.take_profits?.length ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {p.take_profits.map((t, i) => (
            <span
              key={i}
              className={`rounded px-1.5 py-0.5 font-mono text-[8.5px] ${
                t.hit ? "bg-bull/15 text-bull line-through" : "bg-neon/10 text-neon"
              }`}
            >
              TP{i + 1} {t.price} ({t.pct}%)
            </span>
          ))}
        </div>
      ) : null}

      {edit ? (
        <div className="mt-2 flex items-center gap-1.5">
          <input
            value={tp}
            onChange={(e) => setTp(e.target.value.replace(/[^\d.,]/g, ""))}
            placeholder="TP"
            className="w-full rounded border border-bull/30 bg-abyss px-2 py-1.5 font-mono text-[10.5px] text-bull outline-none"
          />
          <input
            value={sl}
            onChange={(e) => setSl(e.target.value.replace(/[^\d.,]/g, ""))}
            placeholder="SL"
            className="w-full rounded border border-bear/30 bg-abyss px-2 py-1.5 font-mono text-[10.5px] text-bear outline-none"
          />
          <button
            onClick={() =>
              act("save", {
                action: "update_position_levels",
                ticker: p.ticker,
                tp: parseNum(tp) || undefined,
                sl: parseNum(sl) || undefined,
              }).then(() => setEdit(false))
            }
            className="flex shrink-0 items-center gap-1 rounded bg-neon/20 px-2.5 py-1.5 font-mono text-[9.5px] text-neon"
          >
            {busy === "save" ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
          </button>
        </div>
      ) : null}

      <div className="mt-2 grid grid-cols-4 gap-1.5">
        <button
          onClick={() => setEdit(!edit)}
          className="rounded border border-line bg-white/[0.03] py-1.5 font-mono text-[8.5px] uppercase tracking-wider text-fog transition-colors hover:border-neon/40 hover:text-neon"
        >
          уровни
        </button>
        <button
          onClick={() => act("be", { action: "update_position_levels", ticker: p.ticker, to_be: true })}
          disabled={busy !== null}
          className="rounded border border-line bg-white/[0.03] py-1.5 font-mono text-[8.5px] uppercase tracking-wider text-fog transition-colors hover:border-gold/40 hover:text-gold disabled:opacity-50"
          title="Переставить стоп в безубыток"
        >
          в б/у
        </button>
        <button
          onClick={() => act("reduce", { action: "reduce_position", ticker: p.ticker, reduce_pct: 50 })}
          disabled={busy !== null}
          className="rounded border border-line bg-white/[0.03] py-1.5 font-mono text-[8.5px] uppercase tracking-wider text-fog transition-colors hover:border-violet/40 hover:text-violet disabled:opacity-50"
        >
          {busy === "reduce" ? "…" : "−50%"}
        </button>
        <button
          onClick={() =>
            act("close", p.strategy
              ? { action: "untrack_strat", ticker: p.ticker, strategy: p.strategy }
              : { action: "untrack", ticker: p.ticker })
          }
          disabled={busy !== null}
          className="rounded border border-bear/30 bg-bear/[0.07] py-1.5 font-mono text-[8.5px] uppercase tracking-wider text-bear transition-colors hover:bg-bear/15 disabled:opacity-50"
        >
          {busy === "close" ? "…" : "закрыть"}
        </button>
      </div>
    </div>
  );
}

function Positions({ tracked, pending, strats, onActionDone, onSelect }: Props) {
  const [panicBusy, setPanicBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  const act = async (label: string, body: Record<string, unknown>, needConfirm = true) => {
    if (needConfirm && confirm !== label) {
      setConfirm(label);
      setTimeout(() => setConfirm((c) => (c === label ? null : c)), 3200);
      return;
    }
    setConfirm(null);
    setPanicBusy(label);
    try {
      const res = await apiAction(body);
      onActionDone(res.message || (res.ok ? "Готово" : res.error || "Ошибка"), Boolean(res.ok));
    } catch {
      onActionDone("Нет связи с ботом", false);
    } finally {
      setPanicBusy(null);
    }
  };

  const dangerBtn = (
    label: string,
    text: string,
    body: Record<string, unknown>,
    cls: string,
    Icon: typeof ShieldAlert
  ) => (
    <button
      onClick={() => act(label, body)}
      disabled={panicBusy !== null}
      className={`flex items-center justify-center gap-1.5 rounded-lg border px-2 py-2 font-mono text-[8.5px] uppercase tracking-wider transition-all disabled:opacity-50 ${cls} ${
        confirm === label ? "animate-pulse ring-2 ring-bear/60" : ""
      }`}
    >
      {panicBusy === label ? <Loader2 size={11} className="animate-spin" /> : <Icon size={11} />}
      {confirm === label ? "точно? жми ещё" : text}
    </button>
  );

  return (
    <div className="flex h-full flex-col gap-3">
      {/* открытые позиции */}
      <div className="glass flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <span className="flex items-center gap-2 font-mono text-[9.5px] uppercase tracking-[0.22em] text-smoke">
            <Briefcase size={11} />
            открытые сделки · {tracked.length}
          </span>
        </div>
        <div className="flex min-h-[64px] flex-1 flex-col gap-2 overflow-y-auto p-2.5">
          {tracked.map((p) => (
            <PositionCard key={`${p.owner_uid}-${p.ticker}-${p.strategy ?? "m"}`} p={p} onActionDone={onActionDone} onSelect={onSelect} />
          ))}
          {!tracked.length && (
            <div className="flex flex-1 items-center justify-center py-6 font-mono text-[10px] text-smoke">
              открытых сделок нет
            </div>
          )}
        </div>
      </div>

      {/* отложенные ордера */}
      <div className="glass overflow-hidden rounded-xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <span className="flex items-center gap-2 font-mono text-[9.5px] uppercase tracking-[0.22em] text-smoke">
            <Timer size={11} />
            очередь на открытие · {pending.length}
          </span>
        </div>
        <div className="flex flex-col gap-1.5 p-2.5">
          {pending.map((o) => (
            <div key={o.ticker} className="flex items-center justify-between gap-2 rounded-lg border border-neon/20 bg-neon/[0.05] px-3 py-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 font-mono text-[8.5px] font-800 ${o.side === "LONG" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"}`}>
                    {o.side}
                  </span>
                  <button onClick={() => onSelect(o.ticker)} className="font-mono text-[11.5px] font-700 text-white">
                    {o.ticker}
                  </button>
                  <span className="font-mono text-[9px] text-smoke">{o.dep_pct}% · гэп≤{o.max_gap_pct}%</span>
                </div>
                <div className="mt-0.5 truncate font-mono text-[8.5px] text-smoke">
                  ref {fmtPrice(o.ref_price)} ₽ · {o.created_at}
                </div>
              </div>
              <button
                onClick={() => act("cancelpo", { action: "cancel_open_order", ticker: o.ticker }, false)}
                className="shrink-0 rounded border border-line p-1.5 text-smoke transition-colors hover:border-bear/50 hover:text-bear"
                title="Отменить ордер"
              >
                <X size={11} />
              </button>
            </div>
          ))}
          {!pending.length && (
            <div className="py-3 text-center font-mono text-[9.5px] text-smoke">очередь пуста</div>
          )}
        </div>
      </div>

      {/* стратегии */}
      {strats.length > 0 && (
        <div className="glass overflow-hidden rounded-xl">
          <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
            <span className="flex items-center gap-2">
              <Layers3 size={11} className="text-violet" />
              <span className="font-mono text-[9.5px] uppercase tracking-[0.22em] text-smoke">
                стратегии · {strats.length}
              </span>
            </span>
            <span className="flex items-center gap-2 font-mono text-[9px]">
              <span className="text-smoke">в рынке</span>
              <span className="text-white">
                {strats.reduce((n, s) => n + (s.open?.length ?? 0), 0)}
              </span>
              <span
                className={
                  strats.reduce((n, s) => n + (s.pnl_rub || 0), 0) >= 0 ? "text-bull" : "text-bear"
                }
              >
                {(() => {
                  const sum = strats.reduce((n, s) => n + (s.pnl_rub || 0), 0);
                  return `${sum >= 0 ? "+" : ""}${Math.round(sum).toLocaleString("ru-RU")} ₽`;
                })()}
              </span>
            </span>
          </div>
          <div className="flex max-h-[330px] flex-col gap-2 overflow-y-auto p-2.5">
            {strats.map((st) => {
              const pct = ((st.compound_mult - 1) * 100).toFixed(2);
              return (
                <div key={st.key} className="rounded-lg border border-line bg-panel-2/70 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12px] font-700 text-white">{st.name}</span>
                    <span className={`font-mono text-[10.5px] font-700 ${st.pnl_rub >= 0 ? "text-bull" : "text-bear"}`}>
                      {st.pnl_rub >= 0 ? "+" : ""}
                      {Math.round(st.pnl_rub).toLocaleString("ru-RU")} ₽ ({pct}%)
                    </span>
                  </div>
                  <div className="mt-1 font-mono text-[9px] text-smoke">
                    винрейт {st.winrate}% · {st.wins}В/{st.losses}С/{st.be}Б · открыто {(st.open || []).length}/{st.max_positions}
                  </div>
                  {(st.open || []).map((o) => (
                    <div key={o.ticker} className="mt-1.5 flex items-center justify-between rounded bg-abyss/70 px-2.5 py-1.5 font-mono text-[10px]">
                      <button onClick={() => onSelect(o.ticker)} className="font-700 text-white">
                        {o.ticker} <span className="text-smoke">{o.side} @ {o.entry}</span>
                      </button>
                      <span className="flex items-center gap-1.5">
                        <span className={o.pnl_pct >= 0 ? "text-bull" : "text-bear"}>{fmtPct(o.pnl_pct)}</span>
                        <button
                          onClick={() => act(`s_${o.ticker}`, { action: "untrack_strat", strategy: st.key, ticker: o.ticker }, false)}
                          className="text-smoke transition-colors hover:text-bear"
                          title="Закрыть по рынку"
                        >
                          <X size={10} />
                        </button>
                      </span>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* аварийные действия */}
      <div className="grid grid-cols-3 gap-1.5">
        {dangerBtn(
          "panic",
          "закрыть всё",
          { action: "panic_close_all" },
          "border-bear/40 bg-bear/[0.08] text-bear hover:bg-bear/15",
          ShieldAlert
        )}
        {dangerBtn(
          "clear",
          "очистить",
          { action: "clear_tracked" },
          "border-amberx/40 bg-amberx/[0.08] text-amberx hover:bg-amberx/15",
          Eraser
        )}
        {dangerBtn(
          "reset",
          "сброс стат.",
          { action: "reset_stats" },
          "border-line-2 bg-white/[0.03] text-fog hover:text-white",
          RotateCcw
        )}
      </div>
    </div>
  );
}

export default memo(Positions);
