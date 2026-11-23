"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Search, X, Star, Plus, Check, ArrowUpRight, SlidersHorizontal, Code2, TrendingUp, ChevronRight, Eye, EyeOff, Trash2, Activity, ShieldCheck, Command, Layers3, RotateCcw, CandlestickChart, ChartLine, ChartArea, ExternalLink } from "lucide-react";
import { INSTRUMENTS, formatPrice, formatChange, demoQuote, parseFormula, type Indicator, type Instrument, type InstrumentKind, type Quote, type WorkspaceSettings } from "@/lib/market";

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

export function SearchDialog({ onClose, onSelect, quotes, watchlist, onToggle, addMode = false }: { onClose: () => void; onSelect: (symbol: string) => void; quotes: Quote[]; watchlist: string[]; onToggle: (symbol: string) => void; addMode?: boolean }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<InstrumentKind | "all">("all");
  const [active, setActive] = useState(0);
  const filtered = INSTRUMENTS.filter(i => (kind === "all" || i.kind === kind) && `${i.symbol} ${i.name} ${i.fullName}`.toLowerCase().includes(query.toLowerCase()));
  return <Modal title={addMode ? "Добавить в список" : "Поиск инструмента"} subtitle="Московская биржа · акции, индексы и валюты" onClose={onClose} className="search-modal">
    <div className="dialog-search"><Search size={19}/><input autoFocus placeholder="Название компании или тикер" value={query} onChange={e => { setQuery(e.target.value); setActive(0); }} onKeyDown={e => { if (e.key === "ArrowDown") { e.preventDefault(); setActive(a => Math.min(a + 1, filtered.length - 1)); } if (e.key === "ArrowUp") { e.preventDefault(); setActive(a => Math.max(0, a - 1)); } if (e.key === "Enter" && filtered[active]) { onSelect(filtered[active].symbol); onClose(); } }}/><kbd>↵</kbd></div>
    <div className="dialog-tabs">{([["all", "Все инструменты"], ["stock", "Акции"], ["index", "Индексы"], ["currency", "Валюты"]] as const).map(([value, label]) => <button key={value} className={kind === value ? "active" : ""} onClick={() => { setKind(value); setActive(0); }}>{label}</button>)}</div>
    <div className="search-result-label"><span>ИНСТРУМЕНТ</span><span>ЦЕНА / ИЗМЕНЕНИЕ</span></div>
    <div className="search-results">{filtered.length ? filtered.map((instrument, index) => {
      const quote = quotes.find(q => q.symbol === instrument.symbol) ?? demoQuote(instrument);
      return <div key={instrument.symbol} className={`search-result ${index === active ? "keyboard-active" : ""}`}>
        <button className="search-result-main" onClick={() => { onSelect(instrument.symbol); onClose(); }}><AssetLogo instrument={instrument} size={35}/><span className="search-result-name"><strong>{instrument.symbol}</strong><span>{instrument.name}</span></span><span className="exchange-tag">MOEX</span><span className="search-result-price"><strong>{formatPrice(quote.price)}</strong><span className={quote.change >= 0 ? "positive" : "negative"}>{formatChange(quote.change)}</span></span></button>
        <button className={`icon-button favorite-button ${watchlist.includes(instrument.symbol) ? "is-favorite" : ""}`} onClick={() => onToggle(instrument.symbol)} aria-label={watchlist.includes(instrument.symbol) ? `Убрать ${instrument.symbol} из списка` : `Добавить ${instrument.symbol} в список`}><Star size={17} fill={watchlist.includes(instrument.symbol) ? "currentColor" : "none"}/></button>
      </div>;
    }) : <div className="empty-state"><Search size={30}/><h3>Ничего не найдено</h3><p>Попробуйте название компании или другой тикер.</p></div>}</div>
    <div className="modal-footnote"><span><kbd>↑</kbd> <kbd>↓</kbd> для навигации</span><span><kbd>esc</kbd> закрыть</span></div>
  </Modal>;
}

