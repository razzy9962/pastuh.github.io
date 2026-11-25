import { test } from "node:test";
import assert from "node:assert/strict";
import { generateCandles, DEFAULT_SETTINGS, INSTRUMENTS, TIMEFRAMES, TIERS, formatMoney, formatChange, mskBucket as __mskBucket, mskWeekBucket as __mskWeekBucket } from "../src/lib/market.ts";

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

test("метрики рынка: ATR, RSI, наклон EMA 20 и Фибоначчи считаются по свечам", async () => {
  const { computeMetrics, rsiLabel } = await import("../src/lib/metrics.ts");
  const candles = generateCandles("SBER", "1d", 260);
  const metrics = computeMetrics(candles);
  assert.ok(metrics);
  assert.ok(metrics.atr > 0 && metrics.atrPercent > 0);
  assert.ok(metrics.rsi >= 0 && metrics.rsi <= 100);
  assert.ok(metrics.ema20 != null && metrics.ema20 > 0);
  assert.ok(metrics.high52 >= metrics.low52);
  assert.equal(metrics.fib.length, 7);
  assert.equal(metrics.fib[0].price, metrics.swingHigh);
  assert.ok(metrics.fib.at(-1).price < metrics.swingHigh);
  assert.ok(rsiLabel(80).includes("перекуп") && rsiLabel(20).includes("перепрод") && rsiLabel(50) === "нейтрально");
  assert.equal(computeMetrics(candles.slice(0, 5)), null);
});

test("сессия дня: хай/лоу/открытие/объём считаются только по текущим суткам МСК", async () => {
  const { computeSession } = await import("../src/lib/metrics.ts");
  const candles = generateCandles("SBER", "1h", 48);
  const session = computeSession(candles);
  assert.ok(session);
  const lastTime = candles.at(-1).time;
  const moscowDay = (time) => new Date(time * 1000).toLocaleDateString("ru-RU", { timeZone: "Europe/Moscow" });
  const today = candles.filter(c => moscowDay(c.time) === moscowDay(lastTime));
  assert.equal(session.sessionBars, today.length);
  assert.equal(session.sessionHigh, Math.max(...today.map(c => c.high)));
  assert.equal(session.sessionLow, Math.min(...today.map(c => c.low)));
  assert.equal(session.sessionOpen, today[0].open);
  assert.ok(session.sessionVolume > 0);
  assert.equal(computeSession(candles.slice(0, 1)), null);
});

test("виртуальный счёт: сделки, частичное закрытие и статистика консистентны", async () => {
  const { emptyAccount, openPosition, closePosition, accountSnapshot, totalReturn, sanitizeAccount } = await import("../src/lib/broker.ts");
  const account = emptyAccount();
  const opened = openPosition(account, { symbol: "SBER", side: "long", lots: 10, price: 285, take: 300, stop: 275 });
  assert.ok(opened.ok);
  assert.equal(opened.account.positions.length, 1);
  assert.ok(opened.account.positions[0].lots === 10 || opened.account.positions[0].lots > 0);
  const closed = closePosition(opened.account, opened.account.positions[0].id, 295);
  assert.ok(closed.ok && closed.trade);
  assert.ok(closed.trade.pnl > 0);
  assert.equal(closePosition(closed.account, "нет-такой", 290).ok, false);
  assert.ok(Number.isFinite(totalReturn(accountSnapshot(closed.account, { SBER: 295 }))));
  const restored = sanitizeAccount(JSON.parse(JSON.stringify(closed.account)));
  assert.equal(restored.trades.length, closed.account.trades.length);
});

