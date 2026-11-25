/**
 * Рыночные метрики по свечам: волатильность, ATR, RSI, наклон EMA 20,
 * 52-недельный диапазон и уровни Фибоначчи от последнего свинга.
 * Всё считается по закрытым барам и только для отображения — не рекомендация.
 */
import type { Candle, Timeframe } from "./market";

export type MarketMetrics = {
  /** Интервал, на котором посчитаны метрики: дневные метрики считаются по дневным свечам. */
  timeframe: Timeframe;
  changePercent: number;
  atr: number;
  atrPercent: number;
  rsi: number;
  ema20: number | null;
  ema20Slope: number;
  high52: number;
  low52: number;
  positionInRange: number;
  fib: { label: string; price: number }[];
  swingHigh: number;
  swingLow: number;
};

const ema = (values: number[], period: number) => {
  if (!values.length) return [];
  const k = 2 / (period + 1);
  const out = [values[0]];
  for (let i = 1; i < values.length; i++) out.push(values[i] * k + out[i - 1] * (1 - k));
  return out;
};

const rsi = (values: number[], period = 14) => {
  if (values.length <= period) return 50;
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = values[i] - values[i - 1];
    if (diff >= 0) gain += diff; else loss -= diff;
  }
  gain /= period; loss /= period;
  for (let i = period + 1; i < values.length; i++) {
    const diff = values[i] - values[i - 1];
    gain = (gain * (period - 1) + Math.max(diff, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-diff, 0)) / period;
  }
  if (!loss) return 100;
  return 100 - 100 / (1 + gain / loss);
};

const swing = (candles: Candle[], lookback: number) => {
  const window = candles.slice(-lookback);
  const high = window.reduce((best, candle) => Math.max(best, candle.high), -Infinity);
  const low = window.reduce((best, candle) => Math.min(best, candle.low), Infinity);
  return { high, low };
};

export function computeMetrics(candles: Candle[], timeframe: Timeframe = "1d"): MarketMetrics | null {
  if (candles.length < 20) return null;
  const closes = candles.map(candle => candle.close);
  const last = candles[candles.length - 1];

  let atrSum = 0;
  const atrWindow = Math.min(14, candles.length - 1);
  for (let i = candles.length - atrWindow; i < candles.length; i++) {
    const previous = candles[i - 1].close;
    atrSum += Math.max(candles[i].high - candles[i].low, Math.abs(candles[i].high - previous), Math.abs(candles[i].low - previous));
  }
  const atr = atrSum / atrWindow;

  const emaSeries = ema(closes, 20);
  const ema20 = emaSeries[emaSeries.length - 1];
  const emaBack = emaSeries[Math.max(0, emaSeries.length - 11)];
  const ema20Slope = emaBack ? (ema20 / emaBack - 1) * 100 : 0;

  // 52 недели — это календарный год, а не «365 последних баров»: на часовом графике
  // такое окно покрывало две недели, и «Год» показывал двухнедельный диапазон.
  const barSeconds = candles.length > 1 ? Math.max(60, last.time - candles[candles.length - 2].time) : 86400;
  const barsPerYear = Math.max(1, Math.round(365 * 86400 / barSeconds));
  const yearWindow = candles.slice(-Math.min(candles.length, barsPerYear));
  const high52 = yearWindow.reduce((best, candle) => Math.max(best, candle.high), last.high);
  const low52 = yearWindow.reduce((best, candle) => Math.min(best, candle.low), last.low);

  const { high, low } = swing(candles, Math.min(candles.length, 120));
  const span = high - low || 1;
  const ratios: [string, number][] = [["0", 0], ["0.236", 0.236], ["0.382", 0.382], ["0.5", 0.5], ["0.618", 0.618], ["0.786", 0.786], ["1", 1]];

  return {
    timeframe,
    changePercent: closes[0] ? (last.close / closes[0] - 1) * 100 : 0,
    atr,
    atrPercent: last.close ? atr / last.close * 100 : 0,
    rsi: rsi(closes),
    ema20,
    ema20Slope,
    high52,
    low52,
    positionInRange: high52 - low52 > 0 ? (last.close - low52) / (high52 - low52) * 100 : 50,
    fib: ratios.map(([label, ratio]) => ({ label, price: high - span * ratio })),
    swingHigh: high,
    swingLow: low,
  };
}

export type SessionStats = {
  sessionHigh: number;   // максимум за текущие торговые сутки
  sessionLow: number;
  sessionOpen: number;
  sessionVolume: number;
  sessionBars: number;
};

/**
 * Статистика текущей сессии: сегодняшние максимум, минимум, открытие и объём.
 * Сутки считаются по московскому времени — так же, как торгуется биржа.
 */
export function computeSession(candles: Candle[]): SessionStats | null {
  if (candles.length < 2) return null;
  const moscowDay = (time: number) => new Date(time * 1000).toLocaleDateString("ru-RU", { timeZone: "Europe/Moscow" });
  const today = moscowDay(candles[candles.length - 1].time);
  const session = candles.filter(candle => moscowDay(candle.time) === today);
  if (!session.length) return null;
  return {
    sessionHigh: session.reduce((best, candle) => Math.max(best, candle.high), -Infinity),
    sessionLow: session.reduce((best, candle) => Math.min(best, candle.low), Infinity),
    sessionOpen: session[0].open,
    sessionVolume: session.reduce((sum, candle) => sum + candle.volume, 0),
    sessionBars: session.length,
  };
}

/** Пояснение к RSI без «сигналов купить/продать». */
export const rsiLabel = (value: number) => value >= 70 ? "перекупленность" : value <= 30 ? "перепроданность" : value >= 55 ? "умеренно сильный" : value <= 45 ? "умеренно слабый" : "нейтрально";
