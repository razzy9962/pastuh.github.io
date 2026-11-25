// SMC Pro [improved + LuxAlgo OB] — порт Pine Script v6 в TypeScript.
// Логика Order Blocks повторяет метод Smart Money Concepts [LuxAlgo] (CC BY-NC-SA 4.0):
// пары "нога/пивот" -> пробой -> блок из парсинга high/low с фильтром волатильности.
// Расчёт полностью детерминирован и не репейнтит: используются только закрытые бары.
import type { Candle, Timeframe } from "./market";
import { mskBucket } from "./time-buckets";

export type SmcEmaRow = { enabled: boolean; timeframe: Timeframe; period: number; color: string };
export type SmcStructure = {
  mode: "pivot" | "luxalgo";
  swingLegs: number;
  internalLegs: number;
  showSwing: boolean;
  showInternal: boolean;
  showLabels: boolean;
  swings: boolean;
  keep: number;
  displacementAtr: number;
  wickBreak: boolean;
};
export type SmcSettings = {
  /** Версия схемы настроек: нужна, чтобы добавлять новые значения в старые сохранения. */
  version?: number;
  enabled: boolean;
  structure: SmcStructure;
  ob: { internal: boolean; swing: boolean; maxInternal: number; maxSwing: number; swingLength: number; internalLength: number; filter: "atr" | "mean"; mitigation: "hl" | "close" };
  fvg: { show: boolean; minAtr: number; mitigation: "full" | "half"; max: number };
  eq: { show: boolean; toleranceAtr: number };
  premiumDiscount: boolean;
  levels: { show: boolean; pd: boolean; pw: boolean; swings: boolean };
  emas: SmcEmaRow[];
  poc: { show: boolean; stepAtr: number; valueArea: number };
  aplus: { enabled: boolean; minPercent: number; only: boolean };
  signals: { enabled: boolean; minScorePercent: number };
};

export const SMC_PALETTE = {
  bull: "#089981",
  bear: "#f23645",
  internalBull: "rgba(41,98,255,0.20)",
  internalBear: "rgba(247,124,128,0.18)",
  swingBull: "rgba(49,121,245,0.22)",
  swingBear: "rgba(178,40,51,0.22)",
  fvgBull: "rgba(8,153,129,0.16)",
  fvgBear: "rgba(242,54,69,0.15)",
  strong: "#ffb000",
  levelDaily: "#787b86",
  levelWeekly: "#ff9800",
  levelSwing1: "#42a5f5",
  levelSwing2: "#ab47bc",
  poc: "#ff9800",
  valueArea: "#9598a1",
  emaColors: ["#22e39a", "#00d9d9", "#4d9bff", "#ff8a3d", "#c070ff", "#ffc93a", "#6ee7ff", "#b8e986", "#ff5ce0"],
};

// Версия схемы настроек: при её росте сохранённые настройки дополняются новыми значениями.
export const SMC_SETTINGS_VERSION = 3;

export const DEFAULT_SMC: SmcSettings = {
  version: SMC_SETTINGS_VERSION,
  enabled: true,
  structure: { mode: "luxalgo", swingLegs: 5, internalLegs: 3, showSwing: true, showInternal: false, showLabels: true, swings: false, keep: 2, displacementAtr: 0.1, wickBreak: false },
  ob: { internal: true, swing: false, maxInternal: 5, maxSwing: 5, swingLength: 50, internalLength: 5, filter: "atr", mitigation: "hl" },
  fvg: { show: true, minAtr: 0.2, mitigation: "full", max: 8 },
  eq: { show: true, toleranceAtr: 0.15 },
  premiumDiscount: false,
  levels: { show: true, pd: true, pw: true, swings: true },
  emas: [
    { enabled: true, timeframe: "15m", period: 20, color: SMC_PALETTE.emaColors[0] },
    { enabled: true, timeframe: "15m", period: 50, color: SMC_PALETTE.emaColors[1] },
    { enabled: true, timeframe: "1h", period: 50, color: SMC_PALETTE.emaColors[2] },
    // Дневная EMA 20 — обязательная линия (просьба пользователя). Дневная EMA 200 по
    // умолчанию выключена: она есть в списке, но не растягивает шкалу минутного графика.
    { enabled: true, timeframe: "1d", period: 20, color: "#ff9f0a" },
    { enabled: true, timeframe: "4h", period: 50, color: SMC_PALETTE.emaColors[4] },
    { enabled: false, timeframe: "1d", period: 200, color: "#ffd60a" },
  ],
  poc: { show: true, stepAtr: 0.2, valueArea: 70 },
  aplus: { enabled: true, minPercent: 60, only: false },
  signals: { enabled: true, minScorePercent: 80 },
};

const TIMEFRAME_SECONDS: Record<Timeframe, number> = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800 };
const isTimeframe = (value: unknown): value is Timeframe => typeof value === "string" && value in TIMEFRAME_SECONDS;
const isHex = (value: unknown) => typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);
const clampInt = (value: unknown, min: number, max: number, fallback: number) => Number.isFinite(value) ? Math.min(max, Math.max(min, Math.round(Number(value)))) : fallback;
const clampNum = (value: unknown, min: number, max: number, fallback: number) => Number.isFinite(value) ? Math.min(max, Math.max(min, Number(value))) : fallback;

