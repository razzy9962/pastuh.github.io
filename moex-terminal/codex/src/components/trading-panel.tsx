"use client";

import { useMemo, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Briefcase, ChevronDown, CircleDollarSign, History, TrendingDown, TrendingUp, Wallet, X } from "lucide-react";
import { formatChange, formatMoney, formatPrice, getInstrument } from "@/lib/market";
import { COMMISSION, MAX_LEVERAGE, START_BALANCE, accountSnapshot, riskRatio, totalReturn, type Account, type AccountSnapshot, type Side } from "@/lib/broker";

const pct = (value: number) => `${value >= 0 ? "+" : "−"}${formatMoney(Math.abs(value))}%`;

/** Верхняя строка счёта: эквити, свободная маржа, результат. */
export function AccountBar({ snapshot, onOpen }: { snapshot: AccountSnapshot; onOpen: () => void }) {
  const daily = totalReturn(snapshot);
  return <button className={`account-bar ${daily >= 0 ? "positive-bg" : "negative-bg"}`} onClick={onOpen} title="Открыть виртуальный счёт">
    <span className="account-bar-icon"><Wallet size={15}/></span>
    <span className="account-bar-item"><small>Виртуальный счёт</small><strong>{formatMoney(snapshot.equity)} ₽</strong></span>
    <span className="account-bar-item"><small>Свободно</small><b>{formatMoney(snapshot.freeMargin)} ₽</b></span>
    <span className={`account-bar-item account-bar-pnl ${daily >= 0 ? "positive" : "negative"}`}><small>Результат</small><b>{pct(daily)}</b></span>
    {snapshot.positions.length > 0 && <span className="account-bar-badge">{snapshot.positions.length} поз.</span>}
  </button>;
}

type OrderState = { side: Side; lots: string; amount: string; take: string; stop: string; mode: "lots" | "amount" };

