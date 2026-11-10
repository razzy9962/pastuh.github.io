import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { FlaskConical, X, Loader2, TrendingUp, TrendingDown } from "lucide-react";
import { apiBacktest } from "../api";
import type { BacktestResult } from "../types";
import { fmtRub } from "../utils";

interface Props {
  open: boolean;
  onClose: () => void;
}

const DAY_OPTIONS = [30, 60, 90, 180];

export default function BacktestModal({ open, onClose }: Props) {
  const [days, setDays] = useState(60);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<BacktestResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await apiBacktest(days);
      if (!r.ok) setErr(r.error || "неизвестная ошибка");
      setRes(r.ok ? r : null);
      if (!r.ok) setErr(r.error || "ошибка бэктеста");
    } catch (e) {
      setErr(e instanceof Error && e.name === "AbortError" ? "таймаут запроса" : "нет связи с ботом");
      setRes(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[120] flex items-center justify-center bg-abyss/80 p-4 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, y: 26, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
            className="glass flex max-h-[86vh] w-full max-w-[720px] flex-col overflow-hidden rounded-2xl"
          >
            <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
              <div className="flex items-center gap-2.5">
                <FlaskConical size={14} className="text-violet" />
                <span className="font-display text-[13px] font-700 text-white">Портфельный бэктест</span>
                <span className="font-mono text-[9px] text-smoke">дневная модель · комиссия 0.05%×2</span>
              </div>
              <button onClick={onClose} className="rounded-lg border border-line p-1.5 text-smoke transition-colors hover:text-white">
                <X size={14} />
              </button>
            </div>

            <div className="flex items-center gap-2 border-b border-line px-5 py-3">
              {DAY_OPTIONS.map((d) => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={`rounded-lg px-3 py-1.5 font-mono text-[10.5px] transition-colors ${
                    days === d ? "bg-violet/20 text-violet border border-violet/40" : "border border-line text-smoke hover:text-fog"
                  }`}
                >
                  {d}д
                </button>
              ))}
              <button
                onClick={run}
                disabled={busy}
                className="ml-auto flex items-center gap-2 rounded-lg bg-violet px-4 py-1.5 font-display text-[10px] font-700 uppercase tracking-wider text-white transition-all hover:shadow-[0_0_22px_-4px_rgba(192,132,252,0.7)] disabled:opacity-60"
              >
                {busy ? <Loader2 size={12} className="animate-spin" /> : <FlaskConical size={12} />}
                {busy ? "считаем…" : "запустить"}
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              {err && (
                <div className="rounded-lg border border-bear/30 bg-bear/[0.08] px-4 py-3 text-[12px] text-[#ffb3c1]">
                  Ошибка: {err}
                </div>
              )}

              {!res && !err && !busy && (
                <div className="py-10 text-center font-mono text-[10.5px] text-smoke">
                  выбери глубину истории и нажми «запустить».
                  <br />
                  расчёт идёт 20–60 секунд на сервере бота.
                </div>
              )}

              {busy && (
                <div className="flex flex-col items-center gap-3 py-12">
                  <Loader2 size={22} className="animate-spin text-violet" />
                  <div className="font-mono text-[10px] text-smoke">прогон исторических свечей по всему универсуму…</div>
                </div>
              )}

              {res && !busy && (
                <div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {[
                      { l: "сделок", v: String(res.trades), c: "text-white" },
                      { l: "винрейт", v: `${res.winrate}%`, c: "text-neon" },
                      { l: "средний pnl/бумага", v: `${res.avg_pnl_per_ticker_pct >= 0 ? "+" : ""}${res.avg_pnl_per_ticker_pct}%`, c: res.avg_pnl_per_ticker_pct >= 0 ? "text-bull" : "text-bear" },
                      { l: `на депозит`, v: `${res.pnl_rub >= 0 ? "+" : ""}${fmtRub(res.pnl_rub)}`, c: res.pnl_rub >= 0 ? "text-bull" : "text-bear" },
                    ].map((k) => (
                      <div key={k.l} className="rounded-lg border border-line bg-panel-2/70 px-3 py-2.5">
                        <div className="font-mono text-[8px] uppercase tracking-[0.16em] text-smoke">{k.l}</div>
                        <div className={`mt-1 font-mono text-[15px] font-800 ${k.c}`}>{k.v}</div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 font-mono text-[9px] text-smoke">
                    проверено бумаг: {res.tickers}/{res.watchlist_size}
                    {res.note ? ` · ${res.note}` : ""}
                  </div>

                  <div className="mt-3 overflow-hidden rounded-lg border border-line">
                    <div className="grid grid-cols-[1.2fr_repeat(4,0.8fr)] gap-px bg-line font-mono text-[8.5px] uppercase tracking-[0.14em] text-smoke max-sm:grid-cols-[1.2fr_repeat(3,0.7fr)]">
                      <div className="bg-panel px-3 py-2">бумага</div>
                      <div className="bg-panel px-2 py-2 text-right">сделок</div>
                      <div className="bg-panel px-2 py-2 text-right">винрейт</div>
                      <div className="bg-panel px-2 py-2 text-right">pnl</div>
                      <div className="bg-panel px-2 py-2 text-right max-sm:hidden">макс.ду</div>
                    </div>
                    {[...(res.per_ticker || [])]
                      .sort((a, b) => b.pnl_pct - a.pnl_pct)
                      .map((t) => (
                        <div
                          key={t.ticker}
                          className="grid grid-cols-[1.2fr_repeat(4,0.8fr)] gap-px bg-line font-mono text-[10.5px] max-sm:grid-cols-[1.2fr_repeat(3,0.7fr)]"
                        >
                          <div className="bg-abyss px-3 py-2 text-white">
                            <b>{t.ticker}</b> <span className="text-smoke">{t.name}</span>
                          </div>
                          <div className="bg-abyss px-2 py-2 text-right text-fog">
                            {t.trades} <span className="text-smoke">({t.wins}в)</span>
                          </div>
                          <div className="bg-abyss px-2 py-2 text-right text-fog">{t.winrate}%</div>
                          <div className="bg-abyss px-2 py-2 text-right font-700">
                            <span className={`flex items-center justify-end gap-1 ${t.pnl_pct >= 0 ? "text-bull" : "text-bear"}`}>
                              {t.pnl_pct >= 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                              {t.pnl_pct >= 0 ? "+" : ""}
                              {t.pnl_pct}%
                            </span>
                          </div>
                          <div className="bg-abyss px-2 py-2 text-right text-smoke max-sm:hidden">−{t.max_dd_pct}%</div>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
