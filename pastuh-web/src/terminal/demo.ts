// Демо-данные: используются ТОЛЬКО когда бэкенд бота недоступен,
// чтобы терминал можно было посмотреть/верстать без поднятого бота.
// При живом API структуры идентичны ответам investrobot.py.

import type { AnalyzeData, Candle, DashboardData, Stock } from "./types";

const UNIVERSE: [string, string, number][] = [
  ["SBER", "Сбербанк", 301.4],
  ["GAZP", "Газпром", 178.6],
  ["LKOH", "Лукойл", 7412],
  ["YDEX", "Яндекс", 4185],
  ["ROSN", "Роснефть", 552.3],
  ["MGNT", "Магнит", 4891],
  ["TATN", "Татнефть", 672.4],
  ["NVTK", "Новатэк", 1124.8],
  ["MOEX", "МосБиржа", 201.3],
  ["CHMF", "Северсталь", 1523.6],
  ["PLZL", "Полюс", 10412],
  ["AFKS", "АФК Система", 28.4],
];

const FACTOR_POOL = [
  "CVD-дивергенция на M15 против движения",
  "Стена покупок 4.2M ₽ в стакане ×3.4",
  "Крупный принт 1.8M ₽ по рынку",
  "Пробой VWAP на повышенном объёме",
  "Дисбаланс стакана 68/32 в пользу bid",
  "Повторяющиеся принты ×7 за 5 минут",
  "Отскок от POC дня с реакцией",
  "Снятие ликвидности ниже локального минимума",
  "Делта-всплеск +240% за последние 6 свечей",
  "Поглощение продаж на уровне (absorption)",
];

const rnd = (a: number, b: number) => a + Math.random() * (b - a);
const pick = <T,>(arr: T[]): T => arr[Math.floor(Math.random() * arr.length)];

function makeStock(ticker: string, name: string, base: number, i: number): Stock {
  const hot = i < 3;
  const side = Math.random() < 0.55 ? "LONG" : "SHORT";
  const score = hot ? Math.round(rnd(7, 10)) : Math.round(rnd(0, 6));
  const price = base * (1 + rnd(-0.01, 0.012));
  const slPct = rnd(0.005, 0.012);
  const rr = rnd(1.6, 3.2);
  const entry = price;
  const tp = side === "LONG" ? entry * (1 + slPct * rr) : entry * (1 - slPct * rr);
  const sl = side === "LONG" ? entry * (1 - slPct) : entry * (1 + slPct);
  const verdict: Stock["verdict"] = score >= 7 ? side : "WAIT";
  const factors = [...FACTOR_POOL].sort(() => Math.random() - 0.5).slice(0, verdict === "WAIT" ? 1 : 3);
  return {
    ticker,
    name,
    price: +price.toFixed(2),
    change: +rnd(-2.4, 2.8).toFixed(2),
    tf_key: "15m",
    score: verdict === "WAIT" ? score : Math.max(score, 7),
    verdict,
    calc_side: side,
    factors,
    block_reasons: verdict === "WAIT" ? ["Недостаточно перевеса для авто-сигнала"] : [],
    entry: +entry.toFixed(2),
    tp: +tp.toFixed(2),
    sl: +sl.toFixed(2),
    profit_pct: +((Math.abs(tp - entry) / entry) * 100).toFixed(2),
    risk_pct: +((Math.abs(entry - sl) / entry) * 100).toFixed(2),
    rr_ratio: +rr.toFixed(1),
    rvol: +rnd(0.6, 2.8).toFixed(1),
    leverage_long: pick([2, 3, 4, 5]),
    leverage_short: pick([1, 2, 3]),
    cvd_data: {
      bar_delta: Math.round(rnd(-9000, 9000)),
      cvd_today: Math.round(rnd(-90000, 90000)),
      cum_delta_change_6: Math.round(rnd(-40, 40)),
      tape_cov_pct: 87,
    },
    sr_levels: {
      poc: +(price * (1 - 0.004)).toFixed(2),
      res1_price: +(price * 1.011).toFixed(2),
      res1_dist_pct: 1.1,
      sup1_price: +(price * 0.99).toFixed(2),
      sup1_dist_pct: 1.0,
    },
    entry_true: true,
    ticker_live: true,
    is_live_market: true,
    last_activity_age_min_now: +rnd(0.2, 4).toFixed(1),
    whale_kinds: hot && Math.random() < 0.5 ? ["big_print"] : [],
    short_proposal: false,
  } as Stock;
}

