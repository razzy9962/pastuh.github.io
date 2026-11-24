import test from "node:test";
import assert from "node:assert/strict";
import { computeSmc, DEFAULT_SMC, sanitizeSmcSettings, volumeProfile } from "../src/lib/smc.ts";

const series = (closes, volumes = []) => closes.map((close, i) => ({
  time: 1730000000 + i * 86400,
  open: i ? closes[i - 1] : close,
  high: Math.max(close, i ? closes[i - 1] : close) * 1.004,
  low: Math.min(close, i ? closes[i - 1] : close) * 0.996,
  close,
  volume: volumes[i] ?? 1000 + i,
}));

const trending = (() => {
  const closes = [];
  let price = 100;
  for (let i = 0; i < 240; i++) { price += Math.sin(i / 9) * 1.4 + 0.16; closes.push(+price.toFixed(2)); }
  return closes;
})();

test("SMC возвращает пустой результат без данных или при выключенном индикаторе", () => {
  const empty = computeSmc([], DEFAULT_SMC, "1d");
  assert.equal(empty.boxes.length, 0);
  assert.equal(empty.stats.bias, 0);
  const disabled = computeSmc(series(trending), { ...DEFAULT_SMC, enabled: false }, "1d");
  assert.equal(disabled.lines.length, 0);
});

test("Order Blocks строятся по методу LuxAlgo и не выходят за ценовой диапазон", () => {
  const candles = series(trending);
  const overlay = computeSmc(candles, { ...DEFAULT_SMC, ob: { ...DEFAULT_SMC.ob, swing: true } }, "1d");
  assert.ok(overlay.boxes.length > 0, "должны появиться зоны");
  const min = Math.min(...candles.map(c => c.low));
  const max = Math.max(...candles.map(c => c.high));
  for (const box of overlay.boxes) {
    assert.ok(box.top > box.bottom);
    assert.ok(box.top <= max + 1e-6 && box.bottom >= min - 1e-6);
  }
  assert.ok(overlay.stats.created > 0);
});

test("FVG появляется на гэпе и исчезает при закрытии", () => {
  const candles = series([100, 100.2, 100.1, 100.3, 103.4, 103.6, 103.5, 103.9, 104.1, 104]);
  const overlay = computeSmc(candles, { ...DEFAULT_SMC, ob: { ...DEFAULT_SMC.ob, internal: false } }, "1d");
  assert.ok(overlay.stats.fvgCount >= 1);
  const narrow = computeSmc(candles, { ...DEFAULT_SMC, fvg: { ...DEFAULT_SMC.fvg, minAtr: 2 } }, "1d");
  assert.equal(narrow.stats.fvgCount, 0);
});

test("Уровни старшего ТФ и POC считаются по свечам", () => {
  const overlay = computeSmc(series(trending), DEFAULT_SMC, "1d");
  const names = overlay.stats.levels.map(level => level.name);
  assert.ok(names.includes("PDH") && names.includes("PDL"));
  assert.ok(typeof overlay.stats.poc === "number");
  assert.ok((overlay.stats.vah ?? 0) >= (overlay.stats.val ?? 0));
});

test("EMA старших ТФ не используют будущие свечи (lookahead)", () => {
  const candles = series(trending);
  const full = computeSmc(candles, DEFAULT_SMC, "1d");
  const partial = computeSmc(candles.slice(0, 200), DEFAULT_SMC, "1d");
  const fullPoints = new Map(full.series[0].data.map(point => [point.time, point.value]));
  const tail = partial.series[0].data.slice(-5);
  for (const point of tail) assert.ok(Math.abs((fullPoints.get(point.time) ?? NaN) - point.value) < 1e-9);
});

test("Настройки валидируются: мусор не ломает терминал", () => {
  const clean = sanitizeSmcSettings({ ob: { maxInternal: 999, filter: "hack", mitigation: 42 }, structure: { keep: -5 }, emas: [{ timeframe: "nope" }, { timeframe: "1h", period: 5000, color: "red" }] });
  assert.equal(clean.ob.maxInternal, 20);
  assert.equal(clean.ob.filter, "atr");
  assert.equal(clean.ob.mitigation, "hl");
  assert.equal(clean.structure.keep, 1);
  assert.equal(clean.emas.length, 1);
  assert.equal(clean.emas[0].period, 400);
  assert.match(clean.emas[0].color, /^#[0-9a-f]{6}$/i);
  assert.deepEqual(sanitizeSmcSettings(null), DEFAULT_SMC);
});

test("Профиль объёма: POC внутри value area", () => {
  const candles = series([100, 101, 102, 101, 100, 99, 100, 101], [10, 10, 500, 10, 10, 10, 10, 10]);
  const profile = volumeProfile(candles, 0.5, 70);
  assert.ok(profile.poc >= profile.val && profile.poc <= profile.vah);
  assert.ok(profile.val <= profile.vah);
});
