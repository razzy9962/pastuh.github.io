"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Search, X, Star, Plus, Check, ArrowUpRight, SlidersHorizontal, Code2, TrendingUp, ChevronRight, Eye, EyeOff, Trash2, Activity, ShieldCheck, Command, Layers3, RotateCcw, CandlestickChart, ChartLine, ChartArea, ExternalLink } from "lucide-react";
import { changeLabel, INSTRUMENTS, TIERS, formatPrice, formatChange, formatMoney, type Instrument, type InstrumentKind, type Quote, type WorkspaceSettings } from "@/lib/market";

export function AssetLogo({ instrument, size = 30 }: { instrument: Instrument; size?: number }) {
  return <span className={`asset-logo logo-${instrument.symbol}`} style={{ background: instrument.color, width: size, height: size, fontSize: size * .48 }} aria-hidden="true">{instrument.symbol.startsWith("SBER") ? <svg width={size * .72} height={size * .72} viewBox="0 0 24 24" fill="none"><path d="M19.5 10.4a8 8 0 1 1-4.6-5.7" stroke="white" strokeWidth="1.8" strokeLinecap="round"/><path d="m6.5 9 5 3.3L21 5.8M6.5 13l5 3.2 9.5-6.4" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg> : instrument.mark}</span>;
}

export function Modal({ title, subtitle, children, onClose, className = "", icon }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void; className?: string; icon?: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab" && root.current) {
        const items = root.current.querySelectorAll<HTMLElement>('button:not(:disabled), input, textarea, select, a[href], [tabindex="0"]');
        const first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", handle);
    const timer = setTimeout(() => root.current?.querySelector<HTMLElement>("input, textarea, button")?.focus(), 50);
    return () => { document.removeEventListener("keydown", handle); clearTimeout(timer); previous?.focus(); };
  }, [onClose]);
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}><div ref={root} className={`modal ${className}`} role="dialog" aria-modal="true" aria-label={title}>
    <div className="modal-heading"><div className="modal-title-wrap">{icon && <span className="modal-icon">{icon}</span>}<div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div></div><button className="icon-button close-modal" onClick={onClose} aria-label="Закрыть"><X size={19}/></button></div>
    {children}
  </div></div>;
}

/** Живая котировка инструмента или null: в каталоге лежат демо-цены, их показывать нельзя. */
const liveQuote = (quotes: Quote[], symbol: string): Quote | null => quotes.find(q => q.symbol === symbol && q.source !== "demo") ?? null;

