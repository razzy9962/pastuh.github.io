import { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CandlestickChart, Info } from "lucide-react";
import { apiAction } from "./api";
import { useAnalysis, useDashboard, useToasts } from "./hooks";
import { TIMEFRAMES } from "./types";
import TopBar from "./components/TopBar";
import Scanner from "./components/Scanner";
import Detail from "./components/Detail";
import Positions from "./components/Positions";
import CandleChart from "./components/CandleChart";
import OrderBook from "./components/OrderBook";
import BacktestModal from "./components/BacktestModal";
import { EquitySpark, FeedsTabs, KpiStrip, MarketTape, TiersPanel } from "./components/Panels";

export default function TerminalApp() {
  const { data, isDemo, loading, authError, reload } = useDashboard(15000);
  const { toasts, push } = useToasts();
  const [ticker, setTicker] = useState<string | null>(null);
  const [tf, setTf] = useState<string>("15m");
  const [btOpen, setBtOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // дефолтный тикер — первый с сигналом, иначе первый в списке
  useEffect(() => {
    if (ticker || !data?.stocks?.length) return;
    const withSig = data.stocks.find((s) => s.verdict === "LONG" || s.verdict === "SHORT");
    setTicker((withSig ?? data.stocks[0]).ticker);
  }, [data, ticker]);

  const { data: analysis, loading: analysisLoading } = useAnalysis(ticker, tf);

  const trackedTickers = useMemo(
    () => new Set((data?.tracked ?? []).map((t) => t.ticker)),
    [data]
  );

  const activePosition = useMemo(
    () => (ticker ? (data?.tracked ?? []).find((t) => t.ticker === ticker && !t.strategy) ?? (data?.tracked ?? []).find((t) => t.ticker === ticker) ?? null : null),
    [data, ticker]
  );

  const onLevelDragEnd = useCallback(
    async (type: "tp" | "sl", price: number) => {
      if (!ticker) return;
      if (!activePosition) {
        push("Перетаскивание уровней активно для открытой позиции — для новой сделки задай custom TP/SL в форме", "info");
        return;
      }
      try {
        const res = await apiAction({
          action: "update_position_levels",
          ticker,
          [type]: price,
        });
        push(
          res.message || `${type.toUpperCase()} перенесён на ${price.toFixed(2)} ₽`,
          res.ok ? "ok" : "err"
        );
        setTimeout(() => reload(true), 700);
      } catch {
        push("Нет связи с ботом — уровень не сохранён", "err");
      }
    },
    [ticker, activePosition, push, reload]
  );

  const onActionDone = useCallback(
    (msg: string, ok: boolean) => {
      push(msg, ok ? "ok" : "err");
      // дать боту секунду и подтянуть свежий стейт
      setTimeout(() => reload(true), 900);
    },
    [push, reload]
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await reload(true);
    setRefreshing(false);
    push("Данные обновлены", "ok");
  }, [reload, push]);

  const hist = useMemo(() => {
    const st = data?.stats;
    if (!st) return [];
    const list = st.all_history?.length ? st.all_history : st.history;
    return (list || []).map((h) => (typeof h === "string" ? h : h.text));
  }, [data]);

  return (
    <div className="min-h-screen bg-ink text-white">
      <TopBar
        serverTime={data?.server_time}
        marketOpen={data?.market_open}
        isDemo={isDemo}
        authError={authError}
        deposit={data?.deposit_rub}
        imoex={data?.imoex}
        onRefresh={onRefresh}
        onOpenBacktest={() => setBtOpen(true)}
        refreshSpin={refreshing || (loading && !data)}
      />

      {data && <MarketTape stocks={data.stocks} onSelect={setTicker} />}

      <main className="mx-auto max-w-[1600px] px-3 py-3 md:px-4">
        {/* KPI */}
        {data ? (
          <KpiStrip data={data} />
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="glass h-[74px] animate-pulse rounded-xl" />
            ))}
          </div>
        )}

        {/* основная сетка */}
        <div className="mt-3 grid gap-3 xl:grid-cols-[300px_minmax(0,1fr)_330px]">
          {/* сканер */}
          <div className="order-2 h-[560px] xl:order-1 xl:h-[760px]">
            <Scanner
              stocks={data?.stocks ?? []}
              activeTicker={ticker}
              onSelect={setTicker}
              loading={loading}
            />
          </div>

          {/* центр: график + детали */}
          <div className="order-1 flex min-w-0 flex-col gap-3 xl:order-2">
            <div className="glass overflow-hidden rounded-xl">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
                <span className="flex items-center gap-2 font-mono text-[9.5px] uppercase tracking-[0.22em] text-smoke">
                  <CandlestickChart size={11} />
                  график · {ticker ?? "—"} · {tf}
                  <span className="hidden tracking-normal text-smoke/70 lg:inline">
                    — колесо: зум · drag: панорама · тяни TP/SL по линиям
                  </span>
                </span>
                <div className="flex gap-1">
                  {TIMEFRAMES.map((t) => (
                    <button
                      key={t}
                      onClick={() => setTf(t)}
                      className={`rounded-md px-2 py-1 font-mono text-[9.5px] transition-colors ${
                        tf === t ? "bg-neon/20 text-neon border border-neon/40" : "border border-line text-smoke hover:text-fog"
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              {ticker ? (
                <div className={`transition-opacity duration-300 ${analysisLoading ? "opacity-40" : ""}`}>
                  <CandleChart
                    candles={analysis?.candles ?? []}
                    signal={analysis?.signal ?? null}
                    position={activePosition}
                    onLevelDragEnd={onLevelDragEnd}
                    height={420}
                  />
                </div>
              ) : (
                <div className="grid h-[340px] place-items-center font-mono text-[10px] text-smoke">
                  выбери бумагу в сканере
                </div>
              )}
            </div>

            {ticker && (
              <Detail
                ticker={ticker}
                tf={tf}
                analysis={analysis}
                loading={analysisLoading}
                trackedTickers={trackedTickers}
                onActionDone={onActionDone}
              />
            )}

            <div className="grid gap-3 lg:grid-cols-2">
              <OrderBook
                bids={analysis?.orderbook?.bids ?? []}
                asks={analysis?.orderbook?.asks ?? []}
              />
              <div className="glass overflow-hidden rounded-xl p-0">
                <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
                  <Info size={11} className="text-bull" />
                  <span className="font-mono text-[9.5px] uppercase tracking-[0.22em] text-smoke">
                    эквити из истории сделок
                  </span>
                </div>
                <div className="h-[230px]">
                  <EquitySpark history={hist} />
                </div>
              </div>
            </div>
          </div>

          {/* позиции */}
          <div className="order-3 h-[620px] xl:h-[760px]">
            <Positions
              tracked={data?.tracked ?? []}
              pending={data?.pending_orders ?? []}
              strats={data?.strats ?? []}
              onActionDone={onActionDone}
              onSelect={setTicker}
            />
          </div>
        </div>

        {/* нижний ряд */}
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div className="h-[380px]">{data && <FeedsTabs data={data} onSelect={setTicker} />}</div>
          <div className="h-[380px] overflow-hidden">
            {data && (
              <div className="h-full overflow-hidden rounded-xl">
                <TiersPanel tiers={data.tiers} activeCount={data.active_count} onChanged={onActionDone} />
              </div>
            )}
          </div>
        </div>

        <footer className="mt-6 border-t border-line pt-4 pb-2 text-center font-mono text-[9px] tracking-[0.2em] text-smoke">
          TG//PRO TERMINAL · обновление каждые 15с · {isDemo ? "демо-режим (бот офлайн)" : "подключено к боту"}
        </footer>
      </main>

      {/* тосты */}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[130] flex w-[min(340px,90vw)] flex-col gap-2">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, x: 40, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 30 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
              className={`pointer-events-auto rounded-lg border px-4 py-3 font-mono text-[11px] leading-snug backdrop-blur-xl ${
                t.kind === "ok"
                  ? "border-bull/40 bg-[#06120c]/90 text-[#a7f3d0]"
                  : t.kind === "err"
                    ? "border-bear/40 bg-[#170a0e]/90 text-[#ffb3c1]"
                    : "border-neon/40 bg-[#071018]/90 text-[#a5dcff]"
              }`}
            >
              {t.text}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      <BacktestModal open={btOpen} onClose={() => setBtOpen(false)} />
    </div>
  );
}