test("метки сделок прилипают к ближайшему бару и понимают секунды и миллисекунды", async () => {
  const { buildTradeMarkers } = await import("../src/lib/marks.ts");
  const candles = generateCandles("SBER", "1h", 24);
  const last = candles.at(-1);
  const prev = candles.at(-2);
  const marks = buildTradeMarkers([
    { side: "long", price: 280, time: last.time * 1000 },
    { side: "short", price: 290, time: prev.time + 60 },
    { side: "long", price: 0, time: last.time },
    { side: "short", price: 285, time: last.time - 86400 * 400 },
  ], candles);
  assert.equal(marks.length, 2, "битая и далёкая метки отбрасываются");
  assert.equal(marks[0].time, prev.time);
  assert.equal(marks[1].time, last.time);
  assert.equal(marks[0].shape, "arrowDown");
  assert.equal(marks[1].shape, "arrowUp");
  assert.ok(String(marks[1].text).startsWith("Покупка"));
});

test("свечи провайдера санируются: без дублей, битых цен и с корректным OHLC", async () => {
  const { sanitizeCandles } = await import("../src/lib/market.ts");
  const raw = [
    { time: 300, open: 10, high: 9, low: 11, close: 10, volume: 0 },
    { time: 100, open: 5, high: 6, low: 4, close: 5.5, volume: 100 },
    { time: 300, open: 10, high: 12, low: 9, close: 11, volume: 50 },
    { time: 200, open: NaN, high: 6, low: 4, close: 5, volume: 10 },
    { time: 400, open: 1, high: 1, low: 1, close: 1, volume: NaN },
  ];
  const clean = sanitizeCandles(raw);
  assert.deepEqual(clean.map(c => c.time), [100, 300, 400]);
  const first = clean[1];
  assert.ok(first.high >= Math.max(first.open, first.close) && first.low <= Math.min(first.open, first.close));
  assert.equal(clean[0].volume, 100);
  assert.equal(clean[1].close, 11, "при дубле времени сохраняется последняя запись провайдера");
  assert.equal(clean[2].volume, 0, "невалидный объём заменяется нулём");
});

test("виртуальный счёт отклоняет бессмысленные тейк-профит и стоп-лосс", async () => {
  const { emptyAccount, openPosition } = await import("../src/lib/broker.ts");
  const base = { symbol: "SBER", side: "long", lots: 1, price: 300 };
  assert.match(openPosition(emptyAccount(), { ...base, take: 290 }).error, /тейк-профит/);
  assert.match(openPosition(emptyAccount(), { ...base, stop: 310 }).error, /стоп-лосс/);
  assert.ok(openPosition(emptyAccount(), { ...base, take: 320, stop: 280 }).ok);
  assert.ok(openPosition(emptyAccount(), { symbol: "SBER", side: "short", lots: 1, price: 300, take: 280, stop: 320 }).ok);
  assert.match(openPosition(emptyAccount(), { symbol: "SBER", side: "short", lots: 1, price: 300, take: 320 }).error, /тейк-профит/);
});

test("часовые свечи склеиваются в четырёхчасовые без потери объёма", async () => {
  const { aggregateCandles, sanitizeCandles } = await import("../src/lib/market.ts");
  const hour = 3600;
  const base = 1800000000 - (1800000000 % hour);
  const hours = Array.from({ length: 8 }, (_, i) => ({ time: base + i * hour, open: 100 + i, high: 110 + i, low: 90 + i, close: 105 + i, volume: 10 }));
  const four = aggregateCandles(sanitizeCandles(hours), 4 * hour);
  assert.equal(four.length, 2);
  assert.equal(four[0].open, 100);
  assert.equal(four[0].close, 108);
  assert.equal(four[0].high, 113);
  assert.equal(four[0].low, 90);
  assert.equal(four[0].volume, 40);
  assert.equal(four[1].time - four[0].time, 4 * hour);
});