const LIBRARY: { type: Indicator["type"]; name: string; title: string; description: string; period: number; color: string; category: string }[] = [
  { type: "ema", name: "EMA", title: "Exponential Moving Average", description: "Экспоненциальная скользящая средняя", period: 20, color: "#7194f5", category: "Тренд" },
  { type: "sma", name: "SMA", title: "Simple Moving Average", description: "Простая скользящая средняя", period: 50, color: "#c8a46a", category: "Тренд" },
  { type: "bb", name: "BB", title: "Bollinger Bands", description: "Полосы Боллинджера · отклонение 2σ", period: 20, color: "#9b87de", category: "Волатильность" },
  { type: "rsi", name: "RSI", title: "Relative Strength Index", description: "Индекс относительной силы · метод Уайлдера", period: 14, color: "#bd8bdf", category: "Осциллятор" },
];

export function IndicatorDialog({ onClose, indicators, onChange, initialTab = "library" }: { onClose: () => void; indicators: Indicator[]; onChange: (items: Indicator[]) => void; initialTab?: "library" | "editor" }) {
  const [tab, setTab] = useState(initialTab);
  const [query, setQuery] = useState("");
  const [name, setName] = useState("Моя скользящая средняя");
  const [formula, setFormula] = useState("ema(close, 34)");
  const [color, setColor] = useState("#a48bf0");
  const [error, setError] = useState("");
  const update = (id: string, values: Partial<Indicator>) => onChange(indicators.map(i => i.id === id ? { ...i, ...values } : i));
  return <Modal title="Индикаторы" subtitle="Больше контекста для каждого движения цены" onClose={onClose} className="indicators-modal" icon={<Layers3 size={21}/>}>
    <div className="dialog-tabs wide-tabs"><button className={tab === "library" ? "active" : ""} onClick={() => setTab("library")}><Activity size={15}/>Библиотека индикаторов</button><button className={tab === "editor" ? "active" : ""} onClick={() => setTab("editor")}><Code2 size={15}/>Свой индикатор</button></div>
    <div className="indicator-dialog-body">{tab === "library" ? <><div className="dialog-search compact"><Search size={16}/><input placeholder="Найти индикатор" value={query} onChange={e => setQuery(e.target.value)}/></div><div className="indicator-library">{LIBRARY.filter(i => `${i.name} ${i.title} ${i.description}`.toLowerCase().includes(query.toLowerCase())).map(item => {
      const added = indicators.some(i => i.type === item.type && !i.custom);
      return <div className="library-row" key={item.type}><span className="indicator-symbol" style={{ color: item.color, background: `${item.color}12` }}>{item.name}</span><div><strong>{item.title}</strong><p>{item.description}</p><small>{item.category}</small></div><button className={`add-indicator ${added ? "added" : ""}`} disabled={added || indicators.length >= 20} onClick={() => onChange([...indicators, { id: crypto.randomUUID(), name: item.name, type: item.type, period: item.period, color: item.color, enabled: true }])}>{added ? <Check size={17}/> : <Plus size={17}/>}<span>{added ? "На графике" : "Добавить"}</span></button></div>;
    })}</div></> : <form className="indicator-editor" onSubmit={e => { e.preventDefault(); const parsed = parseFormula(formula); if (!parsed) { setError("Используйте sma(close, N), ema(close, N) или rsi(close, N), где N от 2 до 200. Код Pine Script и Python необходимо предварительно адаптировать."); return; } if (!name.trim()) { setError("Введите название индикатора"); return; } if (indicators.length >= 20) { setError("Максимум 20 индикаторов. Удалите один из списка."); return; } onChange([...indicators, { id: crypto.randomUUID(), name: name.trim(), ...parsed, color, enabled: true, custom: true, formula }]); setError(""); setTab("library"); }}>
      <div className="editor-notice"><Code2 size={19}/><div><strong>Ваша логика. Ваш график.</strong><p>Добавьте формулу и наложите результат на график. Исходный код сложных индикаторов можно будет адаптировать отдельно.</p></div></div>
      <label className="field-label">Название<input maxLength={60} value={name} onChange={e => setName(e.target.value)} placeholder="Название индикатора"/></label>
      <div className="code-editor-label"><span>ФОРМУЛА</span><span>MOEX Formula</span></div><div className="code-editor"><span className="line-number">1</span><textarea spellCheck={false} maxLength={500} aria-label="Формула индикатора" value={formula} onChange={e => { setFormula(e.target.value); setError(""); }}/></div>
      <p className="formula-hint">Доступно: <code>sma(close, 20)</code>, <code>ema(close, 50)</code>, <code>rsi(close, 14)</code>. Расчёт выполняется локально, без запуска произвольного кода.</p>
      {error && <p className="form-error">{error}</p>}
      <div className="editor-actions"><label className="color-field"><input type="color" aria-label="Цвет индикатора" value={color} onChange={e => setColor(e.target.value)}/>Цвет линии</label><button className="primary-button" type="submit"><Plus size={16}/>Сохранить и применить</button></div>
    </form>}
    {indicators.length > 0 && <div className="active-indicators"><h3>На вашем графике <span>{indicators.length}</span></h3>{indicators.map(i => <div className="active-indicator-row" key={i.id}><span className="line-sample" style={{ background: i.color }}/><strong>{i.name}</strong>{i.custom && <Code2 size={12}/>}<label className="period-field">Период<input type="number" min={2} max={200} value={i.period} onChange={e => { const period = Math.min(200, Math.max(2, +e.target.value)); update(i.id, { period, ...(i.custom ? { formula: `${i.type}(close, ${period})` } : {}) }); }}/></label><input className="small-color" type="color" aria-label={`Цвет ${i.name}`} value={i.color} onChange={e => update(i.id, { color: e.target.value })}/><button className="icon-button" onClick={() => update(i.id, { enabled: !i.enabled })} aria-label={i.enabled ? `Скрыть ${i.name}` : `Показать ${i.name}`}>{i.enabled ? <Eye size={16}/> : <EyeOff size={16}/>}</button><button className="icon-button danger-hover" onClick={() => onChange(indicators.filter(item => item.id !== i.id))} aria-label={`Удалить ${i.name}`}><Trash2 size={15}/></button></div>)}</div>}
    </div><div className="modal-footnote"><ShieldCheck size={14}/><span>Индикаторы и настройки сохраняются в вашем рабочем пространстве</span></div>
  </Modal>;
}