export function demoDashboard(): DashboardData {
  const stocks = UNIVERSE.map(([t, n, p], i) => makeStock(t, n, p, i)).sort(
    (a, b) => Math.abs(b.score) - Math.abs(a.score)
  );
  const sber = stocks[0];
  const now = new Date();
  return {
    server_time: now.toLocaleTimeString("ru-RU") + " МСК",
    market_open: true,
    min_score: 7,
    imoex: { price: 3241.7, change_pct: 0.42 },
    stats: {
      wins: 34,
      losses: 17,
      winrate: 66.7,
      net_pct: 12.4,
      history: [
        "✅ SBER (LONG) закрыта +1.84%",
        "🛡 LKOH (SHORT) -0.62%",
        "✅ GAZP (LONG) закрыта +2.31%",
        "✅ YDEX (LONG) +1.15%",
        "🎯 MGNT (SHORT) +0.98%",
        "✅ TATN (LONG) закрыта +1.42%",
      ],
      all_history: [],
    },
    tracked: [
      {
        ticker: sber.ticker,
        name: sber.name,
        side: "LONG",
        entry: sber.entry,
        tp: sber.tp,
        sl: sber.sl,
        current_price: +(sber.price * 1.004).toFixed(2),
        pnl_pct: +rnd(0.2, 1.1).toFixed(2),
        is_be: false,
        leverage: 2,
        margin_rub: 24000,
        dep_pct: 20,
        auto_partial_enabled: true,
        partial_take_pct: 50,
        partial_trigger_pct: 55,
        take_profits: [
          { price: +(sber.price * 1.006).toFixed(2), pct: 50, hit: false },
          { price: +(sber.price * 1.015).toFixed(2), pct: 50, hit: false },
        ],
      },
    ],
    pending_orders: [
      {
        ticker: "GAZP",
        side: "LONG",
        dep_pct: 15,
        use_leverage: true,
        auto_partial: true,
        custom_tp: 0,
        custom_sl: 0,
        max_gap_pct: 1,
        ref_price: 178.6,
        created_at: "сегодня 12:40",
      },
    ],
    robots: [],
    stocks,
    tiers: {
      "1": UNIVERSE.slice(0, 6).map(([t, n], i) => ({ ticker: t, name: n, active: i < 5 })),
      "2": UNIVERSE.slice(6).map(([t, n], i) => ({ ticker: t, name: n, active: i % 2 === 0 })),
    },
    active_count: 8,
    deposit_rub: 120000,
    strats: [
      {
        key: "cvd_flow",
        name: "💧 Поток CVD",
        desc: "Вход по поглощению + делта-всплеск, трейлинг стоп",
        pnl_rub: 4210,
        portfolio_rub: 38400,
        compound_mult: 1.123,
        winrate: 61.5,
        wins: 16,
        losses: 9,
        be: 1,
        open: [{ ticker: "MGNT", side: "SHORT", entry: 4901, current_price: 4883, pnl_pct: 0.37, tp_trailed: true }],
        max_positions: 3,
      },
    ],
    whales: [
      {
        ticker: "LKOH",
        name: "Лукойл",
        price: 7412,
        change: 0.87,
        events: ["Крупный принт 2.1M ₽ по ask", "TWAP-покупка ~12 мин", "Айсберг на bid 7400"],
      },
      {
        ticker: "SBER",
        name: "Сбербанк",
        price: 301.4,
        change: 1.24,
        events: ["Серия принтов ×7 по рынку", "Стена 4.2M ₽ съедена"],
      },
    ],
    news: [
      { source: "MOEX", important: true, time: "13:05", date: "05.02", title: "МосБиржа расширяет вечернюю сессию по ликвидным акциям", url: "" },
      { source: "РБК", important: false, time: "12:41", date: "05.02", title: "ЦБ сохранил ключевую ставку — что это значит для дивидендных историй", url: "" },
      { source: "MOEX", important: false, time: "11:58", date: "05.02", title: "Индекс IMOEX обновил локальный максимум на объёме выше среднего", url: "" },
    ],
    dividend_calendar: [
      { ticker: "LKOH", date: "12.02", days_left: 7, div_rub: 542, yield_pct: 7.3, cutoff_soon: true, risk: "ВЫСОКИЙ" },
      { ticker: "TATN", date: "21.02", days_left: 16, div_rub: 38.6, yield_pct: 5.7, cutoff_soon: false, risk: "СРЕДНИЙ" },
    ],
  };
}

