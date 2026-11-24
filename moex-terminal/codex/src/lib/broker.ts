// Виртуальный брокерский счёт: рыночные заявки, лонг и шорт, комиссия биржи и брокера.
// Деньги ненастоящие — счёт существует только в браузере пользователя.
import { getInstrument, type Timeframe, type Quote } from "./market";

export const START_BALANCE = 10_000_000;
export const COMMISSION = 0.0005; // 0,05 % от оборота в каждую сторону (биржа + брокер)
export const MAX_LEVERAGE = 3;    // плечо в пределах маржи
export const TRADE_LIMIT = 500;   // глубина истории сделок в браузере

export type Side = "long" | "short";
export type Position = {
  id: string;
  symbol: string;
  side: Side;
  quantity: number;      // в лотах
  lots: number;          // размер лота на момент сделки
  entry: number;         // цена входа
  opened: number;        // время входа (мс)
  take?: number;         // тейк-профит
  stop?: number;         // стоп-лосс
};
export type Trade = {
  id: string;
  symbol: string;
  side: Side;
  lots: number;
  quantity: number;
  entry: number;
  exit: number;
  opened: number;
  closed: number;
  pnl: number;           // до комиссии на выходе
  fee: number;
  reason: "manual" | "take" | "stop";
};
export type Account = {
  balance: number;
  positions: Position[];
  trades: Trade[];
  limit: number;         // количество сохранённых сделок
};
export type Mark = { price: number; time?: number };

export function emptyAccount(): Account {
  return { balance: START_BALANCE, positions: [], trades: [], limit: TRADE_LIMIT };
}

// Числа из localStorage могут приходить строками — приводим безопасно.
const num = (value: unknown, fallback = 0) => {
  const parsed = typeof value === "number" ? value : typeof value === "string" && value.trim() !== "" ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
};
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** Проверка сохранённого счёта: неизвестные поля отбрасываются, отрицательные значения невозможны. */
export function sanitizeAccount(value: unknown): Account {
  const base = emptyAccount();
  if (!value || typeof value !== "object") return base;
  const raw = value as Record<string, unknown>;
  base.balance = clamp(num(raw.balance, START_BALANCE), 0, 1e12);
  base.limit = 200;
  if (Array.isArray(raw.positions)) {
    base.positions = raw.positions.slice(0, 60).flatMap(item => {
      const p = item as Record<string, unknown>;
      const symbol = typeof p.symbol === "string" ? p.symbol : "";
      if (!symbol) return [];
      const instrument = getInstrument(symbol);
      if (instrument.symbol !== symbol) return [];
      const side: Side = p.side === "short" ? "short" : "long";
      const lots = Math.max(0, Math.round(num(p.lots, 0)));
      if (!lots) return [];
      if (p.side !== "long" && p.side !== "short") return [];
      return [{
        id: typeof p.id === "string" ? p.id.slice(0, 40) : `${symbol}-${side}-${Math.random().toString(36).slice(2, 8)}`,
        symbol, side, lots,
        quantity: lots * instrument.lot,
        entry: Math.max(0.0001, num(p.entry, instrument.price)),
        opened: num(p.opened, Date.now()),
        take: num(p.take) > 0 ? num(p.take) : undefined,
        stop: num(p.stop) > 0 ? num(p.stop) : undefined,
      }];
    });
  }
  if (Array.isArray(raw.trades)) {
    base.trades = raw.trades.slice(0, TRADE_LIMIT).flatMap(item => {
      const t = item as Record<string, unknown>;
      if (typeof t.symbol !== "string") return [];
      return [{
        id: typeof t.id === "string" ? t.id.slice(0, 40) : Math.random().toString(36).slice(2),
        symbol: t.symbol,
        side: t.side === "short" ? "short" as Side : "long" as Side,
        lots: Math.max(0, Math.round(num(t.lots))),
        quantity: Math.max(0, num(t.quantity)),
        entry: num(t.entry),
        exit: num(t.exit),
        opened: num(t.opened),
        closed: num(t.closed),
        pnl: num(t.pnl),
        fee: num(t.fee),
        reason: t.reason === "take" ? "take" : t.reason === "stop" ? "stop" : "manual",
      }];
    });
  }
  return { ...base, limit: TRADE_LIMIT };
}