export function SearchDialog({ onClose, onSelect, quotes, watchlist, onToggle, addMode = false }: { onClose: () => void; onSelect: (symbol: string) => void; quotes: Quote[]; watchlist: string[]; onToggle: (symbol: string) => void; addMode?: boolean }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<string>("all");
  const [active, setActive] = useState(0);
  const filtered = INSTRUMENTS.filter(i => (kind === "all" ? true : kind === "stock" || kind === "index" || kind === "currency" ? i.kind === kind : String(i.tier ?? "") === kind) && `${i.symbol} ${i.name} ${i.fullName}`.toLowerCase().includes(query.toLowerCase()));
  return <Modal title={addMode ? "Добавить в список" : "Поиск инструмента"} subtitle="Московская биржа · акции, индексы и валюты" onClose={onClose} className="search-modal">
    <div className="dialog-search"><Search size={19}/><input autoFocus placeholder="Название компании или тикер" value={query} onChange={e => { setQuery(e.target.value); setActive(0); }} onKeyDown={e => { if (e.key === "ArrowDown") { e.preventDefault(); setActive(a => Math.min(a + 1, filtered.length - 1)); } if (e.key === "ArrowUp") { e.preventDefault(); setActive(a => Math.max(0, a - 1)); } if (e.key === "Enter" && filtered[active]) { onSelect(filtered[active].symbol); onClose(); } }}/><kbd>↵</kbd></div>
    <div className="dialog-tabs">{([["all", "Все инструменты"], ["1", "1-й эшелон"], ["2", "2-й эшелон"], ["3", "3-й эшелон"], ["index", "Индексы"], ["currency", "Валюты"]] as const).map(([value, label]) => <button key={value} className={kind === value ? "active" : ""} onClick={() => { setKind(value); setActive(0); }}>{label}</button>)}</div>
    <div className="search-result-label"><span>ИНСТРУМЕНТ</span><span>ЦЕНА / ИЗМЕНЕНИЕ</span></div>
    <div className="search-results">{filtered.length ? filtered.map((instrument, index) => {
      const quote = liveQuote(quotes, instrument.symbol);
      return <div key={instrument.symbol} className={`search-result ${index === active ? "keyboard-active" : ""}`}>
        <button className="search-result-main" onClick={() => { onSelect(instrument.symbol); onClose(); }}><AssetLogo instrument={instrument} size={35}/><span className="search-result-name"><strong>{instrument.symbol}</strong><span>{instrument.name}</span></span>{instrument.tier ? <span className={`tier-tag tier-${instrument.tier}`}>{instrument.tier} эш.</span> : <span className="exchange-tag">MOEX</span>}<span className="search-result-price"><strong>{quote ? formatPrice(quote.price) : "—"}</strong>{quote && <span className={quote.change >= 0 ? "positive" : "negative"}>{changeLabel(quote)}</span>}</span></button>
        <button className={`icon-button favorite-button ${watchlist.includes(instrument.symbol) ? "is-favorite" : ""}`} onClick={() => onToggle(instrument.symbol)} aria-label={watchlist.includes(instrument.symbol) ? `Убрать ${instrument.symbol} из списка` : `Добавить ${instrument.symbol} в список`}><Star size={17} fill={watchlist.includes(instrument.symbol) ? "currentColor" : "none"}/></button>
      </div>;
    }) : <div className="empty-state"><Search size={30}/><h3>Ничего не найдено</h3><p>Попробуйте название компании или другой тикер.</p></div>}</div>
    <div className="modal-footnote"><span><kbd>↑</kbd> <kbd>↓</kbd> для навигации</span><span><kbd>esc</kbd> закрыть</span></div>
  </Modal>;
}

export function MarketDialog({ onClose, onSelect, quotes, screener = false }: { onClose: () => void; onSelect: (symbol: string) => void; quotes: Quote[]; screener?: boolean }) {
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("Все секторы");
  const [gainers, setGainers] = useState(false);
  const [tier, setTier] = useState(0);
  const [sort, setSort] = useState<"symbol" | "change" | "price">("change");
  const stocks = INSTRUMENTS.filter(i => i.kind === "stock");
  const getQuote = (i: Instrument) => liveQuote(quotes, i.symbol);
  const filtered = stocks.filter(i => `${i.name} ${i.symbol}`.toLowerCase().includes(query.toLowerCase()) && (sector === "Все секторы" || i.sector === sector) && (!tier || i.tier === tier) && (!gainers || (getQuote(i)?.change ?? 0) > 0)).sort((a, b) => sort === "symbol" ? a.symbol.localeCompare(b.symbol) : (getQuote(b)?.[sort] ?? 0) - (getQuote(a)?.[sort] ?? 0));
  const rising = stocks.filter(i => (getQuote(i)?.change ?? 0) > 0).length;
  const leader = [...stocks].sort((a, b) => (getQuote(b)?.change ?? 0) - (getQuote(a)?.change ?? 0))[0];
  return <Modal title={screener ? "Скринер акций" : "Обзор рынка"} subtitle="Российский рынок в одном месте" onClose={onClose} className="market-modal" icon={<TrendingUp size={21}/>}>
    <div className="market-summary"><div><span>Акций в каталоге</span><strong>{stocks.length}<small>MOEX</small></strong></div><div><span>Растут / снижаются</span><strong><b className="positive">{rising}</b><small>/</small><b className="negative">{stocks.length - rising}</b></strong></div><div><span>Лидер роста</span><strong>{leader.symbol}<small className="positive">{changeLabel(getQuote(leader))}</small></strong></div></div>
    <div className="screener-filters"><div className="dialog-search compact"><Search size={16}/><input placeholder="Поиск акции" value={query} onChange={e => setQuery(e.target.value)}/></div><select aria-label="Сектор" value={sector} onChange={e => setSector(e.target.value)}>{["Все секторы", ...new Set(stocks.map(i => i.sector))].map(s => <option key={s}>{s}</option>)}</select><div className="tier-chips">{TIERS.map(t => <button key={t.value} className={`filter-chip ${tier === t.value ? "active" : ""}`} onClick={() => setTier(tier === t.value ? 0 : t.value)}>{t.short}</button>)}</div><button className={`filter-chip ${gainers ? "active" : ""}`} onClick={() => setGainers(!gainers)}><TrendingUp size={14}/>Растущие</button></div>
    <div className="screener-table-wrap"><table className="screener-table"><thead><tr><th><button onClick={() => setSort("symbol")}>Инструмент {sort === "symbol" && "↓"}</button></th><th>Эшелон</th><th>Сектор</th><th><button onClick={() => setSort("price")}>Цена, ₽ {sort === "price" && "↓"}</button></th><th><button onClick={() => setSort("change")}>Изменение {sort === "change" && "↓"}</button></th><th/></tr></thead><tbody>{filtered.map(i => { const q = getQuote(i); return <tr key={i.symbol} onClick={() => { onSelect(i.symbol); onClose(); }}><td><AssetLogo instrument={i}/><span><strong>{i.symbol}</strong><small>{i.name}</small></span></td><td className="muted"><span className={`tier-tag tier-${i.tier ?? 0}`}>{i.tier ? `${i.tier} эш.` : "—"}</span></td><td className="muted">{i.sector}</td><td>{q ? formatPrice(q.price) : "—"}</td><td className={q && q.change >= 0 ? "positive" : q ? "negative" : "muted"}>{changeLabel(q)}</td><td><ChevronRight size={15}/></td></tr>; })}</tbody></table>{!filtered.length && <div className="empty-state"><SlidersHorizontal size={25}/><h3>Нет подходящих инструментов</h3><p>Измените фильтры или поисковый запрос.</p></div>}</div>
    <div className="modal-footnote"><span>{filtered.length} инструментов</span><span>Нажмите на строку, чтобы открыть график</span></div>
  </Modal>;
}