/** Разбор настроек из рабочего пространства: любые неизвестные поля отбрасываются. */
export function sanitizeSmcSettings(value: unknown): SmcSettings {
  const base = structuredClone(DEFAULT_SMC);
  if (!value || typeof value !== "object") return base;
  const raw = value as Record<string, unknown>;
  const obj = (key: string) => (raw[key] && typeof raw[key] === "object" ? raw[key] as Record<string, unknown> : {});
  const structure = obj("structure"), ob = obj("ob"), fvg = obj("fvg"), eq = obj("eq"), levels = obj("levels"), poc = obj("poc"), aplus = obj("aplus"), signals = obj("signals");
  base.enabled = typeof raw.enabled === "boolean" ? raw.enabled : base.enabled;
  base.structure = {
    mode: structure.mode === "pivot" ? "pivot" : "luxalgo",
    swingLegs: clampInt(structure.swingLegs, 1, 50, base.structure.swingLegs),
    internalLegs: clampInt(structure.internalLegs, 1, 20, base.structure.internalLegs),
    showSwing: typeof structure.showSwing === "boolean" ? structure.showSwing : base.structure.showSwing,
    showInternal: typeof structure.showInternal === "boolean" ? structure.showInternal : base.structure.showInternal,
    showLabels: typeof structure.showLabels === "boolean" ? structure.showLabels : base.structure.showLabels,
    swings: typeof structure.swings === "boolean" ? structure.swings : base.structure.swings,
    keep: clampInt(structure.keep, 1, 10, base.structure.keep),
    displacementAtr: clampNum(structure.displacementAtr, 0, 2, base.structure.displacementAtr),
    wickBreak: typeof structure.wickBreak === "boolean" ? structure.wickBreak : base.structure.wickBreak,
  };
  base.ob = {
    internal: typeof ob.internal === "boolean" ? ob.internal : base.ob.internal,
    swing: typeof ob.swing === "boolean" ? ob.swing : base.ob.swing,
    maxInternal: clampInt(ob.maxInternal, 1, 20, base.ob.maxInternal),
    maxSwing: clampInt(ob.maxSwing, 1, 20, base.ob.maxSwing),
    swingLength: clampInt(ob.swingLength, 10, 200, base.ob.swingLength),
    internalLength: clampInt(ob.internalLength, 1, 50, base.ob.internalLength),
    filter: ob.filter === "mean" ? "mean" : "atr",
    mitigation: ob.mitigation === "close" ? "close" : "hl",
  };
  base.fvg = {
    show: typeof fvg.show === "boolean" ? fvg.show : base.fvg.show,
    minAtr: clampNum(fvg.minAtr, 0, 3, base.fvg.minAtr),
    mitigation: fvg.mitigation === "half" ? "half" : "full",
    max: clampInt(fvg.max, 1, 40, base.fvg.max),
  };
  base.eq = { show: typeof eq.show === "boolean" ? eq.show : base.eq.show, toleranceAtr: clampNum(eq.toleranceAtr, 0, 2, base.eq.toleranceAtr) };
  base.premiumDiscount = typeof raw.premiumDiscount === "boolean" ? raw.premiumDiscount : base.premiumDiscount;
  base.levels = {
    show: typeof levels.show === "boolean" ? levels.show : base.levels.show,
    pd: typeof levels.pd === "boolean" ? levels.pd : base.levels.pd,
    pw: typeof levels.pw === "boolean" ? levels.pw : base.levels.pw,
    swings: typeof levels.swings === "boolean" ? levels.swings : base.levels.swings,
  };
  const emas = Array.isArray(raw.emas) ? raw.emas.slice(0, 8) : [];
  // В сохранениях без поля version ещё не было дневной EMA 20 — добавляем её один раз,
  // чтобы после обновления на графике появилась именно «EMA 20 по дням».
  const version = Number.isFinite(Number(raw.version)) ? Number(raw.version) : 1;
  if (emas.length && version < SMC_SETTINGS_VERSION && !emas.some(row => row && typeof row === "object" && (row as Record<string, unknown>).timeframe === "1d" && Number((row as Record<string, unknown>).period) === 20)) {
    emas.push({ enabled: true, timeframe: "1d", period: 20, color: "#ff9f0a" });
  }
  if (emas.length) {
    base.emas = emas.flatMap((row, index) => {
      if (!row || typeof row !== "object") return [];
      const item = row as Record<string, unknown>;
      if (!isTimeframe(item.timeframe)) return [];
      const fallbackColor: string = SMC_PALETTE.emaColors[index % SMC_PALETTE.emaColors.length];
      return [{
        enabled: typeof item.enabled === "boolean" ? item.enabled : true,
        timeframe: item.timeframe,
        period: clampInt(item.period, 2, 400, 50),
        color: isHex(item.color) ? String(item.color) : fallbackColor,
      }];
    });
  }
  base.poc = {
    show: typeof poc.show === "boolean" ? poc.show : base.poc.show,
    stepAtr: clampNum(poc.stepAtr, 0.02, 2, base.poc.stepAtr),
    valueArea: clampNum(poc.valueArea, 50, 95, base.poc.valueArea),
  };
  base.aplus = {
    enabled: typeof aplus.enabled === "boolean" ? aplus.enabled : base.aplus.enabled,
    minPercent: clampInt(aplus.minPercent, 30, 100, base.aplus.minPercent),
    only: typeof aplus.only === "boolean" ? aplus.only : base.aplus.only,
  };
  base.signals = {
    enabled: typeof signals.enabled === "boolean" ? signals.enabled : base.signals.enabled,
    minScorePercent: clampInt(signals.minScorePercent, 30, 100, base.signals.minScorePercent),
  };
  base.version = SMC_SETTINGS_VERSION;
  return base;
}

// ---------------------------------------------------------------------------
// Математика
// ---------------------------------------------------------------------------
function rma(values: number[], period: number): number[] {
  const out: number[] = [];
  let sum = 0, prev = NaN;
  for (let i = 0; i < values.length; i++) {
    if (i < period) { sum += values[i]; if (i === period - 1) { prev = sum / period; out.push(prev); } else out.push(NaN); }
    else { prev = (prev * (period - 1) + values[i]) / period; out.push(prev); }
  }
  return out;
}

function atrSeries(candles: Candle[], period = 200): number[] {
  const tr = candles.map((c, i) => i === 0 ? c.high - c.low : Math.max(c.high - c.low, Math.abs(c.high - candles[i - 1].close), Math.abs(c.low - candles[i - 1].close)));
  const atr = rma(tr, Math.min(period, Math.max(2, Math.floor(candles.length / 2))));
  const fallback = candles.reduce((sum, c) => sum + (c.high - c.low), 0) / Math.max(1, candles.length) || 1;
  return atr.map(value => Number.isFinite(value) && value > 0 ? value : fallback);
}