/** Марковая стоимость позиции по текущей цене. */
export function positionValue(position: Position, price: number) {
  const direction = position.side === "long" ? 1 : -1;
  const pnl = (price - position.entry) * direction * position.quantity;
  const notional = price * position.quantity;
  return { pnl: Number.isFinite(pnl) ? pnl : 0, notional: Number.isFinite(notional) ? notional : 0 };
}

export type AccountSnapshot = {
  balance: number;
  equity: number;
  marginUsed: number;
  freeMargin: number;
  unrealized: number;
  realized: number;
  positions: (Position & { price: number; pnl: number; pnlPercent: number; notional: number; value: number })[];
  winRate: number;
  trades: number;
  best: number;
  worst: number;
};

/** Полный расчёт счёта: эквити, маржа, нереализованный результат, статистика сделок. */
export function accountSnapshot(account: Account, prices: Record<string, number>): AccountSnapshot {
  const positions = account.positions.map(position => {
    const price = prices[position.symbol] ?? position.entry;
    const { pnl, notional } = positionValue(position, price);
    const base = position.entry * position.quantity;
    return { ...position, price, pnl, notional, pnlPercent: base > 0 ? (pnl / base) * 100 : 0, value: base + pnl };
  });
  const unrealized = positions.reduce((sum, p) => sum + p.pnl, 0);
  const marginUsed = positions.reduce((sum, p) => sum + p.notional / MAX_LEVERAGE, 0);
  const equity = account.balance + unrealized;
  const realized = account.trades.reduce((sum, t) => sum + t.pnl - t.fee, 0);
  const wins = account.trades.filter(t => t.pnl - t.fee > 0).length;
  return {
    balance: account.balance,
    equity,
    marginUsed,
    freeMargin: equity - marginUsed,
    unrealized,
    realized,
    positions,
    winRate: account.trades.length ? (wins / account.trades.length) * 100 : 0,
    trades: account.trades.length,
    best: account.trades.reduce((best, t) => Math.max(best, t.pnl - t.fee), 0),
    worst: account.trades.reduce((worst, t) => Math.min(worst, t.pnl - t.fee), 0),
  };
}

export type OrderRequest = {
  symbol: string;
  side: Side;
  /** Количество в лотах. 0 — рассчитать по сумме. */
  lots: number;
  /** Сумма сделки в рублях (если лоты не заданы). */
  amount?: number;
  price: number;
  take?: number;
  stop?: number;
  slippage?: number;
};

export type OrderResult = { ok: true; account: Account; position: Position; filled: number } | { ok: false; error: string };

/** Рыночная заявка: открывает или увеличивает позицию по направлению. */
export function openPosition(account: Account, request: OrderRequest): OrderResult {
  const instrument = getInstrument(request.symbol);
  if (instrument.symbol !== request.symbol) return { ok: false, error: "Инструмент не найден" };
  const slip = clamp(request.slippage ?? 0, 0, 0.05);
  const price = request.price * (1 + (request.side === "long" ? slip : -slip));
  if (!(price > 0)) return { ok: false, error: "Нет цены для исполнения заявки" };

  let lots = Math.round(request.lots);
  if (lots <= 0 && request.amount && request.amount > 0) lots = Math.floor(request.amount / (price * instrument.lot));
  if (lots <= 0) return { ok: false, error: "Количество должно быть больше нуля" };

  const quantity = lots * instrument.lot;
  const notional = price * quantity;
  const fee = notional * COMMISSION;
  const snapshot = accountSnapshot(account, { [instrument.symbol]: price });
  const need = notional / MAX_LEVERAGE + fee;
  const free = snapshot.equity - snapshot.marginUsed;
  if (need > free + 0.01) return { ok: false, error: `Недостаточно средств: нужно ${Math.ceil(need).toLocaleString("ru-RU")} ₽ свободной маржи` };

  const existing = account.positions.find(p => p.symbol === instrument.symbol && p.side === request.side);
  let position: Position;
  let positions: Position[];
  if (existing) {
    const total = existing.quantity + quantity;
    position = { ...existing, quantity: total, lots: existing.lots + lots, entry: (existing.entry * existing.quantity + price * quantity) / total };
    positions = account.positions.map(p => (p === existing ? position : p));
  } else {
    position = {
      id: `${instrument.symbol}-${request.side}-${Date.now().toString(36)}`,
      symbol: instrument.symbol, side: request.side, lots, quantity, entry: price, opened: Date.now(),
      take: request.take && request.take > 0 ? request.take : undefined,
      stop: request.stop && request.stop > 0 ? request.stop : undefined,
    };
    positions = [...account.positions, position];
  }
  return { ok: true, account: { ...account, balance: account.balance - fee, positions }, position, filled: quantity };
}

