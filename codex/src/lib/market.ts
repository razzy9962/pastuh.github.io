export type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d" | "1w";
export type DataSource = "tinvest" | "moex" | "demo";
export type InstrumentKind = "stock" | "index" | "currency";
export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
export type Instrument = { symbol: string; name: string; fullName: string; sector: string; kind: InstrumentKind; price: number; change: number; color: string; mark: string; description: string; lot: number; step: number };
export type Quote = { symbol: string; price: number; change: number; absolute: number; high: number; low: number; volume: number; source: DataSource; time?: string };
export type Indicator = { id: string; name: string; type: "sma" | "ema" | "bb" | "rsi"; period: number; color: string; enabled: boolean; custom?: boolean; formula?: string };
export type Drawing = { id: string; type: "horizontal" | "trend"; price: number; time: number; endPrice?: number; endTime?: number; color: string };
export type WorkspaceSettings = { symbol: string; timeframe: Timeframe; watchlist: string[]; indicators: Indicator[]; chartType: "candles" | "line" | "area"; drawings: Record<string, Drawing[]>; showVolume: boolean };

export const TIMEFRAMES: { value: Timeframe; label: string; seconds: number }[] = [
  { value: "1m", label: "1м", seconds: 60 }, { value: "5m", label: "5м", seconds: 300 },
  { value: "15m", label: "15м", seconds: 900 }, { value: "1h", label: "1ч", seconds: 3600 },
  { value: "4h", label: "4ч", seconds: 14400 }, { value: "1d", label: "1Д", seconds: 86400 },
  { value: "1w", label: "1Н", seconds: 604800 },
];