export function demoAnalyze(ticker: string): AnalyzeData {
  const u = UNIVERSE.find(([t]) => t === ticker) ?? UNIVERSE[0];
  const [t, name, base] = u;
  const candles: Candle[] = [];
  let price = base * 0.985;
  const times = 56;
  let cum = -2000;
  for (let i = 0; i < times; i++) {
    const o = price;
    const c = o * (1 + rnd(-0.006, 0.0066));
    const dlt = Math.round(rnd(-3000, 3000));
    cum += dlt;
    const cvdO = cum - dlt;
    const cvdC = cum;
    candles.push({
      time: `${String(9 + Math.floor(i / 4)).padStart(2, "0")}:${String((i % 4) * 15).padStart(2, "0")}`,
      open: +o.toFixed(2),
      high: +Math.max(o, c).toFixed(2),
      low: +Math.min(o, c).toFixed(2),
      close: +c.toFixed(2),
      vol: Math.round(rnd(400, 3200)),
      delta: dlt,
      cvd_open: cvdO,
      cvd_high: Math.max(cvdO, cvdC) + Math.round(rnd(0, 300)),
      cvd_low: Math.min(cvdO, cvdC) - Math.round(rnd(0, 300)),
      cvd_close: cvdC,
      cum_delta: cum,
      tape_cum_delta: cum * 0.85,
      tape_cov: i % 7 === 3 ? 0.3 : 0.85,
      tape_delta: dlt,
    });
    price = c;
  }
  let e20 = candles[0].close;
  let e50 = candles[0].close;
  let e200 = candles[0].close;
  candles.forEach((cd) => {
    e20 = cd.close * (2 / 21) + e20 * (1 - 2 / 21);
    e50 = cd.close * (2 / 51) + e50 * (1 - 2 / 51);
    e200 = cd.close * (2 / 201) + e200 * (1 - 2 / 201);
    cd.ema20 = +e20.toFixed(2);
    cd.ema50 = +e50.toFixed(2);
    cd.ema200 = +e200.toFixed(2);
  });
  const sig = makeStock(t, name, base, 0);
  const spread = base * 0.0012;
  const bids = Array.from({ length: 10 }, (_, i) => ({
    price: +(base - spread * (i + 1)).toFixed(2),
    quantity: Math.round(rnd(200, 9000) * (1 + Math.max(0, 3 - i))),
  }));
  const asks = Array.from({ length: 10 }, (_, i) => ({
    price: +(base + spread * (i + 1)).toFixed(2),
    quantity: Math.round(rnd(200, 9000) * (1 + Math.max(0, 2 - i))),
  }));
  return {
    signal: sig,
    candles,
    orderbook: { bids, asks },
    cvd_estimated: false,
    tape_cov_pct: 87,
    margin: { dlong: 0.25, dshort: 0.5, leverage_long: 4, leverage_short: 2, short_enabled: true },
  };
}
