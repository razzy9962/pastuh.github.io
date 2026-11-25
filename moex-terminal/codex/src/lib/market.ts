import { DEFAULT_SMC, type SmcSettings } from "./smc";
import { mskBucket } from "./time-buckets";

export { mskBucket, mskWeekBucket } from "./time-buckets";

export { sanitizeSmcSettings } from "./smc";

export type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d" | "1w";
export type DataSource = "tinvest" | "moex" | "demo";
export type InstrumentKind = "stock" | "index" | "currency";
export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
export type Instrument = { symbol: string; name: string; fullName: string; sector: string; kind: InstrumentKind; tier?: number; price: number; change: number; color: string; mark: string; description: string; lot: number; step: number };
export type Quote = { symbol: string; price: number; change: number; /** false — предыдущее закрытие неизвестно, «0,00%» показывать нельзя. */ changeKnown?: boolean; absolute: number; high: number; low: number; volume: number; source: DataSource; time?: string; /** Цена старше 15 минут: показываем как «последнюю известную», а не текущую. */ stale?: boolean };
export type Drawing = { id: string; type: "horizontal" | "trend"; price: number; time: number; endPrice?: number; endTime?: number; color: string };
export type WorkspaceSettings = { symbol: string; timeframe: Timeframe; watchlist: string[]; chartType: "candles" | "line" | "area"; drawings: Record<string, Drawing[]>; showVolume: boolean; smc?: SmcSettings };

/**
 * Свечи младшего таймфрейма склеиваются в старший. Для 4ч нужны актуальные часовые:
 * провайдер отдаёт последнюю часовую свечу только после её закрытия, поэтому
 * 4ч-бар «замирал» на три часа дольше, чем нужно.
 */
/**
 * Свечи младшего таймфрейма склеиваются в старший. moscow = true — границы бакетов
 * по МСК (4ч от открытия сессии), иначе — по UTC, как приходит от MOEX ISS.
 */
export function aggregateCandles(candles: Candle[], seconds: number, moscow = false): Candle[] {
  const result: Candle[] = [];
  for (const candle of candles) {
    const time = moscow ? mskBucket(candle.time, seconds, seconds === 14400 ? 10 : 0) : Math.floor(candle.time / seconds) * seconds;
    const last = result[result.length - 1];
    if (last && last.time === time) {
      last.high = Math.max(last.high, candle.high);
      last.low = Math.min(last.low, candle.low);
      last.close = candle.close;
      last.volume += candle.volume;
    } else result.push({ ...candle, time });
  }
  return result;
}

/**
 * Свечи провайдера приводятся к пригодному для графика виду: без дублей по времени,
 * с положительными ценами и корректным OHLC. Битый бар ломает Lightweight Charts
 * целиком (пустой график без ошибки в консоли), поэтому фильтр обязателен.
 */
export function sanitizeCandles(candles: Candle[]): Candle[] {
  const sorted = candles
    .filter(c => Number.isFinite(c.time) && c.time > 0 && [c.open, c.high, c.low, c.close].every(v => Number.isFinite(v) && v > 0))
    .map(c => ({ ...c, high: Math.max(c.high, c.open, c.close), low: Math.min(c.low, c.open, c.close), volume: Number.isFinite(c.volume) && c.volume > 0 ? c.volume : 0 }))
    .sort((a, b) => a.time - b.time);
  const result: Candle[] = [];
  for (const candle of sorted) {
    const previous = result[result.length - 1];
    if (!previous || previous.time !== candle.time) result.push(candle);
    else result[result.length - 1] = candle;
  }
  return result;
}

/** Смещение московского времени от UTC в секундах. */
export const MSK_OFFSET = 3 * 3600;
const MSK_MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const pad = (value: number) => String(value).padStart(2, "0");

/**
 * Время свечи в московском времени. Lightweight Charts по умолчанию печатает UTC,
 * из-за чего свеча 18:00 MSK подписывалась как «15:00» и график казался отставшим
 * на три часа. Все подписи времени в терминале считаются этой функцией.
 * tickMark: 0 — год, 1 — месяц, 2 — день, 3 — время, 4 — время с секундами.
 */
export function formatMsk(time: number, withTime = false, tickMark?: number): string {
  const date = new Date((time + MSK_OFFSET) * 1000);
  const year = date.getUTCFullYear(), month = date.getUTCMonth(), day = date.getUTCDate();
  const hm = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
  if (tickMark === 0) return String(year);
  if (tickMark === 1) return MSK_MONTHS[month];
  if (tickMark === 2) return String(day);
  if (tickMark === 3) return hm;
  if (tickMark === 4) return `${hm}:${pad(date.getUTCSeconds())}`;
  return withTime ? `${day} ${MSK_MONTHS[month]} ${hm}` : `${day} ${MSK_MONTHS[month]}`;
}