/** Форма рыночной заявки под графиком. */
export function OrderTicket({ symbol, price, snapshot, onSubmit, notify }: {
  symbol: string; price: number; snapshot: AccountSnapshot;
  onSubmit: (order: { side: Side; lots: number; amount?: number; take?: number; stop?: number }) => void;
  notify: (message: string) => void;
}) {
  const instrument = getInstrument(symbol);
  const market = snapshot.positions.find(p => p.symbol === symbol) ?? null;
  const [side, setSide] = useState<Side>("long");
  const [state, setState] = useState<OrderState>({ side: "long", lots: "1", amount: "100000", take: "", stop: "", mode: "lots" });
  const lots = Math.max(0, Math.round(Number(state.lots) || 0));
  const amount = Math.max(0, Number(state.amount) || 0);
  const orderLots = state.mode === "lots" ? lots : Math.floor(amount / Math.max(price * instrument.lot, 1e-9));
  // Объём заявки — ровно то, что исполнится: лоты × размер лота (в режиме «Сумма»
  // это целое число лотов, а не дробная доля).
  const notional = orderLots * instrument.lot * price;
  const fee = notional * COMMISSION;
  const margin = notional / MAX_LEVERAGE;
  const take = Number(state.take) || undefined;
  const stop = Number(state.stop) || undefined;
  const rr = riskRatio(price, stop, take);
  const preset = (share: number) => setState(s => ({ ...s, mode: "amount", amount: String(Math.max(0, Math.floor(snapshot.freeMargin * MAX_LEVERAGE * share))) }));

  const submit = () => {
    // Без цены заявку исполнить нечем: раньше она «проходила» по нулевой цене.
    if (!(price > 0)) { notify("Нет текущей цены — заявка невозможна. Дождитесь данных с биржи."); return; }
    if (!orderLots) { notify(state.mode === "amount" ? "Суммы не хватает даже на один лот" : "Укажите количество: минимум один лот"); return; }
    onSubmit({ side, lots: orderLots, amount: state.mode === "amount" ? amount : undefined, take, stop });
  };

  return <div className="order-ticket">
    <div className="order-side-switch">
      <button className={side === "long" ? "active long" : ""} onClick={() => setSide("long")}><TrendingUp size={15}/>Купить</button>
      <button className={side === "short" ? "active short" : ""} onClick={() => setSide("short")}><TrendingDown size={15}/>Продать</button>
    </div>
    <div className="order-fields">
      <label className="order-field"><span>Количество</span><div className="order-input"><input inputMode="numeric" value={state.mode === "lots" ? state.lots : state.amount} onChange={event => setState(s => ({ ...s, [s.mode === "lots" ? "lots" : "amount"]: event.target.value.replace(/[^\d.]/g, "") }))}/><em>{state.mode === "lots" ? "лот." : "₽"}</em></div></label>
      <div className="order-mode">{(["lots", "amount"] as const).map(mode => <button key={mode} className={state.mode === mode ? "active" : ""} onClick={() => setState(s => ({ ...s, mode }))}>{mode === "lots" ? "Лоты" : "Сумма"}</button>)}</div>
      <div className="order-presets">{[0.25, 0.5, 1].map(share => <button key={share} onClick={() => preset(share)}>{share === 1 ? "Макс." : `${share * 100}%`}</button>)}</div>
    </div>
    <div className="order-fields">
      <label className="order-field"><span>Тейк-профит</span><div className="order-input"><input inputMode="decimal" placeholder="—" value={state.take} onChange={event => setState(s => ({ ...s, take: event.target.value.replace(/[^\d.]/g, "") }))}/><em>₽</em></div></label>
      <label className="order-field"><span>Стоп-лосс</span><div className="order-input"><input inputMode="decimal" placeholder="—" value={state.stop} onChange={event => setState(s => ({ ...s, stop: event.target.value.replace(/[^\d.]/g, "") }))}/><em>₽</em></div></label>
    </div>
    <div className="order-summary">
      <span>Цена <b>{formatPrice(price, price < 10 ? 3 : 2)} ₽</b></span>
      <span>Объём <b>{formatMoney(notional)} ₽</b></span>
      <span>Маржа <b>{formatMoney(margin)} ₽</b></span>
      <span>Комиссия <b>{formatMoney(fee)} ₽</b></span>
      {rr && <span>Риск/прибыль <b>1 : {rr.toFixed(2)}</b></span>}
    </div>
    <button className={`order-submit ${side}`} onClick={submit}>{side === "long" ? "Купить" : "Продать"} {instrument.symbol} · {formatMoney(notional)} ₽</button>
    {market && <div className="order-existing">
      <span>Текущая позиция: <b className={market.side === "long" ? "positive" : "negative"}>{market.side === "long" ? "лонг" : "шорт"} {market.lots} лот.</b> · {formatPrice(market.entry)} ₽ · <b className={market.pnl >= 0 ? "positive" : "negative"}>{market.pnl >= 0 ? "+" : "−"}{formatMoney(Math.abs(market.pnl))} ₽</b></span>
      <button onClick={() => onSubmit({ side: market.side, lots: 0 })} title="Закрыть позицию">Закрыть<X size={12}/></button>
    </div>}
  </div>;
}

/** Список открытых позиций с кнопками закрытия. */
export function PositionTable({ snapshot, onClose, compact = false }: { snapshot: AccountSnapshot; onClose: (id: string) => void; compact?: boolean }) {
  if (!snapshot.positions.length) return <div className="positions-empty"><Briefcase size={20}/><div><strong>Открытых позиций нет</strong><p>Заявка исполнится по текущей цене графика.</p></div></div>;
  return <div className={`position-table ${compact ? "compact" : ""}`}>
    <div className="position-row position-head"><span>Инструмент</span><span>Направление</span><span>Лоты</span><span>Вход</span><span>Тек.</span><span>Результат</span><span/></div>
    {snapshot.positions.map(position => <div className="position-row" key={position.id}>
      <span className="position-symbol">{position.symbol}</span>
      <span className={position.side === "long" ? "positive" : "negative"}>{position.side === "long" ? "Лонг" : "Шорт"}</span>
      <span>{position.lots}</span>
      <span>{formatPrice(position.entry)}</span>
      <span>{formatPrice(position.price)}</span>
      <span className={position.pnl >= 0 ? "positive" : "negative"}>{position.pnl >= 0 ? "+" : "−"}{formatMoney(Math.abs(position.pnl))}<small>{pct(position.pnlPercent)}</small></span>
      <button className="position-close" onClick={() => onClose(position.id)} title="Закрыть по рынку">Закрыть</button>
    </div>)}
  </div>;
}

