import "server-only";
import { tInvestRequest } from "./tinvest-client";
import { DEFAULT_SETTINGS, INSTRUMENTS, aggregateCandles, getInstrument, previousSessionClose, sanitizeCandles, type Candle, type DataSource, type Instrument, type Quote, type Timeframe } from "./market";

const MSK_OFFSET = 3 * 3600;

type Quotation = { units?: string | number; nano?: number };
type CacheEntry<T> = { value: T; until: number };
// Кеш свечей ограничен по размеру: на бесплатном инстансе Render доступно 512 МБ,
// а сочетаний «инструмент × таймфрейм» может быть много. Держим не больше 40 наборов.
const CANDLE_CACHE_LIMIT = 24;
const candleCache = new Map<string, CacheEntry<{ candles: Candle[]; source: DataSource; asOf: string }>>();
function rememberCandles(key: string, entry: CacheEntry<{ candles: Candle[]; source: DataSource; asOf: string }>) {
  candleCache.delete(key);
  candleCache.set(key, entry);
  while (candleCache.size > CANDLE_CACHE_LIMIT) {
    const oldest = candleCache.keys().next().value;
    if (oldest === undefined) break;
    candleCache.delete(oldest);
  }
}
let quotesCache: CacheEntry<Quote[]> | undefined;
const numeric = (q?: Quotation) => Number(q?.units ?? 0) + Number(q?.nano ?? 0) / 1e9;
// Ответы по идентификаторам вида SBER_TQBR приходят без поля ticker — вытаскиваем тикер из id.
const tickerFromId = (id?: string) => (id && id.includes("_") ? id.slice(0, id.indexOf("_")) : id);
let indexCache: CacheEntry<Map<string, string>> | undefined;

/** Тикер → uid для индексов MOEX из сервиса Indicatives (IMOEX, RTSI, RGBI…). */
async function getIndexIds(): Promise<Map<string, string>> {
  if (indexCache && indexCache.until > Date.now()) return indexCache.value;
  const result = await tinvest<{ instruments: { ticker: string; uid: string; instrumentKind?: string }[] }>("InstrumentsService", "Indicatives", {});
  const map = new Map<string, string>();
  for (const item of result.instruments) if (item.instrumentKind === "INSTRUMENT_TYPE_INDEX" || item.ticker) map.set(item.ticker, item.uid);
  indexCache = { value: map, until: Date.now() + 43200000 };
  return map;
}

// Токен никогда не хранится в исходниках: на локальной машине и хостинге
// он должен передаваться только через переменную окружения.
async function tinvest<T>(service: string, method: string, body: unknown): Promise<T> {
  const token = process.env.TINKOFF_TOKEN?.trim();
  if (!token) throw new Error("T-Invest token is not set");
  try {
    return await tInvestRequest<T>(service, method, body, token);
  } catch (error) {
    // Причина сбоя видна в логах Render: без неё «всё демо» невозможно диагностировать.
    console.warn(`[tinvest] ${service}/${method}: ${String(error instanceof Error ? error.message : error).slice(0, 200)}`);
    throw new Error("T-Invest unavailable");
  }
}

type IssBlock = { columns: string[]; data: unknown[][] };
type IssResponse = { marketdata?: IssBlock; securities?: IssBlock; candles?: IssBlock };
function rows(block?: IssBlock): Record<string, unknown>[] { return block?.data.map(row => Object.fromEntries(block.columns.map((key, i) => [key, row[i]]))) ?? []; }
async function iss(path: string, parameters: Record<string, string> = {}): Promise<IssResponse> {
  const url = new URL(`https://iss.moex.com/iss/${path}.json`);
  url.searchParams.set("iss.meta", "off");
  Object.entries(parameters).forEach(([key, value]) => url.searchParams.set(key, value));
  const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(6000) });
  if (!response.ok) throw new Error("MOEX unavailable");
  return response.json();
}