export function MarketDialog({ onClose, onSelect, quotes, screener = false }: { onClose: () => void; onSelect: (symbol: string) => void; quotes: Quote[]; screener?: boolean }) {
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("Все секторы");
  const [gainers, setGainers] = useState(false);
  const [sort, setSort] = useState<"symbol" | "change" | "price">("change");
  const stocks = INSTRUMENTS.filter(i => i.kind === "stock");
  const getQuote = (i: Instrument) => quotes.find(q => q.symbol === i.symbol) ?? demoQuote(i);
  const filtered = stocks.filter(i => `${i.name} ${i.symbol}`.toLowerCase().includes(query.toLowerCase()) && (sector === "Все секторы" || i.sector === sector) && (!gainers || getQuote(i).change > 0)).sort((a, b) => sort === "symbol" ? a.symbol.localeCompare(b.symbol) : getQuote(b)[sort] - getQuote(a)[sort]);
  const rising = stocks.filter(i => getQuote(i).change > 0).length;
  const leader = [...stocks].sort((a, b) => getQuote(b).change - getQuote(a).change)[0];
  return <Modal title={screener ? "Скринер акций" : "Обзор рынка"} subtitle="Российский рынок в одном месте" onClose={onClose} className="market-modal" icon={<TrendingUp size={21}/>}>
    <div className="market-summary"><div><span>Акций в каталоге</span><strong>{stocks.length}<small>MOEX</small></strong></div><div><span>Растут / снижаются</span><strong><b className="positive">{rising}</b><small>/</small><b className="negative">{stocks.length - rising}</b></strong></div><div><span>Лидер роста</span><strong>{leader.symbol}<small className="positive">{formatChange(getQuote(leader).change)}</small></strong></div></div>
    <div className="screener-filters"><div className="dialog-search compact"><Search size={16}/><input placeholder="Поиск акции" value={query} onChange={e => setQuery(e.target.value)}/></div><select aria-label="Сектор" value={sector} onChange={e => setSector(e.target.value)}>{["Все секторы", ...new Set(stocks.map(i => i.sector))].map(s => <option key={s}>{s}</option>)}</select><button className={`filter-chip ${gainers ? "active" : ""}`} onClick={() => setGainers(!gainers)}><TrendingUp size={14}/>Только растущие</button></div>
    <div className="screener-table-wrap"><table className="screener-table"><thead><tr><th><button onClick={() => setSort("symbol")}>Инструмент {sort === "symbol" && "↓"}</button></th><th>Сектор</th><th><button onClick={() => setSort("price")}>Цена, ₽ {sort === "price" && "↓"}</button></th><th><button onClick={() => setSort("change")}>Изменение {sort === "change" && "↓"}</button></th><th/></tr></thead><tbody>{filtered.map(i => { const q = getQuote(i); return <tr key={i.symbol} onClick={() => { onSelect(i.symbol); onClose(); }}><td><AssetLogo instrument={i}/><span><strong>{i.symbol}</strong><small>{i.name}</small></span></td><td className="muted">{i.sector}</td><td>{formatPrice(q.price)}</td><td className={q.change >= 0 ? "positive" : "negative"}>{formatChange(q.change)}</td><td><ChevronRight size={15}/></td></tr>; })}</tbody></table>{!filtered.length && <div className="empty-state"><SlidersHorizontal size={25}/><h3>Нет подходящих инструментов</h3><p>Измените фильтры или поисковый запрос.</p></div>}</div>
    <div className="modal-footnote"><span>{filtered.length} инструментов</span><span>Нажмите на строку, чтобы открыть график</span></div>
  </Modal>;
}