/** Полное окно брокерского счёта. */
export function AccountDialog({ snapshot, account, onClose, onClosePosition, onSelect, onReset, onExport }: {
  snapshot: AccountSnapshot; account: Account; onClose: () => void; onClosePosition: (id: string) => void; onSelect: (symbol: string) => void; onReset: () => void; onExport: () => void;
}) {
  const [tab, setTab] = useState<"positions" | "history" | "stats">("positions");
  const equityShare = Math.max(0, Math.min(100, (snapshot.equity / START_BALANCE) * 100));
  const stats = useMemo(() => [
    { label: "Сделок закрыто", value: String(snapshot.trades) },
    { label: "Прибыльных", value: `${snapshot.winRate.toFixed(0)}%` },
    { label: "Лучшая сделка", value: `${snapshot.best >= 0 ? "+" : "−"}${formatMoney(Math.abs(snapshot.best))} ₽` },
    { label: "Худшая сделка", value: `${snapshot.worst >= 0 ? "+" : "−"}${formatMoney(Math.abs(snapshot.worst))} ₽` },
    { label: "Реализовано", value: `${snapshot.realized >= 0 ? "+" : "−"}${formatMoney(Math.abs(snapshot.realized))} ₽` },
    { label: "Маржа занята", value: `${formatMoney(snapshot.marginUsed)} ₽` },
  ], [snapshot]);
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="modal account-modal" role="dialog" aria-modal="true" aria-label="Виртуальный счёт">
      <div className="modal-heading"><div className="modal-title-wrap"><span className="modal-icon"><CircleDollarSign size={20}/></span><div><h2>Виртуальный счёт</h2><p>10 000 000 ₽ · рыночные заявки, лонг и шорт, плечо до 1:{MAX_LEVERAGE}</p></div></div><button className="icon-button close-modal" onClick={onClose} aria-label="Закрыть"><X size={19}/></button></div>
      <div className="account-hero">
        <div className="account-hero-main"><span>Эквити</span><strong>{formatMoney(snapshot.equity)}<small>₽</small></strong><em className={totalReturn(snapshot) >= 0 ? "positive" : "negative"}>{pct(totalReturn(snapshot))} с начала</em></div>
        <div className="account-hero-grid">
          <div><span>Свободные средства</span><b>{formatMoney(snapshot.freeMargin)} ₽</b></div>
          <div><span>Нереализованный результат</span><b className={snapshot.unrealized >= 0 ? "positive" : "negative"}>{snapshot.unrealized >= 0 ? "+" : "−"}{formatMoney(Math.abs(snapshot.unrealized))} ₽</b></div>
          <div><span>Занято в марже</span><b>{formatMoney(snapshot.marginUsed)} ₽</b></div>
          <div><span>Оборот позиций</span><b>{formatMoney(snapshot.positions.reduce((sum, p) => sum + p.notional, 0))} ₽</b></div>
        </div>
        <div className="account-equity-track"><span style={{ width: `${equityShare}%` }}/></div>
      </div>
      <div className="dialog-tabs"><button className={tab === "positions" ? "active" : ""} onClick={() => setTab("positions")}><Briefcase size={14}/>Позиции<span className="tab-count">{snapshot.positions.length}</span></button><button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}><History size={14}/>История<span className="tab-count">{account.trades.length}</span></button><button className={tab === "stats" ? "active" : ""} onClick={() => setTab("stats")}><ArrowUpRight size={14}/>Статистика</button></div>
      <div className="account-body">
        {tab === "positions" && (snapshot.positions.length ? <table className="account-table"><thead><tr><th>Инструмент</th><th>Направление</th><th>Лоты</th><th>Вход</th><th>Текущая</th><th>Результат</th><th/></tr></thead><tbody>{snapshot.positions.map(position => <tr key={position.id}>
          <td><button className="account-link" onClick={() => onSelect(position.symbol)}>{position.symbol}</button></td>
          <td className={position.side === "long" ? "positive" : "negative"}>{position.side === "long" ? "Лонг" : "Шорт"}</td>
          <td>{position.lots}</td><td>{formatPrice(position.entry)}</td><td>{formatPrice(position.price)}</td>
          <td className={position.pnl >= 0 ? "positive" : "negative"}>{position.pnl >= 0 ? "+" : "−"}{formatMoney(Math.abs(position.pnl))}<small>{pct(position.pnlPercent)}</small></td>
          <td><button className="position-close" onClick={() => onClosePosition(position.id)}>Закрыть</button></td>
        </tr>)}</tbody></table> : <div className="positions-empty"><Briefcase size={22}/><div><strong>Позиций пока нет</strong><p>Купите или продайте инструмент на панели под графиком — заявка исполнится по текущей цене.</p></div></div>)}
        {tab === "history" && (account.trades.length ? <table className="account-table"><thead><tr><th>Время</th><th>Инструмент</th><th>Направление</th><th>Лоты</th><th>Вход</th><th>Выход</th><th>Результат</th><th>Причина</th></tr></thead><tbody>{account.trades.map(trade => <tr key={trade.id}>
          <td>{new Date(trade.closed).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</td>
          <td><button className="account-link" onClick={() => onSelect(trade.symbol)}>{trade.symbol}</button></td>
          <td className={trade.side === "long" ? "positive" : "negative"}>{trade.side === "long" ? "Лонг" : "Шорт"}</td>
          <td>{trade.lots}</td><td>{formatPrice(trade.entry)}</td><td>{formatPrice(trade.exit)}</td>
          <td className={trade.pnl - trade.fee >= 0 ? "positive" : "negative"}>{trade.pnl - trade.fee >= 0 ? "+" : "−"}{formatMoney(Math.abs(trade.pnl - trade.fee))}</td>
          <td className="muted">{trade.reason === "take" ? "тейк" : trade.reason === "stop" ? "стоп" : "вручную"}</td>
        </tr>)}</tbody></table> : <div className="positions-empty"><History size={22}/><div><strong>Сделок ещё не было</strong><p>Закрытые позиции появятся здесь с результатом и комиссией.</p></div></div>)}
        {tab === "stats" && <div className="account-stats">{stats.map(item => <div key={item.label}><span>{item.label}</span><b>{item.value}</b></div>)}<div className="account-note"><ArrowDownRight size={14}/>Комиссия {COMMISSION * 100}% от оборота в каждую сторону. Данные виртуальные, к реальному счёту доступа нет.</div></div>}
      </div>
      <div className="modal-footnote"><span>Обновление по текущим котировкам · рынок MOEX</span><span className="account-foot-actions"><button className="account-reset" onClick={onExport}>Экспорт истории CSV</button><button className="account-reset" onClick={() => { if (window.confirm("Сбросить виртуальный счёт до 10 000 000 ₽? Позиции и история сделок будут удалены.")) onReset(); }}>Сбросить счёт</button><span>Счёт хранится в браузере</span></span></div>
    </div>
  </div>;
}

export function useSnapshot(account: Account, prices: Record<string, number>) {
  return useMemo(() => accountSnapshot(account, prices), [account, prices]);
}

export function ChevronToggle({ open }: { open: boolean }) {
  return <ChevronDown size={14} style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .15s" }}/>;
}