test("подписи времени показываются по Москве, а не по UTC", async () => {
  const { formatMsk, formatMskFull } = await import("../src/lib/market.ts");
  // 18:00 MSK 24 ноября 2026 = 15:00 UTC
  const t = Date.UTC(2026, 10, 24, 15, 0) / 1000;
  assert.equal(formatMsk(t, true), "24 ноя 18:00");
  assert.equal(formatMskFull(t), "24.11.26 18:00");
  assert.equal(formatMsk(t, true, 3), "18:00");
  assert.equal(formatMsk(t, true, 2), "24");
  assert.equal(formatMsk(t, true, 1), "ноя");
  assert.equal(formatMsk(t, true, 0), "2026");
  // переход через полночь UTC: 23:30 UTC = 02:30 следующего дня по МСК
  const late = Date.UTC(2026, 10, 24, 23, 30) / 1000;
  assert.equal(formatMsk(late, true), "25 ноя 02:30");
});

test("тейк не срабатывает, если цена до него не дошла (движение было до входа)", async () => {
  const { emptyAccount, openPosition, applyProtection } = await import("../src/lib/broker.ts");
  const opened = openPosition(emptyAccount(), { symbol: "SBER", side: "long", lots: 1, price: 300, take: 320, stop: 280 });
  assert.ok(opened.ok);
  const position = opened.account.positions[0];
  // Цена наблюдения ниже тейка — закрытия быть не должно.
  assert.equal(applyProtection(opened.account, { SBER: { price: 305, time: position.opened + 1000 } }).closed.length, 0);
  // Наблюдение было до открытия позиции — тоже не считается.
  assert.equal(applyProtection(opened.account, { SBER: { price: 325, time: position.opened - 1000 } }).closed.length, 0);
  // Цена реально дошла до тейка после входа — закрываем по тейку.
  const hit = applyProtection(opened.account, { SBER: { price: 321, time: position.opened + 1000 } });
  assert.equal(hit.closed.length, 1);
  assert.equal(hit.closed[0].reason, "take");
  assert.equal(hit.closed[0].exit, 320);
  assert.equal(hit.account.positions.length, 0);
  // Стоп для лонга — падение цены ниже уровня.
  const stopped = applyProtection(opened.account, { SBER: { price: 279, time: position.opened + 1000 } });
  assert.equal(stopped.closed[0].reason, "stop");
  assert.equal(stopped.closed[0].exit, 280);
});

test("шорт: тейк срабатывает только при падении цены до уровня после входа", async () => {
  const { emptyAccount, openPosition, applyProtection } = await import("../src/lib/broker.ts");
  const opened = openPosition(emptyAccount(), { symbol: "SBER", side: "short", lots: 1, price: 300, take: 280, stop: 320 });
  const position = opened.account.positions[0];
  assert.equal(applyProtection(opened.account, { SBER: { price: 295, time: position.opened + 1000 } }).closed.length, 0);
  const hit = applyProtection(opened.account, { SBER: { price: 279, time: position.opened + 1000 } });
  assert.equal(hit.closed.length, 1);
  assert.equal(hit.closed[0].reason, "take");
  assert.ok(hit.closed[0].pnl > 0);
});

test("рисование: клик по бару даёт точку с временем существующей свечи", async () => {
  const { generateCandles } = await import("../src/lib/market.ts");
  const candles = generateCandles("SBER", "1h", 40);
  const byTime = new Map(candles.map(c => [Math.floor(c.time), c]));
  // Эмуляция barCandle(): время приходит числом — берём бар по времени,
  // иначе по индексу (ближайший бар), чтобы точка всегда попадала на свечу.
  const barCandle = (param) => {
    if (typeof param.time === "number") return byTime.get(Math.floor(param.time)) ?? byTime.get(param.time) ?? null;
    const index = typeof param.logical === "number" ? Math.round(param.logical) : -1;
    return index >= 0 && index < candles.length ? candles[index] : null;
  };
  assert.equal(barCandle({ time: candles[3].time, logical: 3 }).time, candles[3].time);
  assert.equal(barCandle({ time: candles[3].time + 0.4, logical: 3 }).time, candles[3].time, "дробное время приводится к бару");
  assert.equal(barCandle({ logical: 5.4 }).time, candles[5].time, "без времени берётся ближайший индекс");
  assert.equal(barCandle({ logical: -1 }), null);
  assert.equal(barCandle({ logical: 999 }), null);
});

