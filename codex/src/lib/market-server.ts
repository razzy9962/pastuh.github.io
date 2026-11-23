import "server-only";
import { tInvestRequest } from "./tinvest-client";
import { INSTRUMENTS, demoQuote, generateCandles, getInstrument, type Candle, type DataSource, type Quote, type Timeframe } from "./market";

type Quotation = { units?: string | number; nano?: number };
type TInstrument = { ticker: string; classCode: string; figi: string; uid: string };
type CacheEntry<T> = { value: T; until: number };
const candleCache = new Map<string, CacheEntry<{ candles: Candle[]; source: DataSource; asOf: string }>>();
let quotesCache: CacheEntry<Quote[]> | undefined;
let instrumentCache: CacheEntry<TInstrument[]> | undefined;
let tinvestRetryAt = 0;
const numeric = (q?: Quotation) => Number(q?.units ?? 0) + Number(q?.nano ?? 0) / 1e9;

async function tinvest<T>(service: string, method: string, body: unknown): Promise<T> {
  const token = process.env.TINKOFF_TOKEN;
  if (!token || Date.now() < tinvestRetryAt) throw new Error("T-Invest unavailable");
  try {
    return await tInvestRequest<T>(service, method, body, token);
  } catch { tinvestRetryAt = Date.now() + 60000; throw new Error("T-Invest unavailable"); }
}

async function getTInstruments() {
  if (instrumentCache && instrumentCache.until > Date.now()) return instrumentCache.value;
  const result = await tinvest<{ instruments: TInstrument[] }>("InstrumentsService", "Shares", { instrumentStatus: "INSTRUMENT_STATUS_BASE" });
  const instruments = result.instruments.filter(i => i.classCode === "TQBR" && INSTRUMENTS.some(item => item.symbol === i.ticker));
  instrumentCache = { value: instruments, until: Date.now() + 14400000 };
  return instruments;
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
  for (const response of results) {
    if (response.status !== "fulfilled") continue;
    const previous = new Map(rows(response.value.securities).map(r => [r.SECID, Number(r.PREVPRICE)]));
    for (const row of rows(response.value.marketdata)) {
      const symbol = String(row.SECID);
      if (["USD000UTSTOM", "EUR_RUB__TOM"].includes(symbol) || !INSTRUMENTS.some(i => i.symbol === symbol) || result.some(q => q.symbol === symbol)) continue;
      const price = Number(row.LAST || row.CURRENTVALUE || row.LCURRENTPRICE);
      if (!(price > 0)) continue;
      const prev = previous.get(symbol);
      const change = row.LASTTOPREVPRICE != null ? Number(row.LASTTOPREVPRICE) : prev ? (price / prev - 1) * 100 : 0;
      result.push({ symbol, price, change, absolute: prev ? price - prev : Number(row.CHANGE || 0), high: Number(row.HIGH || price), low: Number(row.LOW || price), volume: Number(row.VOLTODAY || 0), source: "moex", time: String(row.UPDATETIME ?? "") });
    }
  }
  return result;
}

export async function getQuotes(): Promise<Quote[]> {
  if (quotesCache && quotesCache.until > Date.now()) return quotesCache.value;
  const live: Quote[] = [];
  try {
    const instruments = await getTInstruments();
    const ids = instruments.map(i => i.uid);
    if (!ids.length) throw new Error("No matching instruments");
    const [last, previous] = await Promise.all([
      tinvest<{ lastPrices: { figi: string; instrumentUid: string; price: Quotation; time: string }[] }>("MarketDataService", "GetLastPrices", { instrumentId: ids, lastPriceType: "LAST_PRICE_EXCHANGE" }),
      tinvest<{ closePrices: { figi: string; instrumentUid: string; price?: Quotation; closePrice?: Quotation }[] }>("MarketDataService", "GetClosePrices", { instruments: ids.map(instrumentId => ({ instrumentId })) }),
    ]);
    for (const entry of last.lastPrices) {
      const item = instruments.find(i => i.uid === entry.instrumentUid || i.figi === entry.figi);
      const price = numeric(entry.price);
      if (!item || price <= 0) continue;
      const closing = previous.closePrices?.find(i => i.instrumentUid === entry.instrumentUid || i.figi === entry.figi);
      const prev = numeric(closing?.price ?? closing?.closePrice);
      live.push({ symbol: item.ticker, price, change: prev > 0 ? (price / prev - 1) * 100 : 0, absolute: prev > 0 ? price - prev : 0, high: price, low: price, volume: 0, source: "tinvest", time: entry.time });
    }
  } catch { /* Provider errors never include credentials in the response. */ }
  try { const moex = await moexQuotes(); for (const q of moex) if (!live.some(i => i.symbol === q.symbol)) live.push(q); } catch { /* Explicitly labelled demo fallback. */ }
  const value = INSTRUMENTS.map(i => live.find(q => q.symbol === i.symbol) ?? demoQuote(i));
  quotesCache = { value, until: Date.now() + 25000 };
  return value;
}

