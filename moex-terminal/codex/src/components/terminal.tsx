"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowDown, Wallet, ArrowUpRight, Bell, Camera, CandlestickChart, ChartArea, ChartLine, Check, ChevronDown, CircleHelp, CloudCheck, Code2, Crosshair, Download, Eye, EyeOff, FolderOpen, History, Info, Layers3, List, LockKeyhole, Magnet, Maximize2, Minimize2, Minus, MoreHorizontal, Plus, RefreshCw, Ruler, Search, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Star, Trash2, TrendingUp, Undo2, UnlockKeyhole, Wifi, WifiOff, X } from "lucide-react";
import { DEFAULT_SETTINGS, INSTRUMENTS, TIMEFRAMES, demoQuote, formatChange, formatCompact, formatMoney, formatPrice, generateCandles, getInstrument, type Candle, type DataSource, type Drawing, type InstrumentKind, type Quote, type WorkspaceSettings } from "@/lib/market";
import { AssetLogo, HelpDialog, InstrumentDialog, MarketDialog, SearchDialog, SettingsDialog } from "./dialogs";
import { AccountBar, AccountDialog, OrderTicket, PositionTable, useSnapshot } from "./trading-panel";
import { applyProtection, closePosition, emptyAccount, openPosition, sanitizeAccount, totalReturn, type Account, type Mark, type Side } from "@/lib/broker";
import SmcPanel from "./smc-panel";
import type { ChartHandle, DrawingTool } from "./trading-chart";
import { computeSmc, sanitizeSmcSettings, type SmcOverlay } from "@/lib/smc";

/** Убирает дубли и неизвестные тикеры из списка наблюдения, сохраняя порядок. */
function withCleanWatchlist(settings: WorkspaceSettings): WorkspaceSettings {
  const seen = new Set<string>();
  const watchlist = (Array.isArray(settings.watchlist) ? settings.watchlist : [])
    .filter(symbol => INSTRUMENTS.some(i => i.symbol === symbol))
    .filter(symbol => (seen.has(symbol) ? false : (seen.add(symbol), true)));
  return { ...settings, watchlist: watchlist.length ? watchlist : DEFAULT_SETTINGS.watchlist };
}

