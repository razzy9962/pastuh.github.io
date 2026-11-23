import assert from "node:assert/strict";

const base = process.env.API_BASE_URL || "http://localhost:3000";
const health = await fetch(`${base}/api/health`);
assert.equal(health.status, 200);
assert.equal((await health.json()).ok, true);
console.log("✓ PostgreSQL health check");

const workspace = await fetch(`${base}/api/workspace`);
assert.equal(workspace.status, 200);
const cookie = workspace.headers.get("set-cookie")?.split(";")[0];
assert.ok(cookie);
const { settings } = await workspace.json();
const modified = { ...settings, timeframe: "1h", indicators: [...settings.indicators, { id: "smoke-custom", name: "Smoke EMA", type: "ema", period: 34, color: "#a48bf0", enabled: true, custom: true, formula: "ema(close, 34)" }] };
const save = value => fetch(`${base}/api/workspace`, { method: "PATCH", headers: { "Content-Type": "application/json", cookie }, body: JSON.stringify(value) });
try {
  assert.equal((await save(modified)).status, 200);
  const restored = await (await fetch(`${base}/api/workspace`, { headers: { cookie } })).json();
  assert.equal(restored.settings.timeframe, "1h");
  assert.ok(restored.settings.indicators.some(i => i.id === "smoke-custom"));
  console.log("✓ Workspace and custom indicator persisted in PostgreSQL");
  assert.equal((await save({ ...settings, symbol: "INVALID" })).status, 400);
  assert.equal((await save({ ...modified, indicators: [{ ...modified.indicators.at(-1), formula: "eval(close)" }] })).status, 400);
  console.log("✓ Server rejects invalid symbols and unsafe formulas");
} finally { await save(settings); }

const marketResponse = await fetch(`${base}/api/market?symbol=SBER&timeframe=1d`);
assert.equal(marketResponse.status, 200);
const { candles, source } = await marketResponse.json();
assert.ok(candles.length >= 20);
assert.ok(["tinvest", "moex", "demo"].includes(source));
assert.ok(candles.every((c, i) => c.close > 0 && c.high >= Math.max(c.open, c.close) && c.low <= Math.min(c.open, c.close) && (!i || c.time > candles[i - 1].time)));
console.log(`✓ Candle data: ${candles.length} bars, source: ${source}`);

const quoteResponse = await fetch(`${base}/api/market?mode=quotes`);
assert.equal(quoteResponse.status, 200);
const { quotes } = await quoteResponse.json();
assert.ok(quotes.length >= 12);
assert.ok(quotes.every(q => q.price > 0 && Number.isFinite(q.change)));
assert.equal(new Set(quotes.map(q => q.symbol)).size, quotes.length);
console.log("✓ Quote catalog:", JSON.stringify(quotes.reduce((counts, q) => ({ ...counts, [q.source]: (counts[q.source] || 0) + 1 }), {})));
assert.equal((await fetch(`${base}/api/market?symbol=INVALID`)).status, 400);
console.log("✓ Unknown market instruments rejected");