export function SettingsDialog({ onClose, settings, onChange, onReset, source, onRefresh }: { onClose: () => void; settings: WorkspaceSettings; onChange: (s: WorkspaceSettings) => void; onReset: () => void; source: string; onRefresh: () => void }) {
  const [confirmReset, setConfirmReset] = useState(false);
  return <Modal title="Настройки терминала" subtitle="Ваше рабочее пространство" onClose={onClose} className="settings-modal" icon={<SlidersHorizontal size={20}/>}><div className="settings-body">
    <h3>Вид графика</h3><div className="chart-type-options">{([{ type: "candles", label: "Свечи", icon: <CandlestickChart size={25}/> }, { type: "line", label: "Линия", icon: <ChartLine size={25}/> }, { type: "area", label: "Область", icon: <ChartArea size={25}/> }] as const).map(t => <button key={t.type} className={settings.chartType === t.type ? "active" : ""} onClick={() => onChange({ ...settings, chartType: t.type })}>{t.icon}{t.label}{settings.chartType === t.type && <Check size={13}/>}</button>)}</div>
    <div className="setting-row"><div><strong>Объёмы торгов</strong><p>Гистограмма под ценовым графиком</p></div><button className={`switch ${settings.showVolume ? "on" : ""}`} role="switch" aria-checked={settings.showVolume} aria-label="Показывать объёмы" onClick={() => onChange({ ...settings, showVolume: !settings.showVolume })}><span/></button></div>
    <div className="setting-row"><div><strong>Источник данных</strong><p>{source}</p></div><button className="secondary-button" onClick={onRefresh}><RotateCcw size={14}/>Обновить</button></div>
    <div className="readonly-notice"><ShieldCheck size={20}/><div><strong>Биржевые данные · только чтение</strong><p>Токен Т-Инвест хранится на сервере, заявки на биржу не отправляются. Торговля идёт на виртуальном счёте в браузере.</p></div></div>
    <div className="setting-row reset-row"><div><strong>Сбросить рабочее пространство</strong><p>Вернуть исходный график и список инструментов</p></div><button className="danger-button" onClick={() => { if (confirmReset) { onReset(); onClose(); } else setConfirmReset(true); }}>{confirmReset ? "Подтвердить сброс" : "Сбросить"}</button></div>
  </div></Modal>;
}