export const INSTRUMENTS: Instrument[] = [
  { symbol: "SBER", name: "Сбербанк", fullName: "ПАО Сбербанк", sector: "Финансы", kind: "stock", price: 318.64, change: 1.24, color: "#269d58", mark: "S", description: "Крупнейший универсальный банк России. Банковские, инвестиционные и цифровые сервисы для частных клиентов и бизнеса.", lot: 10, step: 0.01 },
  { symbol: "GAZP", name: "Газпром", fullName: "ПАО «Газпром»", sector: "Нефть и газ", kind: "stock", price: 159.28, change: 0.86, color: "#147ac8", mark: "Г", description: "Глобальная энергетическая компания. Разведка, добыча, транспортировка и реализация природного газа.", lot: 10, step: 0.01 },
  { symbol: "LKOH", name: "Лукойл", fullName: "ПАО «ЛУКОЙЛ»", sector: "Нефть и газ", kind: "stock", price: 7124, change: -0.47, color: "#c63b4b", mark: "Л", description: "Одна из крупнейших нефтегазовых компаний России с полным циклом добычи и переработки.", lot: 1, step: 0.5 },
  { symbol: "YDEX", name: "Яндекс", fullName: "МКПАО «Яндекс»", sector: "Технологии", kind: "stock", price: 4182.5, change: 2.18, color: "#f0c838", mark: "Я", description: "Технологическая компания: поиск, городские сервисы, электронная коммерция и искусственный интеллект.", lot: 1, step: 0.5 },
  { symbol: "T", name: "Т-Технологии", fullName: "МКПАО «Т-Технологии»", sector: "Финансы", kind: "stock", price: 3126, change: 1.53, color: "#ecc83e", mark: "Т", description: "Финансовая технологическая экосистема для частных клиентов и бизнеса.", lot: 1, step: 0.5 },
  { symbol: "GMKN", name: "Норникель", fullName: "ПАО «ГМК «Норильский никель»", sector: "Металлы и добыча", kind: "stock", price: 128.46, change: -0.32, color: "#6d80c7", mark: "Н", description: "Крупный производитель никеля, палладия, платины и меди.", lot: 10, step: 0.02 },
  { symbol: "NVTK", name: "Новатэк", fullName: "ПАО «НОВАТЭК»", sector: "Нефть и газ", kind: "stock", price: 1186.8, change: 0.74, color: "#4260a7", mark: "Н", description: "Независимый производитель природного газа и сжиженного природного газа.", lot: 1, step: 0.2 },
  { symbol: "ROSN", name: "Роснефть", fullName: "ПАО «НК «Роснефть»", sector: "Нефть и газ", kind: "stock", price: 572.45, change: 0.92, color: "#d4ad50", mark: "Р", description: "Нефтегазовая компания с активами в разведке, добыче, переработке и сбыте.", lot: 1, step: 0.05 },
  { symbol: "PLZL", name: "Полюс", fullName: "ПАО «Полюс»", sector: "Металлы и добыча", kind: "stock", price: 15780, change: 1.67, color: "#bd9a58", mark: "П", description: "Ведущий российский производитель золота с открытыми и подземными месторождениями.", lot: 1, step: 1 },
  { symbol: "MGNT", name: "Магнит", fullName: "ПАО «Магнит»", sector: "Ритейл", kind: "stock", price: 6842, change: -0.58, color: "#c74b5b", mark: "М", description: "Одна из крупнейших розничных сетей России: продуктовые магазины и дрогери.", lot: 1, step: 0.5 },
  { symbol: "SBERP", name: "Сбербанк-п", fullName: "Сбербанк · привилегированные", sector: "Финансы", kind: "stock", price: 315.2, change: 1.11, color: "#269d58", mark: "S", description: "Привилегированные акции ПАО Сбербанк.", lot: 10, step: 0.01 },
  { symbol: "VTBR", name: "ВТБ", fullName: "Банк ВТБ (ПАО)", sector: "Финансы", kind: "stock", price: 91.42, change: -0.24, color: "#386cbb", mark: "В", description: "Универсальная банковская группа с государственным участием.", lot: 10, step: 0.01 },
  { symbol: "IMOEX", name: "Индекс МосБиржи", fullName: "Индекс Московской биржи", sector: "Индексы", kind: "index", price: 3245.81, change: 0.82, color: "#cf4e5b", mark: "M", description: "Основной рублёвый индикатор российского рынка акций. Рассчитывается Московской биржей.", lot: 1, step: 0.01 },
  { symbol: "RTSI", name: "Индекс РТС", fullName: "Индекс Российской торговой системы", sector: "Индексы", kind: "index", price: 1128.34, change: 0.56, color: "#7394ca", mark: "R", description: "Долларовый индикатор российского рынка акций.", lot: 1, step: 0.01 },
  { symbol: "RGBI", name: "Индекс ОФЗ", fullName: "Индекс государственных облигаций", sector: "Индексы", kind: "index", price: 107.82, change: -0.12, color: "#8f7ac5", mark: "О", description: "Индекс цен наиболее ликвидных государственных облигаций России.", lot: 1, step: 0.01 },
  { symbol: "CNYRUB_TOM", name: "Юань / Рубль", fullName: "Китайский юань к российскому рублю", sector: "Валюты", kind: "currency", price: 12.486, change: -0.18, color: "#c45d53", mark: "¥", description: "Курс китайского юаня к российскому рублю с расчётами завтра.", lot: 1000, step: 0.001 },
  { symbol: "USD000UTSTOM", name: "Доллар / Рубль", fullName: "Доллар США к российскому рублю", sector: "Валюты", kind: "currency", price: 91.24, change: 0.24, color: "#579b7d", mark: "$", description: "Справочный валютный инструмент. Биржевые торги долларом на Мосбирже приостановлены; доступны только демонстрационные данные.", lot: 1000, step: 0.001 },
  { symbol: "EUR_RUB__TOM", name: "Евро / Рубль", fullName: "Евро к российскому рублю", sector: "Валюты", kind: "currency", price: 99.72, change: 0.31, color: "#6283be", mark: "€", description: "Справочный валютный инструмент. Биржевые торги евро на Мосбирже приостановлены; доступны только демонстрационные данные.", lot: 1000, step: 0.001 },
];

export const DEFAULT_SETTINGS: WorkspaceSettings = {
  symbol: "SBER", timeframe: "1d", watchlist: [...INSTRUMENTS.filter(i => i.kind === "stock").slice(0, 10).map(i => i.symbol), ...INSTRUMENTS.filter(i => i.kind !== "stock").map(i => i.symbol)],
  indicators: [
    { id: "ema20", name: "EMA", type: "ema", period: 20, color: "#7194f5", enabled: true },
    { id: "sma50", name: "SMA", type: "sma", period: 50, color: "#c8a46a", enabled: true },
  ], chartType: "candles", drawings: {}, showVolume: true,
};