const INTERVALS: Record<Timeframe, { interval: string; days: number; moex: number; factor: number }> = {
  "1m": { interval: "CANDLE_INTERVAL_1_MIN", days: 1, moex: 1, factor: 1 },
  "5m": { interval: "CANDLE_INTERVAL_5_MIN", days: 7, moex: 1, factor: 5 },
  "15m": { interval: "CANDLE_INTERVAL_15_MIN", days: 14, moex: 1, factor: 15 },
  "1h": { interval: "CANDLE_INTERVAL_HOUR", days: 30, moex: 60, factor: 1 },
  "4h": { interval: "CANDLE_INTERVAL_4_HOUR", days: 90, moex: 60, factor: 4 },
  "1d": { interval: "CANDLE_INTERVAL_DAY", days: 330, moex: 24, factor: 1 },
  "1w": { interval: "CANDLE_INTERVAL_WEEK", days: 1400, moex: 7, factor: 1 },
};

function aggregate(candles: Candle[], seconds: number): Candle[] {
  const result: Candle[] = [];
  for (const candle of candles) {
    const time = Math.floor(candle.time / seconds) * seconds;
    const last = result[result.length - 1];
    if (last && last.time === time) { last.high = Math.max(last.high, candle.high); last.low = Math.min(last.low, candle.low); last.close = candle.close; last.volume += candle.volume; }
    else result.push({ ...candle, time });
  }
  return result;
}

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
  if (item.kind === "stock" || symbol === "CNYRUB_TOM") {
    try {
      const response = await tinvest<{ candles: { time: string; open: Quotation; high: Quotation; low: Quotation; close: Quotation; volume: string }[] }>("MarketDataService", "GetCandles", { instrumentId: `${symbol}_${item.kind === "stock" ? "TQBR" : "CETS"}`, from: from.toISOString(), to: to.toISOString(), interval: config.interval, limit: timeframe === "1w" ? 300 : timeframe === "4h" ? 700 : 2400 });
      candles = response.candles.map(c => ({ time: Math.floor(Date.parse(c.time) / 1000), open: numeric(c.open), high: numeric(c.high), low: numeric(c.low), close: numeric(c.close), volume: Number(c.volume) }));
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
          const time = Date.parse(config.moex >= 7 && config.moex !== 60 ? `${begin.slice(0, 10)}T00:00:00Z` : `${begin.replace(" ", "T")}+03:00`) / 1000;
          if (Number(r.close) > 0 && Number.isFinite(time)) candles.push({ time, open: Number(r.open), high: Number(r.high), low: Number(r.low), close: Number(r.close), volume: Number(r.volume) / item.lot });
        }
        if (batch.length < 500) break;
      }
      candles = [...new Map(candles.map(c => [c.time, c])).values()].sort((a, b) => a.time - b.time);
      if (config.factor > 1) candles = aggregate(candles, (config.moex === 60 ? 3600 : 60) * config.factor);
      if (candles.length) source = "moex";
    } catch { candles = []; }
  }
  if (!candles.length) candles = generateCandles(symbol, timeframe);
  const value = { candles: candles.slice(-350), source, asOf: new Date().toISOString() };
  candleCache.set(key, { value, until: Date.now() + 25000 });
  return value;
}