export function SettingsDialog({ onClose, settings, onChange, onReset, source, onRefresh }: { onClose: () => void; settings: WorkspaceSettings; onChange: (s: WorkspaceSettings) => void; onReset: () => void; source: string; onRefresh: () => void }) {
  const [confirmReset, setConfirmReset] = useState(false);
  return <Modal title="Настройки терминала" subtitle="Ваше рабочее пространство" onClose={onClose} className="settings-modal" icon={<SlidersHorizontal size={20}/>}><div className="settings-body">
    <h3>Вид графика</h3><div className="chart-type-options">{([{ type: "candles", label: "Свечи", icon: <CandlestickChart size={25}/> }, { type: "line", label: "Линия", icon: <ChartLine size={25}/> }, { type: "area", label: "Область", icon: <ChartArea size={25}/> }] as const).map(t => <button key={t.type} className={settings.chartType === t.type ? "active" : ""} onClick={() => onChange({ ...settings, chartType: t.type })}>{t.icon}{t.label}{settings.chartType === t.type && <Check size={13}/>}</button>)}</div>
    <div className="setting-row"><div><strong>Объёмы торгов</strong><p>Гистограмма под ценовым графиком</p></div><button className={`switch ${settings.showVolume ? "on" : ""}`} role="switch" aria-checked={settings.showVolume} aria-label="Показывать объёмы" onClick={() => onChange({ ...settings, showVolume: !settings.showVolume })}><span/></button></div>
    <div className="setting-row"><div><strong>Источник данных</strong><p>{source}</p></div><button className="secondary-button" onClick={onRefresh}><RotateCcw size={14}/>Обновить</button></div>
    <div className="readonly-notice"><ShieldCheck size={20}/><div><strong>Безопасный режим · только чтение</strong><p>Токен хранится на сервере. Терминал не размещает заявки и не запрашивает данные вашего портфеля.</p></div></div>
    <div className="setting-row reset-row"><div><strong>Сбросить рабочее пространство</strong><p>Вернуть исходный график и список инструментов</p></div><button className="danger-button" onClick={() => { if (confirmReset) { onReset(); onClose(); } else setConfirmReset(true); }}>{confirmReset ? "Подтвердить сброс" : "Сбросить"}</button></div>
  </div></Modal>;
}

