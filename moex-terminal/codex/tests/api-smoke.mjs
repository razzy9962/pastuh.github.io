import assert from "node:assert/strict";

const base = process.env.API_BASE_URL || "http://localhost:3000";
const health = await fetch(`${base}/api/health`);
assert.equal(health.status, 200);
assert.equal((await health.json()).ok, true);
console.log("✓ PostgreSQL health check");

const workspace = await fetch(`${base}/api/workspace`);
if (workspace.status === 503) {
  // Без PostgreSQL (бесплатный Render) настройки хранятся в браузере — API отвечает 503.
  const body = await workspace.json();
  assert.equal(body.storage, "local");
  assert.equal((await fetch(`${base}/api/workspace`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) })).status, 503);
  console.log("✓ Workspace: серверное хранилище отключено, клиент работает на localStorage");
} else {
  assert.equal(workspace.status, 200);
  const cookie = workspace.headers.get("set-cookie")?.split(";")[0];
  assert.ok(cookie);
  const { settings } = await workspace.json();
  assert.ok(!("indicators" in settings), "индикаторы Pine удалены из настроек");
  assert.ok(settings.smc && typeof settings.smc === "object", "настройки SMC присутствуют");
  const changed = !settings.smc.showFvg;
  const modified = { ...settings, timeframe: "1h", smc: { ...settings.smc, showFvg: changed } };
  const save = value => fetch(`${base}/api/workspace`, { method: "PATCH", headers: { "Content-Type": "application/json", cookie }, body: JSON.stringify(value) });
  try {
    assert.equal((await save(modified)).status, 200);
    const restored = await (await fetch(`${base}/api/workspace`, { headers: { cookie } })).json();
    assert.equal(restored.settings.timeframe, "1h");
    assert.equal(restored.settings.smc.showFvg, changed);
    console.log("✓ Workspace and SMC settings persisted in PostgreSQL");
    assert.equal((await save({ ...settings, symbol: "INVALID" })).status, 400);
    assert.equal((await save({ ...settings, timeframe: "7h" })).status, 400);
    console.log("✓ Server rejects invalid symbols and timeframes");
  } finally { await save(settings); }
}

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
assert.equal((await fetch(`${base}/api/market?symbol=SBER&timeframe=7h`)).status, 400);
console.log("✓ Unknown market instruments and timeframes rejected");

const symbolsResponse = await fetch(`${base}/api/market?mode=symbols`);
assert.equal(symbolsResponse.status, 200);
const { symbols } = await symbolsResponse.json();
const stocks = symbols.filter(s => s.kind === "stock");
assert.ok(stocks.length >= 250, `акций в каталоге: ${stocks.length}`);
assert.equal(new Set(symbols.map(s => s.symbol)).size, symbols.length);
assert.ok(stocks.every(s => [1, 2, 3].includes(s.tier) && s.lot > 0 && s.name.length > 0));
const tiers = stocks.reduce((acc, s) => ({ ...acc, [s.tier]: (acc[s.tier] || 0) + 1 }), {});
assert.ok(tiers[1] >= 20 && tiers[2] >= 20 && tiers[3] >= 20, JSON.stringify(tiers));
assert.ok(symbols.some(s => s.kind === "index"));
console.log(`✓ Symbol catalog: ${stocks.length} акций, эшелоны ${JSON.stringify(tiers)}`);