function emaSeries(values: number[], period: number): number[] {
  const alpha = 2 / (period + 1);
  const out: number[] = [];
  let prev = NaN;
  for (let i = 0; i < values.length; i++) {
    prev = Number.isFinite(prev) ? values[i] * alpha + prev * (1 - alpha) : values[i];
    out.push(i >= period - 1 ? prev : NaN);
  }
  return out;
}

/** Свинговые пивоты (аналог ta.pivothigh / ta.pivotlow). Возвращает карту: индекс бара -> значение пивота. */
function pivotMap(candles: Candle[], legs: number, field: "high" | "low"): Map<number, number> {
  const map = new Map<number, number>();
  for (let i = legs; i + legs < candles.length; i++) {
    let extreme = field === "high" ? -Infinity : Infinity;
    for (let k = i - legs; k <= i + legs; k++) extreme = field === "high" ? Math.max(extreme, candles[k].high) : Math.min(extreme, candles[k].low);
    const value = candles[i][field];
    if (field === "high" ? value >= extreme : value <= extreme) map.set(i, value);
  }
  return map;
}

/**
 * Агрегация свечей в старший таймфрейм (для EMA, PDH/PWH и свингов старших ТФ).
 * Границы бакетов — по московскому времени: иначе «дневная» свеча начиналась в 03:00 МСК,
 * а «недельная» — в четверг, и PDH/PWH показывали экстремум не того дня и не той недели.
 */
export function resample(candles: Candle[], seconds: number): Candle[] {
  const out: Candle[] = [];
  for (const candle of candles) {
    const bucket = mskBucket(candle.time, seconds, seconds === 14400 ? 10 : 0);
    const last = out[out.length - 1];
    if (last && last.time === bucket) {
      last.high = Math.max(last.high, candle.high);
      last.low = Math.min(last.low, candle.low);
      last.close = candle.close;
      last.volume += candle.volume;
    } else out.push({ ...candle, time: bucket, open: candle.open });
  }
  return out;
}

type Level = { name: string; price: number; color: string };
type Flags = { score: number; max: number; mask: number };

type OrderBlock = {
  top: number; bot: number; bias: 1 | -1; from: number; born: number;
  strong: boolean; score: number; max: number; touched: boolean; done: boolean;
  touchBar: number; maxExcursion: number; minExcursion: number;
};

type Fvg = { top: number; bot: number; bias: 1 | -1; from: number; born: number; mitigated: boolean };

// ---------------------------------------------------------------------------
// Результат расчёта (всё, что рисуется на графике)
// ---------------------------------------------------------------------------
export type SmcBox = { top: number; bottom: number; from: number; to: number | null; fill: string; border: string; bias: 1 | -1; strong: boolean; label?: string };
export type SmcLine = { price: number; from: number; to: number | null; color: string; width: number; style: "solid" | "dashed" | "dotted"; axisLabel?: string };
export type SmcText = { time: number; price: number; text: string; color: string; above: boolean };
export type SmcMarker = { time: number; bias: 1 | -1; text: string; strong: boolean };
export type SmcSeries = { id: string; label: string; color: string; data: { time: number; value: number }[]; labelAt?: number };
export type SmcStats = {
  bias: 1 | -1 | 0;
  equilibrium: number | null;
  range: number | null;
  premiumDiscountZone: "premium" | "discount" | "equilibrium" | null;
  levels: Level[];
  poc: number | null; vah: number | null; val: number | null;
  fvgCount: number; obCount: number; internalObCount: number;
  aplusBuy: { wins: number; losses: number };
  aplusSell: { wins: number; losses: number };
  created: number; removed: number;
  support: number | null; resistance: number | null;
};
export type SmcOverlay = { boxes: SmcBox[]; lines: SmcLine[]; texts: SmcText[]; markers: SmcMarker[]; series: SmcSeries[]; stats: SmcStats; lastPrice?: number };

export const EMPTY_OVERLAY: SmcOverlay = {
  boxes: [], lines: [], texts: [], markers: [], series: [],
  stats: { bias: 0, equilibrium: null, range: null, premiumDiscountZone: null, levels: [], poc: null, vah: null, val: null, fvgCount: 0, obCount: 0, internalObCount: 0, aplusBuy: { wins: 0, losses: 0 }, aplusSell: { wins: 0, losses: 0 }, created: 0, removed: 0, support: null, resistance: null },
};