async function moexQuotes(): Promise<Quote[]> {
  const paths = ["engines/stock/markets/shares/boards/TQBR/securities", "engines/stock/markets/index/securities", "engines/currency/markets/selt/boards/CETS/securities"];
  const results = await Promise.allSettled(paths.map(path => iss(path, { "iss.only": "marketdata,securities", "marketdata.columns": "SECID,LAST,CURRENTVALUE,LCURRENTPRICE,LASTTOPREVPRICE,CHANGE,HIGH,LOW,VOLTODAY,UPDATETIME", "securities.columns": "SECID,PREVPRICE" })));
  const result: Quote[] = [];
  const catalog = new Set(INSTRUMENTS.map(i => i.symbol));
  const seen = new Set<string>();
  for (const response of results) {
    if (response.status !== "fulfilled") continue;
    const previous = new Map(rows(response.value.securities).map(r => [r.SECID, Number(r.PREVPRICE)]));
    for (const row of rows(response.value.marketdata)) {
      const symbol = String(row.SECID);
      if (["USD000UTSTOM", "EUR_RUB__TOM"].includes(symbol) || !catalog.has(symbol) || seen.has(symbol)) continue;
      seen.add(symbol);
      const price = Number(row.LAST || row.CURRENTVALUE || row.LCURRENTPRICE);
      if (!(price > 0)) continue;
      const prev = previous.get(symbol);
      const change = row.LASTTOPREVPRICE != null ? Number(row.LASTTOPREVPRICE) : prev ? (price / prev - 1) * 100 : 0;
      result.push({ symbol, price, change, absolute: prev ? price - prev : Number(row.CHANGE || 0), high: Number(row.HIGH || price), low: Number(row.LOW || price), volume: Number(row.VOLTODAY || 0), source: "moex", time: String(row.UPDATETIME ?? "") });
    }
  }
  return result;
}

/**
 * Закрытие предыдущей торговой сессии для каждого инструмента.
 *
 * «Изменение за день» нельзя считать по `GetClosePrices`: провайдер отдаёт там не всегда
 * закрытие прошлого дня (для SMLT приходило 276,69 вместо 266,60), и в интерфейсе
 * появлялись неверные проценты. Дневные свечи дают точное значение: последний бар —
 * текущие сутки, предыдущий — прошлая сессия (а если текущего бара ещё нет, предыдущее
 * закрытие и есть последний бар).
 *
 * 258 отдельных запросов сразу — это лишняя нагрузка, поэтому справочник обновляется
 * порциями (по 20 инструментов за цикл котировок) и живёт 10 минут: за пару минут
 * корректные значения есть у всего каталога, а провайдер не получает шквал запросов.
 */
const REFERENCE_TTL = 600000;
const REFERENCE_SWEEP = 60;
const reference = new Map<string, { close: number; at: number }>();
let referenceCursor = 0;
let referenceSweep: Promise<void> | null = null;

// Порядок важен: сначала инструменты списка наблюдения по умолчанию и первый эшелон —
// именно их пользователь видит сразу. Остальные подтягиваются порциями в фоне.
const referenceOrder = [
  ...DEFAULT_SETTINGS.watchlist,
  ...INSTRUMENTS.filter(i => i.tier === 1).map(i => i.symbol),
  ...INSTRUMENTS.filter(i => i.kind !== "stock").map(i => i.symbol),
  ...INSTRUMENTS.map(i => i.symbol),
].filter((symbol, index, list) => list.indexOf(symbol) === index);

async function refreshReferenceBatch(): Promise<void> {
  const symbols = referenceOrder;
  const batch: string[] = [];
  for (let step = 0; step < symbols.length && batch.length < REFERENCE_SWEEP; step++) {
    const symbol = symbols[(referenceCursor + step) % symbols.length];
    const entry = reference.get(symbol);
    if (!entry || Date.now() - entry.at > REFERENCE_TTL) batch.push(symbol);
  }
  referenceCursor = (referenceCursor + REFERENCE_SWEEP) % symbols.length;
  if (!batch.length) return;
  const from = new Date(Date.now() - 12 * 86400000).toISOString();
  const to = new Date(Date.now() + 86400000).toISOString();
  await Promise.allSettled(batch.map(async symbol => {
    const item = getInstrument(symbol);
    const instrumentId = item.kind === "index" ? (await getIndexIds()).get(symbol) : `${symbol}_${item.kind === "stock" ? "TQBR" : "CETS"}`;
    if (!instrumentId) return;
    const response = await tinvest<{ candles: { time: string; open: Quotation; high: Quotation; low: Quotation; close: Quotation }[] }>("MarketDataService", "GetCandles", {
      instrumentId, from, to, interval: "CANDLE_INTERVAL_DAY", limit: 30,
    });
    const candles = sanitizeCandles(response.candles.map(c => ({ time: Math.floor(Date.parse(c.time) / 1000), open: numeric(c.open), high: numeric(c.high), low: numeric(c.low), close: numeric(c.close), volume: 0 })));
    const previous = previousSessionClose(candles);
    if (previous == null) return;
    reference.set(symbol, { close: previous, at: Date.now() });
  }));
}

