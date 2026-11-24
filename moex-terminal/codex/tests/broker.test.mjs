import { test } from "node:test";
import assert from "node:assert/strict";
import { emptyAccount, openPosition, closePosition, accountSnapshot, applyProtection, sanitizeAccount, START_BALANCE, COMMISSION, MAX_LEVERAGE } from "../src/lib/broker.ts";
import { INSTRUMENTS, TIERS } from "../src/lib/market.ts";

const SBER = 289.72;

test("счёт начинается с 10 млн и пустого портфеля", () => {
  const account = emptyAccount();
  assert.equal(account.balance, START_BALANCE);
  assert.equal(account.positions.length, 0);
  assert.equal(accountSnapshot(account, {}).equity, START_BALANCE);
});

test("рыночная покупка списывает комиссию и создаёт позицию", () => {
  const result = openPosition(emptyAccount(), { symbol: "SBER", side: "long", lots: 1, price: SBER });
  assert.equal(result.ok, true);
  const position = result.account.positions[0];
  assert.equal(position.side, "long");
  assert.equal(position.lots, 1);
  assert.equal(position.quantity, 10);
  assert.ok(Math.abs(result.account.balance - (START_BALANCE - SBER * 10 * COMMISSION)) < 1e-6);
});

test("заявка без свободной маржи отклоняется", () => {
  const result = openPosition(emptyAccount(), { symbol: "SBER", side: "long", lots: 1_000_000, price: SBER });
  assert.equal(result.ok, false);
  assert.match(result.error, /Недостаточно средств/);
});

test("лонг и шорт считают результат с правильным знаком", () => {
  const long = openPosition(emptyAccount(), { symbol: "SBER", side: "long", lots: 1, price: 100 }).account;
  const closedLong = closePosition(long, long.positions[0].id, 110);
  assert.equal(closedLong.ok, true);
  assert.equal(closedLong.trade.pnl, 100);
  const short = openPosition(emptyAccount(), { symbol: "SBER", side: "short", lots: 1, price: 100 }).account;
  const closedShort = closePosition(short, short.positions[0].id, 90);
  assert.equal(closedShort.trade.pnl, 100);
});

test("частичное закрытие уменьшает лоты и оставляет позицию", () => {
  const account = openPosition(emptyAccount(), { symbol: "SBER", side: "long", lots: 4, price: 100 }).account;
  const partial = closePosition(account, account.positions[0].id, 110, 2);
  assert.equal(partial.account.positions[0].lots, 2);
  assert.equal(partial.trade.lots, 2);
  assert.equal(partial.trade.pnl, 200);
});

test("тейк-профит и стоп-лосс исполняются по свече", () => {
  const withTake = openPosition(emptyAccount(), { symbol: "SBER", side: "long", lots: 1, price: 100, take: 110 }).account;
  const takeHit = applyProtection(withTake, { SBER: { high: 112, low: 99 } });
  assert.equal(takeHit.closed.length, 1);
  assert.equal(takeHit.closed[0].reason, "take");
  assert.equal(takeHit.closed[0].exit, 110);
  const withStop = openPosition(emptyAccount(), { symbol: "SBER", side: "long", lots: 1, price: 100, stop: 95 }).account;
  const stopHit = applyProtection(withStop, { SBER: { high: 101, low: 94 } });
  assert.equal(stopHit.closed[0].reason, "stop");
  assert.ok(stopHit.closed[0].pnl < 0);
});

test("эквити учитывает маржу и нереализованный результат", () => {
  const account = openPosition(emptyAccount(), { symbol: "SBER", side: "long", lots: 10, price: 100 }).account;
  const snapshot = accountSnapshot(account, { SBER: 110 });
  assert.ok(Math.abs(snapshot.unrealized - 1000) < 1e-6);
  assert.ok(Math.abs(snapshot.marginUsed - (110 * 100) / MAX_LEVERAGE) < 1e-6);
  assert.ok(snapshot.equity > START_BALANCE);
  assert.equal(snapshot.positions[0].pnlPercent.toFixed(2), "10.00");
});

test("сохранённый счёт очищается от мусора", () => {
  const dirty = { balance: -5, positions: [{ symbol: "НЕТ", side: "long", lots: 1, entry: 10 }, { symbol: "SBER", side: "short", lots: "3", entry: 100 }], trades: [{ symbol: "SBER", side: "long", lots: 1, entry: 100, exit: 110, pnl: 100, fee: 1, opened: 1, closed: 2 }] };
  const clean = sanitizeAccount(dirty);
  assert.equal(clean.balance, 0);
  assert.equal(clean.positions.length, 1);
  assert.equal(clean.positions[0].symbol, "SBER");
  assert.equal(clean.positions[0].side, "short");
  assert.equal(clean.positions[0].lots, 3);
  assert.equal(clean.trades.length, 1);
  assert.equal(sanitizeAccount(null).balance, START_BALANCE);
});

test("каталог покрывает все акции MOEX с эшелонами", () => {
  const stocks = INSTRUMENTS.filter(i => i.kind === "stock");
  assert.ok(stocks.length >= 250, `акций в каталоге: ${stocks.length}`);
  for (const tier of TIERS) assert.ok(stocks.filter(i => i.tier === tier.value).length >= 20, `эшелон ${tier.value}`);
  assert.equal(new Set(INSTRUMENTS.map(i => i.symbol)).size, INSTRUMENTS.length);
  assert.ok(stocks.every(i => i.tier === undefined || (i.tier >= 1 && i.tier <= 3)));
  assert.ok(stocks.every(i => i.lot > 0 && i.price > 0));
});

test("история сделок сохраняется в счёте и переживает сохранение/загрузку", () => {
  let account = emptyAccount();
  for (let i = 1; i <= 3; i++) {
    account = openPosition(account, { symbol: "SBER", side: "long", lots: i, price: 100 }).account;
    account = closePosition(account, account.positions[0].id, 100 + i * 5).account;
  }
  assert.equal(account.trades.length, 3);
  assert.equal(account.trades[0].lots, 3, "свежая сделка идёт первой");
  const restored = sanitizeAccount(JSON.parse(JSON.stringify(account)));
  assert.equal(restored.trades.length, 3);
  assert.deepEqual(restored.trades.map(t => t.lots), [3, 2, 1]);
  assert.equal(restored.trades[0].reason, "manual");
  assert.ok(restored.trades.every(t => t.closed >= t.opened));
});

test("история ограничена 500 сделками", () => {
  const many = Array.from({ length: 700 }, (_, i) => ({ symbol: "SBER", side: "long", lots: 1, quantity: 10, entry: 100, exit: 101, opened: i, closed: i + 1, pnl: 10, fee: 1, reason: "manual" }));
  const restored = sanitizeAccount({ balance: 100, positions: [], trades: many });
  assert.equal(restored.trades.length, 500);
  assert.equal(restored.limit, 500);
});