export function InstrumentDialog({ instrument, quote, onClose }: { instrument: Instrument; quote: Quote | null; onClose: () => void }) {
  return <Modal title="Об инструменте" onClose={onClose} className="instrument-modal"><div className="instrument-dialog-body"><div className="instrument-title"><AssetLogo instrument={instrument} size={54}/><div><h2>{instrument.name}</h2><span>{instrument.symbol} · MOEX</span></div></div><div className="instrument-big-price">{quote ? formatPrice(quote.price) : "—"}<small>{instrument.kind === "index" ? "п." : instrument.kind === "currency" ? "₽/юань" : "RUB"}</small>{quote && <span className={quote.change >= 0 ? "positive" : "negative"}>{changeLabel(quote)}</span>}</div><p className="instrument-description">{instrument.description}</p><dl className="instrument-facts"><div><dt>Полное название</dt><dd>{instrument.fullName}</dd></div><div><dt>Сектор</dt><dd>{instrument.sector}</dd></div><div><dt>Эшелон</dt><dd>{instrument.tier ? `${instrument.tier}-й` : "—"}</dd></div><div><dt>Биржа</dt><dd>Московская биржа</dd></div><div><dt>Валюта</dt><dd>Российский рубль · RUB</dd></div><div><dt>Размер лота</dt><dd>{instrument.lot} шт.</dd></div><div><dt>Шаг цены</dt><dd>{instrument.step} ₽</dd></div><div><dt>Источник котировки</dt><dd>{!quote || quote.source === "demo" ? "Нет данных" : quote.source === "moex" ? "MOEX ISS · задержка до 15 минут" : "Т-Инвест API"}</dd></div></dl><a className="secondary-button external-button" href={`https://www.moex.com/ru/issue.aspx?board=${instrument.kind === "stock" ? "TQBR" : instrument.kind === "currency" ? "CETS" : "SNDX"}&code=${encodeURIComponent(instrument.symbol)}`} target="_blank" rel="noreferrer">Открыть на сайте биржи<ExternalLink size={15}/></a></div></Modal>;
}

export function HelpDialog({ onClose }: { onClose: () => void }) {
  return <Modal title="Ваш взгляд на рынок" subtitle="Небольшая инструкция по MOEX Terminal" onClose={onClose} className="help-modal" icon={<Command size={20}/>}><div className="help-body"><div className="help-shortcut"><span>Поиск инструмента</span><span><kbd>⌘ / Ctrl</kbd> + <kbd>K</kbd></span></div><div className="help-shortcut"><span>Закрыть окно / выйти из режима рисования</span><kbd>Esc</kbd></div><div className="help-shortcut"><span>Изменить масштаб</span><span>Колесо мыши / жест щипка</span></div><div className="help-shortcut"><span>Линейка (измерение)</span><kbd>L</kbd></div><div className="help-shortcut"><span>Линия тренда</span><kbd>T</kbd></div><div className="help-shortcut"><span>Горизонтальный уровень</span><kbd>H</kbd></div><div className="help-shortcut"><span>Курсор</span><kbd>C</kbd></div><div className="help-shortcut"><span>Прокрутить историю</span><span>Перетащите график</span></div><h3>Инструменты рисования</h3><p>Нажмите <kbd>H</kbd> и щёлкните по графику, чтобы поставить горизонтальный уровень. Для линии тренда (<kbd>T</kbd>) и линейки (<kbd>L</kbd>) выберите две точки: пока двигаете мышь, цифры обновляются на лету — показываются прибыль в пунктах и процентах, число баров и длительность. Рисунки сохраняются отдельно для каждого тикера.</p><h3>Индикаторы</h3><p>Единственный индикатор на графике — SMC Pro: структура BOS/CHoCH, Order Blocks по методу LuxAlgo, FVG, EQH/EQL, Premium/Discount, POC и профиль объёма, A+ зоны и сигналы BUY/SELL. Настройки — кнопка «SMC Pro» на панели графика.</p><h3>Виртуальный счёт</h3><p>Стартовый капитал 10 000 000 ₽. Заявки только рыночные, доступны лонг и шорт с плечом до 1:3, комиссия 0,05 % от оборота. Тейк-профит и стоп-лосс исполняются автоматически по свечам. Счёт хранится в браузере и не связан с реальным брокерским счётом.</p><a href="https://developer.tbank.ru/invest/intro/intro" target="_blank" rel="noreferrer" className="text-link">Документация Т-Инвест API<ArrowUpRight size={14}/></a></div></Modal>;
}
