import test from "node:test";
import assert from "node:assert/strict";
import { calculateIndicator, generateCandles, parseFormula, DEFAULT_SETTINGS, INSTRUMENTS } from "../src/lib/market.ts";

const bars = closes => closes.map((close, i) => ({ time: 1700000000 + i * 86400, open: close, high: close, low: close, close, volume: 100 }));

test("SMA uses the exact rolling close-price average", () => {
  assert.deepEqual(calculateIndicator(bars([1, 2, 3, 4, 5, 6]), "sma", 3).map(p => p.value), [2, 3, 4, 5]);
});
test("EMA uses alpha=2/(period+1), with a warm-up period", () => {
  const result = calculateIndicator(bars([1, 2, 3, 4]), "ema", 3);
  assert.deepEqual(result.map(p => p.value), [2.25, 3.125]);
});
test("Wilder RSI matches the published reference example", () => {
  const data = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.1, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28];
  const result = calculateIndicator(bars(data), "rsi", 14);
  assert.equal(result.length, 1);
  assert.ok(Math.abs(result[0].value - 70.46413502109705) < .0000001);
});
test("RSI handles rising, falling and flat prices without NaN", () => {
  const rising = Array.from({ length: 30 }, (_, i) => i + 1);
  assert.equal(calculateIndicator(bars(rising), "rsi", 14).at(-1).value, 100);
  assert.equal(calculateIndicator(bars([...rising].reverse()), "rsi", 14).at(-1).value, 0);
  assert.equal(calculateIndicator(bars(Array(30).fill(10)), "rsi", 14).at(-1).value, 50);
});
test("Indicator warm-up and empty input are safe", () => {
  for (const type of ["sma", "ema", "bb", "rsi"]) {
    assert.deepEqual(calculateIndicator([], type, 20), []);
    assert.deepEqual(calculateIndicator(bars([1, 2]), type, 20), []);
  }
});
test("Custom formulas use a strict whitelist and period bounds", () => {
  assert.deepEqual(parseFormula(" EMA ( close, 34 ) "), { type: "ema", period: 34 });
  assert.deepEqual(parseFormula("rsi(close, 14)"), { type: "rsi", period: 14 });
  for (const formula of ["ema(close, 0)", "sma(close, 201)", "fetch('https://example.com')", "ema(close, 20);alert(1)", "process.env.TINKOFF_TOKEN", ""]) assert.equal(parseFormula(formula), null);
});
test("Demonstration candles are chronological, positive and valid OHLCV", () => {
  for (const timeframe of ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]) {
    const data = generateCandles("SBER", timeframe);
    assert.equal(data.length, 195);
    assert.equal(data.at(-1).close, INSTRUMENTS[0].price);
    for (let i = 0; i < data.length; i++) {
      const c = data[i];
      assert.ok(c.low > 0 && c.volume > 0);
      assert.ok(c.high >= Math.max(c.open, c.close));
      assert.ok(c.low <= Math.min(c.open, c.close));
      if (i) assert.ok(c.time > data[i - 1].time);
    }
  }
});
test("Default workspace uses unique known instruments", () => {
  assert.equal(new Set(DEFAULT_SETTINGS.watchlist).size, DEFAULT_SETTINGS.watchlist.length);
  assert.ok(DEFAULT_SETTINGS.watchlist.every(symbol => INSTRUMENTS.some(i => i.symbol === symbol)));
});