test("границы бакетов по МСК: 4ч от открытия сессии, неделя с понедельника", () => {
  // Свеча 07:00 UTC = 10:00 МСК — первый 4ч-бар дня должен начинаться здесь.
  const at = (iso) => Math.floor(Date.parse(iso) / 1000);
  const msk = (time) => new Date(time * 1000).toLocaleString("ru-RU", { timeZone: "Europe/Moscow", weekday: "short", hour: "2-digit", minute: "2-digit" });
  assert.equal(msk(__mskBucket(at("2026-11-24T07:00:00Z"), 14400, 10)), "вт 10:00");
  assert.equal(msk(__mskBucket(at("2026-11-24T10:30:00Z"), 14400, 10)), "вт 10:00");
  assert.equal(msk(__mskBucket(at("2026-11-24T13:00:00Z"), 14400, 10)), "вт 14:00");
  // Дневной бар начинается в 00:00 МСК, а не в 03:00.
  assert.equal(msk(__mskBucket(at("2026-11-24T21:00:00Z"), 86400)), "ср 00:00");
  // Недельный — с понедельника 00:00 МСК.
  assert.equal(msk(__mskWeekBucket(at("2026-11-24T09:00:00Z"))), "пн 00:00");
  assert.equal(__mskWeekBucket(at("2026-11-24T09:00:00Z")), __mskWeekBucket(at("2026-11-26T20:00:00Z")));
});

test("SMC: дневные и недельные уровни считаются по МСК, а не по UTC", async () => {
  const { computeSmc, sanitizeSmcSettings, DEFAULT_SMC } = await import("../src/lib/smc.ts");
  const settings = sanitizeSmcSettings(DEFAULT_SMC);
  const hourly = [];
  // Три полных торговых дня по МСК: 10:00–23:00, с разными экстремумами.
  for (let day = 0; day < 3; day++) {
    for (let hour = 10; hour < 23; hour++) {
      const time = Math.floor(Date.parse("2026-11-16T00:00:00Z") / 1000) + day * 86400 + (hour - 3) * 3600;
      const base = 100 + day * 5 + hour * 0.1;
      hourly.push({ time, open: base, high: base + (hour === 12 ? 3 : 0.5), low: base - (hour === 18 ? 3 : 0.5), close: base, volume: 1000 });
    }
  }
  const overlay = computeSmc(hourly, settings, "1h");
  const pdh = overlay.stats.levels.find(level => level.name === "PDH");
  assert.ok(pdh, "PDH посчитан");
  const lastDay = hourly.filter(c => c.time >= hourly.at(-1).time - 13 * 3600);
  const previousDay = hourly.filter(c => c.time >= hourly.at(-1).time - 37 * 3600 && c.time < hourly.at(-1).time - 13 * 3600);
  assert.equal(pdh.price, Math.max(...previousDay.map(c => c.high)), "PDH — максимум предыдущего дня по МСК");
  assert.notEqual(pdh.price, Math.max(...lastDay.map(c => c.high)));
});

test("метрики «Год» на часовом графике покрывают календарный год", async () => {
  const { computeMetrics } = await import("../src/lib/metrics.ts");
  const hourly = [];
  const start = Math.floor(Date.parse("2025-01-01T00:00:00Z") / 1000);
  for (let i = 0; i < 6000; i++) {
    const base = 100 + Math.sin(i / 40) * 20;
    hourly.push({ time: start + i * 3600, open: base, high: base + 1, low: base - 1, close: base, volume: 100 });
  }
  const metrics = computeMetrics(hourly, "1h");
  assert.equal(metrics.timeframe, "1h");
  // Окно в 365 дней: диапазон заметно шире, чем «365 последних часов».
  assert.ok(metrics.high52 - metrics.low52 > 30, `диапазон ${metrics.low52}–${metrics.high52}`);
});

