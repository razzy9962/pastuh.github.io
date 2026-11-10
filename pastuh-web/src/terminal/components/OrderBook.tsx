import { memo, useMemo } from "react";
import type { BookRow } from "../types";
import { BookOpen } from "lucide-react";

interface Props {
  bids: BookRow[];
  asks: BookRow[];
}

/** Биржевой стакан L2 — чистый CSS, глубина бара через transform (GPU), без layout-вычислений. */
function OrderBook({ bids, asks }: Props) {
  const { rows, imbalance, maxQ } = useMemo(() => {
    const a = [...asks].reverse();
    const m = Math.max(1, ...bids.map((b) => b.quantity), ...asks.map((x) => x.quantity));
    const sumB = bids.reduce((s, b) => s + b.quantity, 0);
    const sumA = asks.reduce((s, x) => s + x.quantity, 0);
    return {
      rows: { asks: a, bids },
      imbalance: sumB + sumA > 0 ? Math.round((sumB / (sumB + sumA)) * 100) : 50,
      maxQ: m,
    };
  }, [bids, asks]);

  const row = (r: BookRow, side: "bid" | "ask", i: number) => (
    <div key={`${side}-${r.price}-${i}`} className="relative flex items-center justify-between py-[3px] font-mono text-[10px]">
      <div
        className={`absolute inset-y-0 right-0 origin-right rounded-sm ${
          side === "bid" ? "bg-bull/15" : "bg-bear/15"
        }`}
        style={{ width: "100%", transform: `scaleX(${(r.quantity / maxQ).toFixed(3)})` }}
      />
      <span className={`relative z-10 pl-1.5 ${side === "bid" ? "text-bull" : "text-bear"}`}>
        {r.price.toFixed(2)}
      </span>
      <span className="relative z-10 pr-1.5 text-fog">{r.quantity.toLocaleString("ru-RU")}</span>
    </div>
  );

  const empty = !bids.length && !asks.length;

  return (
    <div className="glass overflow-hidden rounded-xl">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="flex items-center gap-2 font-mono text-[9.5px] uppercase tracking-[0.22em] text-smoke">
          <BookOpen size={11} />
          стакан L2 · 10×10
        </span>
        <span className="font-mono text-[9.5px]">
          <span className="text-bull">{imbalance}%</span>
          <span className="text-smoke">/</span>
          <span className="text-bear">{100 - imbalance}%</span>
        </span>
      </div>
      {empty ? (
        <div className="px-4 py-5 text-center font-mono text-[10px] text-smoke">
          стакан пуст — биржа закрыта или данные не пришли
        </div>
      ) : (
        <div className="px-1.5 py-2">
          <div className="mb-1">{rows.asks.map((r, i) => row(r, "ask", i))}</div>
          <div className="my-1.5 flex h-1 overflow-hidden rounded-full bg-bear/30">
            <div className="h-full bg-bull transition-[width] duration-700" style={{ width: `${imbalance}%` }} />
          </div>
          <div>{rows.bids.map((r, i) => row(r, "bid", i))}</div>
        </div>
      )}
    </div>
  );
}

export default memo(OrderBook);
