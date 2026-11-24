import { test } from "node:test";
import assert from "node:assert/strict";
import { generateCandles, DEFAULT_SETTINGS, INSTRUMENTS, TIMEFRAMES, TIERS, formatMoney, formatChange } from "../src/lib/market.ts";

test("демо-свечи детерминированы и корректны по OHLCV", () => {
  const candles = generateCandles("SBER", "1h");
  assert.equal(candles.length, 195);
  assert.deepEqual(candles.map(c => c.time), generateCandles("SBER", "1h").map(c => c.time).slice(0, candles.length));
  for (const candle of candles) {
    assert.ok(candle.high >= Math.max(candle.open, candle.close));
    assert.ok(candle.low <= Math.min(candle.open, candle.close));
    assert.ok(candle.volume >= 0);
    assert.ok(candle.time > 0);
  }
});

test("дневные свечи пропускают выходные", () => {
  for (const candle of generateCandles("GAZP", "1d", 60)) {
    const day = new Date(candle.time * 1000).getUTCDay();
    assert.ok(day !== 0 && day !== 6);
  }
});

test("каталог акций покрывает три эшелона и не содержит дублей", () => {
  const stocks = INSTRUMENTS.filter(i => i.kind === "stock");
  assert.ok(stocks.length >= 250, `акций в каталоге: ${stocks.length}`);
  assert.equal(new Set(INSTRUMENTS.map(i => i.symbol)).size, INSTRUMENTS.length);
  for (const tier of TIERS) assert.ok(stocks.filter(i => i.tier === tier.value).length >= 20, `эшелон ${tier.value}`);
  assert.ok(INSTRUMENTS.some(i => i.kind === "index"));
  assert.ok(INSTRUMENTS.some(i => i.kind === "currency"));
});

test("настройки по умолчанию ссылаются на существующий инструмент и список", () => {
  assert.ok(INSTRUMENTS.some(i => i.symbol === DEFAULT_SETTINGS.symbol));
  assert.ok(TIMEFRAMES.some(t => t.value === DEFAULT_SETTINGS.timeframe));
  assert.ok(DEFAULT_SETTINGS.watchlist.every(symbol => INSTRUMENTS.some(i => i.symbol === symbol)));
  assert.ok(DEFAULT_SETTINGS.watchlist.length >= 10);
});

test("форматирование денег и процентов", () => {
  assert.equal(formatMoney(10000000).replace(/\s/g, " "), "10 000 000,00");
  assert.equal(formatChange(1.5), "+1,50%");
  assert.equal(formatChange(-2), "−2,00%");
});