export function InstrumentDialog({ instrument, quote, onClose }: { instrument: Instrument; quote: Quote; onClose: () => void }) {
  return <Modal title="Об инструменте" onClose={onClose} className="instrument-modal"><div className="instrument-dialog-body"><div className="instrument-title"><AssetLogo instrument={instrument} size={54}/><div><h2>{instrument.name}</h2><span>{instrument.symbol} · MOEX</span></div></div><div className="instrument-big-price">{formatPrice(quote.price)}<small>RUB</small><span className={quote.change >= 0 ? "positive" : "negative"}>{formatChange(quote.change)}</span></div><p className="instrument-description">{instrument.description}</p><dl className="instrument-facts"><div><dt>Полное название</dt><dd>{instrument.fullName}</dd></div><div><dt>Сектор</dt><dd>{instrument.sector}</dd></div><div><dt>Биржа</dt><dd>Московская биржа</dd></div><div><dt>Валюта</dt><dd>Российский рубль · RUB</dd></div><div><dt>Размер лота</dt><dd>{instrument.lot} шт.</dd></div><div><dt>Шаг цены</dt><dd>{instrument.step} ₽</dd></div><div><dt>Источник котировки</dt><dd>{quote.source === "demo" ? "Демонстрационные данные" : quote.source === "moex" ? "MOEX ISS · задержка до 15 минут" : "Т-Инвест API"}</dd></div></dl><a className="secondary-button external-button" href={`https://www.moex.com/ru/issue.aspx?board=${instrument.kind === "stock" ? "TQBR" : instrument.kind === "currency" ? "CETS" : "SNDX"}&code=${encodeURIComponent(instrument.symbol)}`} target="_blank" rel="noreferrer">Открыть на сайте биржи<ExternalLink size={15}/></a></div></Modal>;
}

export function HelpDialog({ onClose }: { onClose: () => void }) {
  return <Modal title="Ваш взгляд на рынок" subtitle="Небольшая инструкция по MOEX Terminal" onClose={onClose} className="help-modal" icon={<Command size={20}/>}><div className="help-body"><div className="help-shortcut"><span>Поиск инструмента</span><span><kbd>⌘ / Ctrl</kbd> + <kbd>K</kbd></span></div><div className="help-shortcut"><span>Закрыть окно / выйти из режима рисования</span><kbd>Esc</kbd></div><div className="help-shortcut"><span>Изменить масштаб</span><span>Колесо мыши / жест щипка</span></div><div className="help-shortcut"><span>Прокрутить историю</span><span>Перетащите график</span></div><h3>Инструменты рисования</h3><p>Выберите горизонтальный уровень и нажмите на график. Для линии тренда и измерения последовательно выберите две точки. Рисунки сохраняются отдельно для каждого тикера.</p><h3>Пользовательские индикаторы</h3><p>В меню «Индикаторы → Свой индикатор» можно наложить формулы SMA, EMA и RSI. Сложный исходный код можно адаптировать и добавить следующим этапом.</p><a href="https://developer.tbank.ru/invest/intro/intro" target="_blank" rel="noreferrer" className="text-link">Документация Т-Инвест API<ArrowUpRight size={14}/></a></div></Modal>;
}
