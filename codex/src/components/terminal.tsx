"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowDown, ArrowUpRight, Bell, Camera, CandlestickChart, ChartArea, ChartLine, Check, ChevronDown, ChevronRight, CircleHelp, CloudCheck, Code2, Crosshair, Download, Eye, EyeOff, FolderOpen, History, Info, Layers3, List, LockKeyhole, Magnet, Maximize2, Minimize2, Minus, MoreHorizontal, Plus, RefreshCw, Ruler, Search, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Star, Trash2, TrendingUp, Undo2, UnlockKeyhole, Wifi, WifiOff, X } from "lucide-react";
import { DEFAULT_SETTINGS, INSTRUMENTS, TIMEFRAMES, calculateIndicator, demoQuote, formatChange, formatCompact, formatPrice, generateCandles, getInstrument, type Candle, type DataSource, type Drawing, type InstrumentKind, type Quote, type WorkspaceSettings } from "@/lib/market";
import { AssetLogo, HelpDialog, IndicatorDialog, InstrumentDialog, MarketDialog, SearchDialog, SettingsDialog } from "./dialogs";
import type { ChartHandle, DrawingTool } from "./trading-chart";

const TradingChart = dynamic(() => import("./trading-chart"), { ssr: false, loading: () => <div className="chart-initializing"><span className="loading-spinner"/>Подготавливаем график</div> });
const EMPTY_DRAWINGS: Drawing[] = [];
type ModalName = "search" | "add" | "indicators" | "editor" | "market" | "screener" | "settings" | "info" | "help" | null;
type Popover = "chartType" | "workspace" | "notifications" | "watchlist" | "profile" | "history" | null;
const RANGE_OPTIONS = [{ label: "1Д", days: 1 }, { label: "5Д", days: 5 }, { label: "1М", days: 30 }, { label: "3М", days: 90 }, { label: "6М", days: 180 }, { label: "YTD", days: -1 }, { label: "1Г", days: 365 }, { label: "Всё", days: 0 }];
const SOURCE_LABELS: Record<DataSource, string> = { tinvest: "Т-Инвест API · обновление 30 с", moex: "MOEX ISS · задержка до 15 мин", demo: "Демонстрационные данные" };