export function getInstrument(symbol: string) { return INSTRUMENTS.find(i => i.symbol === symbol) ?? INSTRUMENTS[0]; }
export function formatPrice(price: number, digits = 2) { return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(price); }
export function formatCompact(value: number) { return new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 2 }).format(value); }
export function formatChange(change: number) { return `${change >= 0 ? "+" : "−"}${formatPrice(Math.abs(change))}%`; }
export function demoQuote(instrument: Instrument): Quote { return { symbol: instrument.symbol, price: instrument.price, change: instrument.change, absolute: instrument.price - instrument.price / (1 + instrument.change / 100), high: instrument.price * 1.006, low: instrument.price * .988, volume: Math.round(16450000 / (instrument.price / 100)), source: "demo" }; }

export function generateCandles(symbol: string, timeframe: Timeframe, count = 195): Candle[] {
  const instrument = getInstrument(symbol);
  let seed = symbol.split("").reduce((a, c) => a + c.charCodeAt(0), 0) + 27;
  const random = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const seconds = TIMEFRAMES.find(t => t.value === timeframe)!.seconds;
  const daily = seconds >= 86400;
  const end = Math.floor(Date.now() / (seconds * 1000)) * seconds;
  const times: number[] = [];
  let t = end;
  while (times.length < count) { const day = new Date(t * 1000).getUTCDay(); if (!daily || (day !== 0 && day !== 6)) times.unshift(t); t -= seconds; }
  const anchors = [.827, .85, .839, .883, .867, .909, .934, .9, .931, .922, .97, .959, 1];
  const data: Candle[] = [];
  let prev = instrument.price * anchors[0];
  for (let i = 0; i < count; i++) {
    const pos = i / (count - 1) * (anchors.length - 1), a = Math.floor(pos), f = pos - a;
    const base = anchors[a] * (1 - f) + anchors[Math.min(a + 1, anchors.length - 1)] * f;
    const noise = (Math.sin(i * .79) * .0039 + (random() - .5) * .008) * Math.sin(Math.PI * i / (count - 1));
    const close = i === count - 1 ? instrument.price : instrument.price * (base + noise);
    const open = prev * (1 + (random() - .5) * .003);
    const high = Math.max(open, close) + instrument.price * (.001 + random() * .005);
    const low = Math.min(open, close) - instrument.price * (.001 + random() * .004);
    data.push({ time: times[i], open: +open.toFixed(3), close: +close.toFixed(3), high: +high.toFixed(3), low: +low.toFixed(3), volume: Math.round((.6 + random() * 2.8 + Math.abs(close - open) / instrument.price * 190) * 900000) });
    prev = close;
  }
  return data;
}

export function calculateIndicator(candles: Candle[], type: Indicator["type"], period: number): { time: number; value: number }[] {
  if (!candles.length || period < 2) return [];
  const result: { time: number; value: number }[] = [];
  let ema = candles[0].close;
  let averageGain = 0, averageLoss = 0;
  for (let i = 0; i < candles.length; i++) {
    if (type === "ema") {
      ema = candles[i].close * (2 / (period + 1)) + ema * (1 - 2 / (period + 1));
      if (i >= period - 1) result.push({ time: candles[i].time, value: ema });
    } else if (type === "rsi") {
      if (i === 0) continue;
      const change = candles[i].close - candles[i - 1].close;
      if (i <= period) { averageGain += Math.max(change, 0) / period; averageLoss += Math.max(-change, 0) / period; }
      else { averageGain = (averageGain * (period - 1) + Math.max(change, 0)) / period; averageLoss = (averageLoss * (period - 1) + Math.max(-change, 0)) / period; }
      if (i >= period) result.push({ time: candles[i].time, value: averageLoss === 0 ? (averageGain === 0 ? 50 : 100) : 100 - 100 / (1 + averageGain / averageLoss) });
    } else if (i >= period - 1) {
      let sum = 0; for (let j = i - period + 1; j <= i; j++) sum += candles[j].close;
      result.push({ time: candles[i].time, value: sum / period });
    }
  }
  return result;
}

export function parseFormula(formula: string): { type: "sma" | "ema" | "rsi"; period: number } | null {
  const match = formula.trim().match(/^(sma|ema|rsi)\s*\(\s*close\s*,\s*(\d+)\s*\)$/i);
  if (!match || +match[2] < 2 || +match[2] > 200) return null;
  return { type: match[1].toLowerCase() as "sma" | "ema" | "rsi", period: +match[2] };
}