const TradingChart = dynamic(() => import("./trading-chart"), { ssr: false, loading: () => <div className="chart-initializing"><span className="loading-spinner"/>Загрузка графика…</div> });
const EMPTY_DRAWINGS: Drawing[] = [];
type ModalName = "search" | "add" | "market" | "screener" | "settings" | "info" | "help" | "account" | null;
type Popover = "chartType" | "workspace" | "notifications" | "watchlist" | "profile" | "history" | null;
const RANGE_OPTIONS = [{ label: "1Д", days: 1 }, { label: "5Д", days: 5 }, { label: "1М", days: 30 }, { label: "3М", days: 90 }, { label: "6М", days: 180 }, { label: "YTD", days: -1 }, { label: "1Г", days: 365 }, { label: "Все", days: 0 }];
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
  const [aboutTab, setAboutTab] = useState<"overview" | "analysis" | "trading">("overview");
  const [account, setAccount] = useState<Account>(() => emptyAccount());
  const [accountLoaded, setAccountLoaded] = useState(false);
  const [tradeMarks, setTradeMarks] = useState<Mark[]>([]);
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
  const [smcPanel, setSmcPanel] = useState(false);
  const chartApi = useRef<ChartHandle | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const smcSettings = useMemo(() => sanitizeSmcSettings(settings.smc), [settings.smc]);
  const smc = useMemo<SmcOverlay>(() => computeSmc(candles, smcSettings, settings.timeframe), [candles, smcSettings, settings.timeframe]);
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
  const prices = useMemo<Record<string, number>>(() => {
    const map: Record<string, number> = {};
    for (const q of quotes) if (q.source !== "demo") map[q.symbol] = q.price;
    map[settings.symbol] = last.close;
    return map;
  }, [quotes, settings.symbol, last.close]);
  const snapshot = useSnapshot(account, prices);

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
        if (!cancelled && data.settings) { setSettings(withCleanWatchlist(data.settings)); setRecent([data.settings.symbol]); }
      } catch {
        try {
          const stored = localStorage.getItem("moex-workspace");
          if (stored && !cancelled) {
            const parsed = JSON.parse(stored);
            // Старые сохранения могли содержать удалённые индикаторы и дубли в списке наблюдения.
            if (INSTRUMENTS.some(i => i.symbol === parsed.symbol)) setSettings(withCleanWatchlist({ ...DEFAULT_SETTINGS, ...parsed }));
          }
        } catch { /* Ignore corrupted browser storage. */ }
        if (!cancelled) setSaveState("local");
      } finally { if (!cancelled) setLoaded(true); }
    };
    void load();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    try { const stored = localStorage.getItem("moex-account"); if (stored) setAccount(sanitizeAccount(JSON.parse(stored))); } catch { /* Corrupted storage is ignored. */ }
    setAccountLoaded(true);
  }, []);

  useEffect(() => {
    if (!accountLoaded) return;
    try { localStorage.setItem("moex-account", JSON.stringify(account)); } catch { /* Browser storage may be full. */ }
  }, [account, accountLoaded]);

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
    // На бесплатном Render каждый запрос — это трафик и работа инстанса.
    // В скрытой вкладке опрос стоит, а автообновление идёт только на младших
    // таймфреймах: на 1ч–1Н закрытая свеча за 30 секунд не меняется.
    const fast = ["1m", "5m", "15m"].includes(settings.timeframe);
    const timer = setInterval(() => { if (!document.hidden && fast) void update(); }, 30000);
    const onVisible = () => { if (!document.hidden) void update(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [settings.symbol, settings.timeframe, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    const update = async () => { try { const response = await fetch("/api/market?mode=quotes", { signal: controller.signal }); if (response.ok) { const data = await response.json(); if (!controller.signal.aborted) setQuotes(data.quotes); } } catch { /* Demo quotes are explicitly labelled. */ } };
    void update();
    const timer = setInterval(() => { if (!document.hidden) void update(); }, 30000);
    const onVisible = () => { if (!document.hidden) void update(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
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
  const toggleWatch = useCallback((symbol: string) => setSettings(s => ({ ...s, watchlist: s.watchlist.includes(symbol) ? s.watchlist.filter(i => i !== symbol) : [...new Set([...s.watchlist, symbol])] })), []);
  const addDrawing = useCallback((drawing: Drawing) => { setSettings(s => ({ ...s, drawings: { ...s.drawings, [s.symbol]: [...(s.drawings[s.symbol] ?? []), drawing].slice(-40) } })); }, []);
  const undoDrawing = () => { setSettings(s => ({ ...s, drawings: { ...s.drawings, [s.symbol]: (s.drawings[s.symbol] ?? []).slice(0, -1) } })); };
  const clearDrawings = () => { setSettings(s => ({ ...s, drawings: { ...s.drawings, [s.symbol]: [] } })); notify("Рисунки на текущем инструменте удалены"); };
  const togglePopover = (name: Popover) => setPopover(p => p === name ? null : name);
  const openModal = (name: ModalName) => { setModal(name); setPopover(null); };
  const download = (name: string, content: string, type: string) => { const url = URL.createObjectURL(new Blob([content], { type })); const link = document.createElement("a"); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
  // История сделок хранится только в браузере, поэтому её можно выгрузить в CSV.
  const exportTrades = () => {
    if (!account.trades.length) { notify("История сделок пуста"); return; }
    const head = "\uFEFFЗакрыта;Инструмент;Направление;Лоты;Вход;Выход;Результат до комиссии;Комиссия;Итог;Причина";
    const rows = account.trades.map(trade => [
      new Date(trade.closed).toLocaleString("ru-RU"),
      trade.symbol,
      trade.side === "long" ? "Лонг" : "Шорт",
      trade.lots,
      formatPrice(trade.entry),
      formatPrice(trade.exit),
      formatMoney(trade.pnl),
      formatMoney(trade.fee),
      formatMoney(trade.pnl - trade.fee),
      trade.reason === "take" ? "тейк-профит" : trade.reason === "stop" ? "стоп-лосс" : "вручную",
    ].join(";"));
    download(`MOEX-trades-${new Date().toISOString().slice(0, 10)}.csv`, [head, ...rows].join("\n"), "text/csv;charset=utf-8");
    notify(`История сделок выгружена: ${account.trades.length}`);
  };

  const exportWatchlist = () => { const content = "\uFEFFТикер;Название;Цена;Изменение, %;Источник\n" + settings.watchlist.map(symbol => { const i = getInstrument(symbol), q = quotes.find(q => q.symbol === symbol) ?? demoQuote(i); return `${symbol};${i.name};${q.price};${q.change};${SOURCE_LABELS[q.source]}`; }).join("\n"); download("MOEX-watchlist.csv", content, "text/csv;charset=utf-8"); setPopover(null); notify("Список наблюдения экспортирован"); };
  const refreshData = () => { setRefresh(r => r + 1); notify("Запрашиваем свежие данные у провайдера"); };
  const currentPriceChange = candle.close - candle.open;
  const symbolLabel = settings.symbol === "CNYRUB_TOM" ? "CNY/RUB" : settings.symbol;
  const displayCurrency = instrument.kind === "index" ? "пункты" : "RUB";

  const recordMark = (side: Side, price: number) => setTradeMarks(marks => [...marks.slice(-40), { side, price, time: Date.now() }]);

  const submitOrder = useCallback((order: { side: Side; lots: number; amount?: number; take?: number; stop?: number }) => {
    if (!order.lots) {
      // lots = 0 — это запрос на закрытие текущей позиции по инструменту.
      const position = account.positions.find(p => p.symbol === settings.symbol);
      if (!position) return;
      const result = closePosition(account, position.id, last.close);
      if (result.ok) { setAccount(result.account); recordMark(result.trade?.side === "long" ? "short" : "long", last.close); notify(`Позиция ${position.symbol} закрыта: ${result.trade ? (result.trade.pnl >= 0 ? "+" : "−") + formatMoney(Math.abs(result.trade.pnl - result.trade.fee)) + " ₽" : ""}`); }
      return;
    }
    const result = openPosition(account, { symbol: settings.symbol, side: order.side, lots: order.lots, amount: order.amount, price: last.close, take: order.take, stop: order.stop, slippage: 0.0002 });
    if (!result.ok) { notify(result.error); return; }
    setAccount(result.account);
    recordMark(order.side, last.close);
    notify(`${order.side === "long" ? "Куплено" : "Продано"} ${result.position.lots} лот. ${settings.symbol} по ${formatPrice(last.close)} ₽`);
  }, [account, settings.symbol, last.close]);

  const closeById = useCallback((id: string) => {
    const position = account.positions.find(p => p.id === id);
    const price = position ? prices[position.symbol] ?? position.entry : 0;
    const result = closePosition(account, id, price);
    if (result.ok) { setAccount(result.account); if (result.trade) recordMark(result.trade.side === "long" ? "short" : "long", price); notify(result.trade ? `Сделка закрыта: ${(result.trade.pnl - result.trade.fee >= 0 ? "+" : "−") + formatMoney(Math.abs(result.trade.pnl - result.trade.fee))} ₽` : "Позиция закрыта"); }
  }, [account, prices]);

  // Тейк-профит и стоп-лосс проверяются по последней свече выбранного инструмента и по котировкам.
  useEffect(() => {
    if (!account.positions.length) return;
    const candlesBySymbol: Record<string, { high: number; low: number }> = {};
    for (const position of account.positions) {
      if (position.symbol === settings.symbol && last) candlesBySymbol[position.symbol] = { high: last.high, low: last.low };
      else { const q = quotes.find(item => item.symbol === position.symbol && item.source !== "demo"); if (q) candlesBySymbol[position.symbol] = { high: Math.max(q.price, q.high), low: Math.min(q.price, q.low) }; }
    }
    const result = applyProtection(account, candlesBySymbol);
    if (!result.closed.length) return;
    setAccount(result.account);
    for (const trade of result.closed) notify(`${trade.reason === "take" ? "Тейк-профит" : "Стоп-лосс"} ${trade.symbol}: ${(trade.pnl - trade.fee >= 0 ? "+" : "−") + formatMoney(Math.abs(trade.pnl - trade.fee))} ₽`);
  }, [account, quotes, last, settings.symbol]);

  return <main className={`terminal-shell ${focusMode ? "focus-mode" : ""}`}>
    <header className="topbar">
      <a className="brand" href="/" aria-label="MOEX Terminal — главная"><span className="brand-mark"><svg viewBox="0 0 28 28" fill="none"><path d="M6 21V9l7 7L22 5v16" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"/></svg></span><span className="brand-word">moex<span>.</span></span><span className="brand-product">terminal</span></a>
      <nav className="main-nav" aria-label="Основная навигация"><button className={!modal || !["market", "screener"].includes(modal) ? "active" : ""} onClick={() => setModal(null)}>График</button><button className={modal === "market" ? "active" : ""} onClick={() => openModal("market")}>Обзор рынка</button><button className={modal === "screener" ? "active" : ""} onClick={() => openModal("screener")}>Скринер<span className="new-dot"/></button></nav>
      <div className="header-actions">
        <button className="global-search" onClick={() => openModal("search")}><Search size={15}/><span>Поиск (Ctrl+K)</span><kbd>Ctrl K</kbd></button>
        <span className="header-divider"/>
        <span className="read-only"><ShieldCheck size={13}/><span>Только чтение</span></span>
        <div className="dropdown-anchor" data-popover><button className={`icon-button notification-button ${popover === "notifications" ? "selected" : ""}`} aria-label="Уведомления" onClick={() => togglePopover("notifications")}><Bell size={18}/><i/></button>{popover === "notifications" && <div className="dropdown-menu notifications-menu"><div className="dropdown-title">Уведомления<span>3</span></div><div className="notification-item"><span className={`notification-item-icon ${source === "demo" ? "amber" : "green"}`}>{source === "demo" ? <WifiOff size={15}/> : <Wifi size={15}/>}</span><div><strong>{loading ? "Подключение к рынку" : source === "demo" ? "Демонстрационный режим" : "Данные подключены"}</strong><p>{source === "demo" ? "Т-Инвест и MOEX не ответили — на графике тестовые цены. Проверьте токен и нажмите «Повторить запрос»." : SOURCE_LABELS[source]}</p></div></div><div className="notification-item"><span className="notification-item-icon"><CloudCheck size={15}/></span><div><strong>Пространство сохранено</strong><p>{saveState === "local" ? "Резервная копия в браузере. Сервер недоступен." : "Список, индикаторы и рисунки сохраняются автоматически."}</p></div></div><div className="notification-item"><span className="notification-item-icon"><ShieldCheck size={15}/></span><div><strong>Безопасное подключение</strong><p>Торговые операции отключены.</p></div></div><button className="dropdown-footer" onClick={() => { refreshData(); notify(source === "demo" ? "Повторный запрос к Т-Инвест…" : "Данные обновляются"); }}><RefreshCw size={13}/>{source === "demo" ? "Повторить запрос" : "Проверить подключение"}</button></div>}</div>
        <div className="dropdown-anchor" data-popover><button className="avatar" onClick={() => togglePopover("profile")} aria-label="Профиль">АК<span/></button>{popover === "profile" && <div className="dropdown-menu profile-menu"><div className="profile-heading"><strong>Моё пространство</strong><span>Персональный терминал</span></div><button onClick={() => openModal("settings")}><Settings2 size={15}/>Настройки</button><button onClick={() => openModal("help")}><CircleHelp size={15}/>Помощь и горячие клавиши</button><div className="dropdown-note">Настройки привязаны к браузеру и сохраняются в PostgreSQL.</div></div>}</div>
      </div>
    </header>

    <div className="chart-toolbar">
      <button className="symbol-select" onClick={() => openModal("search")}><Search size={15}/><AssetLogo instrument={instrument} size={20}/><strong>{symbolLabel}</strong><ChevronDown size={12}/></button>
      <span className="toolbar-divider"/>
      <div className="timeframes" aria-label="Интервал">{TIMEFRAMES.map(t => <button className={settings.timeframe === t.value ? "active" : ""} key={t.value} onClick={() => { setSettings(s => ({ ...s, timeframe: t.value })); setActiveRange(""); }}>{t.label}</button>)}</div>
      <span className="toolbar-divider"/>
      <div className="dropdown-anchor" data-popover><button className="chart-style-button" onClick={() => togglePopover("chartType")} title="Тип графика" aria-label="Тип графика">{settings.chartType === "candles" ? <CandlestickChart size={18}/> : settings.chartType === "line" ? <ChartLine size={18}/> : <ChartArea size={18}/>}<ChevronDown size={10}/></button>{popover === "chartType" && <div className="dropdown-menu chart-type-menu">{([{ type: "candles", label: "Бары", icon: <CandlestickChart size={16}/> }, { type: "line", label: "Линия", icon: <ChartLine size={16}/> }, { type: "area", label: "Область", icon: <ChartArea size={16}/> }] as const).map(t => <button className={settings.chartType === t.type ? "active" : ""} key={t.type} onClick={() => { setSettings(s => ({ ...s, chartType: t.type })); setPopover(null); }}>{t.icon}{t.label}{settings.chartType === t.type && <Check size={14} style={{ marginLeft: "auto" }}/>}</button>)}</div>}</div>
      <span className="toolbar-divider"/>
      <button className={`toolbar-text-button smc-toolbar-button ${smcPanel ? "selected" : ""}`} onClick={() => setSmcPanel(panel => !panel)} title="SMC Pro: Order Blocks, FVG, структура, A+ зоны" aria-pressed={smcPanel}><Sparkles size={16}/><span>SMC Pro</span><span className="count-badge">{[smc.stats.obCount + smc.stats.internalObCount, smc.stats.fvgCount, smc.stats.levels.length].filter(Boolean).join("+")}</span></button>
      <button className="toolbar-text-button account-toolbar-button" onClick={() => openModal("account")} title="Виртуальный счёт 10 000 000 ₽"><Wallet size={16}/><span>{formatMoney(snapshot.equity)} ₽</span><em className={totalReturn(snapshot) >= 0 ? "positive" : "negative"}>{totalReturn(snapshot) >= 0 ? "+" : "−"}{formatMoney(Math.abs(totalReturn(snapshot)))}%</em></button>
      <span className="toolbar-divider"/>
      <div className="dropdown-anchor" data-popover><button className={`icon-button ${magnet ? "selected" : ""}`} title="Магнит к ценам" aria-label="Магнит" onClick={() => setMagnet(!magnet)}><Magnet size={16}/></button></div>
      <button className={`icon-button ${locked ? "selected" : ""}`} title={locked ? "Разблокировать рисунки" : "Заблокировать рисунки"} aria-label="Блокировка рисунков" onClick={() => setLocked(!locked)}>{locked ? <LockKeyhole size={16}/> : <UnlockKeyhole size={16}/>}</button>
      <button className={`icon-button ${!drawingsVisible ? "selected" : ""}`} title="Показать / скрыть рисунки" aria-label="Видимость рисунков" onClick={() => setDrawingsVisible(!drawingsVisible)}>{drawingsVisible ? <Eye size={16}/> : <EyeOff size={16}/>}</button>
      <button className="icon-button" disabled={!currentDrawings.length} onClick={undoDrawing} title="Удалить последний рисунок" aria-label="Отменить рисунок"><Undo2 size={16}/></button>
      <button className="icon-button" disabled={!currentDrawings.length} onClick={clearDrawings} title="Удалить все рисунки" aria-label="Удалить рисунки"><Trash2 size={16}/></button>
      <div className="toolbar-spacer"/>
      <div className="dropdown-anchor workspace-anchor" data-popover><button className="workspace-button" onClick={() => togglePopover("workspace")}><FolderOpen size={14}/><span>Основной график</span><ChevronDown size={10}/><CloudCheck className={saveState === "saving" ? "saving-pulse" : "workspace-cloud"} size={15}/></button>{popover === "workspace" && <div className="dropdown-menu workspace-menu"><div className="dropdown-title">Рабочее пространство</div><button className="active" onClick={() => { setPopover(null); notify("Открыто основное рабочее пространство"); }}><Check size={14}/>Основной график</button><button onClick={() => { download("moex-workspace.json", JSON.stringify(settings, null, 2), "application/json"); setPopover(null); }}><Download size={14}/>Экспорт настроек</button><button onClick={() => openModal("settings")}><Settings2 size={14}/>Настройки пространства</button><div className="dropdown-note">{saveState === "saved" ? "Все изменения сохранены" : saveState === "saving" ? "Сохраняем изменения…" : "Сохранено локально в браузере"}</div></div>}</div>
      <span className="toolbar-divider"/>
      <button className="icon-button camera-button" title="Снимок графика" aria-label="Снимок графика" onClick={() => chartApi.current?.screenshot()}><Camera size={17}/></button>
      <button className={`icon-button ${focusMode ? "selected" : ""}`} title="Полноэкранный режим" aria-label="Полноэкранный режим" onClick={() => setFocusMode(!focusMode)}>{focusMode ? <Minimize2 size={16}/> : <Maximize2 size={16}/>}</button>
      <button className="icon-button" title="Свойства графика" aria-label="Свойства графика" onClick={() => openModal("settings")}><Settings2 size={17}/></button>
    </div>

    <div className={`workspace-grid ${!showWatchlist || focusMode ? "watchlist-hidden" : ""}`}>
      <aside className="drawing-rail" aria-label="Панель инструментов рисования">
        <div className="rail-group">
          <button className={`rail-button ${tool === "cursor" ? "active" : ""}`} title="Курсор" aria-label="Курсор" onClick={() => setTool("cursor")}><Crosshair size={18}/><span/></button>
          <button className={`rail-button ${tool === "trend" ? "active" : ""}`} title="Линия тренда" aria-label="Линия тренда" onClick={() => setTool("trend")}><TrendingUp size={18}/><span/></button>
          <button className={`rail-button ${tool === "horizontal" ? "active" : ""}`} title="Горизонтальная линия" aria-label="Горизонтальная линия" onClick={() => setTool("horizontal")}><Minus size={18}/><span/></button>
          <button className={`rail-button ${tool === "measure" ? "active" : ""}`} title="Линейка" aria-label="Линейка" onClick={() => setTool("measure")}><Ruler size={18}/><span/></button>
          <span className="rail-divider"/>
          <button className={`rail-button ${magnet ? "active" : ""}`} title="Магнит к ценам" aria-label="Магнит" onClick={() => setMagnet(!magnet)}><Magnet size={18}/></button>
          <button className={`rail-button ${locked ? "active" : ""}`} title={locked ? "Разблокировать рисунки" : "Заблокировать рисунки"} aria-label="Блокировка" onClick={() => setLocked(!locked)}>{locked ? <LockKeyhole size={18}/> : <UnlockKeyhole size={18}/>}</button>
          <button className={`rail-button ${drawingsVisible ? "" : "active"}`} title="Скрыть / показать рисунки" aria-label="Видимость рисунков" onClick={() => setDrawingsVisible(!drawingsVisible)}>{drawingsVisible ? <Eye size={18}/> : <EyeOff size={18}/>}</button>
          <button className="rail-button" title="Удалить все рисунки" aria-label="Удалить рисунки" onClick={clearDrawings}><Trash2 size={18}/></button>
        </div>
        <span className="rail-spacer"/>
        <div className="rail-corner"><button className="help-rail-button" title="Помощь" aria-label="Помощь" onClick={() => openModal("help")}><CircleHelp size={17}/></button></div>
      </aside>

      <section className="chart-panel" aria-label="График инструмента">
        <div className="chart-frame">
          <TradingChart candles={candles} symbol={settings.symbol} timeframe={settings.timeframe} chartType={settings.chartType} showVolume={settings.showVolume} drawings={currentDrawings} tool={tool} magnet={magnet} locked={locked} drawingsVisible={drawingsVisible} logarithmic={logarithmic} smc={smc} apiRef={chartApi} onHover={setHover} onDraw={addDrawing} onMeasure={notify}/>
          <div className="chart-watermark" aria-hidden="true"><strong>{instrument.symbol.length < 7 ? instrument.symbol : instrument.name}</strong><span>MOEX TERMINAL</span></div>
          <div className="chart-heading">
            <div className="chart-asset-title"><AssetLogo instrument={instrument} size={22}/><button onClick={() => openModal("info")}>{instrument.name}</button><span className="chart-title-dot">·</span><span className="chart-tf-title">{timeframeLabel}</span><span className="chart-title-dot">·</span><span className="chart-exchange">MOEX</span><span className={`source-pill ${source}`} title={SOURCE_LABELS[source]}><i/>{source === "demo" ? "Демо" : source === "moex" ? "15 мин" : "T-Invest"}</span>{loading && <RefreshCw size={11} className="refresh-indicator"/>}</div>
            <div className="ohlc-row"><span>ОТКР<span>{formatPrice(candle.open)}</span></span><span>МАКС<span>{formatPrice(candle.high)}</span></span><span>МИН<span>{formatPrice(candle.low)}</span></span><span>ЗАКР<span className={currentPriceChange >= 0 ? "positive" : "negative"}>{formatPrice(candle.close)}</span></span><span className={currentPriceChange >= 0 ? "positive ohlc-delta" : "negative ohlc-delta"}>{currentPriceChange >= 0 ? "+" : ""}{formatPrice(currentPriceChange)} ({formatChange(currentPriceChange / candle.open * 100)})</span></div>
            <div className="chart-indicator-legends">{smcSettings.enabled && <div className="chart-indicator-legend smc-legend"><span className="legend-stroke" style={{ background: "#ffd400" }}/><span>SMC Pro</span><span className="legend-parameters">{smc.stats.bias === 1 ? "бычья" : smc.stats.bias === -1 ? "медвежья" : "нейтр."}{smc.stats.support != null ? ` · подд. ${formatPrice(smc.stats.support)}` : ""}{smc.stats.resistance != null ? ` · сопр. ${formatPrice(smc.stats.resistance)}` : ""}</span><button className="legend-action" aria-label="Настройки SMC Pro" onClick={() => setSmcPanel(true)}><SlidersHorizontal size={11}/></button></div>}</div>
          </div>
          <div className="chart-currency">{displayCurrency.toUpperCase()}<ChevronDown size={9}/></div>
          {settings.showVolume && <div className="volume-legend"><span className="volume-legend-color"/>Объём<span>{formatCompact(candle.volume)}</span></div>}
          <div className="chart-zoom"><button aria-label="Уменьшить масштаб" onClick={() => chartApi.current?.zoom(1.3)}><Minus size={13}/></button><button aria-label="Увеличить масштаб" onClick={() => chartApi.current?.zoom(.75)}><Plus size={13}/></button><span/><button aria-label="Вписать в экран" onClick={() => { chartApi.current?.fit(); setActiveRange("Все"); }}><Maximize2 size={12}/></button></div>
          {tool !== "cursor" && <div className="drawing-mode-badge"><span/>{tool === "horizontal" ? "Горизонтальная линия" : tool === "trend" ? "Линия тренда" : "Линейка"}<button onClick={() => setTool("cursor")} aria-label="Завершить рисование"><X size={12}/></button></div>}
        </div>
        <SmcPanel open={smcPanel} settings={smcSettings} overlay={smc} onChange={next => setSettings(current => ({ ...current, smc: next }))} onClose={() => setSmcPanel(false)}/>
        <div className="chart-bottom-toolbar"><div className="range-options">{RANGE_OPTIONS.map(range => <button className={activeRange === range.label ? "active" : ""} key={range.label} onClick={() => { setActiveRange(range.label); const days = range.days === -1 ? Math.ceil((Date.now() - Date.UTC(new Date().getUTCFullYear(), 0, 1)) / 86400000) : range.days; chartApi.current?.range(days); }}>{range.label}</button>)}</div><a className="chart-attribution" href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer" title="Графики TradingView Lightweight Charts">Lightweight Charts<ArrowUpRight size={9}/></a><div className="chart-scale-options"><span className="chart-timezone">UTC+3</span><span className="mini-divider"/><button className={logarithmic ? "active" : ""} onClick={() => setLogarithmic(!logarithmic)}>лог</button><button className="auto-scale" onClick={() => { chartApi.current?.fit(); setActiveRange("Все"); }}>авто</button></div></div>
      </section>

      <section className="instrument-panel" aria-label="Финансовые инструменты">
        <div className="instrument-tabs"><button className={aboutTab === "overview" ? "active" : ""} onClick={() => setAboutTab("overview")}>Обзор</button><button className={aboutTab === "analysis" ? "active" : ""} onClick={() => setAboutTab("analysis")}>Теханализ</button><button className={aboutTab === "trading" ? "active" : ""} onClick={() => setAboutTab("trading")}>Торговля<span className="tab-count">{snapshot.positions.length}</span></button><button className="panel-expand-button" title="Подробнее" aria-label="Подробнее" onClick={() => openModal("info")}><ArrowUpRight size={16}/></button></div>
        {aboutTab === "overview" && <div className="instrument-overview"><div className="overview-heading"><AssetLogo instrument={instrument} size={34}/><div><h1>{instrument.name}<span>{instrument.kind === "index" ? "Индекс" : instrument.kind === "currency" ? "Валюта" : "Акция"}</span></h1><p>{instrument.fullName} <span>·</span> {instrument.sector}</p></div><button className="instrument-link" onClick={() => openModal("info")}>MOEX: {instrument.symbol}<ArrowUpRight size={12}/></button></div><div className="instrument-metrics"><div><span>Пред. закрытие <Info size={10}/></span><strong>{formatPrice(previous.close)}<small>{instrument.kind === "index" ? "п." : "₽"}</small></strong></div><div><span>Открытие</span><strong>{formatPrice(last.open)}<small>{instrument.kind === "index" ? "п." : "₽"}</small></strong></div><div><span>Объём свечи</span><strong>{formatCompact(last.volume)}<small>{instrument.kind === "index" ? "ед." : "лотов"}</small></strong></div><div><span>Диапазон</span><strong>{formatPrice(last.low)}<i>–</i>{formatPrice(last.high)}</strong></div></div></div>}
        {aboutTab === "analysis" && <div className="technical-content"><div className="technical-summary"><span>СВОДКА SMC PRO</span><strong className={smc.stats.bias === 1 ? "positive" : smc.stats.bias === -1 ? "negative" : "muted"}>{smc.stats.bias === 1 ? "Бычья структура" : smc.stats.bias === -1 ? "Медвежья структура" : "Нет структуры"}</strong><div className="sentiment-scale"><i/><i/><i/><i/><i/><b style={{ left: `${smc.stats.bias === 1 ? 82 : smc.stats.bias === -1 ? 18 : 50}%` }}/></div><small>Расчётная оценка, не рекомендация</small></div><div className="technical-metrics"><div><span>Поддержка</span><strong>{smc.stats.support != null ? formatPrice(smc.stats.support) : "—"}</strong><small>{smc.stats.support != null && last.close > smc.stats.support ? "Цена выше" : "Цена ниже"}</small></div><div><span>Сопротивление</span><strong>{smc.stats.resistance != null ? formatPrice(smc.stats.resistance) : "—"}</strong><small>{smc.stats.resistance != null && last.close > smc.stats.resistance ? "Пробой вверх" : "Под зоной"}</small></div><div><span>POC</span><strong>{smc.stats.poc != null ? formatPrice(smc.stats.poc) : "—"}</strong><small>{smc.stats.poc != null && last.close > smc.stats.poc ? "Выше POC" : "Ниже POC"}</small></div><div><span>Зоны OB</span><strong>{smc.stats.obCount + smc.stats.internalObCount}</strong><small>FVG {smc.stats.fvgCount}</small></div><div><span>Диапазон</span><strong>{smc.stats.equilibrium != null ? formatPrice(smc.stats.equilibrium) : "—"}</strong><small>{smc.stats.premiumDiscountZone === "premium" ? "Премиум" : smc.stats.premiumDiscountZone === "discount" ? "Дисконт" : "Равновесие"}</small></div><div><span>A+ покупки</span><strong className="positive">{smc.stats.aplusBuy.wins} / {smc.stats.aplusBuy.losses}</strong><small>A+ продажи {smc.stats.aplusSell.wins} / {smc.stats.aplusSell.losses}</small></div></div></div>}
        {aboutTab === "trading" && <div className="trading-content">
          <div className="trading-left"><OrderTicket symbol={settings.symbol} price={last.close} snapshot={snapshot} onSubmit={submitOrder} notify={notify}/></div>
          <div className="trading-right"><PositionTable snapshot={snapshot} onClose={closeById} compact/><div className="trading-account-link"><AccountBar snapshot={snapshot} onOpen={() => openModal("account")}/></div></div>
        </div>}
      </section>

      <aside className="watchlist-sidebar" aria-label="Список наблюдения">
        <div className="watchlist-panel">
          <div className="watchlist-heading"><h2>Список наблюдения</h2><ChevronDown size={12}/><div className="watch-heading-actions"><div className="dropdown-anchor" data-popover><button className="icon-button" aria-label="Меню списка наблюдения" onClick={() => togglePopover("watchlist")}><MoreHorizontal size={17}/></button>{popover === "watchlist" && <div className="dropdown-menu watchlist-dropdown"><button onClick={() => openModal("add")}><Plus size={14}/>Добавить инструмент</button><button onClick={exportWatchlist}><Download size={14}/>Экспорт CSV</button><button onClick={() => { setSettings(s => ({ ...s, watchlist: [...DEFAULT_SETTINGS.watchlist] })); setPopover(null); notify("Восстановлен исходный список"); }}><RefreshCw size={14}/>Восстановить список</button></div>}</div><button className="icon-button watchlist-add" title="Добавить инструмент" aria-label="Добавить инструмент" onClick={() => openModal("add")}><Plus size={17}/></button></div></div>
          <div className="watchlist-tabs">{([{ value: "stock", label: "Акции" }, { value: "index", label: "Индексы" }, { value: "currency", label: "Валюты" }] as const).map(t => <button className={watchKind === t.value ? "active" : ""} key={t.value} onClick={() => setWatchKind(t.value)}>{t.label}{t.value === "stock" && <span>{settings.watchlist.filter(s => getInstrument(s).kind === "stock").length}</span>}</button>)}</div>
          <div className="watch-table-heading"><span>Инструмент</span><span>Посл.</span><button onClick={() => setSortWatch(s => s === "none" ? "down" : s === "down" ? "up" : "none")}>Изм., %{sortWatch !== "none" && <ArrowDown size={9} style={{ transform: sortWatch === "up" ? "rotate(180deg)" : "none" }}/>}</button></div>
          <div className="watchlist-rows">{visibleInstruments.length ? visibleInstruments.map(i => { const q = quotes.find(q => q.symbol === i.symbol) ?? demoQuote(i); return <button className={`watch-row ${settings.symbol === i.symbol ? "selected" : ""}`} key={i.symbol} onClick={() => selectSymbol(i.symbol)} title={`${i.fullName} · ${q.source === "demo" ? "демонстрационная котировка" : SOURCE_LABELS[q.source]}`}><span className="watch-instrument"><AssetLogo instrument={i} size={22}/><span><strong>{i.kind === "currency" ? i.name.split(" / ").map(n => n === "Юань" ? "CNY" : n === "Рубль" ? "RUB" : n === "Доллар" ? "USD" : "EUR").join("/") : i.symbol}{q.source === "demo" && <em className="watch-demo-tag" title="Демонстрационная котировка">демо</em>}</strong><small>{i.name}</small></span></span><span className="watch-price">{formatPrice(q.price, i.kind === "currency" ? 3 : 2)}</span><span className={`watch-change ${q.change >= 0 ? "positive" : "negative"}`}>{formatChange(q.change)}</span></button>; }) : <div className="watchlist-empty"><Star size={22}/><strong>Список пуст</strong><button onClick={() => openModal("add")}>Добавить инструмент<Plus size={12}/></button></div>}</div>
          <div className="watchlist-footnote"><span>{visibleInstruments.length} инструментов</span><span><span className="small-status-dot"/>{quotes.every(q => q.source === "demo") ? "Демо-котировки" : "Обновление 30 с"}</span></div>
        </div>
        <div className="quote-panel"><div className="quote-panel-heading"><AssetLogo instrument={instrument} size={28}/><div><strong>{instrument.symbol.length > 9 ? instrument.name : instrument.symbol}</strong><span>{instrument.fullName}</span></div><button className={`icon-button quote-star ${settings.watchlist.includes(settings.symbol) ? "is-starred" : ""}`} onClick={() => toggleWatch(settings.symbol)} title="В список наблюдения" aria-label="В список наблюдения"><Star size={15} fill={settings.watchlist.includes(settings.symbol) ? "currentColor" : "none"}/></button><button className="icon-button" aria-label="Информация" onClick={() => openModal("info")}><MoreHorizontal size={17}/></button></div><div className="quote-current-price">{formatPrice(quote.price)}<span>{displayCurrency}</span></div><div className={`quote-current-change ${quote.change >= 0 ? "positive" : "negative"}`}><span>{quote.absolute >= 0 ? "+" : "−"}{formatPrice(Math.abs(quote.absolute))}</span><span>({formatChange(quote.change)})</span><span className="quote-period">за день</span></div><div className="daily-range"><div className="range-track"><span style={{ left: `${Math.min(96, Math.max(4, (quote.price - last.low) / (last.high - last.low || 1) * 100))}%` }}/></div><div className="range-labels"><span>{formatPrice(last.low)}<small>Мин. свечи</small></span><span>{formatPrice(last.high)}<small>Макс. свечи</small></span></div></div></div>
      </aside>

      <aside className="utility-rail" aria-label="Боковые панели">
        <button className={`utility-button ${showWatchlist ? "active" : ""}`} title="Список наблюдения" aria-label="Список наблюдения" onClick={() => setShowWatchlist(!showWatchlist)}><List size={18}/></button>
        <button className="utility-button" title="SMC Pro" aria-label="SMC Pro" onClick={() => setSmcPanel(true)}><Layers3 size={18}/></button>
        <button className="utility-button" title="Виртуальный счёт" aria-label="Виртуальный счёт" onClick={() => openModal("account")}><Wallet size={18}/></button>
        <button className="utility-button" title="Оповещения" aria-label="Оповещения" onClick={() => notify("Оповещения настраиваются в SMC Pro: раздел «Сигналы»")}><Bell size={18}/></button>
        <button className="utility-button" title="Идеи и сделки" aria-label="Идеи" onClick={() => openModal("market")}><Activity size={18}/></button>
        <div className="utility-history-anchor" data-popover><button className={`utility-button ${popover === "history" ? "active" : ""}`} title="Недавние инструменты" aria-label="Недавние инструменты" onClick={() => togglePopover("history")}><History size={18}/></button>{popover === "history" && <div className="dropdown-menu history-menu"><div className="dropdown-title">Недавние</div>{recent.map(symbol => { const i = getInstrument(symbol); return <button key={symbol} onClick={() => { selectSymbol(symbol); setPopover(null); }}><AssetLogo instrument={i} size={20}/><span>{i.name}</span><small>{symbol}</small></button>; })}</div>}</div>
        <span className="utility-divider"/>
        <button className="utility-button" title="Скринер" aria-label="Скринер" onClick={() => openModal("screener")}><SlidersHorizontal size={18}/></button>
        <button className="utility-button" title="Настройки" aria-label="Настройки" onClick={() => openModal("settings")}><Settings2 size={18}/></button>
        <div className="utility-help"><button className="utility-button" title="Помощь" aria-label="Помощь" onClick={() => openModal("help")}><CircleHelp size={18}/></button></div>
      </aside>
    </div>

    <footer className="statusbar"><div className="connection-status"><span className={`connection-dot ${source === "demo" ? "demo" : ""}`}/><button onClick={refreshData} title="Обновить подключение">{loading ? "Подключение к данным…" : source === "demo" ? "Демо-режим" : source === "moex" ? "MOEX ISS · 15 мин" : "Т-Инвест API"}</button><span className="status-divider"/><span className="footer-readonly"><ShieldCheck size={10}/>Только чтение</span></div><span className="status-disclaimer">{source === "demo" ? "Демонстрационные данные · не являются биржевыми котировками" : "Не является индивидуальной инвестиционной рекомендацией"}</span><div className="statusbar-right"><span className="saved-status"><CloudCheck size={11}/>{saveState === "saving" ? "Сохранение…" : saveState === "local" ? "Сохранено локально" : "Сохранено"}</span><span className="status-divider"/><time>{clock}<span> (UTC+3)</span></time><span className="connection-bars"><i/><i/><i/><i/></span></div></footer>

    {toast && <div className="toast" role="status"><Check size={15}/><span>{toast}</span><button aria-label="Закрыть уведомление" onClick={() => setToast("")}><X size={13}/></button></div>}
    {(modal === "search" || modal === "add") && <SearchDialog onClose={closeModal} onSelect={symbol => { if (modal === "add" && !settings.watchlist.includes(symbol)) toggleWatch(symbol); selectSymbol(symbol); }} quotes={quotes} watchlist={settings.watchlist} onToggle={toggleWatch} addMode={modal === "add"}/>}
    {(modal === "market" || modal === "screener") && <MarketDialog onClose={closeModal} onSelect={selectSymbol} quotes={quotes} screener={modal === "screener"}/>}
    {modal === "settings" && <SettingsDialog onClose={closeModal} settings={settings} onChange={setSettings} onReset={() => { setSettings(structuredClone(DEFAULT_SETTINGS)); setLogarithmic(false); setTool("cursor"); notify("Рабочее пространство сброшено"); }} source={SOURCE_LABELS[source]} onRefresh={refreshData}/>}
    {modal === "account" && <AccountDialog snapshot={snapshot} account={account} onClose={closeModal} onClosePosition={id => { closeById(id); }} onSelect={symbol => { selectSymbol(symbol); closeModal(); }} onReset={() => { setAccount(emptyAccount()); notify("Виртуальный счёт сброшен до 10 000 000 ₽"); }} onExport={exportTrades}/>}
    {modal === "info" && <InstrumentDialog instrument={instrument} quote={quote} onClose={closeModal}/>}
    {modal === "help" && <HelpDialog onClose={closeModal}/>}
  </main>;
}