const quoteMap = new Map<string, Quote>();
const quoteSources = new Map<string, DataSource>();

/**
 * Котировки всего каталога.
 * Запросы идут напрямую по идентификаторам вида `SBER_TQBR`: каталог акций Т-Инвест
 * весит около 3 МБ и на медленном канале не успевает загрузиться (из-за этого весь
 * терминал раньше показывал демо-цены). Индексы MOEX живут в отдельном сервисе
 * Indicatives — его список маленький и кешируется надолго.
 */
export async function getQuotes(force = false): Promise<Quote[]> {
  if (!force && quotesCache && quotesCache.until > Date.now()) return quotesCache.value;
  // Справочник прошлых закрытий обновляется порциями в фоне; первый цикл ждём,
  // чтобы самый первый ответ уже содержал корректное изменение за день.
  referenceSweep = referenceSweep ?? refreshReferenceBatch().catch(() => undefined).finally(() => { referenceSweep = null; });
  if (!reference.size) await referenceSweep;
  // Последние удачные котировки держим в резерве: кратковременный сбой провайдера
  // не должен переключать панель на демонстрационные значения.
  const live: Quote[] = [...quoteMap.values()];
  try {
    const ids = INSTRUMENTS.filter(i => i.kind !== "index").map(i => `${i.symbol}_${i.kind === "currency" ? "CETS" : "TQBR"}`);
    const batches: string[][] = [];
    for (let index = 0; index < ids.length; index += 60) batches.push(ids.slice(index, index + 60));
    type PriceRow = { figi: string; instrumentUid: string; ticker?: string; classCode?: string; price?: Quotation; time?: string };
    type PriceResponse = { lastPrices: PriceRow[] };
    type CloseResponse = { closePrices: PriceRow[] };
    // Пакет, который провайдер не отдал с первого раза, повторяем поштучно — но только
    // по одной причине: шлюз Т-Инвест иногда отвечает 404 на конкретный инструмент внутри
    // пакета. Сетевые сбои (таймаут, обрыв) повторять поштучно нельзя: это 60 запросов
    // вместо одного, лишний трафик и риск упереться в лимит провайдера.
    const loadPrices = async <T,>(batch: string[], call: (ids: string[]) => Promise<T>): Promise<T[]> => {
      try { return [await call(batch)]; } catch (error) {
        if (!/status 404/.test(String(error instanceof Error ? error.message : error))) return [];
        const results: T[] = [];
        for (const id of batch.slice(0, 20)) {
          try { results.push(await call([id])); } catch { /* Инструмент недоступен — просто без цены. */ }
        }
        return results;
      }
    };
    const [lastParts, closeParts] = await Promise.all([
      Promise.all(batches.map(batch => loadPrices(batch, ids => tinvest<PriceResponse>("MarketDataService", "GetLastPrices", { instrumentId: ids, lastPriceType: "LAST_PRICE_EXCHANGE" })))),
      Promise.all(batches.map(batch => loadPrices(batch, ids => tinvest<CloseResponse>("MarketDataService", "GetClosePrices", { instruments: ids.map(instrumentId => ({ instrumentId })) })))),
    ]);
    const last = lastParts.flatMap(list => list.flatMap(part => part.lastPrices ?? []));
    // «Цена закрытия» из GetClosePrices приходит не всегда за предыдущий торговый день,
    // поэтому точный ориентир «за день» берём из дневных свечей (справочник reference),
    // а этот ответ остаётся резервом, когда дневной истории нет.
    const close = closeParts.flatMap(list => list.flatMap(part => part.closePrices ?? []));

    // Сопоставляем ответ с нашим каталогом по тикеру: провайдер возвращает ticker у акций и валют.
    const bySymbol = new Map<string, Instrument>();
    for (const instrument of INSTRUMENTS) bySymbol.set(instrument.symbol, instrument);
    const closeBySymbol = new Map<string, number>();
    for (const row of close) {
      const ticker = row.ticker ?? tickerFromId(row.instrumentUid);
      const value = numeric(row.price);
      if (ticker && value > 0) closeBySymbol.set(ticker, value);
    }
    // Точное закрытие прошлой сессии из дневных свечей приоритетнее ответа GetClosePrices.
    for (const [symbol, entry] of reference) closeBySymbol.set(symbol, entry.close);
    for (const row of last) {
      const ticker = row.ticker ?? tickerFromId(row.instrumentUid);
      const instrument = ticker ? bySymbol.get(ticker) : undefined;
      const price = numeric(row.price);
      if (!instrument || price <= 0) continue;
      const prev = closeBySymbol.get(instrument.symbol) ?? 0;
      live.push({ symbol: instrument.symbol, price, change: prev > 0 ? (price / prev - 1) * 100 : 0, changeKnown: prev > 0, absolute: prev > 0 ? price - prev : 0, high: price, low: price, volume: 0, source: "tinvest", time: row.time ?? new Date().toISOString() });
    }

    // Индексы: IMOEX, RTSI, RGBI и другие бумаги из каталога Indicatives.
    const indexSymbols = INSTRUMENTS.filter(i => i.kind === "index").map(i => i.symbol);
    if (indexSymbols.length) {
      const indexIds = await getIndexIds();
      const wanted = indexSymbols.filter(symbol => indexIds.has(symbol)).map(symbol => indexIds.get(symbol)!);
      if (wanted.length) {
        const [indexLast, indexClose] = await Promise.allSettled([
          tinvest<PriceResponse>("MarketDataService", "GetLastPrices", { instrumentId: wanted, lastPriceType: "LAST_PRICE_EXCHANGE" }),
          tinvest<CloseResponse>("MarketDataService", "GetClosePrices", { instruments: wanted.map(instrumentId => ({ instrumentId })) }),
        ]);
        const indexCloseById = new Map((indexClose.status === "fulfilled" ? indexClose.value.closePrices ?? [] : []).map(row => [row.instrumentUid, numeric(row.price)]));

        if (indexLast.status === "fulfilled") for (const row of indexLast.value.lastPrices ?? []) {
          const ticker = [...indexIds.entries()].find(([, uid]) => uid === row.instrumentUid)?.[0];
          const price = numeric(row.price);
          if (!ticker || price <= 0) continue;
          const prev = reference.get(ticker)?.close ?? indexCloseById.get(row.instrumentUid) ?? 0;
          live.push({ symbol: ticker, price, change: prev > 0 ? (price / prev - 1) * 100 : 0, changeKnown: prev > 0, absolute: prev > 0 ? price - prev : 0, high: price, low: price, volume: 0, source: "tinvest", time: row.time ?? new Date().toISOString() });
        }
      }
    }
    if (!last.length) throw new Error("No prices");
  } catch (error) { console.warn(`[quotes] T-Invest: ${String(error instanceof Error ? error.message : error).slice(0, 200)}`); }
  try { const moex = await moexQuotes(); for (const q of moex) if (!live.some(i => i.symbol === q.symbol)) live.push(q); } catch { /* MOEX ISS — резервный источник; если и он молчит, ниже вернём пустой список. */ }
  const seen = new Set<string>();
  for (const quote of live) {
    const previous = quoteSources.get(quote.symbol);
    // Данные T-Invest приоритетнее MOEX; демонстрационные значения не перетирают живые.
    if (quote.source === "tinvest" || previous !== "tinvest") {
      quoteMap.set(quote.symbol, quote);
      quoteSources.set(quote.symbol, quote.source);
    }
    seen.add(quote.symbol);
  }
  // Только настоящие котировки. Инструмент без живых данных не попадает в ответ,
  // и клиент честно рисует прочерк — выдуманных цен в терминале нет.
  const value = INSTRUMENTS.flatMap(i => { const quote = quoteMap.get(i.symbol); return quote ? [quote] : []; });
  // Частичный ответ (часть пакетов не дошла) кешируем короче: иначе список наблюдения
  // висел с прочерками до следующего опроса, хотя данные уже были доступны.
  const complete = value.length >= INSTRUMENTS.length * 0.8;
  quotesCache = { value, until: Date.now() + (complete ? 30000 : 8000) };
  return value;
}

