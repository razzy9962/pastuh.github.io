/**
 * Метки входа виртуального счёта на графике.
 * Время метки может прийти в миллисекундах (Date.now) или в секундах, а Lightweight Charts
 * принимает метку только по существующему бару — иначе стрелка молча не рисуется.
 */
import type { SeriesMarker, Time } from "lightweight-charts";
import { formatPrice, type Candle } from "./market";

export type TradeMarkInput = { side: "long" | "short"; price: number; time: number };

/** Время метки в секундах: поддерживаются и миллисекунды, и уже секунды. */
export const markSeconds = (time: number) => Math.floor(time > 1e11 ? time / 1000 : time);

export function buildTradeMarkers(marks: TradeMarkInput[], candles: Candle[]): SeriesMarker<Time>[] {
  if (!candles.length) return [];
  // Медиана интервалов: последний зазор может быть выходным (3 дня), и метка,
  // поставленная в пятницу, «прилипала» к понедельнику.
  const gaps: number[] = [];
  for (let i = Math.max(1, candles.length - 60); i < candles.length; i++) {
    const gap = candles[i].time - candles[i - 1].time;
    if (gap > 0) gaps.push(gap);
  }
  gaps.sort((a, b) => a - b);
  const barSeconds = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 86400;
  const bars = new Set(candles.map(candle => candle.time));
  const nearest = (time: number) => {
    let best: number | null = null;
    for (const candle of candles) if (Math.abs(candle.time - time) < Math.abs((best ?? -Infinity) - time)) best = candle.time;
    return best;
  };
  return marks.flatMap(mark => {
    const seconds = markSeconds(mark.time);
    if (!Number.isFinite(seconds) || !(mark.price > 0)) return [];
    const time = bars.has(seconds) ? seconds : nearest(seconds);
    if (time == null || Math.abs(time - seconds) > barSeconds) return [];
    return [{
      time: time as Time,
      position: (mark.side === "long" ? "belowBar" : "aboveBar") as "belowBar" | "aboveBar",
      shape: (mark.side === "long" ? "arrowUp" : "arrowDown") as "arrowUp" | "arrowDown",
      color: mark.side === "long" ? "#089981" : "#f23645",
      text: (mark.side === "long" ? "Покупка " : "Продажа ") + formatPrice(mark.price),
      size: 1 as const,
    }];
  }).sort((a, b) => (a.time as number) - (b.time as number));
}
