// Типы данных — контракт 1-в-1 с ответами investrobot.py

export interface CvdData {
  bar_delta?: number;
  cvd_today?: number;
  cum_delta_change_6?: number;
  delta_efficiency_6?: number;
  tape_cov_pct?: number;
  pivot_bearish_div?: boolean;
  pivot_bullish_div?: boolean;
  [k: string]: unknown;
}

export interface SrLevels {
  poc: number;
  res1_price: number;
  res1_dist_pct: number;
  sup1_price: number;
  sup1_dist_pct: number;
}

export type Verdict = "LONG" | "SHORT" | "WAIT" | string;

export interface Stock {
  ticker: string;
  name: string;
  price: number;
  change: number;
  tf_key: string;
  score: number;
  verdict: Verdict;
  calc_side: "LONG" | "SHORT" | string;
  factors: string[];
  block_reasons?: string[];
  entry: number;
  tp: number;
  sl: number;
  profit_pct: number;
  risk_pct: number;
  rr_ratio: number;
  rvol?: number;
  leverage_long?: number;
  leverage_short?: number;
  dlong?: number;
  dshort?: number;
  cvd_data?: CvdData;
  mtf_cvd?: Record<string, { absorption_side?: string; pressure_side?: string } & Record<string, unknown>>;
  mtf_emas?: Record<string, unknown>;
  sr_levels?: SrLevels;
  last_activity_age_min_now?: number;
  last_candle_age_min_now?: number;
  ticker_live?: boolean;
  is_live_market?: boolean;
  iceberg_events?: unknown[];
  whale_kinds?: string[];
  short_proposal?: boolean;
  robots?: unknown[];
  dividend_info?: { cutoff_soon?: boolean; warning?: string };
  [k: string]: unknown;
}

export interface TakeProfitStep {
  price: number;
  pct: number;
  hit?: boolean;
}

export interface TrackedPos {
  ticker: string;
  name?: string;
  side: "LONG" | "SHORT" | string;
  entry: number;
  tp: number;
  sl: number;
  current_price: number;
  pnl_pct: number;
  is_be?: boolean;
  leverage?: number;
  margin_rub?: number;
  dep_pct?: number;
  owner_uid?: number;
  strategy?: string;
  auto_partial_enabled?: boolean;
  partial_take_pct?: number;
  partial_trigger_pct?: number;
  take_profits?: TakeProfitStep[];
  remaining_frac?: number;
  trail_stop?: number;
  time?: string;
  opened_at?: string;
  [k: string]: unknown;
}

export interface PendingOrder {
  ticker: string;
  side: "LONG" | "SHORT" | string;
  dep_pct: number;
  use_leverage: boolean;
  auto_partial: boolean;
  custom_tp: number;
  custom_sl: number;
  max_gap_pct: number;
  ref_price: number;
  created_at: string;
  user_id?: number;
}

export interface StratOpen {
  ticker: string;
  side: string;
  entry: number;
  current_price: number;
  pnl_pct: number;
  tp_trailed?: boolean;
  partial_taken?: boolean;
}

export interface Strat {
  key: string;
  name: string;
  desc: string;
  pnl_rub: number;
  portfolio_rub: number;
  compound_mult: number;
  winrate: number;
  wins: number;
  losses: number;
  be: number;
  open: StratOpen[];
  max_positions: number;
}

export interface WhaleEvent {
  ticker: string;
  name: string;
  price: number;
  change: number;
  events: string[];
}

export interface NewsItem {
  source?: string;
  important?: boolean;
  time?: string;
  date?: string;
  url?: string;
  title: string;
}

export interface DivItem {
  ticker: string;
  date: string;
  days_left: number;
  div_rub: number;
  yield_pct: number;
  cutoff_soon?: boolean;
  risk: string;
}

export interface TierEntry {
  name: string;
  ticker: string;
  active: boolean;
}

export interface DashboardData {
  server_time: string;
  market_open: boolean;
  min_score: number;
  imoex?: { price?: number; change?: number; change_pct?: number; [k: string]: unknown } | null;
  stats: {
    wins: number;
    losses: number;
    winrate: number;
    net_pct: number;
    history: (string | { text: string })[];
    all_history: string[];
  };
  tracked: TrackedPos[];
  pending_orders: PendingOrder[];
  robots: unknown[];
  stocks: Stock[];
  tiers: Record<string, TierEntry[]>;
  active_count: number;
  deposit_rub: number;
  margin_summary?: Record<string, unknown>;
  strats: Strat[];
  whales: WhaleEvent[];
  news: NewsItem[];
  dividend_calendar?: DivItem[];
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  delta?: number;
  cvd_open?: number;
  cvd_high?: number;
  cvd_low?: number;
  cvd_close?: number;
  EMA20?: number;
  EMA50?: number;
  ema20?: number;
  ema50?: number;
  [k: string]: unknown;
}

export interface BookRow {
  price: number;
  quantity: number;
}

export interface AnalyzeData {
  signal: Stock | null;
  candles: Candle[];
  orderbook: { bids: BookRow[]; asks: BookRow[] };
  cvd_estimated?: boolean;
  tape_cov_pct?: number;
  margin?: {
    dlong: number;
    dshort: number;
    leverage_long: number;
    leverage_short: number;
    short_enabled: boolean;
  };
}

export interface BacktestResult {
  ok: boolean;
  error?: string;
  days: number;
  tickers: number;
  watchlist_size: number;
  trades: number;
  winrate: number;
  avg_pnl_per_ticker_pct: number;
  deposit_rub: number;
  pnl_rub: number;
  per_ticker: {
    ticker: string;
    name: string;
    trades: number;
    wins: number;
    winrate: number;
    pnl_pct: number;
    max_dd_pct: number;
  }[];
  note?: string;
}

export type ScannerFilter = "ALL" | "SNIPER" | "WHALE" | "CVD" | "DIV";

export const TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"] as const;
export type TfKey = (typeof TIMEFRAMES)[number] | string;