// days — запрашиваемое окно истории, keep — сколько баров показываем на графике.
const INTERVALS: Record<Timeframe, { interval: string; days: number; keep: number; moex: number; factor: number }> = {
  "1m": { interval: "CANDLE_INTERVAL_1_MIN", days: 3, keep: 900, moex: 1, factor: 1 },
  "5m": { interval: "CANDLE_INTERVAL_5_MIN", days: 20, keep: 1000, moex: 1, factor: 5 },
  "15m": { interval: "CANDLE_INTERVAL_15_MIN", days: 40, keep: 1000, moex: 1, factor: 15 },
  "1h": { interval: "CANDLE_INTERVAL_HOUR", days: 365, keep: 1200, moex: 60, factor: 1 },
  // Интервала 4 часа у Т-Инвест нет — часовые свечи агрегируются вручную.
  "4h": { interval: "CANDLE_INTERVAL_HOUR", days: 730, keep: 1000, moex: 60, factor: 4 },
  "1d": { interval: "CANDLE_INTERVAL_DAY", days: 2000, keep: 1000, moex: 24, factor: 1 },
  // Дальше ~2000 дней провайдер по неделям уже не отдаёт данные.
  "1w": { interval: "CANDLE_INTERVAL_WEEK", days: 2000, keep: 400, moex: 7, factor: 1 },
};