// ---------------------------------------------------------------------------
// Основной расчёт
// ---------------------------------------------------------------------------
export function computeSmc(candles: Candle[], settings: SmcSettings, timeframe: Timeframe, daily?: Candle[]): SmcOverlay {
  if (!candles.length || !settings.enabled) return EMPTY_OVERLAY;
  const s = settings;
  const n = candles.length;
  // ATR на первых барах — NaN (RMA ещё не набрала период). Подставляем средний диапазон,
  // иначе все пороги (размер FVG, допуск равенства, смещение пробоя) обнулялись и
  // индикатор либо молчал, либо рисовал всё подряд.
  const rawAtr = atrSeries(candles);
  const fallbackAtr = candles.reduce((sum, c) => sum + (c.high - c.low), 0) / Math.max(1, n) || 1;
  const atrAt = (i: number) => {
    const value = rawAtr[Math.max(0, Math.min(n - 1, i))];
    return Number.isFinite(value) && value > 0 ? value : fallbackAtr;
  };
  const barSeconds = TIMEFRAME_SECONDS[timeframe];
  const lastTime = candles[n - 1].time;

  // --- EMA со старших таймфреймов (без lookahead: берём предыдущий закрытый бар старшего ТФ) ---
  const series: SmcSeries[] = [];
  const emaValuesAtBar: number[][] = Array.from({ length: n }, () => []);
  if (s.emas.some(row => row.enabled)) {
    for (const row of s.emas.filter(item => item.enabled)) {
      // Дневная EMA считается по настоящим дневным свечам (на часовом графике из 1200 баров
      // получается всего ~50 дней — период 20 «съедал» историю и линия врала).
      const source = row.timeframe === "1d" && timeframe !== "1d" && daily && daily.length >= row.period + 2 ? daily : candles;
      const higher = resample(source, TIMEFRAME_SECONDS[row.timeframe]);
      const values = emaSeries(higher.map(c => c.close), row.period);
      const data: { time: number; value: number }[] = [];
      let bucket = 0;
      for (let i = 0; i < n; i++) {
        while (bucket + 1 < higher.length && higher[bucket + 1].time <= candles[i].time) bucket++;
        // Берём EMA закрытого бара старшего ТФ (bucket - 1): текущий бар ещё формируется,
        // и его значение перерисовывалось бы на каждом тике (lookahead).
        // Если истории меньше периода, честно не рисуем линию, а не экстраполируем.
        const value = values[bucket - 1];
        if (Number.isFinite(value)) {
          data.push({ time: candles[i].time, value });
          emaValuesAtBar[i].push(value);
        }
      }
      if (data.length) series.push({ id: `smc-ema-${row.timeframe}-${row.period}-${row.color}`, label: `${row.timeframe.toUpperCase()} EMA ${row.period}`, color: row.color, data, labelAt: candles[n - 1].time });
    }
  }

  // --- POC / value area по последнему окну ---
  let poc: number | null = null, vah: number | null = null, val: number | null = null;
  const profileWindow = Math.min(n, 220);
  // Объёмный профиль имеет смысл только при настоящем объёме: у индексов и валют
  // провайдер отдаёт нули, и POC/VAH/VAL превращались в случайные линии.
  const windowCandles = candles.slice(n - profileWindow);
  const hasVolume = windowCandles.reduce((sum, c) => sum + (Number.isFinite(c.volume) ? c.volume : 0), 0) > 0;
  if (s.poc.show && profileWindow > 12 && hasVolume) {
    const profile = volumeProfile(windowCandles, atrAt(n - 1) * s.poc.stepAtr, s.poc.valueArea);
    poc = profile.poc; vah = profile.vah; val = profile.val;
  }

  // --- Уровни старшего ТФ: PDH/PDL, PWH/PWL, свинги 1ч/4ч ---
  const levels: Level[] = [];
  if (s.levels.show) {
    const daily = resample(candles, 86400);
    const weekly = resample(candles, 604800);
    // PDH/PDL и PWH/PWL имеют смысл, только когда в истории есть хотя бы два полных
    // периода: иначе «предыдущий день» — это обрубок текущей сессии.
    if (s.levels.pd && daily.length > 1) {
      levels.push({ name: "PDH", price: daily[daily.length - 2].high, color: SMC_PALETTE.levelDaily });
      levels.push({ name: "PDL", price: daily[daily.length - 2].low, color: SMC_PALETTE.levelDaily });
    }
    if (s.levels.pw && weekly.length > 1) {
      levels.push({ name: "PWH", price: weekly[weekly.length - 2].high, color: SMC_PALETTE.levelWeekly });
      levels.push({ name: "PWL", price: weekly[weekly.length - 2].low, color: SMC_PALETTE.levelWeekly });
    }
    if (s.levels.swings) {
      for (const [tf, color, prefix] of [["1h", SMC_PALETTE.levelSwing1, "1H"], ["4h", SMC_PALETTE.levelSwing2, "4H"]] as const) {
        // Свинг старшего ТФ рисуем только если этот ТФ действительно старше графика:
        // на минутном графике «4ч» из resample — это те же минуты, только склеенные.
        if (TIMEFRAME_SECONDS[tf] <= barSeconds) continue;
        const higher = resample(candles, TIMEFRAME_SECONDS[tf]);
        if (higher.length < 6) continue;
        const highs = [...pivotMap(higher, 3, "high").entries()];
        const lows = [...pivotMap(higher, 3, "low").entries()];
        const lastHigh = highs.at(-1), lastLow = lows.at(-1);
        if (lastHigh) levels.push({ name: `${prefix}·H`, price: lastHigh[1], color });
        if (lastLow) levels.push({ name: `${prefix}·L`, price: lastLow[1], color });
      }
    }
  }

  // --- Парсинг high/low с фильтром волатильности (как у LuxAlgo) ---
  const meanRange = (() => {
    let sum = 0;
    return candles.map((c, i) => { sum += Math.max(c.high - c.low, i ? Math.abs(c.high - candles[i - 1].close) : 0); return sum / (i + 1); });
  })();
  const parsedHigh: number[] = [], parsedLow: number[] = [];
  for (let i = 0; i < n; i++) {
    const measure = s.ob.filter === "atr" ? atrAt(i) : meanRange[i];
    const highVolatility = candles[i].high - candles[i].low >= 2 * measure;
    parsedHigh.push(highVolatility ? candles[i].low : candles[i].high);
    parsedLow.push(highVolatility ? candles[i].high : candles[i].low);
  }

  // --- FVG ---
  const fvgs: Fvg[] = [];
  const boxes: SmcBox[] = [];
  const lines: SmcLine[] = [];
  const texts: SmcText[] = [];
  const markers: SmcMarker[] = [];

  if (s.fvg.show) {
    for (let i = 2; i < n; i++) {
      const minGap = s.fvg.minAtr * atrAt(i);
      if (candles[i].low > candles[i - 2].high && candles[i].close > candles[i - 2].high && candles[i].low - candles[i - 2].high >= minGap)
        fvgs.push({ bot: candles[i - 2].high, top: candles[i].low, bias: 1, from: candles[i].time, born: i, mitigated: false });
      if (candles[i].high < candles[i - 2].low && candles[i].close < candles[i - 2].low && candles[i - 2].low - candles[i].high >= minGap)
        fvgs.push({ bot: candles[i].high, top: candles[i - 2].low, bias: -1, from: candles[i].time, born: i, mitigated: false });
      // митигация и лимит активных гэпов
      for (let k = fvgs.length - 1; k >= 0; k--) {
        const zone = fvgs[k];
        if (zone.born === i) continue;
        const half = (zone.top + zone.bot) / 2;
        const hit = zone.bias === 1 ? candles[i].low <= (s.fvg.mitigation === "half" ? half : zone.bot) : candles[i].high >= (s.fvg.mitigation === "half" ? half : zone.top);
        if (hit) fvgs.splice(k, 1);
      }
      const active = fvgs.filter(zone => !zone.mitigated);
      while (active.length > s.fvg.max) {
        const index = fvgs.indexOf(active.shift()!);
        if (index >= 0) fvgs.splice(index, 1);
      }
    }
    for (const zone of fvgs.slice(-s.fvg.max)) {
      boxes.push({
        top: zone.top, bottom: zone.bot, from: zone.from, to: null, bias: zone.bias,
        fill: zone.bias === 1 ? SMC_PALETTE.fvgBull : SMC_PALETTE.fvgBear,
        border: zone.bias === 1 ? "rgba(8,153,129,0.55)" : "rgba(242,54,69,0.52)",
        strong: false,
      });
    }
  }

  // --- Структура: пивоты (симметричные) и/или ноги LuxAlgo ---
  const swingHighPivots = s.structure.mode === "pivot" ? pivotMap(candles, s.structure.swingLegs, "high") : new Map<number, number>();
  const swingLowPivots = s.structure.mode === "pivot" ? pivotMap(candles, s.structure.swingLegs, "low") : new Map<number, number>();
  const internalHighPivots = s.structure.mode === "pivot" ? pivotMap(candles, s.structure.internalLegs, "high") : new Map<number, number>();
  const internalLowPivots = s.structure.mode === "pivot" ? pivotMap(candles, s.structure.internalLegs, "low") : new Map<number, number>();

  const orderBlocks: OrderBlock[] = [];
  const internalOrderBlocks: OrderBlock[] = [];
  const eqHighs: { price: number; from: number; to: number }[] = [];
  const eqLows: { price: number; from: number; to: number }[] = [];
  const swingPivotHistory: { high: { price: number; time: number; index: number }[]; low: { price: number; time: number; index: number }[] } = { high: [], low: [] };
  let created = 0, removed = 0;
  let statWinSup = 0, statWinRes = 0, statLossSup = 0, statLossRes = 0;

  // Битые структуры (для линий BOS/CHoCH)
  let swingBias: 1 | -1 | 0 = 0, internalBias: 1 | -1 | 0 = 0;
  let swingHighLevel: number | null = null, swingLowLevel: number | null = null;
  let prevSwingHigh: number | null = null, prevSwingLow: number | null = null;
  let swingHighTime = 0, swingLowTime = 0;
  let swingHighBroken = false, swingLowBroken = false;
  const structureBreaks: { time: number; level: number; from: number; tag: string; bias: 1 | -1; internal: boolean }[] = [];

  const zoneScore = (bull: boolean, top: number, bot: number, index: number): Flags => {
    let score = 0, mask = 0, max = 0;
    const mid = (top + bot) / 2;
    if (s.fvg.show) {
      max++;
      if (fvgs.some(zone => zone.bias === (bull ? 1 : -1) && Math.min(top, zone.top) - Math.max(bot, zone.bot) > 0)) { score++; mask |= 1; }
    }
    if (s.emas.some(row => row.enabled)) {
      max++;
      const near = 0.5 * atrAt(index);
      if (emaValuesAtBar[index].some(value => Math.abs(mid - value) <= near)) { score++; mask |= 2; }
    }
    if (swingHighLevel != null && swingLowLevel != null && swingHighLevel > swingLowLevel) {
      max++;
      const equilibrium = (swingHighLevel + swingLowLevel) / 2;
      if (bull ? mid < equilibrium : mid > equilibrium) { score++; mask |= 4; }
    }
    if (poc != null) {
      max++;
      const near = Math.abs(mid - poc) <= 0.4 * atrAt(index);
      const inValue = vah != null && val != null && mid >= val && mid <= vah;
      if (near || inValue) { score++; mask |= 8; }
    }
    if (s.levels.show && levels.length) {
      max++;
      if (levels.some(level => Math.abs(mid - level.price) <= 0.4 * atrAt(index))) { score++; mask |= 16; }
    }
    if (swingBias !== 0) {
      max++;
      if (bull ? swingBias >= 0 : swingBias <= 0) { score++; mask |= 32; }
    }
    return { score, max, mask };
  };

  /** Создание OB по методу LuxAlgo: срез парсинга от пивота до бара пробоя, экстремум среза. */
  const storeOrderBlock = (target: OrderBlock[], pivotIndex: number, bias: 1 | -1, index: number) => {
    if (pivotIndex < 0 || pivotIndex >= index) return;
    const slice = parsedHigh.slice(pivotIndex, index);
    const sliceLow = parsedLow.slice(pivotIndex, index);
    if (!slice.length) return;
    let offset = 0;
    if (bias === -1) { let best = -Infinity; slice.forEach((value, i) => { if (value > best) { best = value; offset = i; } }); }
    else { let best = Infinity; sliceLow.forEach((value, i) => { if (value < best) { best = value; offset = i; } }); }
    const top = Math.max(slice[offset], sliceLow[offset]);
    const bot = Math.min(slice[offset], sliceLow[offset]);
    if (!(top > bot)) return;
    const flags = zoneScore(bias === 1, top, bot, index);
    const strong = s.aplus.enabled && flags.max > 0 && flags.score * 100 >= flags.max * s.aplus.minPercent;
    target.unshift({ top, bot, bias, from: candles[pivotIndex].time, born: index, strong, score: flags.score, max: flags.max, touched: false, done: false, touchBar: -1, maxExcursion: NaN, minExcursion: NaN });
    created++;
    if (target.length > 100) target.pop();
  };

  const equalLevelTest = (isHigh: boolean, price: number, index: number) => {
    if (!s.eq.show) return;
    const tolerance = s.eq.toleranceAtr * atrAt(index);
    const history = isHigh ? swingPivotHistory.high : swingPivotHistory.low;
    for (const pivot of [...history].reverse().slice(0, 10)) {
      if (Math.abs(pivot.price - price) <= tolerance) {
        const bucket = isHigh ? eqHighs : eqLows;
        if (bucket.length < 2) bucket.push({ price: isHigh ? Math.max(pivot.price, price) : Math.min(pivot.price, price), from: pivot.time, to: candles[index].time });
        break;
      }
    }
    history.push({ price, time: candles[index].time, index });
    if (history.length > 30) history.shift();
  };

  // Ноги LuxAlgo: 0 — ищем максимум, 1 — ищем минимум
  const legState = (length: number) => {
    const legs: number[] = new Array(n).fill(0);
    let current = 0;
    for (let i = 0; i < n; i++) {
      if (i >= length) {
        let highest = -Infinity, lowest = Infinity;
        for (let k = i - length + 1; k <= i; k++) { highest = Math.max(highest, candles[k].high); lowest = Math.min(lowest, candles[k].low); }
        const newHigh = candles[i - length].high > highest;
        const newLow = candles[i - length].low < lowest;
        if (newHigh) current = 0; else if (newLow) current = 1;
      }
      legs[i] = current;
    }
    return legs;
  };
  const swingLegs = legState(s.ob.swingLength);
  const internalLegs = legState(s.ob.internalLength);
  const luxSwingHigh = { level: NaN, index: -1, born: -1, crossed: false };
  const luxSwingLow = { level: NaN, index: -1, born: -1, crossed: false };
  const luxInternalHigh = { level: NaN, index: -1, born: -1, crossed: false };
  const luxInternalLow = { level: NaN, index: -1, born: -1, crossed: false };
  const updatePivot = (state: { level: number; index: number; born: number; crossed: boolean }, legs: number[], i: number, length: number, isHigh: boolean) => {
    if (i < 1 || i < length) return;
    const change = legs[i] - legs[i - 1];
    const target = candles[i - length];
    if (change === (isHigh ? -1 : 1)) {
      state.level = isHigh ? target.high : target.low;
      state.index = i - length;
      state.born = i;
      state.crossed = isHigh ? candles[i].close > target.high : candles[i].close < target.low;
    }
  };

  for (let i = 0; i < n; i++) {
    const candle = candles[i];

    // 1. Структура на симметричных пивотах
    if (s.structure.mode === "pivot") {
      const pivotHigh = swingHighPivots.get(i);
      if (pivotHigh != null) {
        swingHighLevel = pivotHigh; swingHighTime = candle.time; swingHighBroken = false;
        if (s.eq.show) equalLevelTest(true, pivotHigh, i);
        if (s.structure.swings && s.structure.showSwing) {
          const tag = prevSwingHigh == null ? "H" : pivotHigh > prevSwingHigh ? "HH" : "LH";
          texts.push({ time: candle.time, price: pivotHigh, text: tag, color: SMC_PALETTE.bear, above: true });
        }
        prevSwingHigh = pivotHigh;
      }
      const pivotLow = swingLowPivots.get(i);
      if (pivotLow != null) {
        swingLowLevel = pivotLow; swingLowTime = candle.time; swingLowBroken = false;
        if (s.eq.show) equalLevelTest(false, pivotLow, i);
        if (s.structure.swings && s.structure.showSwing) {
          const tag = prevSwingLow == null ? "L" : pivotLow < prevSwingLow ? "LL" : "HL";
          texts.push({ time: candle.time, price: pivotLow, text: tag, color: SMC_PALETTE.bull, above: false });
        }
        prevSwingLow = pivotLow;
      }
      const displacement = s.structure.displacementAtr * atrAt(i);
      if (swingHighLevel != null && !swingHighBroken && (s.structure.wickBreak ? candle.high : candle.close) > swingHighLevel + displacement) {
        swingHighBroken = true;
        const tag = swingBias === -1 ? "CHoCH" : "BOS";
        structureBreaks.push({ time: candle.time, level: swingHighLevel, from: swingHighTime, tag, bias: 1, internal: false });
        swingBias = 1;
      }
      if (swingLowLevel != null && !swingLowBroken && (s.structure.wickBreak ? candle.low : candle.close) < swingLowLevel - displacement) {
        swingLowBroken = true;
        const tag = swingBias === 1 ? "CHoCH" : "BOS";
        structureBreaks.push({ time: candle.time, level: swingLowLevel, from: swingLowTime, tag, bias: -1, internal: false });
        swingBias = -1;
      }
    }

    // 2. Пивоты и пробои LuxAlgo
    updatePivot(luxSwingHigh, swingLegs, i, s.ob.swingLength, true);
    updatePivot(luxSwingLow, swingLegs, i, s.ob.swingLength, false);
    updatePivot(luxInternalHigh, internalLegs, i, s.ob.internalLength, true);
    updatePivot(luxInternalLow, internalLegs, i, s.ob.internalLength, false);

    const bullishBar = candle.high - Math.max(candle.close, candle.open) > Math.min(candle.close, candle.open) - candle.low;
    const bearishBar = candle.high - Math.max(candle.close, candle.open) < Math.min(candle.close, candle.open) - candle.low;
    const prevClose = i ? candles[i - 1].close : candle.open;

    const intUp = Number.isFinite(luxInternalHigh.level) && !luxInternalHigh.crossed && luxInternalHigh.born < i && candle.close > luxInternalHigh.level && prevClose <= luxInternalHigh.level && (!Number.isFinite(luxSwingHigh.level) || luxInternalHigh.level !== luxSwingHigh.level) && bullishBar;
    const intDown = Number.isFinite(luxInternalLow.level) && !luxInternalLow.crossed && luxInternalLow.born < i && candle.close < luxInternalLow.level && prevClose >= luxInternalLow.level && (!Number.isFinite(luxSwingLow.level) || luxInternalLow.level !== luxSwingLow.level) && bearishBar;
    const swUp = Number.isFinite(luxSwingHigh.level) && !luxSwingHigh.crossed && luxSwingHigh.born < i && candle.close > luxSwingHigh.level && prevClose <= luxSwingHigh.level;
    const swDown = Number.isFinite(luxSwingLow.level) && !luxSwingLow.crossed && luxSwingLow.born < i && candle.close < luxSwingLow.level && prevClose >= luxSwingLow.level;

    if (intUp) {
      luxInternalHigh.crossed = true;
      if (s.structure.mode === "luxalgo") {
        const tag = internalBias === -1 ? "CHoCH" : "BOS"; internalBias = 1;
        if (s.structure.showInternal) structureBreaks.push({ time: candle.time, level: luxInternalHigh.level, from: candles[luxInternalHigh.index].time, tag, bias: 1, internal: true });
      }
      if (s.ob.internal) storeOrderBlock(internalOrderBlocks, luxInternalHigh.index, 1, i);
    }
    if (intDown) {
      luxInternalLow.crossed = true;
      if (s.structure.mode === "luxalgo") {
        const tag = internalBias === 1 ? "CHoCH" : "BOS"; internalBias = -1;
        if (s.structure.showInternal) structureBreaks.push({ time: candle.time, level: luxInternalLow.level, from: candles[luxInternalLow.index].time, tag, bias: -1, internal: true });
      }
      if (s.ob.internal) storeOrderBlock(internalOrderBlocks, luxInternalLow.index, -1, i);
    }
    if (swUp) {
      luxSwingHigh.crossed = true;
      if (s.structure.mode === "luxalgo") {
        const tag = swingBias === -1 ? "CHoCH" : "BOS"; swingBias = 1;
        if (s.structure.showSwing) structureBreaks.push({ time: candle.time, level: luxSwingHigh.level, from: candles[luxSwingHigh.index].time, tag, bias: 1, internal: false });
      }
      if (s.ob.swing) storeOrderBlock(orderBlocks, luxSwingHigh.index, 1, i);
    }
    if (swDown) {
      luxSwingLow.crossed = true;
      if (s.structure.mode === "luxalgo") {
        const tag = swingBias === 1 ? "CHoCH" : "BOS"; swingBias = -1;
        if (s.structure.showSwing) structureBreaks.push({ time: candle.time, level: luxSwingLow.level, from: candles[luxSwingLow.index].time, tag, bias: -1, internal: false });
      }
      if (s.ob.swing) storeOrderBlock(orderBlocks, luxSwingLow.index, -1, i);
    }

    // 3. Митигация и статистика отработки
    for (const [target, limit] of [[orderBlocks, s.ob.maxSwing], [internalOrderBlocks, s.ob.maxInternal]] as const) {
      for (let k = target.length - 1; k >= 0; k--) {
        const zone = target[k];
        if (zone.born === i) continue;
        const bullSource = s.ob.mitigation === "close" ? candle.close : candle.low;
        const bearSource = s.ob.mitigation === "close" ? candle.close : candle.high;
        const broken = zone.bias === 1 ? bullSource < zone.bot : bearSource > zone.top;
        if (broken) {
          if (zone.strong && zone.touched && !zone.done) { if (zone.bias === 1) statLossSup++; else statLossRes++; }
          target.splice(k, 1);
          removed++;
          continue;
        }
        if (zone.strong) {
          const inside = zone.bias === 1 ? candle.low <= zone.top : candle.high >= zone.bot;
          if (!zone.touched && s.signals.enabled && zone.max > 0 && zone.score * 100 >= zone.max * s.signals.minScorePercent) {
            if (inside) {
              zone.touched = true;
              zone.touchBar = i;
              zone.maxExcursion = candle.close;
              zone.minExcursion = candle.close;
              markers.push({ time: candle.time, bias: zone.bias, text: `${zone.bias === 1 ? "BUY" : "SELL"} ${zone.score}/${zone.max}`, strong: zone.score * 100 >= zone.max * 80 });
            }
          } else if (inside && !zone.touched) {
            zone.touched = true;
            zone.touchBar = i;
            zone.maxExcursion = candle.close;
            zone.minExcursion = candle.close;
          } else if (zone.touched) {
            zone.maxExcursion = Math.max(Number.isFinite(zone.maxExcursion) ? zone.maxExcursion : candle.high, candle.high);
            zone.minExcursion = Math.min(Number.isFinite(zone.minExcursion) ? zone.minExcursion : candle.low, candle.low);
          }
          if (zone.touched && !zone.done && zone.touchBar >= 0) {
            const need = atrAt(i) * 1.0;
            const bounced = zone.bias === 1 ? zone.maxExcursion >= zone.top + need : zone.minExcursion <= zone.bot - need;
            if (bounced) { zone.done = true; if (zone.bias === 1) statWinSup++; else statWinRes++; }
            else if (i - zone.touchBar >= 50) { zone.done = true; if (zone.bias === 1) statLossSup++; else statLossRes++; }
          }
        }
      }
      while (target.length > limit) target.pop();
    }
  }

  // --- Отрисовка: Order Blocks ---
  const visibleInternal = internalOrderBlocks.filter(zone => !s.aplus.only || zone.strong).slice(0, s.ob.maxInternal);
  const visibleSwing = orderBlocks.filter(zone => !s.aplus.only || zone.strong).slice(0, s.ob.maxSwing);
  if (s.ob.internal) for (const zone of visibleInternal) {
    boxes.push({
      top: zone.top, bottom: zone.bot, from: zone.from, to: null, bias: zone.bias, strong: zone.strong,
      fill: zone.strong ? "rgba(255,212,0,0.20)" : zone.bias === 1 ? SMC_PALETTE.internalBull : SMC_PALETTE.internalBear,
      border: zone.strong ? "rgba(255,212,0,0.80)" : zone.bias === 1 ? "rgba(77,155,255,0.55)" : "rgba(247,124,128,0.50)",
      label: zone.strong ? "A+" : undefined,
    });
  }
  if (s.ob.swing) for (const zone of visibleSwing) {
    boxes.push({
      top: zone.top, bottom: zone.bot, from: zone.from, to: null, bias: zone.bias, strong: zone.strong,
      fill: zone.strong ? "rgba(255,212,0,0.20)" : zone.bias === 1 ? SMC_PALETTE.swingBull : SMC_PALETTE.swingBear,
      border: zone.strong ? "rgba(255,212,0,0.80)" : zone.bias === 1 ? "rgba(77,155,255,0.50)" : "rgba(255,110,120,0.45)",
      label: zone.strong ? "A+" : undefined,
    });
  }

  // --- Premium / Discount ---
  let equilibrium: number | null = null, range: number | null = null;
  const refHigh = Number.isFinite(luxSwingHigh.level) ? luxSwingHigh.level : swingHighLevel;
  const refLow = Number.isFinite(luxSwingLow.level) ? luxSwingLow.level : swingLowLevel;
  if (refHigh != null && refLow != null && refHigh > refLow) {
    equilibrium = (refHigh + refLow) / 2;
    range = refHigh - refLow;
  }
  if (s.premiumDiscount && equilibrium != null) {
    {
      boxes.push({ top: refHigh as number, bottom: equilibrium, from: candles[Math.max(0, n - 120)].time, to: null, bias: -1, strong: false, fill: "rgba(242,54,69,0.09)", border: "rgba(242,54,69,0.22)" });
      boxes.push({ top: equilibrium as number, bottom: refLow as number, from: candles[Math.max(0, n - 120)].time, to: null, bias: 1, strong: false, fill: "rgba(8,153,129,0.09)", border: "rgba(8,153,129,0.22)" });
    }
  }

  // --- Структурные линии BOS / CHoCH ---
  for (const breaker of structureBreaks.filter(item => item.internal ? s.structure.showInternal : s.structure.showSwing).slice(-s.structure.keep * 2)) {
    lines.push({ price: breaker.level, from: breaker.from, to: breaker.time, color: breaker.bias === 1 ? SMC_PALETTE.bull : SMC_PALETTE.bear, width: 1, style: breaker.internal ? "dashed" : "solid" });
    if (s.structure.showLabels) texts.push({ time: breaker.time, price: breaker.level, text: breaker.tag, color: breaker.bias === 1 ? SMC_PALETTE.bull : SMC_PALETTE.bear, above: breaker.bias === 1 });
  }

  // --- EQH / EQL ---
  for (const item of eqHighs) lines.push({ price: item.price, from: item.from, to: item.to, color: SMC_PALETTE.bear, width: 2, style: "dotted" });
  for (const item of eqLows) lines.push({ price: item.price, from: item.from, to: item.to, color: SMC_PALETTE.bull, width: 2, style: "dotted" });

  // --- Уровни старшего ТФ ---
  if (s.levels.show) for (const level of levels) {
    lines.push({ price: level.price, from: candles[Math.max(0, n - 160)].time, to: null, color: level.color, width: 1, style: level.name.startsWith("PD") || level.name.startsWith("PW") ? "dashed" : "dotted", axisLabel: `${level.name} ${level.price.toFixed(2)}` });
  }

  // --- POC / VAH / VAL ---
  if (s.poc.show && poc != null) {
    const from = candles[Math.max(0, n - profileWindow)].time;
    lines.push({ price: poc, from, to: null, color: SMC_PALETTE.poc, width: 2, style: "dashed", axisLabel: `POC ${poc.toFixed(2)}` });
    if (vah != null && val != null) {
      lines.push({ price: vah, from, to: null, color: SMC_PALETTE.valueArea, width: 1, style: "dotted", axisLabel: `VAH ${vah.toFixed(2)}` });
      lines.push({ price: val, from, to: null, color: SMC_PALETTE.valueArea, width: 1, style: "dotted", axisLabel: `VAL ${val.toFixed(2)}` });
    }
  }

  // --- Ближайшие зоны и режим рынка ---
  const close = candles[n - 1].close;
  const nearest = (list: OrderBlock[], bias: 1 | -1) => {
    let price: number | null = null, distance = Infinity;
    for (const zone of list) {
      if (zone.bias !== bias) continue;
      const mid = (zone.top + zone.bot) / 2;
      const next = Math.abs(mid - close);
      if (next < distance) { distance = next; price = mid; }
    }
    return price;
  };
  const support = nearest([...visibleSwing, ...visibleInternal], 1);
  const resistance = nearest([...visibleSwing, ...visibleInternal], -1);
  const bias: 1 | -1 | 0 = (s.structure.mode === "luxalgo" ? swingBias : swingBias) || 0;
  const equity = equilibrium ?? (Number.isFinite(luxSwingHigh.level) && Number.isFinite(luxSwingLow.level) ? (luxSwingHigh.level + luxSwingLow.level) / 2 : null);
  const premiumDiscountZone = equity == null ? null : close > equity ? "premium" : close < equity ? "discount" : "equilibrium";

  return {
    boxes, lines, texts, markers, series, lastPrice: close,
    stats: {
      bias, equilibrium: equity, range,
      premiumDiscountZone,
      levels,
      poc, vah, val,
      fvgCount: fvgs.length,
      obCount: visibleSwing.length,
      internalObCount: visibleInternal.length,
      aplusBuy: { wins: statWinSup, losses: statLossSup },
      aplusSell: { wins: statWinRes, losses: statLossRes },
      created, removed,
      support, resistance,
    },
  };
}