/** Полная дата и время в МСК для подписей линейки и подсказок. */
export function formatMskFull(time: number): string {
  const date = new Date((time + MSK_OFFSET) * 1000);
  return `${pad(date.getUTCDate())}.${pad(date.getUTCMonth() + 1)}.${String(date.getUTCFullYear()).slice(2)} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
}

export const TIMEFRAMES: { value: Timeframe; label: string; seconds: number }[] = [
  { value: "1m", label: "1м", seconds: 60 }, { value: "5m", label: "5м", seconds: 300 },
  { value: "15m", label: "15м", seconds: 900 }, { value: "1h", label: "1ч", seconds: 3600 },
  { value: "4h", label: "4ч", seconds: 14400 }, { value: "1d", label: "1Д", seconds: 86400 },
  { value: "1w", label: "1Н", seconds: 604800 },
];

export const TIERS: { value: number; label: string; short: string }[] = [
  { value: 1, label: "1-й эшелон", short: "1 эш." },
  { value: 2, label: "2-й эшелон", short: "2 эш." },
  { value: 3, label: "3-й эшелон", short: "3 эш." },
];

/** Все акции Московской биржи в каталоге: 1-й эшелон — состав индекса IMOEX, далее 2-й и 3-й. */
const STOCKS: Instrument[] = [
  { symbol: "SBER", name: "Сбербанк", fullName: "ПАО Сбербанк", sector: "Финансы", kind: "stock", tier: 1, price: 318.64, change: 0, color: "#269d58", mark: "С", description: "ПАО Сбербанк · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "GAZP", name: "Газпром", fullName: "ПАО «Газпром»", sector: "Нефть и газ", kind: "stock", tier: 1, price: 159.28, change: 0, color: "#147ac8", mark: "Г", description: "ПАО «Газпром» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "LKOH", name: "Лукойл", fullName: "ПАО «ЛУКОЙЛ»", sector: "Нефть и газ", kind: "stock", tier: 1, price: 7124, change: 0, color: "#c63b4b", mark: "Л", description: "ПАО «ЛУКОЙЛ» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 1 },
  { symbol: "YDEX", name: "Яндекс", fullName: "МКПАО «Яндекс»", sector: "Технологии", kind: "stock", tier: 1, price: 4182.5, change: 0, color: "#f0c838", mark: "Я", description: "МКПАО «Яндекс» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "TATN", name: "Татнефть", fullName: "ПАО «Татнефть» им. В.Д. Шашина", sector: "Нефть и газ", kind: "stock", tier: 1, price: 612.4, change: 0, color: "#2f8f5b", mark: "Т", description: "ПАО «Татнефть» им. В.Д. Шашина · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "T", name: "Т-Технологии", fullName: "МКПАО «Т-Технологии»", sector: "Финансы", kind: "stock", tier: 1, price: 3126, change: 0, color: "#ecc83e", mark: "Т", description: "МКПАО «Т-Технологии» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "NVTK", name: "Новатэк", fullName: "ПАО «НОВАТЭК»", sector: "Нефть и газ", kind: "stock", tier: 1, price: 1186.8, change: 0, color: "#4260a7", mark: "Н", description: "ПАО «НОВАТЭК» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "GMKN", name: "Норникель", fullName: "ПАО «ГМК «Норильский никель»", sector: "Металлы и добыча", kind: "stock", tier: 1, price: 128.46, change: 0, color: "#6d80c7", mark: "Н", description: "ПАО «ГМК «Норильский никель» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "ROSN", name: "Роснефть", fullName: "ПАО «НК «Роснефть»", sector: "Нефть и газ", kind: "stock", tier: 1, price: 572.45, change: 0, color: "#d4ad50", mark: "Р", description: "ПАО «НК «Роснефть» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "X5", name: "ИКС 5", fullName: "ПАО «Корпоративный центр ИКС 5»", sector: "Ритейл", kind: "stock", tier: 1, price: 4310, change: 0, color: "#3f9c6d", mark: "X", description: "ПАО «Корпоративный центр ИКС 5» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "VTBR", name: "ВТБ", fullName: "Банк ВТБ (ПАО)", sector: "Финансы", kind: "stock", tier: 1, price: 91.42, change: 0, color: "#386cbb", mark: "В", description: "Банк ВТБ (ПАО) · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "SBERP", name: "Сбербанк-п", fullName: "Сбербанк · привилегированные", sector: "Финансы", kind: "stock", tier: 1, price: 315.2, change: 0, color: "#269d58", mark: "S", description: "Сбербанк · привилегированные · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "OZON", name: "Озон", fullName: "МКПАО «Озон»", sector: "Технологии", kind: "stock", tier: 1, price: 3980, change: 0, color: "#2a6df4", mark: "O", description: "МКПАО «Озон» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "PLZL", name: "Полюс", fullName: "ПАО «Полюс»", sector: "Металлы и добыча", kind: "stock", tier: 1, price: 15780, change: 0, color: "#bd9a58", mark: "П", description: "ПАО «Полюс» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 1 },
  { symbol: "SNGSP", name: "Сургутнефтегаз-п", fullName: "ПАО «Сургутнефтегаз» · привилегированные", sector: "Нефть и газ", kind: "stock", tier: 1, price: 52.4, change: 0, color: "#8d6fb8", mark: "С", description: "ПАО «Сургутнефтегаз» · привилегированные · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "SNGS", name: "Сургутнефтегаз", fullName: "ПАО «Сургутнефтегаз»", sector: "Нефть и газ", kind: "stock", tier: 1, price: 24.6, change: 0, color: "#7e63a9", mark: "С", description: "ПАО «Сургутнефтегаз» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "HEAD", name: "Хэдхантер", fullName: "МКПАО «Хэдхантер»", sector: "Технологии", kind: "stock", tier: 1, price: 3910, change: 0, color: "#c8493f", mark: "Х", description: "МКПАО «Хэдхантер» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "TATNP", name: "Татнефть-п", fullName: "ПАО «Татнефть» · привилегированные", sector: "Нефть и газ", kind: "stock", tier: 1, price: 590, change: 0, color: "#2f8f5b", mark: "Т", description: "ПАО «Татнефть» · привилегированные · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "MOEX", name: "МосБиржа", fullName: "ПАО Московская Биржа", sector: "Финансы", kind: "stock", tier: 1, price: 214.6, change: 0, color: "#2f7ec4", mark: "М", description: "ПАО Московская Биржа · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "MTSS", name: "МТС", fullName: "ПАО «МТС»", sector: "Телеком", kind: "stock", tier: 1, price: 231.4, change: 0, color: "#c0392b", mark: "М", description: "ПАО «МТС» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "IRAO", name: "Интер РАО", fullName: "ПАО «Интер РАО»", sector: "Энергетика", kind: "stock", tier: 1, price: 6.12, change: 0, color: "#3f8ec9", mark: "И", description: "ПАО «Интер РАО» · акции Московской биржи, 1-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "RUAL", name: "Русал", fullName: "МКПАО «РУСАЛ»", sector: "Металлы и добыча", kind: "stock", tier: 1, price: 48.2, change: 0, color: "#8b6b5b", mark: "Р", description: "МКПАО «РУСАЛ» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "CBOM", name: "МКБ", fullName: "ПАО «МОСКОВСКИЙ КРЕДИТНЫЙ БАНК»", sector: "Финансы", kind: "stock", tier: 1, price: 9.86, change: 0, color: "#35558f", mark: "М", description: "ПАО «МОСКОВСКИЙ КРЕДИТНЫЙ БАНК» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "CHMF", name: "Северсталь", fullName: "ПАО «Северсталь»", sector: "Металлы и добыча", kind: "stock", tier: 1, price: 1180, change: 0, color: "#b8453f", mark: "С", description: "ПАО «Северсталь» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "NLMK", name: "НЛМК", fullName: "ПАО «НЛМК»", sector: "Металлы и добыча", kind: "stock", tier: 1, price: 132.5, change: 0, color: "#4d6fa8", mark: "Н", description: "ПАО «НЛМК» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "PHOR", name: "ФосАгро", fullName: "ПАО «ФосАгро»", sector: "Химия", kind: "stock", tier: 1, price: 6420, change: 0, color: "#3f8f74", mark: "Ф", description: "ПАО «ФосАгро» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 1 },
  { symbol: "DOMRF", name: "ДОМ.РФ", fullName: "АО «ДОМ.РФ»", sector: "Финансы", kind: "stock", tier: 1, price: 3420, change: 0, color: "#2f7f6f", mark: "Д", description: "АО «ДОМ.РФ» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.5 },
  { symbol: "SVCB", name: "Совкомбанк", fullName: "ПАО «Совкомбанк»", sector: "Финансы", kind: "stock", tier: 1, price: 14.8, change: 0, color: "#3a6ea5", mark: "С", description: "ПАО «Совкомбанк» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "MAGN", name: "ММК", fullName: "ПАО «ММК»", sector: "Металлы и добыча", kind: "stock", tier: 1, price: 48.9, change: 0, color: "#7a6bb5", mark: "М", description: "ПАО «ММК» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "RTKM", name: "Ростелеком", fullName: "ПАО «Ростелеком»", sector: "Телеком", kind: "stock", tier: 1, price: 72.4, change: 0, color: "#8a5bb8", mark: "Р", description: "ПАО «Ростелеком» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "AFLT", name: "Аэрофлот", fullName: "ПАО «Аэрофлот»", sector: "Транспорт", kind: "stock", tier: 1, price: 62.8, change: 0, color: "#2f74b5", mark: "А", description: "ПАО «Аэрофлот» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "ENPG", name: "Эн+ Групп", fullName: "МКПАО «ЭН+ ГРУП»", sector: "Энергетика", kind: "stock", tier: 1, price: 412, change: 0, color: "#4a7fb8", mark: "Э", description: "МКПАО «ЭН+ ГРУП» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "TRNFP", name: "Транснефть-п", fullName: "ПАО «Транснефть» · привилегированные", sector: "Нефть и газ", kind: "stock", tier: 1, price: 1320, change: 0, color: "#8f5a5a", mark: "Т", description: "ПАО «Транснефть» · привилегированные · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "BSPB", name: "Банк СПб", fullName: "ПАО «Банк «Санкт-Петербург»", sector: "Финансы", kind: "stock", tier: 1, price: 412, change: 0, color: "#3b6ba5", mark: "Б", description: "ПАО «Банк «Санкт-Петербург» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "MDMG", name: "MD Medical", fullName: "ПАО «МД Медикал Груп»", sector: "Здравоохранение", kind: "stock", tier: 1, price: 1180, change: 0, color: "#4a9d8f", mark: "M", description: "ПАО «МД Медикал Груп» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "FLOT", name: "Совкомфлот", fullName: "ПАО «Совкомфлот»", sector: "Транспорт", kind: "stock", tier: 1, price: 128.4, change: 0, color: "#2f6fa5", mark: "С", description: "ПАО «Совкомфлот» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "ALRS", name: "АЛРОСА", fullName: "ПАО «АЛРОСА»", sector: "Металлы и добыча", kind: "stock", tier: 1, price: 62.4, change: 0, color: "#5b8fc4", mark: "А", description: "ПАО «АЛРОСА» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "LENT", name: "Лента", fullName: "МКПАО «Лента»", sector: "Ритейл", kind: "stock", tier: 1, price: 1180, change: 0, color: "#3f8f4f", mark: "Л", description: "МКПАО «Лента» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "CNRU", name: "Циан", fullName: "МКПАО «Циан»", sector: "Технологии", kind: "stock", tier: 1, price: 720, change: 0, color: "#2f7fd4", mark: "Ц", description: "МКПАО «Циан» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "UGLD", name: "ЮГК", fullName: "ПАО «Южуралзолото Группа Компаний»", sector: "Металлы и добыча", kind: "stock", tier: 1, price: 1.42, change: 0, color: "#c2a24a", mark: "Ю", description: "ПАО «Южуралзолото Группа Компаний» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "POSI", name: "Позитив", fullName: "ПАО «Позитив Текнолоджиз»", sector: "Технологии", kind: "stock", tier: 1, price: 2180, change: 0, color: "#4a7fbf", mark: "П", description: "ПАО «Позитив Текнолоджиз» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "AFKS", name: "АФК Система", fullName: "ПАО АФК «Система»", sector: "Холдинги", kind: "stock", tier: 1, price: 18.4, change: 0, color: "#6b5bb5", mark: "А", description: "ПАО АФК «Система» · акции Московской биржи, 1-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "RAGR", name: "Русагро", fullName: "ПАО «Группа «Русагро»", sector: "Агро", kind: "stock", tier: 1, price: 1180, change: 0, color: "#4a9d5f", mark: "Р", description: "ПАО «Группа «Русагро» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "VKCO", name: "ВК", fullName: "МКПАО «ВК»", sector: "Технологии", kind: "stock", tier: 1, price: 312, change: 0, color: "#3f5bb5", mark: "В", description: "МКПАО «ВК» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "RENI", name: "Ренессанс", fullName: "ПАО «Ренессанс Страхование»", sector: "Финансы", kind: "stock", tier: 1, price: 112, change: 0, color: "#4a7fb8", mark: "Р", description: "ПАО «Ренессанс Страхование» · акции Московской биржи, 1-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "MSNG", name: "Мосэнерго", fullName: "ПАО «Мосэнерго»", sector: "Энергетика", kind: "stock", tier: 1, price: 2.84, change: 0, color: "#3f8fa5", mark: "М", description: "ПАО «Мосэнерго» · акции Московской биржи, 1-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "LSRG", name: "ЛСР", fullName: "ПАО «Группа ЛСР»", sector: "Девелопмент", kind: "stock", tier: 2, price: 812, change: 0, color: "#b8743f", mark: "Л", description: "ПАО «Группа ЛСР» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "SMLT", name: "Самолет", fullName: "ПАО «ГК «Самолет»", sector: "Девелопмент", kind: "stock", tier: 2, price: 1420, change: 0, color: "#c8893f", mark: "С", description: "ПАО «ГК «Самолет» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "FEES", name: "Россети", fullName: "ПАО «Россети»", sector: "Энергетика", kind: "stock", tier: 2, price: 0.32, change: 0, color: "#3f7f9d", mark: "Р", description: "ПАО «Россети» · акции Московской биржи, 2-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "HYDR", name: "РусГидро", fullName: "ПАО «РусГидро»", sector: "Энергетика", kind: "stock", tier: 2, price: 0.62, change: 0, color: "#2f8fbf", mark: "Р", description: "ПАО «РусГидро» · акции Московской биржи, 2-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "UPRO", name: "Юнипро", fullName: "ПАО «Юнипро»", sector: "Энергетика", kind: "stock", tier: 2, price: 2.14, change: 0, color: "#4a9fb5", mark: "Ю", description: "ПАО «Юнипро» · акции Московской биржи, 2-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "TRMK", name: "ТМК", fullName: "ПАО «ТМК»", sector: "Металлы и добыча", kind: "stock", tier: 2, price: 148, change: 0, color: "#6b6ba5", mark: "Т", description: "ПАО «ТМК» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "RASP", name: "Распадская", fullName: "ПАО «Распадская»", sector: "Металлы и добыча", kind: "stock", tier: 2, price: 412, change: 0, color: "#5b6b8f", mark: "Р", description: "ПАО «Распадская» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "MTLR", name: "Мечел", fullName: "ПАО «Мечел»", sector: "Металлы и добыча", kind: "stock", tier: 2, price: 74.2, change: 0, color: "#7a5b6b", mark: "М", description: "ПАО «Мечел» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "MTLRP", name: "Мечел-п", fullName: "ПАО «Мечел» · привилегированные", sector: "Металлы и добыча", kind: "stock", tier: 2, price: 82.4, change: 0, color: "#7a5b6b", mark: "М", description: "ПАО «Мечел» · привилегированные · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "CHMK", name: "ЧМК", fullName: "ПАО «Челябинский металлургический комбинат»", sector: "Металлы и добыча", kind: "stock", tier: 2, price: 4820, change: 0, color: "#8a6b6b", mark: "Ч", description: "ПАО «Челябинский металлургический комбинат» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "VSMO", name: "ВСМПО-Ависма", fullName: "ПАО «Корпорация ВСМПО-АВИСМА»", sector: "Металлы и добыча", kind: "stock", tier: 2, price: 18400, change: 0, color: "#6b7fb5", mark: "В", description: "ПАО «Корпорация ВСМПО-АВИСМА» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 1 },
  { symbol: "KMAZ", name: "КАМАЗ", fullName: "ПАО «КАМАЗ»", sector: "Машиностроение", kind: "stock", tier: 2, price: 72.4, change: 0, color: "#3f7fa5", mark: "К", description: "ПАО «КАМАЗ» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "SVAV", name: "СОЛЛЕРС", fullName: "ПАО «СОЛЛЕРС»", sector: "Машиностроение", kind: "stock", tier: 2, price: 812, change: 0, color: "#4a6b9d", mark: "С", description: "ПАО «СОЛЛЕРС» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "ZVEZ", name: "Звезда", fullName: "ПАО «Звезда»", sector: "Машиностроение", kind: "stock", tier: 2, price: 4.12, change: 0, color: "#4a6b9f", mark: "З", description: "ПАО «Звезда» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "AQUA", name: "Русская аквакультура", fullName: "ПАО «Русская аквакультура»", sector: "Агро", kind: "stock", tier: 2, price: 1180, change: 0, color: "#3f9d8f", mark: "Р", description: "ПАО «Русская аквакультура» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.5 },
  { symbol: "BELU", name: "Белуга", fullName: "ПАО «Белуга Групп»", sector: "Потребительский", kind: "stock", tier: 2, price: 2140, change: 0, color: "#4aa58f", mark: "Б", description: "ПАО «Белуга Групп» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "ABIO", name: "Артген", fullName: "ПАО «Артген»", sector: "Здравоохранение", kind: "stock", tier: 2, price: 268, change: 0, color: "#5b8f7f", mark: "А", description: "ПАО «Артген» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "APTK", name: "Аптеки 36,6", fullName: "ПАО «Аптечная сеть 36,6»", sector: "Ритейл", kind: "stock", tier: 2, price: 14.8, change: 0, color: "#3f8f6f", mark: "А", description: "ПАО «Аптечная сеть 36,6» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "GCHE", name: "Черкизово", fullName: "ПАО «Группа Черкизово»", sector: "Агро", kind: "stock", tier: 2, price: 2840, change: 0, color: "#5b8f4f", mark: "Ч", description: "ПАО «Группа Черкизово» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "LEAS", name: "Европлан", fullName: "ПАО «Европлан»", sector: "Финансы", kind: "stock", tier: 2, price: 1180, change: 0, color: "#4a7fbf", mark: "Е", description: "ПАО «Европлан» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "SFIN", name: "ЭсЭфАй", fullName: "ПАО «ЭсЭфАй»", sector: "Холдинги", kind: "stock", tier: 2, price: 1420, change: 0, color: "#6b5b8f", mark: "Э", description: "ПАО «ЭсЭфАй» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "NMTP", name: "НМТП", fullName: "ПАО «НМТП»", sector: "Транспорт", kind: "stock", tier: 2, price: 12.4, change: 0, color: "#3f7f9f", mark: "Н", description: "ПАО «НМТП» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "SGZH", name: "Сегежа", fullName: "ПАО «Сегежа Групп»", sector: "Лес", kind: "stock", tier: 2, price: 1.86, change: 0, color: "#5b8f6f", mark: "С", description: "ПАО «Сегежа Групп» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "SIBN", name: "Газпром нефть", fullName: "ПАО «Газпром нефть»", sector: "Нефть и газ", kind: "stock", tier: 2, price: 612, change: 0, color: "#3f6fb5", mark: "Г", description: "ПАО «Газпром нефть» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "NKNC", name: "Нижнекамскнефтехим", fullName: "ПАО «Нижнекамскнефтехим»", sector: "Химия", kind: "stock", tier: 2, price: 82.4, change: 0, color: "#4a8f7f", mark: "Н", description: "ПАО «Нижнекамскнефтехим» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "NKNCP", name: "Нижнекамскнефтехим-п", fullName: "ПАО «Нижнекамскнефтехим» · привилегированные", sector: "Химия", kind: "stock", tier: 2, price: 62.4, change: 0, color: "#4a8f7f", mark: "Н", description: "ПАО «Нижнекамскнефтехим» · привилегированные · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "KAZT", name: "КуйбышевАзот", fullName: "ПАО «КуйбышевАзот»", sector: "Химия", kind: "stock", tier: 2, price: 482, change: 0, color: "#4a7f8f", mark: "К", description: "ПАО «КуйбышевАзот» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "AKRN", name: "Акрон", fullName: "ПАО «Акрон»", sector: "Химия", kind: "stock", tier: 2, price: 18400, change: 0, color: "#3f8fa5", mark: "А", description: "ПАО «Акрон» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 1 },
  { symbol: "ELFV", name: "Эл5-Энерго", fullName: "ПАО «Эл5-Энерго»", sector: "Энергетика", kind: "stock", tier: 2, price: 0.42, change: 0, color: "#4a9fbf", mark: "Э", description: "ПАО «Эл5-Энерго» · акции Московской биржи, 2-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "TGKA", name: "ТГК-1", fullName: "ПАО «ТГК-1»", sector: "Энергетика", kind: "stock", tier: 2, price: 0.0086, change: 0, color: "#3f7f9f", mark: "Т", description: "ПАО «ТГК-1» · акции Московской биржи, 2-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "TGKB", name: "ТГК-2", fullName: "ПАО «ТГК-2»", sector: "Энергетика", kind: "stock", tier: 2, price: 0.0032, change: 0, color: "#3f7f9f", mark: "Т", description: "ПАО «ТГК-2» · акции Московской биржи, 2-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "MSRS", name: "Мосэнергосбыт", fullName: "АО «Мосэнергосбыт»", sector: "Энергетика", kind: "stock", tier: 2, price: 2.84, change: 0, color: "#3f8fa5", mark: "М", description: "АО «Мосэнергосбыт» · акции Московской биржи, 2-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "DVEC", name: "ДЭК", fullName: "ПАО «Дальневосточная энергетическая компания»", sector: "Энергетика", kind: "stock", tier: 2, price: 0.86, change: 0, color: "#3b8fa5", mark: "Д", description: "ПАО «Дальневосточная энергетическая компания» · акции Московской биржи, 2-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "BANE", name: "Башнефть", fullName: "ПАО «Башнефть»", sector: "Нефть и газ", kind: "stock", tier: 2, price: 1840, change: 0, color: "#9d6b4a", mark: "Б", description: "ПАО «Башнефть» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "BANEP", name: "Башнефть-п", fullName: "ПАО «Башнефть» · привилегированные", sector: "Нефть и газ", kind: "stock", tier: 2, price: 1620, change: 0, color: "#9d6b4a", mark: "Б", description: "ПАО «Башнефть» · привилегированные · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "DIOD", name: "Диод", fullName: "ПАО «Диод»", sector: "Технологии", kind: "stock", tier: 2, price: 42.4, change: 0, color: "#4a7f8f", mark: "Д", description: "ПАО «Диод» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "RNFT", name: "РуссНефть", fullName: "ПАО «НК «РуссНефть»", sector: "Нефть и газ", kind: "stock", tier: 2, price: 218, change: 0, color: "#8f5a7a", mark: "Р", description: "ПАО «НК «РуссНефть» · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "LPSB", name: "Липецккомбанк", fullName: "ПАО «Липецккомбанк»", sector: "Финансы", kind: "stock", tier: 2, price: 8.42, change: 0, color: "#3b6ba5", mark: "Л", description: "ПАО «Липецккомбанк» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "PRMB", name: "Приморье", fullName: "ПАО «Банк Приморье»", sector: "Финансы", kind: "stock", tier: 2, price: 248, change: 0, color: "#3b6b9f", mark: "П", description: "ПАО «Банк Приморье» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "TUZA", name: "Тулаэнергосбыт", fullName: "ПАО «Тулаэнергосбыт»", sector: "Энергетика", kind: "stock", tier: 2, price: 0.42, change: 0, color: "#3f7f9f", mark: "Т", description: "ПАО «Тулаэнергосбыт» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "VGSB", name: "Волгоградэнергосбыт", fullName: "ПАО «Волгоградэнергосбыт»", sector: "Энергетика", kind: "stock", tier: 2, price: 0.286, change: 0, color: "#3f7f9f", mark: "В", description: "ПАО «Волгоградэнергосбыт» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "SAREP", name: "Самараэнерго", fullName: "ПАО «Самараэнерго»", sector: "Энергетика", kind: "stock", tier: 2, price: 0.386, change: 0, color: "#3f7f8f", mark: "С", description: "ПАО «Самараэнерго» · акции Московской биржи, 2-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "SAGO", name: "Самараэнерго-п", fullName: "ПАО «Самараэнерго» · привилегированные", sector: "Энергетика", kind: "stock", tier: 2, price: 0.482, change: 0, color: "#3f7f8f", mark: "С", description: "ПАО «Самараэнерго» · привилегированные · акции Московской биржи, 2-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "MGTSP", name: "Мосэнерго-п", fullName: "ПАО «Мосэнерго» · привилегированные", sector: "Энергетика", kind: "stock", tier: 2, price: 0.186, change: 0, color: "#3f8fa5", mark: "М", description: "ПАО «Мосэнерго» · привилегированные · акции Московской биржи, 2-й эшелон.", lot: 100, step: 0.01 },
  { symbol: "UTAR", name: "ЮТэйр", fullName: "ПАО «Авиакомпания «ЮТэйр»", sector: "Транспорт", kind: "stock", tier: 3, price: 18.4, change: 0, color: "#4a7f9f", mark: "Ю", description: "ПАО «Авиакомпания «ЮТэйр» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "ASTR", name: "Астра", fullName: "ПАО «Группа Астра»", sector: "Технологии", kind: "stock", tier: 3, price: 612, change: 0, color: "#4a5bb5", mark: "А", description: "ПАО «Группа Астра» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "DELI", name: "Делимобиль", fullName: "ПАО «Делимобиль»", sector: "Транспорт", kind: "stock", tier: 3, price: 412, change: 0, color: "#c9a13f", mark: "Д", description: "ПАО «Делимобиль» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "WUSH", name: "Вуш", fullName: "МКПАО «Вуш Холдинг»", sector: "Технологии", kind: "stock", tier: 3, price: 312, change: 0, color: "#3f8faf", mark: "В", description: "МКПАО «Вуш Холдинг» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "CARM", name: "КарМани", fullName: "ПАО «КарМани»", sector: "Финансы", kind: "stock", tier: 3, price: 218, change: 0, color: "#b5563f", mark: "К", description: "ПАО «КарМани» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "ZAYM", name: "Займер", fullName: "ПАО МФК «Займер»", sector: "Финансы", kind: "stock", tier: 3, price: 112, change: 0, color: "#3f7f6f", mark: "З", description: "ПАО МФК «Займер» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 0.02 },
  { symbol: "GEMC", name: "ЕвроМедЦентр", fullName: "ПАО «Европейский медицинский центр»", sector: "Здравоохранение", kind: "stock", tier: 3, price: 2140, change: 0, color: "#4a9d9f", mark: "Е", description: "ПАО «Европейский медицинский центр» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "ROLO", name: "Русолово", fullName: "ПАО «Русолово»", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 0.62, change: 0, color: "#7f6b4a", mark: "Р", description: "ПАО «Русолово» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "SELG", name: "Селигдар", fullName: "ПАО «Селигдар»", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 62.4, change: 0, color: "#b89a4a", mark: "С", description: "ПАО «Селигдар» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "VJGZ", name: "Варьеганнефтегаз", fullName: "ПАО «Варьеганнефтегаз»", sector: "Нефть и газ", kind: "stock", tier: 3, price: 482, change: 0, color: "#8f6b5a", mark: "В", description: "ПАО «Варьеганнефтегаз» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "TTLK", name: "Таттелеком", fullName: "ПАО «Таттелеком»", sector: "Телеком", kind: "stock", tier: 3, price: 0.62, change: 0, color: "#4a7f8f", mark: "Т", description: "ПАО «Таттелеком» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "KZOS", name: "Казаньоргсинтез", fullName: "ПАО «Казаньоргсинтез»", sector: "Химия", kind: "stock", tier: 3, price: 12.4, change: 0, color: "#4a8f6f", mark: "К", description: "ПАО «Казаньоргсинтез» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "KZOSP", name: "Казаньоргсинтез-п", fullName: "ПАО «Казаньоргсинтез» · привилегированные", sector: "Химия", kind: "stock", tier: 3, price: 10.8, change: 0, color: "#4a8f6f", mark: "К", description: "ПАО «Казаньоргсинтез» · привилегированные · акции Московской биржи, 3-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "MRSB", name: "Мордовэнергосбыт", fullName: "ПАО «Мордовская энергосбытовая компания»", sector: "Энергетика", kind: "stock", tier: 3, price: 0.42, change: 0, color: "#3f7f8f", mark: "М", description: "ПАО «Мордовская энергосбытовая компания» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "UNAC", name: "ОАК", fullName: "ПАО «Объединённая авиастроительная корпорация»", sector: "Машиностроение", kind: "stock", tier: 3, price: 0.42, change: 0, color: "#3b6b9d", mark: "О", description: "ПАО «Объединённая авиастроительная корпорация» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "KROT", name: "Кронос", fullName: "ПАО «Кронос»", sector: "Машиностроение", kind: "stock", tier: 3, price: 4.12, change: 0, color: "#6b7f8f", mark: "К", description: "ПАО «Кронос» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "NAUK", name: "НПО «Наука»", fullName: "ПАО «НПО «Наука»", sector: "Машиностроение", kind: "stock", tier: 3, price: 412, change: 0, color: "#4a7f9f", mark: "Н", description: "ПАО «НПО «Наука» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "RBCM", name: "РБК", fullName: "ПАО «РБК»", sector: "Медиа", kind: "stock", tier: 3, price: 16.4, change: 0, color: "#3f6f8f", mark: "Р", description: "ПАО «РБК» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "PRFN", name: "Профнастил", fullName: "ПАО «Профнастил»", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 218, change: 0, color: "#6b8f7f", mark: "П", description: "ПАО «Профнастил» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "APRI", name: "Апри", fullName: "ПАО «Апри»", sector: "Потребительский", kind: "stock", tier: 3, price: 412, change: 0, color: "#8f5b5b", mark: "А", description: "ПАО «Апри» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "EELT", name: "ЕвроЭлит", fullName: "ПАО «ЕвроЭлит»", sector: "Потребительский", kind: "stock", tier: 3, price: 0.86, change: 0, color: "#5b8f9f", mark: "Е", description: "ПАО «ЕвроЭлит» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 0.01 },
  { symbol: "GAZA", name: "Газпром газораспределение", fullName: "ПАО «Газпром газораспределение»", sector: "Нефть и газ", kind: "stock", tier: 3, price: 284, change: 0, color: "#3f7fb5", mark: "Г", description: "ПАО «Газпром газораспределение» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.02 },
  { symbol: "DIAS", name: "Диасофт", fullName: "ПАО «Диасофт»", sector: "Технологии", kind: "stock", tier: 3, price: 4820, change: 0, color: "#4a6baf", mark: "Д", description: "ПАО «Диасофт» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.5 },
  { symbol: "SOFL", name: "Софтлайн", fullName: "ПАО «Софтлайн»", sector: "Технологии", kind: "stock", tier: 3, price: 62.4, change: 0, color: "#3f5faf", mark: "С", description: "ПАО «Софтлайн» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 0.01 },
  { symbol: "VLHZ", name: "Владимирский хим завод", fullName: "«Владимирский хим завод» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "В", description: "«Владимирский хим завод» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "KBSB", name: "ТНС энерго Кубань", fullName: "«ТНС энерго Кубань» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Т", description: "«ТНС энерго Кубань» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "RZSB", name: "Рязанская энергетическая сбытовая компания", fullName: "«Рязанская энергетическая сбытовая компания» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "Р", description: "«Рязанская энергетическая сбытовая компания» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "KCHEP", name: "Камчатскэнерго ап", fullName: "«Камчатскэнерго ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "К", description: "«Камчатскэнерго ап» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "TASB", name: "Тамбовская энергосбытовая компания", fullName: "«Тамбовская энергосбытовая компания» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "Т", description: "«Тамбовская энергосбытовая компания» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "BISVP", name: "Башинформсвязь - Акции привилегированные ап", fullName: "«Башинформсвязь - Акции привилегированные ап» · акции Московской биржи, 3-й эшелон.", sector: "Телеком", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "Б", description: "«Башинформсвязь - Акции привилегированные ап» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "MGNT", name: "Магнит", fullName: "«Магнит» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "М", description: "«Магнит» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "MFGS", name: "Славнефть-Мегионнефтегаз", fullName: "«Славнефть-Мегионнефтегаз» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "С", description: "«Славнефть-Мегионнефтегаз» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "LNZL", name: "Лензолото", fullName: "«Лензолото» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "Л", description: "«Лензолото» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "RUSI", name: "РУСС-ИНВЕСТ", fullName: "«РУСС-ИНВЕСТ» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Р", description: "«РУСС-ИНВЕСТ» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "DZRDP", name: "Донской завод радиодеталей ап", fullName: "«Донской завод радиодеталей ап» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "Д", description: "«Донской завод радиодеталей ап» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "NKHP", name: "НКХП", fullName: "«НКХП» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Н", description: "«НКХП» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "HIMCP", name: "Химпром ап", fullName: "«Химпром ап» · акции Московской биржи, 3-й эшелон.", sector: "Прочее", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "Х", description: "«Химпром ап» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "KMEZ", name: "Ковровский механический завод", fullName: "«Ковровский механический завод» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "К", description: "«Ковровский механический завод» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "ZILL", name: "ЗИЛ", fullName: "«ЗИЛ» · акции Московской биржи, 3-й эшелон.", sector: "Недвижимость", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "З", description: "«ЗИЛ» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "PRMD", name: "Промомед", fullName: "«Промомед» · акции Московской биржи, 3-й эшелон.", sector: "Здравоохранение", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "П", description: "«Промомед» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "TGKN", name: "ТГК-14", fullName: "«ТГК-14» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "Т", description: "«ТГК-14» · акции Московской биржи, 3-й эшелон.", lot: 100000, step: 1 },
  { symbol: "KRSB", name: "Красноярскэнергосбыт", fullName: "«Красноярскэнергосбыт» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "К", description: "«Красноярскэнергосбыт» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "JNOSP", name: "Славнефть ЯНОС ап", fullName: "«Славнефть ЯНОС ап» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "С", description: "«Славнефть ЯНОС ап» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "TNSE", name: "ТНС энерго", fullName: "«ТНС энерго» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Т", description: "«ТНС энерго» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "MAGE", name: "Магаданэнерго", fullName: "«Магаданэнерго» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "М", description: "«Магаданэнерго» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "GEMA", name: "Гемабанк", fullName: "«Гемабанк» · акции Московской биржи, 3-й эшелон.", sector: "Здравоохранение", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Г", description: "«Гемабанк» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "SVETP", name: "Светофор Групп-ап", fullName: "«Светофор Групп-ап» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "С", description: "«Светофор Групп-ап» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "ASSB", name: "Астраханская энергосбытовая компания", fullName: "«Астраханская энергосбытовая компания» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "А", description: "«Астраханская энергосбытовая компания» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "LVHK", name: "Левенгук", fullName: "«Левенгук» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "Л", description: "«Левенгук» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "UWGN", name: "ОВК", fullName: "«ОВК» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "О", description: "«ОВК» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "TASBP", name: "Тамбовская энергосбытовая компания ап", fullName: "«Тамбовская энергосбытовая компания ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "Т", description: "«Тамбовская энергосбытовая компания ап» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "BRZL", name: "Бурятзолото", fullName: "«Бурятзолото» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "Б", description: "«Бурятзолото» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "FIXR", name: "Фикс Прайс", fullName: "«Фикс Прайс» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "Ф", description: "«Фикс Прайс» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "VRSB", name: "ТНС энерго Воронеж", fullName: "«ТНС энерго Воронеж» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Т", description: "«ТНС энерго Воронеж» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "RDRB", name: "РосДорБанк", fullName: "«РосДорБанк» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "Р", description: "«РосДорБанк» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "MBNK", name: "МТС-Банк", fullName: "«МТС-Банк» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "М", description: "«МТС-Банк» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "NFAZ", name: "НЕФАЗ", fullName: "«НЕФАЗ» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "Н", description: "«НЕФАЗ» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "SLEN", name: "Сахалинэнерго", fullName: "«Сахалинэнерго» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "С", description: "«Сахалинэнерго» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "VRSBP", name: "ТНС энерго Воронеж ап", fullName: "«ТНС энерго Воронеж ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "Т", description: "«ТНС энерго Воронеж ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "KAZTP", name: "КуйбышевАзот - Акции привилегированные ап", fullName: "«КуйбышевАзот - Акции привилегированные ап» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "К", description: "«КуйбышевАзот - Акции привилегированные ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "URKZ", name: "Уралкуз", fullName: "«Уралкуз» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "У", description: "«Уралкуз» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "STSBP", name: "Ставропольэнергосбыт ап", fullName: "«Ставропольэнергосбыт ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "С", description: "«Ставропольэнергосбыт ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "TGKBP", name: "ТГК-2 ап", fullName: "«ТГК-2 ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "Т", description: "«ТГК-2 ап» · акции Московской биржи, 3-й эшелон.", lot: 100000, step: 1 },
  { symbol: "EUTR", name: "ЕвроТранс", fullName: "«ЕвроТранс» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Е", description: "«ЕвроТранс» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "MRKU", name: "Россети Урал", fullName: "«Россети Урал» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "Р", description: "«Россети Урал» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "MRKV", name: "Россети Волга", fullName: "«Россети Волга» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Р", description: "«Россети Волга» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "CNTL", name: "Центральный Телеграф", fullName: "«Центральный Телеграф» · акции Московской биржи, 3-й эшелон.", sector: "Телеком", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "Ц", description: "«Центральный Телеграф» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "VSEH", name: "ВИ.РУ", fullName: "«ВИ.РУ» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "В", description: "«ВИ.РУ» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "MRKK", name: "МРСК Северного Кавказа", fullName: "«МРСК Северного Кавказа» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "М", description: "«МРСК Северного Кавказа» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "KRKOP", name: "Красный котельщик-ап-О", fullName: "«Красный котельщик-ап-О» · акции Московской биржи, 3-й эшелон.", sector: "Прочее", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "К", description: "«Красный котельщик-ап-О» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "KUZB", name: "Кузнецкий Банк", fullName: "«Кузнецкий Банк» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "К", description: "«Кузнецкий Банк» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "OMZZP", name: "ОМЗ (Группа Уралмаш-Ижора) ап", fullName: "«ОМЗ (Группа Уралмаш-Ижора) ап» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "О", description: "«ОМЗ (Группа Уралмаш-Ижора) ап» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "ETLN", name: "Эталон Груп", fullName: "«Эталон Груп» · акции Московской биржи, 3-й эшелон.", sector: "Недвижимость", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "Э", description: "«Эталон Груп» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "RGSS", name: "Росгосстрах", fullName: "«Росгосстрах» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Р", description: "«Росгосстрах» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "YRSBP", name: "ТНС энерго Ярославль ап", fullName: "«ТНС энерго Ярославль ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "Т", description: "«ТНС энерго Ярославль ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "GECO", name: "Генетико", fullName: "«Генетико» · акции Московской биржи, 3-й эшелон.", sector: "Здравоохранение", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Г", description: "«Генетико» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "LSNG", name: "Россети Ленэнерго", fullName: "«Россети Ленэнерго» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "Р", description: "«Россети Ленэнерго» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "SVET", name: "Светофор Групп", fullName: "«Светофор Групп» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "С", description: "«Светофор Групп» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "VSYDP", name: "ВыбСудЗ ап", fullName: "«ВыбСудЗ ап» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "В", description: "«ВыбСудЗ ап» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "KLSB", name: "Калужская сбытовая компания", fullName: "«Калужская сбытовая компания» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "К", description: "«Калужская сбытовая компания» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "MRKZ", name: "Россети Северо-Запад", fullName: "«Россети Северо-Запад» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "Р", description: "«Россети Северо-Запад» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "STSB", name: "Ставропольэнергосбыт", fullName: "«Ставропольэнергосбыт» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "С", description: "«Ставропольэнергосбыт» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "NKSH", name: "Нижнекамскшина", fullName: "«Нижнекамскшина» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "Н", description: "«Нижнекамскшина» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "LNZLP", name: "Лензолото ап", fullName: "«Лензолото ап» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Л", description: "«Лензолото ап» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "BAZA", name: "ГК БАЗИС", fullName: "«ГК БАЗИС» · акции Московской биржи, 3-й эшелон.", sector: "Технологии", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "Г", description: "«ГК БАЗИС» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "CHKZ", name: "Челябинский кузнечно-прессовый завод", fullName: "«Челябинский кузнечно-прессовый завод» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Ч", description: "«Челябинский кузнечно-прессовый завод» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "KFBA", name: "ИНГРАД", fullName: "«ИНГРАД» · акции Московской биржи, 3-й эшелон.", sector: "Недвижимость", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "И", description: "«ИНГРАД» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "RTSBP", name: "ТНС энерго Ростов-на-Дону ап", fullName: "«ТНС энерго Ростов-на-Дону ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "Т", description: "«ТНС энерго Ростов-на-Дону ап» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "RTSB", name: "ТНС энерго Ростов-на-Дону", fullName: "«ТНС энерго Ростов-на-Дону» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "Т", description: "«ТНС энерго Ростов-на-Дону» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "AVAN", name: "Авангард Банк", fullName: "«Авангард Банк» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "А", description: "«Авангард Банк» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "CNTLP", name: "Центральный Телеграф ап", fullName: "«Центральный Телеграф ап» · акции Московской биржи, 3-й эшелон.", sector: "Телеком", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "Ц", description: "«Центральный Телеграф ап» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "LIFE", name: "Фармсинтез", fullName: "«Фармсинтез» · акции Московской биржи, 3-й эшелон.", sector: "Здравоохранение", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "Ф", description: "«Фармсинтез» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "DATA", name: "Группа Аренадата", fullName: "«Группа Аренадата» · акции Московской биржи, 3-й эшелон.", sector: "Технологии", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "Г", description: "«Группа Аренадата» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "IRKT", name: "Яковлев", fullName: "«Яковлев» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Я", description: "«Яковлев» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "ROST", name: "Росинтер Ресторантс Холдинг", fullName: "«Росинтер Ресторантс Холдинг» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "Р", description: "«Росинтер Ресторантс Холдинг» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "NNSB", name: "ТНС энерго Нижний Новгород", fullName: "«ТНС энерго Нижний Новгород» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Т", description: "«ТНС энерго Нижний Новгород» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "SARE", name: "Саратовэнерго", fullName: "«Саратовэнерго» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "С", description: "«Саратовэнерго» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "HNFG", name: "HENDERSON", fullName: "«HENDERSON» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "H", description: "«HENDERSON» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "HHRU", name: "HeadHunter Group PLC", fullName: "«HeadHunter Group PLC» · акции Московской биржи, 3-й эшелон.", sector: "Технологии", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "H", description: "«HeadHunter Group PLC» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "YRSB", name: "ТНС энерго Ярославль", fullName: "«ТНС энерго Ярославль» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "Т", description: "«ТНС энерго Ярославль» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "KROTP", name: "Красный Октябрь ап", fullName: "«Красный Октябрь ап» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "К", description: "«Красный Октябрь ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "WTCM", name: "Центр международной торговли", fullName: "«Центр международной торговли» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "Ц", description: "«Центр международной торговли» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "OKEY", name: "O'Key Group SA", fullName: "«O'Key Group SA» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "O", description: "«O'Key Group SA» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "MRKP", name: "Россети Центр и Приволжье", fullName: "«Россети Центр и Приволжье» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Р", description: "«Россети Центр и Приволжье» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "KCHE", name: "Камчатскэнерго", fullName: "«Камчатскэнерго» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "К", description: "«Камчатскэнерго» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "UKUZ", name: "Южный Кузбасс", fullName: "«Южный Кузбасс» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Ю", description: "«Южный Кузбасс» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "YKENP", name: "Якутскэнерго ап", fullName: "«Якутскэнерго ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "Я", description: "«Якутскэнерго ап» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "OZPH", name: "Озон Фармацевтика", fullName: "«Озон Фармацевтика» · акции Московской биржи, 3-й эшелон.", sector: "Здравоохранение", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "О", description: "«Озон Фармацевтика» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "KOGK", name: "Коршуновский ГОК", fullName: "«Коршуновский ГОК» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "К", description: "«Коршуновский ГОК» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "PMSB", name: "Пермэнергосбыт", fullName: "«Пермэнергосбыт» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "П", description: "«Пермэнергосбыт» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "ARSA", name: "Арсагера", fullName: "«Арсагера» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "А", description: "«Арсагера» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "GLRX", name: "Глоракс", fullName: "«Глоракс» · акции Московской биржи, 3-й эшелон.", sector: "Недвижимость", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "Г", description: "«Глоракс» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "VJGZP", name: "Варьеганнефтегаз ап", fullName: "«Варьеганнефтегаз ап» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "В", description: "«Варьеганнефтегаз ап» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "NSVZ", name: "Наука-Связь", fullName: "«Наука-Связь» · акции Московской биржи, 3-й эшелон.", sector: "Телеком", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Н", description: "«Наука-Связь» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "BLNG", name: "Белон", fullName: "«Белон» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "Б", description: "«Белон» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "DZRD", name: "Донской завод радиодеталей", fullName: "«Донской завод радиодеталей» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Д", description: "«Донской завод радиодеталей» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "UNKL", name: "ЮУНК", fullName: "«ЮУНК» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "Ю", description: "«ЮУНК» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "KRKN", name: "Саратовский нефтеперерабатывающий завод", fullName: "«Саратовский нефтеперерабатывающий завод» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "С", description: "«Саратовский нефтеперерабатывающий завод» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "OGKB", name: "Вторая генерирующая компания оптового рынка электроэнергии", fullName: "«Вторая генерирующая компания оптового рынка электроэнергии» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "В", description: "«Вторая генерирующая компания оптового рынка электроэнергии» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "MGTS", name: "МГТС", fullName: "«МГТС» · акции Московской биржи, 3-й эшелон.", sector: "Телеком", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "М", description: "«МГТС» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "LMBZ", name: "Ламбумиз", fullName: "«Ламбумиз» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "Л", description: "«Ламбумиз» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "KRSBP", name: "Красноярскэнергосбыт ап", fullName: "«Красноярскэнергосбыт ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "К", description: "«Красноярскэнергосбыт ап» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "ABRD", name: "АбрауДюрсо", fullName: "«АбрауДюрсо» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "А", description: "«АбрауДюрсо» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "KRKNP", name: "Саратовский НПЗ ап", fullName: "«Саратовский НПЗ ап» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "С", description: "«Саратовский НПЗ ап» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "EVRZ", name: "Акции обыкновенные ЕВРАЗ НТМК", fullName: "«Акции обыкновенные ЕВРАЗ НТМК» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "А", description: "«Акции обыкновенные ЕВРАЗ НТМК» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "MISB", name: "ТНС энерго Марий Эл", fullName: "«ТНС энерго Марий Эл» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Т", description: "«ТНС энерго Марий Эл» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "GAZAP", name: "ГАЗ ап", fullName: "«ГАЗ ап» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "Г", description: "«ГАЗ ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "RTKMP", name: "Ростелеком - Привилегированные акции", fullName: "«Ростелеком - Привилегированные акции» · акции Московской биржи, 3-й эшелон.", sector: "Телеком", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "Р", description: "«Ростелеком - Привилегированные акции» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "TORS", name: "Томская распределительная компания", fullName: "«Томская распределительная компания» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "Т", description: "«Томская распределительная компания» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "KLVZ", name: "Кристалл", fullName: "«Кристалл» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "К", description: "«Кристалл» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "IGSTP", name: "Ижсталь ап", fullName: "«Ижсталь ап» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "И", description: "«Ижсталь ап» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "IGST", name: "Ижсталь", fullName: "«Ижсталь» · акции Московской биржи, 3-й эшелон.", sector: "Металлы и добыча", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "И", description: "«Ижсталь» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "VEON-RX", name: "VEON", fullName: "«VEON» · акции Московской биржи, 3-й эшелон.", sector: "Телеком", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "V", description: "«VEON» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "SAGOP", name: "Самараэнерго ап", fullName: "«Самараэнерго ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "С", description: "«Самараэнерго ап» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "VSYD", name: "ВыбСудЗ", fullName: "«ВыбСудЗ» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "В", description: "«ВыбСудЗ» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "MISBP", name: "ТНС энерго Марий Эл ап", fullName: "«ТНС энерго Марий Эл ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Т", description: "«ТНС энерго Марий Эл ап» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "MVID", name: "М.Видео", fullName: "«М.Видео» · акции Московской биржи, 3-й эшелон.", sector: "Потребительский сектор", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "М", description: "«М.Видео» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "WTCMP", name: "Центр международной торговли ап", fullName: "«Центр международной торговли ап» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "Ц", description: "«Центр международной торговли ап» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "MFGSP", name: "Славнефть-Мегионнефтегаз ап", fullName: "«Славнефть-Мегионнефтегаз ап» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "С", description: "«Славнефть-Мегионнефтегаз ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "PAZA", name: "Павловский автобус", fullName: "«Павловский автобус» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "П", description: "«Павловский автобус» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "YKEN", name: "Якутскэнерго", fullName: "«Якутскэнерго» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "Я", description: "«Якутскэнерго» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
  { symbol: "PMSBP", name: "Пермэнергосбыт ап", fullName: "«Пермэнергосбыт ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "П", description: "«Пермэнергосбыт ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "MSTT", name: "Мостотрест", fullName: "«Мостотрест» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "М", description: "«Мостотрест» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "USBN", name: "Банк УРАЛСИБ", fullName: "«Банк УРАЛСИБ» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Б", description: "«Банк УРАЛСИБ» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "IVAT", name: "IVA Technologies", fullName: "«IVA Technologies» · акции Московской биржи, 3-й эшелон.", sector: "Технологии", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "I", description: "«IVA Technologies» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "RKKE", name: "РКК Энергия им.С.П.Королева", fullName: "«РКК Энергия им.С.П.Королева» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Р", description: "«РКК Энергия им.С.П.Королева» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "MRKC", name: "Россети Центр", fullName: "«Россети Центр» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "Р", description: "«Россети Центр» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "YAKG", name: "ЯТЭК", fullName: "«ЯТЭК» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "Я", description: "«ЯТЭК» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "GTRK", name: "ГТМ", fullName: "«ГТМ» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "Г", description: "«ГТМ» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "FESH", name: "ДВМП", fullName: "«ДВМП» · акции Московской биржи, 3-й эшелон.", sector: "Промышленность", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "Д", description: "«ДВМП» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "RTGZ", name: "Ростовоблгаз", fullName: "«Ростовоблгаз» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "Р", description: "«Ростовоблгаз» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "VGSBP", name: "Волгоградэнергосбыт ап", fullName: "«Волгоградэнергосбыт ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "В", description: "«Волгоградэнергосбыт ап» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "BSPBP", name: "Банк Санкт-Петербург", fullName: "«Банк Санкт-Петербург» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "Б", description: "«Банк Санкт-Петербург» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "LSNGP", name: "Россети Ленэнерго ап", fullName: "«Россети Ленэнерго ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Р", description: "«Россети Ленэнерго ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "JNOS", name: "Славнефть ЯНОС", fullName: "«Славнефть ЯНОС» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#5b8def", mark: "С", description: "«Славнефть ЯНОС» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "MRKS", name: "Россети Сибирь", fullName: "«Россети Сибирь» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#e0a33e", mark: "Р", description: "«Россети Сибирь» · акции Московской биржи, 3-й эшелон.", lot: 1000, step: 1 },
  { symbol: "MGKL", name: "МГКЛ", fullName: "«МГКЛ» · акции Московской биржи, 3-й эшелон.", sector: "Финансы", kind: "stock", tier: 3, price: 100, change: 0, color: "#3fb6a8", mark: "М", description: "«МГКЛ» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "CHGZ", name: "РН-Западная Сибирь", fullName: "«РН-Западная Сибирь» · акции Московской биржи, 3-й эшелон.", sector: "Нефть и газ", kind: "stock", tier: 3, price: 100, change: 0, color: "#c05c5c", mark: "Р", description: "«РН-Западная Сибирь» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "INCB", name: "Инкаб Холдинг", fullName: "«Инкаб Холдинг» · акции Московской биржи, 3-й эшелон.", sector: "Технологии", kind: "stock", tier: 3, price: 100, change: 0, color: "#8a7bd8", mark: "И", description: "«Инкаб Холдинг» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "MAGEP", name: "Магаданэнерго ап", fullName: "«Магаданэнерго ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#4aa3df", mark: "М", description: "«Магаданэнерго ап» · акции Московской биржи, 3-й эшелон.", lot: 100, step: 1 },
  { symbol: "NNSBP", name: "ТНС энерго Нижний Новгород ап", fullName: "«ТНС энерго Нижний Новгород ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#d0803f", mark: "Т", description: "«ТНС энерго Нижний Новгород ап» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "TORSP", name: "Томская распределительная компания ап", fullName: "«Томская распределительная компания ап» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#59b06f", mark: "Т", description: "«Томская распределительная компания ап» · акции Московской биржи, 3-й эшелон.", lot: 10, step: 1 },
  { symbol: "BTBR", name: "В2В-РТС", fullName: "«В2В-РТС» · акции Московской биржи, 3-й эшелон.", sector: "Технологии", kind: "stock", tier: 3, price: 100, change: 0, color: "#b06fb0", mark: "В", description: "«В2В-РТС» · акции Московской биржи, 3-й эшелон.", lot: 1, step: 1 },
  { symbol: "MRKY", name: "Россети Юг", fullName: "«Россети Юг» · акции Московской биржи, 3-й эшелон.", sector: "Энергетика", kind: "stock", tier: 3, price: 100, change: 0, color: "#7f8c99", mark: "Р", description: "«Россети Юг» · акции Московской биржи, 3-й эшелон.", lot: 10000, step: 1 },
];

const EXTRA: Instrument[] = [
  { symbol: "IMOEX", name: "Индекс МосБиржи", fullName: "Индекс Московской биржи", sector: "Индексы", kind: "index", price: 3245.81, change: 0.82, color: "#cf4e5b", mark: "M", description: "Основной рублёвый индикатор российского рынка акций. Рассчитывается Московской биржей.", lot: 1, step: 0.01 },
  { symbol: "RTSI", name: "Индекс РТС", fullName: "Индекс Российской торговой системы", sector: "Индексы", kind: "index", price: 1128.34, change: 0.56, color: "#7394ca", mark: "R", description: "Долларовый индикатор российского рынка акций.", lot: 1, step: 0.01 },
  { symbol: "RGBI", name: "Индекс ОФЗ", fullName: "Индекс государственных облигаций", sector: "Индексы", kind: "index", price: 107.82, change: -0.12, color: "#8f7ac5", mark: "О", description: "Индекс цен наиболее ликвидных государственных облигаций России.", lot: 1, step: 0.01 },
  { symbol: "CNYRUB_TOM", name: "Юань / Рубль", fullName: "Китайский юань к российскому рублю", sector: "Валюты", kind: "currency", price: 12.486, change: -0.18, color: "#c45d53", mark: "¥", description: "Курс китайского юаня к российскому рублю с расчётами завтра.", lot: 1000, step: 0.001 },
];

export const INSTRUMENTS: Instrument[] = [...STOCKS, ...EXTRA];

export const DEFAULT_SETTINGS: WorkspaceSettings = {
  symbol: "SBER", timeframe: "1h", watchlist: STOCKS.filter(i => i.tier === 1).slice(0, 12).map(i => i.symbol).concat(STOCKS.filter(i => i.tier === 2).slice(0, 6).map(i => i.symbol)),
  chartType: "candles", drawings: {}, showVolume: true, smc: DEFAULT_SMC,
};

export function getInstrument(symbol: string) { return INSTRUMENTS.find(i => i.symbol === symbol) ?? INSTRUMENTS[0]; }
export function formatPrice(price: number, digits = 2) { return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(price); }
export function formatCompact(value: number) { return new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 2 }).format(value); }
export function formatChange(change: number) { return `${change >= 0 ? "+" : "−"}${formatPrice(Math.abs(change))}%`; }
/** Изменение за день: «—», если предыдущее закрытие неизвестно (0,00% вводило в заблуждение). */
export function changeLabel(quote: Quote | null | undefined) {
  if (!quote) return "—";
  return quote.changeKnown === false ? "—" : formatChange(quote.change);
}
export function formatMoney(value: number) { return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value); }
/**
 * Детерминированные «синтетические» свечи. Используются ТОЛЬКО в тестах и в явно
 * помеченном демо-режиме: если живых данных нет, сервер возвращает пустой набор
 * и терминал показывает честное пустое состояние. Никогда не выдаются за биржевые.
 */
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

/**
 * Цена закрытия предыдущей торговой сессии по дневным свечам.
 *
 * Правило простое и важное для «изменения за день»: если последний дневной бар —
 * сегодняшний (торги уже шли), предыдущее закрытие — это бар перед ним; если сегодня
 * бара ещё нет (утро, выходной), последний бар и есть закрытие прошлой сессии.
 * `now` передаётся параметром, чтобы функцию можно было проверить тестом.
 */
export function previousSessionClose(daily: Candle[], now = Date.now()): number | null {
  if (daily.length < 1) return null;
  const todayStart = mskBucket(Math.floor(now / 1000), 86400);
  const last = daily[daily.length - 1];
  if (last.time < todayStart) return last.close > 0 ? last.close : null;
  const previous = daily[daily.length - 2];
  return previous && previous.close > 0 ? previous.close : null;
}

/** Мок-котировка для тестов. В терминале не используется: там прочерк вместо выдуманной цены. */
export function demoQuote(instrument: Instrument): Quote { return { symbol: instrument.symbol, price: instrument.price, change: instrument.change, absolute: instrument.price - instrument.price / (1 + instrument.change / 100), high: instrument.price * 1.006, low: instrument.price * .988, volume: Math.round(16450000 / (instrument.price / 100)), source: "demo" }; }