export async function getCandles(symbol: string, timeframe: Timeframe) {
  const key = `${symbol}:${timeframe}`;
  const cached = candleCache.get(key);
  if (cached && cached.until > Date.now()) return cached.value;
  const config = INTERVALS[timeframe];
  const item = getInstrument(symbol);
  const to = new Date();
  const from = new Date(to.getTime() - config.days * 86400000);
  let candles: Candle[] = [];
  let source: DataSource = "demo";
  if (item.kind === "stock" || item.kind === "index" || symbol === "CNYRUB_TOM") {
    try {
      // Индексы MOEX доступны только по uid из сервиса Indicatives, бумаги и валюта — по TICKER_CLASSCODE.
      const instrumentId = item.kind === "index" ? (await getIndexIds()).get(symbol) : `${symbol}_${item.kind === "stock" ? "TQBR" : "CETS"}`;
      if (!instrumentId) throw new Error("Index not found");
      const response = await tinvest<{ candles: { time: string; open: Quotation; high: Quotation; low: Quotation; close: Quotation; volume: string }[] }>("MarketDataService", "GetCandles", { instrumentId, from: from.toISOString(), to: to.toISOString(), interval: config.interval, limit: timeframe === "1w" ? 400 : 2400 });
      candles = sanitizeCandles(response.candles.map(c => ({ time: Math.floor(Date.parse(c.time) / 1000), open: numeric(c.open), high: numeric(c.high), low: numeric(c.low), close: numeric(c.close), volume: Number(c.volume) })));
      if (candles.length && timeframe === "4h") candles = aggregateCandles(candles, 4 * 3600, true);
      if (candles.length) source = "tinvest";
    } catch { /* Try the exchange's public delayed feed. */ }
  }
  if (!candles.length && !["USD000UTSTOM", "EUR_RUB__TOM"].includes(symbol)) {
    try {
      const path = item.kind === "stock" ? "engines/stock/markets/shares/boards/TQBR" : item.kind === "index" ? "engines/stock/markets/index" : "engines/currency/markets/selt/boards/CETS";
      const moexFrom = config.moex === 1 ? new Date(to.getTime() - 3 * 86400000) : from;
      for (let start = 0; start < 5000; start += 500) {
        const response = await iss(`${path}/securities/${symbol}/candles`, { from: moexFrom.toISOString().slice(0, 10), till: to.toISOString().slice(0, 10), interval: String(config.moex), start: String(start) });
        const batch = rows(response.candles);
        for (const r of batch) {
          const begin = String(r.begin);
          // ISS отдаёт время начала бара в московском времени без смещения, а для дневных
          // и недельных интервалов — только дату. Раньше здесь стояло Z (UTC) для
          // дневных баров, и каждый день на графике сдвигался на 03:00 МСК.
          const time = Date.parse(config.moex >= 7 && config.moex !== 60 ? `${begin.slice(0, 10)}T00:00:00+03:00` : `${begin.replace(" ", "T")}+03:00`) / 1000;
          if (Number(r.close) > 0 && Number.isFinite(time)) candles.push({ time, open: Number(r.open), high: Number(r.high), low: Number(r.low), close: Number(r.close), volume: Number(r.volume) / item.lot });
        }
        if (batch.length < 500) break;
      }
      candles = [...new Map(candles.map(c => [c.time, c])).values()].sort((a, b) => a.time - b.time);
      if (config.factor > 1) candles = aggregateCandles(candles, (config.moex === 60 ? 3600 : 60) * config.factor, true);
      if (candles.length) source = "moex";
    } catch { candles = []; }
  }
  // Ничего не пришло — отдаём пустой набор. Раньше здесь подставлялись «правдоподобные»
  // синтетические бары, и терминал показывал выдуманный график как настоящий.
  const value = { candles: candles.slice(-config.keep), source: candles.length ? source : "demo" as DataSource, asOf: new Date().toISOString() };
  // Пустой ответ кешируем ненадолго: провайдер может восстановиться через несколько секунд.
  rememberCandles(key, { value, until: Date.now() + (candles.length ? 30000 : 10000) });
  return value;
}