export default function Terminal({ initialCandles, initialQuotes }: { initialCandles: Candle[]; initialQuotes: Quote[] }) {
  const [settings, setSettings] = useState<WorkspaceSettings>(() => structuredClone(DEFAULT_SETTINGS));
  const [candles, setCandles] = useState<Candle[]>(initialCandles);
  const [quotes, setQuotes] = useState<Quote[]>(initialQuotes);
  const [source, setSource] = useState<DataSource>("demo");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState<"saved" | "saving" | "local">("saved");
  const [modal, setModal] = useState<ModalName>(null);
  const [popover, setPopover] = useState<Popover>(null);
  const [watchKind, setWatchKind] = useState<InstrumentKind>("stock");
  const [sortWatch, setSortWatch] = useState<"none" | "down" | "up">("none");
  const [aboutTab, setAboutTab] = useState<"overview" | "analysis" | "indicators">("overview");
  const [tool, setTool] = useState<DrawingTool>("cursor");
  const [magnet, setMagnet] = useState(false);
  const [locked, setLocked] = useState(false);
  const [drawingsVisible, setDrawingsVisible] = useState(true);
  const [showWatchlist, setShowWatchlist] = useState(true);
  const [focusMode, setFocusMode] = useState(false);
  const [logarithmic, setLogarithmic] = useState(false);
  const [activeRange, setActiveRange] = useState("6М");
  const [hover, setHover] = useState<Candle | null>(null);
  const [clock, setClock] = useState("—:—:—");
  const [toast, setToast] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [recent, setRecent] = useState(["SBER"]);
  const chartApi = useRef<ChartHandle | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const instrument = getInstrument(settings.symbol);
  const currentDrawings = settings.drawings[settings.symbol] ?? EMPTY_DRAWINGS;
  const last = candles[candles.length - 1];
  const previous = candles[candles.length - 2] ?? last;
  const candle = hover ?? last;
  const timeframeLabel = TIMEFRAMES.find(t => t.value === settings.timeframe)?.label ?? "1Д";
  const closeModal = useCallback(() => setModal(null), []);
  const notify = useCallback((message: string) => { setToast(message); if (toastTimer.current) clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(""), 4500); }, []);

  const quote = useMemo<Quote>(() => {
    if (source === "demo") return demoQuote(instrument);
    const existing = quotes.find(q => q.symbol === settings.symbol && q.source !== "demo");
    if (existing) return existing;
    return { symbol: settings.symbol, price: last.close, change: (last.close / previous.close - 1) * 100, absolute: last.close - previous.close, high: last.high, low: last.low, volume: last.volume, source };
  }, [quotes, settings.symbol, instrument, source, last, previous]);
  const analysis = useMemo(() => {
    const ema = calculateIndicator(candles, "ema", 20).at(-1)?.value ?? last.close;
    const sma = calculateIndicator(candles, "sma", 50).at(-1)?.value ?? last.close;
    const rsi = calculateIndicator(candles, "rsi", 14).at(-1)?.value ?? 50;
    const score = (last.close > ema ? 1 : 0) + (last.close > sma ? 1 : 0) + (rsi > 50 && rsi < 70 ? 1 : 0);
    return { ema, sma, rsi, score };
  }, [candles, last]);
  const visibleInstruments = useMemo(() => {
    const instruments = settings.watchlist.map(getInstrument).filter(i => i.kind === watchKind);
    if (sortWatch === "none") return instruments;
    return [...instruments].sort((a, b) => ((quotes.find(q => q.symbol === b.symbol)?.change ?? b.change) - (quotes.find(q => q.symbol === a.symbol)?.change ?? a.change)) * (sortWatch === "down" ? 1 : -1));
  }, [watchKind, settings.watchlist, sortWatch, quotes]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch("/api/workspace", { signal: AbortSignal.timeout(10000) });
        if (!response.ok) throw new Error("Workspace unavailable");
        const data = await response.json();
        if (!cancelled && data.settings) { setSettings(data.settings); setRecent([data.settings.symbol]); }
      } catch {
        try { const stored = localStorage.getItem("moex-workspace"); if (stored && !cancelled) { const parsed = JSON.parse(stored); if (INSTRUMENTS.some(i => i.symbol === parsed.symbol) && Array.isArray(parsed.indicators)) setSettings({ ...DEFAULT_SETTINGS, ...parsed }); } } catch { /* Ignore corrupted browser storage. */ }
        if (!cancelled) setSaveState("local");
      } finally { if (!cancelled) setLoaded(true); }
    };
    void load();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!loaded) return;
    setSaveState("saving");
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try { localStorage.setItem("moex-workspace", JSON.stringify(settings)); } catch { /* PostgreSQL remains the primary storage. */ }
      try {
        const response = await fetch("/api/workspace", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings), signal: controller.signal });
        if (!response.ok) throw new Error("Save failed");
        setSaveState("saved");
      } catch { if (!controller.signal.aborted) setSaveState("local"); }
    }, 650);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [settings, loaded]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setHover(null); setSource("demo");
    setCandles(generateCandles(settings.symbol, settings.timeframe));
    const update = async () => {
      try {
        const response = await fetch(`/api/market?symbol=${encodeURIComponent(settings.symbol)}&timeframe=${settings.timeframe}`, { signal: controller.signal });
        if (!response.ok) throw new Error("Market unavailable");
        const data = await response.json();
        if (!controller.signal.aborted && data.candles?.length) { setCandles(data.candles); setSource(data.source); setHover(null); }
      } catch { /* The chart stays available with an explicit demo label. */ }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void update();
    const timer = setInterval(update, 30000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [settings.symbol, settings.timeframe, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    const update = async () => { try { const response = await fetch("/api/market?mode=quotes", { signal: controller.signal }); if (response.ok) { const data = await response.json(); if (!controller.signal.aborted) setQuotes(data.quotes); } } catch { /* Demo quotes are explicitly labelled. */ } };
    void update(); const timer = setInterval(update, 30000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [refresh]);

  useEffect(() => {
    const update = () => setClock(new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Moscow" }).format(new Date()));
    update(); const timer = setInterval(update, 1000); return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setModal(m => m === "search" ? null : "search"); setPopover(null); }
      if (event.key === "Escape") { setPopover(null); setTool("cursor"); if (!modal) setFocusMode(false); }
    };
    const outside = (event: PointerEvent) => { if (!(event.target as HTMLElement).closest("[data-popover]")) setPopover(null); };
    document.addEventListener("keydown", handler); document.addEventListener("pointerdown", outside);
    return () => { document.removeEventListener("keydown", handler); document.removeEventListener("pointerdown", outside); };
  }, [modal]);

  const selectSymbol = useCallback((symbol: string) => { setSettings(s => ({ ...s, symbol })); setHover(null); setActiveRange("6М"); setRecent(r => [symbol, ...r.filter(i => i !== symbol)].slice(0, 6)); }, []);
  const toggleWatch = useCallback((symbol: string) => setSettings(s => ({ ...s, watchlist: s.watchlist.includes(symbol) ? s.watchlist.filter(i => i !== symbol) : [...s.watchlist, symbol] })), []);
  const addDrawing = useCallback((drawing: Drawing) => { setSettings(s => ({ ...s, drawings: { ...s.drawings, [s.symbol]: [...(s.drawings[s.symbol] ?? []), drawing].slice(-40) } })); }, []);
  const undoDrawing = () => { setSettings(s => ({ ...s, drawings: { ...s.drawings, [s.symbol]: (s.drawings[s.symbol] ?? []).slice(0, -1) } })); };
  const clearDrawings = () => { setSettings(s => ({ ...s, drawings: { ...s.drawings, [s.symbol]: [] } })); notify("Рисунки на текущем инструменте удалены"); };
  const togglePopover = (name: Popover) => setPopover(p => p === name ? null : name);
  const openModal = (name: ModalName) => { setModal(name); setPopover(null); };
  const download = (name: string, content: string, type: string) => { const url = URL.createObjectURL(new Blob([content], { type })); const link = document.createElement("a"); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
  const exportWatchlist = () => { const content = "\uFEFFТикер;Название;Цена;Изменение, %;Источник\n" + settings.watchlist.map(symbol => { const i = getInstrument(symbol), q = quotes.find(q => q.symbol === symbol) ?? demoQuote(i); return `${symbol};${i.name};${q.price};${q.change};${SOURCE_LABELS[q.source]}`; }).join("\n"); download("MOEX-watchlist.csv", content, "text/csv;charset=utf-8"); setPopover(null); notify("Список наблюдения экспортирован"); };
  const refreshData = () => { setRefresh(r => r + 1); notify("Запрашиваем свежие данные у провайдера"); };
  const currentPriceChange = candle.close - candle.open;

  return <main className={`terminal-shell ${focusMode ? "focus-mode" : ""}`}>
    <header className="topbar">
      <a className="brand" href="/" aria-label="MOEX Terminal — главная"><span className="brand-mark"><svg viewBox="0 0 28 28" fill="none"><path d="M6 21V9l7 7L22 5v16" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round"/></svg></span><span className="brand-word">moex<span>.</span></span><span className="brand-product">terminal</span></a>
      <nav className="main-nav" aria-label="Основная навигация"><button className={!modal || !["market", "screener"].includes(modal) ? "active" : ""} onClick={() => setModal(null)}>Терминал</button><button className={modal === "market" ? "active" : ""} onClick={() => openModal("market")}>Обзор рынка</button><button className={modal === "screener" ? "active" : ""} onClick={() => openModal("screener")}>Скринер<span className="new-dot"/></button></nav>
      <div className="header-actions"><button className="global-search" onClick={() => openModal("search")}><Search size={16}/><span>Найти инструмент</span><kbd>⌘ K</kbd></button><span className="header-divider"/><span className="read-only"><ShieldCheck size={14}/><span>Только чтение</span></span><div className="dropdown-anchor" data-popover><button className={`icon-button notification-button ${popover === "notifications" ? "selected" : ""}`} aria-label="Центр уведомлений" onClick={() => togglePopover("notifications")}><Bell size={19}/><i/></button>{popover === "notifications" && <div className="dropdown-menu notifications-menu"><div className="dropdown-title">Центр уведомлений<span>3</span></div><div className="notification-item"><span className={`notification-item-icon ${source === "demo" ? "amber" : "green"}`}>{source === "demo" ? <WifiOff size={16}/> : <Wifi size={16}/>}</span><div><strong>{loading ? "Подключаемся к рынку" : source === "demo" ? "Демонстрационный режим" : "Данные подключены"}</strong><p>{source === "demo" ? "Провайдер пока недоступен. На графике показаны тестовые, не биржевые цены." : SOURCE_LABELS[source]}</p></div></div><div className="notification-item"><span className="notification-item-icon"><CloudCheck size={16}/></span><div><strong>Ваше пространство сохранено</strong><p>{saveState === "local" ? "Резервная копия в браузере. Синхронизация с сервером недоступна." : "Список инструментов, индикаторы и рисунки сохраняются автоматически."}</p></div></div><div className="notification-item"><span className="notification-item-icon"><ShieldCheck size={16}/></span><div><strong>Безопасное подключение</strong><p>Режим только для чтения. Торговые операции отключены.</p></div></div><button className="dropdown-footer" onClick={refreshData}><RefreshCw size={14}/>Проверить подключение</button></div>}</div><div className="dropdown-anchor" data-popover><button className="avatar" onClick={() => togglePopover("profile")} aria-label="Рабочее пространство">АК<span/></button>{popover === "profile" && <div className="dropdown-menu profile-menu"><div className="profile-heading"><strong>Моё пространство</strong><span>Персональный терминал</span></div><button onClick={() => openModal("settings")}><Settings2 size={16}/>Настройки</button><button onClick={() => openModal("help")}><CircleHelp size={16}/>Помощь и горячие клавиши</button><div className="dropdown-note">Настройки привязаны к этому браузеру и сохраняются в PostgreSQL.</div></div>}</div></div>
    </header>

    <div className="chart-toolbar">
      <button className="symbol-select" onClick={() => openModal("search")}><Search size={16}/><AssetLogo instrument={instrument} size={23}/><strong>{settings.symbol === "CNYRUB_TOM" ? "CNY/RUB" : settings.symbol}</strong><ChevronDown size={13}/></button><span className="toolbar-divider"/>
      <div className="timeframes" aria-label="Таймфрейм">{TIMEFRAMES.map(t => <button className={settings.timeframe === t.value ? "active" : ""} key={t.value} onClick={() => { setSettings(s => ({ ...s, timeframe: t.value })); setActiveRange(""); }}>{t.label}</button>)}</div><span className="toolbar-divider"/>
      <div className="dropdown-anchor" data-popover><button className="chart-style-button" onClick={() => togglePopover("chartType")} title="Вид графика" aria-label="Вид графика">{settings.chartType === "candles" ? <CandlestickChart size={19}/> : settings.chartType === "line" ? <ChartLine size={19}/> : <ChartArea size={19}/>}<ChevronDown size={11}/></button>{popover === "chartType" && <div className="dropdown-menu chart-type-menu">{([{ type: "candles", label: "Японские свечи", icon: <CandlestickChart size={17}/> }, { type: "line", label: "Линия", icon: <ChartLine size={17}/> }, { type: "area", label: "Область", icon: <ChartArea size={17}/> }] as const).map(t => <button className={settings.chartType === t.type ? "active" : ""} key={t.type} onClick={() => { setSettings(s => ({ ...s, chartType: t.type })); setPopover(null); }}>{t.icon}{t.label}{settings.chartType === t.type && <Check size={14}/>}</button>)}</div>}</div><span className="toolbar-divider"/>
      <button className="toolbar-text-button indicators-toolbar-button" onClick={() => openModal("indicators")}><SlidersHorizontal size={17}/><span>Индикаторы</span><span className="count-badge">{settings.indicators.filter(i => i.enabled).length}</span></button>
      <button className="toolbar-text-button code-toolbar-button" onClick={() => openModal("editor")} title="Добавить свой индикатор"><Code2 size={17}/><span>Редактор</span></button>
      <div className="toolbar-spacer"/>
      <div className="dropdown-anchor workspace-anchor" data-popover><button className="workspace-button" onClick={() => togglePopover("workspace")}><FolderOpen size={15}/><span>Основной график</span><ChevronDown size={11}/><CloudCheck className={saveState === "saving" ? "saving-pulse" : "workspace-cloud"} size={16}/></button>{popover === "workspace" && <div className="dropdown-menu workspace-menu"><div className="dropdown-title">Рабочее пространство</div><button className="active" onClick={() => { setPopover(null); notify("Открыто основное рабочее пространство"); }}><Check size={15}/>Основной график</button><button onClick={() => { download("moex-workspace.json", JSON.stringify(settings, null, 2), "application/json"); setPopover(null); }}><Download size={15}/>Экспорт настроек</button><button onClick={() => openModal("settings")}><Settings2 size={15}/>Настройки пространства</button><div className="dropdown-note">{saveState === "saved" ? "Все изменения сохранены" : saveState === "saving" ? "Сохраняем изменения…" : "Сохранено локально в браузере"}</div></div>}</div>
      <span className="toolbar-divider workspace-divider"/><button className="icon-button undo-button" disabled={!currentDrawings.length} onClick={undoDrawing} title="Удалить последний рисунок" aria-label="Отменить последний рисунок"><Undo2 size={17}/></button><button className="icon-button camera-button" title="Скачать изображение графика" aria-label="Скачать изображение графика" onClick={() => chartApi.current?.screenshot()}><Camera size={18}/></button><button className={`icon-button ${focusMode ? "selected" : ""}`} title="Режим фокуса" aria-label={focusMode ? "Выйти из режима фокуса" : "Режим фокуса"} onClick={() => setFocusMode(!focusMode)}>{focusMode ? <Minimize2 size={17}/> : <Maximize2 size={17}/>}</button><button className="icon-button" title="Настройки графика" aria-label="Настройки графика" onClick={() => openModal("settings")}><Settings2 size={18}/></button>
    </div>

    <div className={`workspace-grid ${!showWatchlist ? "watchlist-hidden" : ""}`}>
      <aside className="drawing-rail" aria-label="Инструменты рисования"><div className="rail-group">{([{ type: "cursor", label: "Перекрестие · прокрутка графика", icon: <Crosshair size={22}/> }, { type: "trend", label: "Линия тренда · выберите две точки", icon: <TrendingUp size={22}/> }, { type: "horizontal", label: "Горизонтальный уровень", icon: <Minus size={23}/> }, { type: "measure", label: "Линейка · измерить изменение цены", icon: <Ruler size={21}/> }] as const).map(t => <button className={`rail-button ${tool === t.type ? "active" : ""}`} key={t.type} title={t.label} aria-label={t.label} onClick={() => { setTool(t.type); if (t.type !== "cursor") notify(t.label); }}>{t.icon}{t.type === "trend" && <span className="rail-corner"/>}</button>)}</div><span className="rail-divider"/><div className="rail-group"><button className={`rail-button ${magnet ? "active" : ""}`} onClick={() => setMagnet(!magnet)} title="Привязка перекрестия к свечам" aria-label="Привязка к свечам" aria-pressed={magnet}><Magnet size={21}/></button><button className={`rail-button ${locked ? "active" : ""}`} onClick={() => { setLocked(!locked); notify(locked ? "Рисование разблокировано" : "Рисование заблокировано"); }} title="Заблокировать рисование" aria-label="Заблокировать рисование" aria-pressed={locked}>{locked ? <LockKeyhole size={20}/> : <UnlockKeyhole size={20}/>}</button><button className="rail-button" onClick={() => setDrawingsVisible(!drawingsVisible)} title={drawingsVisible ? "Скрыть рисунки" : "Показать рисунки"} aria-label={drawingsVisible ? "Скрыть рисунки" : "Показать рисунки"}>{drawingsVisible ? <Eye size={21}/> : <EyeOff size={21}/>}</button><button className="rail-button danger-hover" onClick={clearDrawings} disabled={!currentDrawings.length} title="Удалить рисунки текущего инструмента" aria-label="Удалить рисунки"><Trash2 size={20}/></button></div><div className="rail-spacer"/><button className="rail-button help-rail-button" title="Помощь и горячие клавиши" aria-label="Помощь и горячие клавиши" onClick={() => openModal("help")}><CircleHelp size={21}/></button></aside>

      <section className="chart-panel" aria-label="График инструмента">
        <div className="chart-frame">
          <TradingChart candles={candles} symbol={settings.symbol} timeframe={settings.timeframe} indicators={settings.indicators} chartType={settings.chartType} showVolume={settings.showVolume} drawings={currentDrawings} tool={tool} magnet={magnet} locked={locked} drawingsVisible={drawingsVisible} logarithmic={logarithmic} apiRef={chartApi} onHover={setHover} onDraw={addDrawing} onMeasure={notify}/>
          <div className="chart-watermark" aria-hidden="true"><strong>{instrument.symbol.length < 7 ? instrument.symbol : instrument.name}</strong><span>MOEX TERMINAL</span></div>
          <div className="chart-heading"><div className="chart-asset-title"><AssetLogo instrument={instrument} size={24}/><button onClick={() => openModal("info")}>{instrument.name}</button><span className="chart-title-dot">·</span><span className="chart-tf-title">{timeframeLabel}</span><span className="chart-title-dot">·</span><span className="chart-exchange">MOEX</span><span className={`source-pill ${source}`} title={SOURCE_LABELS[source]}><i/>{source === "demo" ? "Демо" : source === "moex" ? "15 мин" : "T-Invest"}</span>{loading && <RefreshCw size={12} className="refresh-indicator"/>}</div><div className="ohlc-row"><span>ОТКР<span>{formatPrice(candle.open)}</span></span><span>МАКС<span>{formatPrice(candle.high)}</span></span><span>МИН<span>{formatPrice(candle.low)}</span></span><span>ЗАКР<span className={currentPriceChange >= 0 ? "positive" : "negative"}>{formatPrice(candle.close)}</span></span><span className={currentPriceChange >= 0 ? "positive ohlc-delta" : "negative ohlc-delta"}>{currentPriceChange >= 0 ? "+" : ""}{formatPrice(currentPriceChange)} ({formatChange(currentPriceChange / candle.open * 100)})</span></div>
            <div className="chart-indicator-legends">{settings.indicators.filter(i => i.enabled).map(i => { const values = calculateIndicator(hover ? candles.slice(0, candles.findIndex(c => c.time === hover.time) + 1) : candles, i.type, i.period); return <div className="chart-indicator-legend" key={i.id}><span className="legend-stroke" style={{ background: i.color }}/><span>{i.name} <span className="legend-parameters">{i.period} close</span></span><span className="legend-value" style={{ color: i.color }}>{values.length ? formatPrice(values[values.length - 1].value) : "—"}</span><button className="legend-action" aria-label={`Скрыть ${i.name}`} onClick={() => setSettings(s => ({ ...s, indicators: s.indicators.map(item => item.id === i.id ? { ...item, enabled: false } : item) }))}><Eye size={12}/></button><button className="legend-action" aria-label={`Удалить ${i.name}`} onClick={() => setSettings(s => ({ ...s, indicators: s.indicators.filter(item => item.id !== i.id) }))}><X size={12}/></button></div>; })}</div>
          </div>
          <div className="chart-currency">{instrument.kind === "index" ? "ПУНКТЫ" : "RUB"}<ChevronDown size={10}/></div>
          {settings.showVolume && <div className="volume-legend"><span className="volume-legend-color"/>Объём<span>{formatCompact(candle.volume)}</span></div>}
          <div className="chart-zoom"><button aria-label="Уменьшить масштаб" onClick={() => chartApi.current?.zoom(1.3)}><Minus size={14}/></button><button aria-label="Увеличить масштаб" onClick={() => chartApi.current?.zoom(.75)}><Plus size={14}/></button><span/><button aria-label="Показать весь график" onClick={() => { chartApi.current?.fit(); setActiveRange("Всё"); }}><Maximize2 size={13}/></button></div>
          {tool !== "cursor" && <div className="drawing-mode-badge"><span/>{tool === "horizontal" ? "Горизонтальный уровень" : tool === "trend" ? "Линия тренда" : "Измерение"}<button onClick={() => setTool("cursor")} aria-label="Завершить рисование"><X size={12}/></button></div>}
        </div>
        <div className="chart-bottom-toolbar"><div className="range-options">{RANGE_OPTIONS.map(range => <button className={activeRange === range.label ? "active" : ""} key={range.label} onClick={() => { setActiveRange(range.label); const days = range.days === -1 ? Math.ceil((Date.now() - Date.UTC(new Date().getUTCFullYear(), 0, 1)) / 86400000) : range.days; chartApi.current?.range(days); }}>{range.label}</button>)}</div><a className="chart-attribution" href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer" title="Графики от TradingView Lightweight Charts">TradingView<ArrowUpRight size={9}/></a><div className="chart-scale-options"><span className="chart-timezone">UTC+3</span><span className="mini-divider"/><button className={logarithmic ? "active" : ""} onClick={() => setLogarithmic(!logarithmic)}>лог</button><button className="auto-scale" onClick={() => { chartApi.current?.fit(); setActiveRange("Всё"); }}>авто</button></div></div>
      </section>

      <section className="instrument-panel" aria-label="Информация об инструменте"><div className="instrument-tabs"><button className={aboutTab === "overview" ? "active" : ""} onClick={() => setAboutTab("overview")}>Об инструменте</button><button className={aboutTab === "analysis" ? "active" : ""} onClick={() => setAboutTab("analysis")}>Технический анализ</button><button className={aboutTab === "indicators" ? "active" : ""} onClick={() => setAboutTab("indicators")}>Мои индикаторы<span className="tab-count">{settings.indicators.length}</span></button><button className="panel-expand-button" title="Подробнее об инструменте" aria-label="Подробнее об инструменте" onClick={() => openModal("info")}><ArrowUpRight size={17}/></button></div>
        {aboutTab === "overview" && <div className="instrument-overview"><div className="overview-heading"><AssetLogo instrument={instrument} size={38}/><div><h1>{instrument.name}<span>{instrument.kind === "index" ? "Биржевой индекс" : instrument.kind === "currency" ? "Валютная пара" : instrument.symbol === "SBERP" ? "Привилегированные акции" : "Обыкновенные акции"}</span></h1><p>{instrument.fullName} <span>·</span> {instrument.sector}</p></div><button className="instrument-link" onClick={() => openModal("info")}>MOEX: {instrument.symbol}<ArrowUpRight size={13}/></button></div><div className="instrument-metrics"><div><span>Пред. закрытие <Info size={11}/></span><strong>{formatPrice(previous.close)}<small>{instrument.kind === "index" ? "п." : "₽"}</small></strong></div><div><span>Открытие</span><strong>{formatPrice(last.open)}<small>{instrument.kind === "index" ? "п." : "₽"}</small></strong></div><div><span>Объём свечи</span><strong>{formatCompact(last.volume)}<small>{instrument.kind === "index" ? "ед." : "лотов"}</small></strong></div><div><span>Диапазон свечи</span><strong>{formatPrice(last.low)}<i>–</i>{formatPrice(last.high)}</strong></div></div></div>}
        {aboutTab === "analysis" && <div className="technical-content"><div className="technical-summary"><span>СВОДКА ИНДИКАТОРОВ</span><strong className={analysis.score >= 2 ? "positive" : analysis.score === 1 ? "muted" : "negative"}>{analysis.score >= 2 ? "Восходящий тренд" : analysis.score === 1 ? "Нейтрально" : "Нисходящий тренд"}</strong><div className="sentiment-scale"><i/><i/><i/><i/><i/><b style={{ left: `${14 + analysis.score * 24}%` }}/></div><small>Расчётная оценка, не рекомендация</small></div><div className="technical-metrics"><div><span>EMA 20</span><strong>{formatPrice(analysis.ema)}</strong><small className={last.close > analysis.ema ? "positive" : "negative"}>{last.close > analysis.ema ? "Цена выше средней" : "Цена ниже средней"}</small></div><div><span>SMA 50</span><strong>{formatPrice(analysis.sma)}</strong><small className={last.close > analysis.sma ? "positive" : "negative"}>{last.close > analysis.sma ? "Цена выше средней" : "Цена ниже средней"}</small></div><div><span>RSI 14</span><strong>{formatPrice(analysis.rsi)}</strong><small>{analysis.rsi > 70 ? "Перекупленность" : analysis.rsi < 30 ? "Перепроданность" : "Нейтральная зона"}</small></div></div></div>}
        {aboutTab === "indicators" && <div className="my-indicators-content"><div className="custom-indicator-intro"><span className="custom-code-icon"><Code2 size={26}/></span><div><h2>Ваши идеи. Ваши индикаторы.</h2><p>Добавьте собственную формулу и посмотрите на рынок по-новому.</p></div><button className="primary-button" onClick={() => openModal("editor")}><Plus size={15}/>Создать индикатор</button></div><div className="indicator-chips">{settings.indicators.map(i => <button className={!i.enabled ? "disabled-chip" : ""} key={i.id} onClick={() => setSettings(s => ({ ...s, indicators: s.indicators.map(item => item.id === i.id ? { ...item, enabled: !item.enabled } : item) }))}><span style={{ background: i.color }}/>{i.name} {i.period}{i.enabled ? <Eye size={12}/> : <EyeOff size={12}/>}</button>)}<button className="manage-indicators" onClick={() => openModal("indicators")}><SlidersHorizontal size={12}/>Управление</button></div></div>}
      </section>

      <aside className="watchlist-sidebar" aria-label="Список наблюдения"><div className="watchlist-panel"><div className="watchlist-heading"><h2>Список наблюдения</h2><ChevronDown size={13}/><div className="watch-heading-actions"><div className="dropdown-anchor" data-popover><button className="icon-button" aria-label="Меню списка наблюдения" onClick={() => togglePopover("watchlist")}><MoreHorizontal size={18}/></button>{popover === "watchlist" && <div className="dropdown-menu watchlist-dropdown"><button onClick={() => openModal("add")}><Plus size={15}/>Добавить инструмент</button><button onClick={exportWatchlist}><Download size={15}/>Экспортировать CSV</button><button onClick={() => { setSettings(s => ({ ...s, watchlist: [...DEFAULT_SETTINGS.watchlist] })); setPopover(null); notify("Восстановлен исходный список инструментов"); }}><RefreshCw size={15}/>Восстановить список</button></div>}</div><button className="icon-button watchlist-add" title="Добавить инструмент" aria-label="Добавить инструмент в список" onClick={() => openModal("add")}><Plus size={19}/></button></div></div>
        <div className="watchlist-tabs">{([{ value: "stock", label: "Акции" }, { value: "index", label: "Индексы" }, { value: "currency", label: "Валюты" }] as const).map(t => <button className={watchKind === t.value ? "active" : ""} key={t.value} onClick={() => setWatchKind(t.value)}>{t.label}{t.value === "stock" && <span>{settings.watchlist.filter(s => getInstrument(s).kind === "stock").length}</span>}</button>)}</div>
        <div className="watch-table-heading"><span>Инструмент</span><span>Цена, ₽</span><button onClick={() => setSortWatch(s => s === "none" ? "down" : s === "down" ? "up" : "none")}>Изм., %{sortWatch !== "none" && <ArrowDown size={10} style={{ transform: sortWatch === "up" ? "rotate(180deg)" : "none" }}/>}</button></div>
        <div className="watchlist-rows">{visibleInstruments.length ? visibleInstruments.map(i => { const q = quotes.find(q => q.symbol === i.symbol) ?? demoQuote(i); return <button className={`watch-row ${settings.symbol === i.symbol ? "selected" : ""}`} key={i.symbol} onClick={() => selectSymbol(i.symbol)} title={`${i.fullName} · ${q.source === "demo" ? "демонстрационная котировка" : SOURCE_LABELS[q.source]}`}><span className="watch-instrument"><AssetLogo instrument={i} size={27}/><span><strong>{i.kind === "currency" ? i.name.split(" / ").map(n => n === "Юань" ? "CNY" : n === "Рубль" ? "RUB" : n === "Доллар" ? "USD" : "EUR").join("/") : i.symbol}{q.source === "demo" && <em className="watch-demo-tag" title="Демонстрационная котировка">демо</em>}</strong><small>{i.name}</small></span></span><span className="watch-price">{formatPrice(q.price, i.kind === "currency" ? 3 : 2)}</span><span className={`watch-change ${q.change >= 0 ? "positive" : "negative"}`}>{formatChange(q.change)}</span></button>; }) : <div className="watchlist-empty"><Star size={24}/><strong>Ваш список пока пуст</strong><button onClick={() => openModal("add")}>Добавить инструмент<Plus size={13}/></button></div>}</div><div className="watchlist-footnote"><span>{visibleInstruments.length} инструментов</span><span><span className="small-status-dot"/>{quotes.every(q => q.source === "demo") ? "Демо-котировки" : "Обновление 30 с"}</span></div></div>
        <div className="quote-panel"><div className="quote-panel-heading"><AssetLogo instrument={instrument} size={27}/><div><strong>{instrument.symbol.length > 9 ? instrument.name : instrument.symbol}</strong><span>{instrument.name}</span></div><button className={`icon-button quote-star ${settings.watchlist.includes(settings.symbol) ? "is-starred" : ""}`} onClick={() => toggleWatch(settings.symbol)} title="В список наблюдения" aria-label="Добавить или убрать из списка наблюдения"><Star size={16} fill={settings.watchlist.includes(settings.symbol) ? "currentColor" : "none"}/></button><button className="icon-button" aria-label="Информация об инструменте" onClick={() => openModal("info")}><MoreHorizontal size={18}/></button></div><div className="quote-current-price">{formatPrice(quote.price)}<span>{instrument.kind === "index" ? "п." : "RUB"}</span></div><div className={`quote-current-change ${quote.change >= 0 ? "positive" : "negative"}`}><span>{quote.absolute >= 0 ? "+" : "−"}{formatPrice(Math.abs(quote.absolute))}</span><span>({formatChange(quote.change)})</span><span className="quote-period">за день</span></div><div className="daily-range"><div className="range-track"><span style={{ left: `${Math.min(96, Math.max(4, (quote.price - last.low) / (last.high - last.low || 1) * 100))}%` }}/></div><div className="range-labels"><span>{formatPrice(last.low)}<small>Мин. свечи</small></span><span>{formatPrice(last.high)}<small>Макс. свечи</small></span></div></div></div>
      </aside>

      <aside className="utility-rail" aria-label="Панели терминала"><button className={`utility-button ${showWatchlist ? "active" : ""}`} title="Список наблюдения" aria-label="Показать или скрыть список наблюдения" onClick={() => setShowWatchlist(!showWatchlist)}><List size={20}/></button><button className="utility-button" title="Индикаторы" aria-label="Библиотека индикаторов" onClick={() => openModal("indicators")}><Layers3 size={19}/></button><button className="utility-button" title="Уведомления" aria-label="Открыть уведомления" onClick={() => togglePopover("notifications")}><Bell size={19}/></button><div className="utility-history-anchor" data-popover><button className={`utility-button ${popover === "history" ? "active" : ""}`} title="Недавние инструменты" aria-label="Недавние инструменты" onClick={() => togglePopover("history")}><History size={19}/></button>{popover === "history" && <div className="dropdown-menu history-menu"><div className="dropdown-title">Недавно открытые</div>{recent.map(symbol => { const i = getInstrument(symbol); return <button key={symbol} onClick={() => { selectSymbol(symbol); setPopover(null); }}><AssetLogo instrument={i} size={22}/><span>{i.name}</span><small>{symbol}</small></button>; })}</div>}</div><span className="utility-divider"/><button className="utility-button" title="Скринер акций" aria-label="Открыть скринер акций" onClick={() => openModal("screener")}><SlidersHorizontal size={19}/></button><div className="rail-spacer"/><button className="utility-button utility-help" title="О терминале" aria-label="О терминале" onClick={() => openModal("help")}><CircleHelp size={19}/></button></aside>
    </div>

    <footer className="statusbar"><div className="connection-status"><span className={`connection-dot ${source === "demo" ? "demo" : ""}`}/><button onClick={refreshData} title="Нажмите, чтобы обновить подключение">{loading ? "Подключение к данным…" : source === "demo" ? "Демо-режим" : source === "moex" ? "MOEX ISS · 15 мин" : "Т-Инвест API"}</button><span className="status-divider"/><span className="footer-readonly"><ShieldCheck size={11}/>Только чтение</span></div><span className="status-disclaimer">{source === "demo" ? "Демонстрационные данные · не являются биржевыми котировками" : "Не является индивидуальной инвестиционной рекомендацией"}</span><div className="statusbar-right"><span className="saved-status"><CloudCheck size={12}/>{saveState === "saving" ? "Сохранение…" : saveState === "local" ? "Сохранено локально" : "Все изменения сохранены"}</span><span className="status-divider"/><time>{clock}<span> (UTC+3)</span></time><span className="connection-bars"><i/><i/><i/><i/></span></div></footer>

    {toast && <div className="toast" role="status"><Check size={16}/><span>{toast}</span><button aria-label="Закрыть уведомление" onClick={() => setToast("")}><X size={14}/></button></div>}
    {(modal === "search" || modal === "add") && <SearchDialog onClose={closeModal} onSelect={symbol => { if (modal === "add" && !settings.watchlist.includes(symbol)) toggleWatch(symbol); selectSymbol(symbol); }} quotes={quotes} watchlist={settings.watchlist} onToggle={toggleWatch} addMode={modal === "add"}/>}
    {(modal === "indicators" || modal === "editor") && <IndicatorDialog onClose={closeModal} indicators={settings.indicators} onChange={indicators => setSettings(s => ({ ...s, indicators }))} initialTab={modal === "editor" ? "editor" : "library"}/>}
    {(modal === "market" || modal === "screener") && <MarketDialog onClose={closeModal} onSelect={selectSymbol} quotes={quotes} screener={modal === "screener"}/>}
    {modal === "settings" && <SettingsDialog onClose={closeModal} settings={settings} onChange={setSettings} onReset={() => { setSettings(structuredClone(DEFAULT_SETTINGS)); setLogarithmic(false); setTool("cursor"); notify("Рабочее пространство сброшено"); }} source={SOURCE_LABELS[source]} onRefresh={refreshData}/>}
    {modal === "info" && <InstrumentDialog instrument={instrument} quote={quote} onClose={closeModal}/>}
    {modal === "help" && <HelpDialog onClose={closeModal}/>}
  </main>;
}