/** Закрытие позиции целиком или частично (в лотах). */
export function closePosition(account: Account, id: string, price: number, lots?: number, reason: Trade["reason"] = "manual"): { ok: boolean; account: Account; trade?: Trade; error?: string } {
  const position = account.positions.find(p => p.id === id);
  if (!position || !(price > 0)) return { ok: false, account, error: "Позиция не найдена" };
  const closeLots = Math.min(position.lots, Math.max(1, Math.round(lots ?? position.lots)));
  const share = closeLots / position.lots;
  const quantity = position.quantity * share;
  const direction = position.side === "long" ? 1 : -1;
  const proceeds = price * quantity;
  const fee = proceeds * COMMISSION;
  const pnl = (price - position.entry) * direction * quantity;
  const trade: Trade = {
    id: `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
    symbol: position.symbol, side: position.side, lots: closeLots, quantity,
    entry: position.entry, exit: price, opened: position.opened, closed: Date.now(),
    pnl, fee, reason,
  };
  const remainingLots = position.lots - closeLots;
  const positions = remainingLots > 0
    ? account.positions.map(p => (p.id === id ? { ...p, lots: remainingLots, quantity: p.quantity - quantity } : p))
    : account.positions.filter(p => p.id !== id);
  return { ok: true, account: { ...account, balance: account.balance + pnl - fee, positions, trades: [trade, ...account.trades].slice(0, account.limit) }, trade };
}

/** Проверка тейка и стопа по последней свече. Возвращает счета с исполненными защитными заявками. */
export function applyProtection(account: Account, candles: Record<string, { high: number; low: number }>): { account: Account; closed: Trade[] } {
  let next = account;
  const closed: Trade[] = [];
  for (const position of [...account.positions]) {
    const candle = candles[position.symbol];
    if (!candle) continue;
    const hitTake = position.take ? (position.side === "long" ? candle.high >= position.take : candle.low <= position.take) : false;
    const hitStop = position.stop ? (position.side === "long" ? candle.low <= position.stop : candle.high >= position.stop) : false;
    if (!hitTake && !hitStop) continue;
    const price = hitStop && hitTake ? position.stop! : hitStop ? position.stop! : position.take!;
    const result = closePosition(next, position.id, price, undefined, hitStop ? "stop" : "take");
    if (result.ok) {
      next = result.account;
      if (result.trade) closed.push(result.trade);
    }
  }
  return { account: next, closed };
}

/** Доходность портфеля в процентах от стартового капитала. */
export function totalReturn(snapshot: AccountSnapshot) {
  return ((snapshot.equity - START_BALANCE) / START_BALANCE) * 100;
}

export function riskRatio(entry: number, stop?: number, take?: number) {
  if (!stop || !take || !(entry > 0)) return null;
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(take - entry);
  if (!(risk > 0)) return null;
  return reward / risk;
}

export type { Quote, Timeframe };