test("брокер: свободная маржа учитывает все открытые позиции", async () => {
  const { emptyAccount, openPosition, START_BALANCE } = await import("../src/lib/broker.ts");
  let account = emptyAccount();
  // Почти вся маржа занята лонгом по SBER.
  const almostAll = Math.floor((START_BALANCE * 3 * 0.98) / (267.5 * 10));
  const first = openPosition(account, { symbol: "SBER", side: "long", lots: almostAll, price: 267.5 });
  assert.ok(first.ok, first.error);
  account = first.account;
  // Вторая позиция по другому инструменту должна упереться в маржу, а не пройти бесплатно.
  const second = openPosition(account, { symbol: "GAZP", side: "long", lots: Math.floor((START_BALANCE * 3 * 0.1) / (140 * 10)), price: 140 });
  assert.equal(second.ok, false, "свободной маржи на вторую позицию не осталось");
  assert.match(second.error, /Недостаточно средств/);
});

test("брокер: доливка усредняет уровень, тейк не оказывается по ту сторону входа", async () => {
  const { emptyAccount, openPosition } = await import("../src/lib/broker.ts");
  const first = openPosition(emptyAccount(), { symbol: "SBER", side: "long", lots: 1, price: 100, take: 110 });
  assert.ok(first.ok);
  const second = openPosition(first.account, { symbol: "SBER", side: "long", lots: 1, price: 120 });
  assert.ok(second.ok);
  const position = second.position;
  // Средняя цена входа сдвинулась к 110, старый тейк 110 стал бессмысленным.
  assert.equal(Math.round(position.entry * 100) / 100, 110);
  assert.equal(position.take, undefined, "невалидный после усреднения тейк снимается");
  // Новый тейк, заданный при доливке, сохраняется.
  const third = openPosition(second.account, { symbol: "SBER", side: "long", lots: 1, price: 120, take: 140 });
  assert.ok(third.ok);
  assert.equal(third.position.take, 140);
});

test("котировки без живых данных не подменяются выдуманными", async () => {
  // Серверная функция getQuotes работает только в Next (server-only), поэтому проверяем
  // главное правило на клиентских хелперах: демо-котировка не попадает в интерфейс.
  const { demoQuote, getInstrument } = await import("../src/lib/market.ts");
  const quote = demoQuote(getInstrument("CNTLP"));
  assert.equal(quote.source, "demo");
  const live = (quotes, symbol) => quotes.find(q => q.symbol === symbol && q.source !== "demo") ?? null;
  assert.equal(live([quote], "CNTLP"), null, "демо-котировка не считается живой");
});

test("закрытие прошлой сессии: сегодняшний бар не считается предыдущим закрытием", async () => {
  const { previousSessionClose } = await import("../src/lib/market.ts");
  const day = (iso) => Math.floor(Date.parse(iso) / 1000);
  const candles = [
    { time: day("2026-11-20T00:00:00+03:00"), open: 1, high: 1, low: 1, close: 250.3, volume: 0 },
    { time: day("2026-11-23T00:00:00+03:00"), open: 1, high: 1, low: 1, close: 289.1, volume: 0 },
    { time: day("2026-11-24T00:00:00+03:00"), open: 1, high: 1, low: 1, close: 266.6, volume: 0 },
    { time: day("2026-11-25T00:00:00+03:00"), open: 1, high: 1, low: 1, close: 276.5, volume: 0 },
  ];
  // Вечер 25 ноября: сегодняшний бар есть, предыдущее закрытие — 24-е.
  assert.equal(previousSessionClose(candles, Date.parse("2026-11-25T19:00:00Z")), 266.6);
  // Утро 26 ноября, бара за сегодня ещё нет: предыдущее закрытие — 25-е.
  assert.equal(previousSessionClose(candles, Date.parse("2026-11-26T06:00:00Z")), 276.5);
  // Пустая история — «нет данных», а не ноль.
  assert.equal(previousSessionClose([], Date.now()), null);
});