/** Горизонтальный профиль объёма: POC, VAH, VAL. */
export function volumeProfile(candles: Candle[], step: number, valueArea: number) {
  const low = Math.min(...candles.map(c => c.low));
  const high = Math.max(...candles.map(c => c.high));
  const size = Math.max(step, (high - low) / 160, 1e-9);
  const bins = Math.min(220, Math.max(8, Math.ceil((high - low) / size) || 8));
  const hist = new Float64Array(bins);
  for (const candle of candles) {
    const first = Math.max(0, Math.min(bins - 1, Math.floor((candle.low - low) / size)));
    const last = Math.max(0, Math.min(bins - 1, Math.floor((candle.high - low) / size)));
    const share = candle.volume / (last - first + 1);
    for (let k = first; k <= last; k++) hist[k] += share;
  }
  let best = 0, index = 0, total = 0;
  for (let k = 0; k < bins; k++) { total += hist[k]; if (hist[k] > best) { best = hist[k]; index = k; } }
  let accumulated = best, up = index, down = index;
  const needed = total * valueArea / 100;
  let guard = 0;
  while (accumulated < needed && guard++ < bins) {
    const upValue = up < bins - 1 ? hist[up + 1] : -1;
    const downValue = down > 0 ? hist[down - 1] : -1;
    if (upValue < 0 && downValue < 0) break;
    if (upValue >= downValue) { up++; accumulated += upValue; } else { down--; accumulated += downValue; }
  }
  return {
    poc: low + (index + 0.5) * size,
    vah: low + (up + 1) * size,
    val: low + down * size,
    bins, high: high, low,
  };
}
