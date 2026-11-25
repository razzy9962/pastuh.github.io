"use client";

import Link from "next/link";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowDown, Wallet, ArrowUpRight, Bell, Camera, CandlestickChart, ChartArea, ChartLine, Check, ChevronDown, CircleHelp, CloudCheck, Code2, Crosshair, Download, Eye, EyeOff, FolderOpen, History, Info, Layers3, List, LockKeyhole, Magnet, Maximize2, Minimize2, Minus, MoreHorizontal, Plus, RefreshCw, Ruler, Search, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Star, Trash2, TrendingUp, Undo2, UnlockKeyhole, Wifi, WifiOff, X } from "lucide-react";
import { changeLabel, DEFAULT_SETTINGS, INSTRUMENTS, TIMEFRAMES, formatChange, formatCompact, formatMoney, formatPrice, getInstrument, type Candle, type DataSource, type Drawing, type InstrumentKind, type Quote, type WorkspaceSettings } from "@/lib/market";
import { AssetLogo, HelpDialog, InstrumentDialog, MarketDialog, SearchDialog, SettingsDialog } from "./dialogs";
import { AccountBar, AccountDialog, OrderTicket, PositionTable, useSnapshot } from "./trading-panel";
import { applyProtection, closePosition, emptyAccount, openPosition, sanitizeAccount, totalReturn, type Account, type Side, type TradeMark } from "@/lib/broker";
import SmcPanel from "./smc-panel";
import type { ChartHandle, DrawingTool } from "./trading-chart";
import { computeSmc, sanitizeSmcSettings, type SmcOverlay } from "@/lib/smc";
import { computeMetrics, computeSession, rsiLabel } from "@/lib/metrics";

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
const EMPTY_CANDLE: Candle = { time: 0, open: 0, high: 0, low: 0, close: 0, volume: 0 };
type ModalName = "search" | "add" | "market" | "screener" | "settings" | "info" | "help" | "account" | null;
type Popover = "chartType" | "workspace" | "notifications" | "watchlist" | "profile" | "history" | null;
const RANGE_OPTIONS = [{ label: "1Д", days: 1 }, { label: "5Д", days: 5 }, { label: "1М", days: 30 }, { label: "3М", days: 90 }, { label: "6М", days: 180 }, { label: "YTD", days: -1 }, { label: "1Г", days: 365 }, { label: "Все", days: 0 }];
const SOURCE_LABELS: Record<DataSource, string> = { tinvest: "Т-Инвест API · обновление 10 с", moex: "MOEX ISS · задержка до 15 мин", demo: "Данных нет" };

export default function Terminal() {
  const [settings, setSettings] = useState<WorkspaceSettings>(() => structuredClone(DEFAULT_SETTINGS));
  const [candles, setCandles] = useState<Candle[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
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
  const [tradeMarks, setTradeMarks] = useState<TradeMark[]>([]);
  const [marksLoaded, setMarksLoaded] = useState(false);
  // Дневные свечи отдельным запросом: на часовом и минутном графике из одного ответа
  // физически не получить 200 дней истории, а без неё дневная EMA 20/200 неверна.
  const [dailyCandles, setDailyCandles] = useState<Candle[]>([]);
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
  // Время последнего успешного ответа по свечам: сразу видно, если данные перестали обновляться.
  const [dataAt, setDataAt] = useState<number | null>(null);
  const [dataError, setDataError] = useState("");
  const [toast, setToast] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [recent, setRecent] = useState(["SBER"]);
  const [smcPanel, setSmcPanel] = useState(false);
  const chartApi = useRef<ChartHandle | null>(null);
  const attachChart = useCallback((handle: ChartHandle | null) => { chartApi.current = handle; }, []);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const smcSettings = useMemo(() => sanitizeSmcSettings(settings.smc), [settings.smc]);
  // Отпечаток закрытых баров: последняя (незакрытая) свеча меняется каждые 30 секунд,
  // но структура, Order Blocks, FVG и профиль объёма от неё не зависят.
  // Без этого SMC пересчитывался на каждом обновлении котировок — это главный источник
  // подтормаживаний на слабых машинах и мобильных.
  const closedFingerprint = useMemo(() => `${settings.symbol}:${settings.timeframe}:${candles.length}:${candles.at(-1)?.time ?? 0}`, [candles, settings.symbol, settings.timeframe]);
  const closedCandles = useMemo(() => candles.slice(0, -1), [closedFingerprint]); // eslint-disable-line react-hooks/exhaustive-deps
  // Метрики «ATR 14 / RSI 14 / EMA 20 / Год» — дневные. На часовом и минутном графике
  // они считались по часовым барам и подписывались как дневные (а «Год» покрывал
  // две недели). Приоритет: дневные свечи отдельного запроса → свечи 1Д → свечи графика.
  const metricsCandles = useMemo(() => {
    if (dailyCandles.length >= 20) return { candles: dailyCandles, timeframe: "1d" as const };
    if (settings.timeframe === "1d" || settings.timeframe === "1w") return { candles, timeframe: settings.timeframe };
    return { candles, timeframe: settings.timeframe };
  }, [closedFingerprint, dailyCandles, settings.timeframe]); // eslint-disable-line react-hooks/exhaustive-deps
  const metrics = useMemo(() => computeMetrics(metricsCandles.candles, metricsCandles.timeframe), [metricsCandles]);
  const session = useMemo(() => computeSession(candles), [closedFingerprint]); // eslint-disable-line react-hooks/exhaustive-deps
  const smc = useMemo<SmcOverlay>(() => computeSmc(closedCandles, smcSettings, settings.timeframe, dailyCandles), [closedFingerprint, smcSettings, settings.timeframe, dailyCandles]); // eslint-disable-line react-hooks/exhaustive-deps
  const instrument = getInstrument(settings.symbol);
  const currentDrawings = settings.drawings[settings.symbol] ?? EMPTY_DRAWINGS;
  // Пустой массив свечей — штатное состояние: данных может не быть вовсе.
  // EMPTY_CANDLE — стабильная ссылка, иначе мемоизация ниже сбрасывается на каждом рендере.
  const last = candles[candles.length - 1] ?? EMPTY_CANDLE;
  const previous = candles[candles.length - 2] ?? last;
  const candle = hover ?? last;
  const timeframeLabel = TIMEFRAMES.find(t => t.value === settings.timeframe)?.label ?? "1Д";
  const metricsLabel = metrics?.timeframe === "1d" ? "дни" : (TIMEFRAMES.find(t => t.value === metrics?.timeframe)?.label ?? "дни");
  const closeModal = useCallback(() => setModal(null), []);
  const notify = useCallback((message: string) => { setToast(message); if (toastTimer.current) clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(""), 4500); }, []);

  // Никаких выдуманных цен: если живых данных нет, quote = null, и интерфейс честно
  // показывает «нет данных» вместо правдоподобного, но ненастоящего графика.
  const quote = useMemo<Quote | null>(() => {
    const existing = quotes.find(q => q.symbol === settings.symbol && q.source !== "demo");
    // Котировка с биржи старше 15 минут — это не «последняя цена», а история: показывать
    // её как текущую нельзя (раньше в выходные висела пятничная цена без пометки).
    // Признак старения выставляет сервер (поле stale), чтобы не звать Date.now в рендере.
    if (existing) return existing;
    // Свечей нет — цены нет. Проверяем длину массива, а не значение last:
    // last всегда содержит безопасную заглушку.
    if (!candles.length) return null;
    // Запасной путь (котировок нет, есть только свечи): изменение считаем от закрытия
    // предыдущего дня, а не предыдущего бара — иначе на минутном графике «за день»
    // показывало колебание за минуту.
    const reference = dailyCandles.length > 1 ? dailyCandles[dailyCandles.length - 2].close : previous.close;
    const known = reference > 0;
    return { symbol: settings.symbol, price: last.close, change: known ? (last.close / reference - 1) * 100 : 0, changeKnown: known, absolute: known ? last.close - reference : 0, high: last.high, low: last.low, volume: last.volume, source };
  }, [quotes, settings.symbol, candles.length, last, previous, dailyCandles, source]);
  // Предыдущее закрытие торгового дня: для «изменения за день» и блока «Обзор».
  // Раньше здесь бралось закрытие предыдущего бара — на минутном графике это была
  // предыдущая минута, и «Пред. закрытие» не сходилось с изменением за день.
  const previousClose = useMemo(() => {
    if (quote && quote.changeKnown !== false && quote.absolute) return quote.price - quote.absolute;
    if (dailyCandles.length > 1) return dailyCandles[dailyCandles.length - 2].close;
    if ((settings.timeframe === "1d" || settings.timeframe === "1w") && candles.length > 1) return candles[candles.length - 2].close;
    return null;
  }, [quote, dailyCandles, candles, settings.timeframe]);
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

  // Чтение настроек с сервера и из localStorage возможно только после монтирования:
  // на сервере localStorage нет, а ленивая инициализация дала бы расхождение гидратации.
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

  // Восстановление счёта и меток: единственный источник — localStorage, он доступен только
  // в браузере, поэтому перенос сохранённого состояния возможен только после монтирования.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    try {
      const stored = localStorage.getItem("moex-account");
      if (stored) setAccount(sanitizeAccount(JSON.parse(stored)));
      const marks = localStorage.getItem("moex-marks");
      const restored = marks ? (JSON.parse(marks) as TradeMark[]).filter(mark => mark && (mark.side === "long" || mark.side === "short") && Number.isFinite(mark.price) && Number.isFinite(mark.time) && mark.price > 0 && typeof mark.symbol === "string").slice(-40) : [];
      if (restored.length) setTradeMarks(restored);
    } catch { /* Corrupted storage is ignored. */ }
    setAccountLoaded(true);
    setMarksLoaded(true);
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    if (!marksLoaded) return;
    try { localStorage.setItem("moex-marks", JSON.stringify(tradeMarks.slice(-40))); } catch { /* Browser storage may be full. */ }
  }, [tradeMarks, marksLoaded]);

  useEffect(() => {
    if (!accountLoaded) return;
    try { localStorage.setItem("moex-account", JSON.stringify(account)); } catch { /* Browser storage may be full. */ }
  }, [account, accountLoaded]);

  useEffect(() => {
    if (!loaded) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setSaveState("saving");
      let local = true;
      try { localStorage.setItem("moex-workspace", JSON.stringify(settings)); } catch { local = false; }
      try {
        const response = await fetch("/api/workspace", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings), signal: controller.signal });
        if (!response.ok) throw new Error("Save failed");
        setSaveState("saved");
      } catch {
        // Ни сервера, ни браузерного хранилища — изменения пропадут после перезагрузки,
        // об этом нужно сказать прямо, а не показывать «сохранено».
        if (!controller.signal.aborted) { setSaveState("local"); if (!local) notify("Браузер не разрешает сохранение настроек — изменения не сохранятся"); }
      }
    }, 650);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [settings, loaded, notify]);

  useEffect(() => {
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true); setHover(null); setDataError(""); setCandles([]); setDailyCandles([]); setDataAt(null);
    const update = async () => {
      try {
        const response = await fetch(`/api/market?symbol=${encodeURIComponent(settings.symbol)}&timeframe=${settings.timeframe}`, { signal: controller.signal });
        if (!response.ok) throw new Error("Market unavailable");
        const data = await response.json();
        if (!controller.signal.aborted) {
          // Пустой ответ — тоже ответ: старые свечи нельзя оставлять на экране как «живые».
          if (data.candles?.length) { setCandles(data.candles); setHover(null); setDataAt(Date.now()); }
          else { setCandles([]); setDataAt(null); setDataError("Провайдер не вернул свечи для выбранного инструмента"); }
          setSource(data.source ?? "demo");
        }
      } catch (error) {
        if (!controller.signal.aborted) setDataError(error instanceof Error ? "Не удалось загрузить данные. Проверьте подключение и повторите запрос." : "Не удалось загрузить данные");
      }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void update();
    // Опрашиваем всегда, пока вкладка видна: раньше автообновление работало только
    // на 1м–15м, и на 1ч–1Н график «замерзал» — последняя свеча оставалась на времени
    // открытия страницы (видно как «последняя свеча 15:35, а сейчас 18:40»).
    // Трафик Render экономится иначе: в скрытой вкладке опрос стоит, интервал на
    // старших таймфреймах вдвое реже, а ответы кешируются (30 с на сервере, ETag + 304).
    // 10 секунд: ~26 КБ на инструмент в час с gzip и ETag — несколько процентов
    // от 5 ГБ бесплатного тарифа Render, даже при открытой вкладке целый день.
    const interval = 10000;
    const timer = setInterval(() => { if (!document.hidden) void update(); }, interval);
    const onVisible = () => { if (!document.hidden) void update(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [settings.symbol, settings.timeframe, refresh]);

  // Дневная история нужна только для EMA со старшего таймфрейма.
  useEffect(() => {
    if (settings.timeframe === "1d" || settings.timeframe === "1w") return;
    const controller = new AbortController();
    const load = async () => {
      try {
        const response = await fetch(`/api/market?symbol=${encodeURIComponent(settings.symbol)}&timeframe=1d`, { signal: controller.signal });
        if (!response.ok) return;
        const data = await response.json();
        if (!controller.signal.aborted && data.candles?.length) setDailyCandles(data.candles);
      } catch { /* Без дневной истории EMA старшего ТФ просто не рисуется. */ }
    };
    void load();
    const timer = setInterval(() => { if (!document.hidden) void load(); }, 60000);
    return () => { controller.abort(); clearInterval(timer); };
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

  // Догоняющий опрос котировок: если провайдер отдал не весь список, повторяем через
  // 8 секунд, не дожидаясь 30-секундного цикла — иначе часть списка висела с прочерками.
  useEffect(() => {
    if (loaded !== true) return;
    const missing = INSTRUMENTS.some(i => !quotes.some(q => q.symbol === i.symbol && q.source !== "demo"));
    if (!missing || !quotes.length) return;
    const timer = setTimeout(async () => {
      try {
        const response = await fetch("/api/market?mode=quotes&retry=1");
        if (!response.ok) return;
        const data = await response.json();
        if (data.quotes?.length) setQuotes(data.quotes);
      } catch { /* Повторим на следующем цикле. */ }
    }, 8000);
    return () => clearTimeout(timer);
  }, [quotes, loaded]);

  // Часы: значение зависит от момента рендера, поэтому на сервере выводится заглушка,
  // а реальное время появляется после монтирования — иначе React ругается на гидратацию.
  useEffect(() => {
    const format = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Moscow" });
    const update = () => setClock(format.format(new Date()));
    update();
    const timer = setInterval(() => { if (!document.hidden) update(); }, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setModal(m => m === "search" ? null : "search"); setPopover(null); }
      // Горячие клавиши инструментов: не мешают вводу в полях и поиске.
      const target = event.target as HTMLElement | null;
      const typing = !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
      if (!typing && !event.metaKey && !event.ctrlKey) {
        const key = event.key.toLowerCase();
        const shortcuts: Record<string, DrawingTool> = { c: "cursor", t: "trend", h: "horizontal", l: "measure" };
        if (shortcuts[key]) { event.preventDefault(); setTool(shortcuts[key]); setPopover(null); }
      }
      if (event.key === "Escape") {
        setPopover(null);
        setSmcPanel(false);
        if (modal) setModal(null);
        else if (tool !== "cursor") setTool("cursor");
        else if (focusMode) setFocusMode(false);
      }
    };
    const outside = (event: PointerEvent) => { if (!(event.target as HTMLElement).closest("[data-popover]")) setPopover(null); };
    document.addEventListener("keydown", handler); document.addEventListener("pointerdown", outside);
    return () => { document.removeEventListener("keydown", handler); document.removeEventListener("pointerdown", outside); };
    // Зависимости важны: без них Esc работал по устаревшему состоянию инструмента.
  }, [modal, tool, focusMode]);

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

  const exportWatchlist = () => { const content = "\uFEFFТикер;Название;Цена;Изменение, %;Источник\n" + settings.watchlist.map(symbol => { const i = getInstrument(symbol), q = quotes.find(q => q.symbol === symbol && q.source !== "demo"); return `${symbol};${i.name};${q ? q.price : ""};${q ? q.change : ""};${q ? SOURCE_LABELS[q.source] : "нет данных"}`; }).join("\n"); download("MOEX-watchlist.csv", content, "text/csv;charset=utf-8"); setPopover(null); notify("Список наблюдения экспортирован"); };
  const refreshData = () => { setRefresh(r => r + 1); notify("Запрашиваем свежие данные у провайдера"); };
  const currentPriceChange = candle.close - candle.open;
  const symbolLabel = settings.symbol === "CNYRUB_TOM" ? "CNY/RUB" : settings.symbol;
  const displayCurrency = instrument.kind === "index" ? "пункты" : "RUB";
  const priceDecimals = instrument.kind === "currency" ? 4 : 2;

  // Метка запоминает и инструмент: иначе покупка SBER рисовалась бы на графике GAZP.
  const recordMark = useCallback((side: Side, price: number, symbol: string) => {
    setTradeMarks(marks => [...marks.slice(-40), { side, price, time: Date.now(), symbol }]);
  }, []);

  const submitOrder = useCallback((order: { side: Side; lots: number; amount?: number; take?: number; stop?: number }) => {
    if (!order.lots) {
      // lots = 0 — это запрос на закрытие текущей позиции по инструменту.
      const position = account.positions.find(p => p.symbol === settings.symbol);
      if (!position) return;
      const result = closePosition(account, position.id, last.close);
      if (result.ok) {
        setAccount(result.account);
        recordMark(position.side === "long" ? "short" : "long", last.close, position.symbol);
        notify(result.trade ? `Позиция ${position.symbol} закрыта: ${result.trade.pnl - result.trade.fee >= 0 ? "+" : "−"}${formatMoney(Math.abs(result.trade.pnl - result.trade.fee))} ₽` : `Позиция ${position.symbol} закрыта`);
      } else notify(result.error ?? "Не удалось закрыть позицию");
      return;
    }
    const result = openPosition(account, { symbol: settings.symbol, side: order.side, lots: order.lots, amount: order.amount, price: last.close, take: order.take, stop: order.stop, slippage: 0.0002 });
    if (!result.ok) { notify(result.error); return; }
    setAccount(result.account);
    recordMark(order.side, last.close, settings.symbol);
    notify(`${order.side === "long" ? "Куплено" : "Продано"} ${result.position.lots} лот. ${settings.symbol} по ${formatPrice(last.close)} ₽`);
  }, [account, settings.symbol, last.close, notify, recordMark]);

  const closeById = useCallback((id: string) => {
    const position = account.positions.find(p => p.id === id);
    // Нет живой цены — закрывать нечем: раньше сделка закрывалась по цене входа,
    // то есть результат «ноль» появлялся из ниоткуда.
    const price = position ? prices[position.symbol] ?? 0 : 0;
    if (position && !(price > 0)) { notify(`Нет текущей цены ${position.symbol} — закрыть позицию нельзя, попробуйте позже`); return; }
    const result = closePosition(account, id, price);
    if (result.ok) { setAccount(result.account); if (result.trade) recordMark(result.trade.side, price, result.trade.symbol); notify(result.trade ? `Сделка закрыта: ${(result.trade.pnl - result.trade.fee >= 0 ? "+" : "−") + formatMoney(Math.abs(result.trade.pnl - result.trade.fee))} ₽` : "Позиция закрыта"); }
  }, [account, prices, notify, recordMark]);

  // Тейк-профит и стоп-лосс проверяются только по цене, наблюдённой после открытия позиции:
  // high/low бара включают движение до входа, из-за этого тейк «срабатывал» без касания.
  useEffect(() => {
    if (!account.positions.length) return;
    const observed: Record<string, { price: number; time: number }> = {};
    for (const position of account.positions) {
      if (position.symbol === settings.symbol && last) observed[position.symbol] = { price: last.close, time: last.time * 1000 };
      else {
        const q = quotes.find(item => item.symbol === position.symbol && item.source !== "demo");
        if (q) observed[position.symbol] = { price: q.price, time: q.time ? Date.parse(q.time) || Date.now() : Date.now() };
      }
    }
    const result = applyProtection(account, observed);
    if (!result.closed.length) return;
    // Автоматическое срабатывание TP/SL переносит исполнение в состояние счёта —
    // без этого позиция осталась бы «открытой» до следующей ручной заявки.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAccount(result.account);
    // Автоматическое закрытие по TP/SL тоже оставляет метку на графике.
    for (const trade of result.closed) recordMark(trade.side, trade.exit, trade.symbol);
    for (const trade of result.closed) notify(`${trade.reason === "take" ? "Тейк-профит" : "Стоп-лосс"} ${trade.symbol}: ${(trade.pnl - trade.fee >= 0 ? "+" : "−") + formatMoney(Math.abs(trade.pnl - trade.fee))} ₽`);
  }, [account, quotes, last, settings.symbol, notify, recordMark]);

  return <main className={`terminal-shell ${focusMode ? "focus-mode" : ""}`}>
    <header className="topbar">
      <Link className="brand" href="/" aria-label="MOEX Terminal — главная"><span className="brand-mark"><svg viewBox="0 0 28 28" fill="none"><path d="M6 21V9l7 7L22 5v16" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"/></svg></span><span className="brand-word">moex<span>.</span></span><span className="brand-product">terminal</span></Link>
      <nav className="main-nav" aria-label="Основная навигация"><button className={!modal || !["market", "screener"].includes(modal) ? "active" : ""} onClick={() => setModal(null)}>График</button><button className={modal === "market" ? "active" : ""} onClick={() => openModal("market")}>Обзор рынка</button><button className={modal === "screener" ? "active" : ""} onClick={() => openModal("screener")}>Скринер<span className="new-dot"/></button></nav>
      <div className="header-actions">
        <button className="global-search" onClick={() => openModal("search")}><Search size={15}/><span>Поиск (Ctrl+K)</span><kbd>Ctrl K</kbd></button>
        <span className="header-divider"/>
        <span className="read-only" title="Реальные заявки на биржу не отправляются"><ShieldCheck size={13}/><span>Виртуальный счёт</span></span>
        <div className="dropdown-anchor" data-popover><button className={`icon-button notification-button ${popover === "notifications" ? "selected" : ""}`} aria-label="Уведомления" onClick={() => togglePopover("notifications")}><Bell size={18}/><i/></button>{popover === "notifications" && <div className="dropdown-menu notifications-menu"><div className="dropdown-title">Уведомления<span>3</span></div><div className="notification-item"><span className={`notification-item-icon ${source === "demo" ? "amber" : "green"}`}>{source === "demo" ? <WifiOff size={15}/> : <Wifi size={15}/>}</span><div><strong>{loading ? "Подключение к рынку" : source === "demo" ? "Режим без данных" : "Данные подключены"}</strong><p>{source === "demo" ? "Т-Инвест и MOEX не ответили — данных нет. Проверьте токен и нажмите «Повторить запрос»." : SOURCE_LABELS[source]}</p></div></div><div className="notification-item"><span className="notification-item-icon"><CloudCheck size={15}/></span><div><strong>Пространство сохранено</strong><p>{saveState === "local" ? "Резервная копия в браузере. Сервер недоступен." : "Список, индикаторы и рисунки сохраняются автоматически."}</p></div></div><div className="notification-item"><span className="notification-item-icon"><ShieldCheck size={15}/></span><div><strong>Безопасное подключение</strong><p>Торговые операции отключены.</p></div></div><button className="dropdown-footer" onClick={() => { refreshData(); notify(source === "demo" ? "Повторный запрос к Т-Инвест…" : "Данные обновляются"); }}><RefreshCw size={13}/>{source === "demo" ? "Повторить запрос" : "Проверить подключение"}</button></div>}</div>
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
          {candles.length > 0 && <TradingChart marks={tradeMarks.filter(mark => mark.symbol === settings.symbol)} candles={candles} symbol={settings.symbol} timeframe={settings.timeframe} chartType={settings.chartType} showVolume={settings.showVolume} drawings={currentDrawings} tool={tool} magnet={magnet} locked={locked} drawingsVisible={drawingsVisible} logarithmic={logarithmic} smc={smc} onApi={attachChart} onHover={setHover} onDraw={addDrawing} onMeasure={notify}/>}
          {!candles.length && <div className="chart-empty" role="status">
            <strong>{loading ? "Загружаем данные…" : dataError ? "Не удалось получить данные" : "Нет данных по инструменту"}</strong>
            <p>{loading ? `${instrument.symbol} · ${timeframeLabel} · запрос к провайдерам рынка` : dataError || "API не вернул свечи. Демонстрационных данных в терминале нет: покажем только настоящие цены."}</p>
            {!loading && <button className="secondary-button" onClick={refreshData}><RefreshCw size={14}/>Повторить запрос</button>}
          </div>}
          <div className="chart-watermark" aria-hidden="true"><strong>{instrument.symbol.length < 7 ? instrument.symbol : instrument.name}</strong><span>MOEX TERMINAL</span></div>
          <div className="chart-heading">
            <div className="chart-asset-title"><AssetLogo instrument={instrument} size={22}/><button onClick={() => openModal("info")}>{instrument.name}</button><span className="chart-title-dot">·</span><span className="chart-tf-title">{timeframeLabel}</span><span className="chart-title-dot">·</span><span className="chart-exchange">MOEX</span><span className={`source-pill ${source}`} title={SOURCE_LABELS[source]}><i/>{source === "demo" ? "нет данных" : source === "moex" ? "15 мин" : "T-Invest"}</span>{loading && <RefreshCw size={11} className="refresh-indicator"/>}</div>
            <div className="ohlc-row"><span>ОТКР<span>{candles.length ? formatPrice(candle.open) : "—"}</span></span><span>МАКС<span>{candles.length ? formatPrice(candle.high) : "—"}</span></span><span>МИН<span>{candles.length ? formatPrice(candle.low) : "—"}</span></span><span>ЗАКР<span className={candles.length ? (currentPriceChange >= 0 ? "positive" : "negative") : "muted"}>{candles.length ? formatPrice(candle.close) : "—"}</span></span><span className={!candles.length ? "ohlc-delta muted" : currentPriceChange >= 0 ? "positive ohlc-delta" : "negative ohlc-delta"}>{!candles.length ? "нет данных" : <>{currentPriceChange >= 0 ? "+" : ""}{formatPrice(currentPriceChange)} ({formatChange(candle.open ? currentPriceChange / candle.open * 100 : 0)})</>}</span></div>
            <div className="chart-indicator-legends">{smcSettings.enabled && <div className="chart-indicator-legend smc-legend"><span className="legend-stroke" style={{ background: "#ffd400" }}/><span>SMC Pro</span><span className="legend-parameters">{smc.stats.bias === 1 ? "бычья" : smc.stats.bias === -1 ? "медвежья" : "нейтр."}{smc.stats.support != null ? ` · подд. ${formatPrice(smc.stats.support)}` : ""}{smc.stats.resistance != null ? ` · сопр. ${formatPrice(smc.stats.resistance)}` : ""}</span><button className="legend-action" aria-label="Настройки SMC Pro" onClick={() => setSmcPanel(true)}><SlidersHorizontal size={11}/></button></div>}</div>
          </div>
          <div className="chart-currency" aria-hidden="true">{displayCurrency.toUpperCase()}</div>
          {settings.showVolume && candles.some(c => c.volume > 0) && <div className="volume-legend"><span className="volume-legend-color"/>Объём<span>{candles.length ? formatCompact(candle.volume) : "—"}</span></div>}
          <div className="chart-zoom"><button aria-label="Уменьшить масштаб" onClick={() => chartApi.current?.zoom(1.3)}><Minus size={13}/></button><button aria-label="Увеличить масштаб" onClick={() => chartApi.current?.zoom(.75)}><Plus size={13}/></button><span/><button aria-label="Вписать в экран" onClick={() => { chartApi.current?.fit(); setActiveRange("Все"); }}><Maximize2 size={12}/></button></div>
          {tool !== "cursor" && <div className="drawing-mode-badge"><span/>{tool === "horizontal" ? "Горизонтальная линия" : tool === "trend" ? "Линия тренда" : "Линейка"}<button onClick={() => setTool("cursor")} aria-label="Завершить рисование"><X size={12}/></button></div>}
        </div>
        <SmcPanel open={smcPanel} settings={smcSettings} overlay={smc} onChange={next => setSettings(current => ({ ...current, smc: next }))} onClose={() => setSmcPanel(false)}/>
        <div className="chart-bottom-toolbar"><div className="range-options">{RANGE_OPTIONS.map(range => <button className={activeRange === range.label ? "active" : ""} key={range.label} onClick={() => { setActiveRange(range.label); const days = range.days === -1 ? Math.ceil((Date.now() - Date.UTC(new Date().getUTCFullYear(), 0, 1)) / 86400000) : range.days; chartApi.current?.range(days); }}>{range.label}</button>)}</div><a className="chart-attribution" href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer" title="Графики TradingView Lightweight Charts">Lightweight Charts<ArrowUpRight size={9}/></a><div className="chart-scale-options"><span className="chart-timezone">UTC+3</span><span className="mini-divider"/><button className={logarithmic ? "active" : ""} onClick={() => setLogarithmic(!logarithmic)}>лог</button><button className="auto-scale" onClick={() => { chartApi.current?.fit(); setActiveRange("Все"); }}>авто</button></div></div>
      </section>

      <section className="instrument-panel" aria-label="Финансовые инструменты">
        <div className="instrument-tabs"><button className={aboutTab === "overview" ? "active" : ""} onClick={() => setAboutTab("overview")}>Обзор</button><button className={aboutTab === "analysis" ? "active" : ""} onClick={() => setAboutTab("analysis")}>Теханализ</button><button className={aboutTab === "trading" ? "active" : ""} onClick={() => setAboutTab("trading")}>Торговля<span className="tab-count">{snapshot.positions.length}</span></button><button className="panel-expand-button" title="Подробнее" aria-label="Подробнее" onClick={() => openModal("info")}><ArrowUpRight size={16}/></button></div>
        {aboutTab === "overview" && <div className="instrument-overview"><div className="overview-heading"><AssetLogo instrument={instrument} size={34}/><div><h1>{instrument.name}<span>{instrument.kind === "index" ? "Индекс" : instrument.kind === "currency" ? "Валюта" : "Акция"}</span></h1><p>{instrument.fullName} <span>·</span> {instrument.sector}</p></div><button className="instrument-link" onClick={() => openModal("info")}>MOEX: {instrument.symbol}<ArrowUpRight size={12}/></button></div><div className="instrument-metrics"><div><span>Пред. закрытие <Info size={10}/></span><strong>{previousClose != null ? formatPrice(previousClose) : "—"}<small>{instrument.kind === "index" ? "п." : "₽"}</small></strong></div><div><span>Открытие дня</span><strong>{session ? formatPrice(session.sessionOpen) : candles.length ? formatPrice(last.open) : "—"}<small>{instrument.kind === "index" ? "п." : "₽"}</small></strong></div><div><span>Объём свечи</span><strong>{candles.length ? formatCompact(last.volume) : "—"}<small>{instrument.kind === "index" ? "ед." : "лотов"}</small></strong></div><div><span>Диапазон дня</span><strong>{session ? <>{formatPrice(session.sessionLow)}<i>–</i>{formatPrice(session.sessionHigh)}</> : candles.length ? <>{formatPrice(last.low)}<i>–</i>{formatPrice(last.high)}</> : "—"}</strong></div></div>
          {metrics && <div className="metrics-strip">
            <div className="metric"><span>ATR 14 · {metricsLabel}</span><strong>{formatPrice(metrics.atr)}</strong><small>{formatPrice(metrics.atrPercent)}% от цены</small></div>
            <div className="metric"><span>RSI 14</span><strong className={metrics.rsi >= 70 ? "negative" : metrics.rsi <= 30 ? "positive" : ""}>{formatPrice(metrics.rsi, 1)}</strong><small>{rsiLabel(metrics.rsi)}</small></div>
            <div className="metric"><span>EMA 20 · {metricsLabel}</span><strong>{metrics.ema20 ? formatPrice(metrics.ema20) : "—"}</strong><small className={metrics.ema20Slope >= 0 ? "positive" : "negative"}>{metrics.ema20Slope >= 0 ? "↑" : "↓"} {formatPrice(Math.abs(metrics.ema20Slope))}% за 10 бар</small></div>
            <div className="metric"><span>Год · {metricsLabel}</span><strong>{formatPrice(metrics.low52)} – {formatPrice(metrics.high52)}</strong><small>позиция {formatPrice(metrics.positionInRange, 0)}% диапазона</small></div>
            <div className="metric metric-fib"><span>Фибоначчи · 120 {metrics.timeframe === "1d" ? "дн." : "бар"}</span><div className="fib-row">{metrics.fib.map(level => <div key={level.label}><em>{level.label}</em><b>{formatPrice(level.price)}</b></div>)}</div></div>
          </div>}
        </div>}
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
          <div className="watchlist-rows">{visibleInstruments.length ? visibleInstruments.map(i => { const q = quotes.find(q => q.symbol === i.symbol && q.source !== "demo"); return <button className={`watch-row ${settings.symbol === i.symbol ? "selected" : ""}`} key={i.symbol} onClick={() => selectSymbol(i.symbol)} title={`${i.fullName} · ${q && q.source !== "demo" ? SOURCE_LABELS[q.source] : "нет данных"}`}><span className="watch-instrument"><AssetLogo instrument={i} size={22}/><span><strong>{i.kind === "currency" ? i.name.split(" / ").map(n => n === "Юань" ? "CNY" : n === "Рубль" ? "RUB" : n === "Доллар" ? "USD" : "EUR").join("/") : i.symbol}</strong><small>{i.name}</small></span></span><span className="watch-price">{q ? formatPrice(q.price, i.kind === "currency" ? 3 : 2) : "—"}</span><span className={`watch-change ${q ? (q.change >= 0 ? "positive" : "negative") : ""}`}>{q ? changeLabel(q) : ""}</span></button>; }) : <div className="watchlist-empty"><Star size={22}/><strong>Список пуст</strong><button onClick={() => openModal("add")}>Добавить инструмент<Plus size={12}/></button></div>}</div>
          <div className="watchlist-footnote"><span>{visibleInstruments.length} инструментов</span><span><span className="small-status-dot"/>{quotes.filter(q => q.source !== "demo").length ? `${quotes.filter(q => q.source !== "demo").length} из ${quotes.length} · 10 с` : "нет данных"}</span></div>
        </div>
        <div className="quote-panel"><div className="quote-panel-heading"><AssetLogo instrument={instrument} size={28}/><div><strong>{instrument.symbol.length > 9 ? instrument.name : instrument.symbol}</strong><span>{instrument.fullName}</span></div><button className={`icon-button quote-star ${settings.watchlist.includes(settings.symbol) ? "is-starred" : ""}`} onClick={() => toggleWatch(settings.symbol)} title="В список наблюдения" aria-label="В список наблюдения"><Star size={15} fill={settings.watchlist.includes(settings.symbol) ? "currentColor" : "none"}/></button><button className="icon-button" aria-label="Информация" onClick={() => openModal("info")}><MoreHorizontal size={17}/></button></div><div className="quote-current-price">{quote ? <>{formatPrice(quote.price, priceDecimals)}<span>{displayCurrency}</span>{quote.stale && <em className="quote-stale" title="Биржа не присылала новых цен больше 15 минут: торги закрыты или нет связи">последняя известная</em>}</> : <span className="muted">Нет данных</span>}</div>{quote ? <div className={`quote-current-change ${quote.change >= 0 ? "positive" : "negative"}`}><span>{quote.absolute >= 0 ? "+" : "−"}{formatPrice(Math.abs(quote.absolute))}</span><span>({changeLabel(quote)})</span><span className="quote-period">за день</span></div> : <div className="quote-current-change muted">Нет данных о цене</div>}<div className="daily-range"><div className="range-track"><span style={{ left: `${Math.min(96, Math.max(4, ((quote?.price ?? last.close) - (session?.sessionLow ?? last.low)) / ((session?.sessionHigh ?? last.high) - (session?.sessionLow ?? last.low) || 1) * 100))}%` }}/></div><div className="range-labels"><span>{formatPrice(session?.sessionLow ?? last.low)}<small>Мин. за день</small></span><span>{formatPrice(session?.sessionHigh ?? last.high)}<small>Макс. за день</small></span></div></div></div>
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

    <footer className="statusbar"><div className="connection-status"><span className={`connection-dot ${source === "demo" ? "demo" : ""}`}/><button onClick={refreshData} title="Обновить подключение">{loading ? "Подключение к данным…" : source === "demo" ? "Нет данных" : source === "moex" ? "MOEX ISS · 15 мин" : "Т-Инвест API"}</button><span className="status-divider"/><span className="data-freshness" title="Время последнего успешного обновления свечей">{dataAt ? `обновлено ${new Date(dataAt).toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit" })}` : "нет данных"}</span><span className="status-divider"/><span className="footer-readonly" title="Данные приходят только на чтение, а сделки совершаются на виртуальном счёте"><ShieldCheck size={10}/>Виртуальный счёт</span></div><span className="status-disclaimer">{source === "demo" ? "Данные от API не получены · не являются биржевыми котировками" : "Не является индивидуальной инвестиционной рекомендацией"}</span><div className="statusbar-right"><span className="saved-status"><CloudCheck size={11}/>{saveState === "saving" ? "Сохранение…" : saveState === "local" ? "Сохранено локально" : "Сохранено"}</span><span className="status-divider"/><time>{clock}<span> (UTC+3)</span></time><span className="connection-bars"><i/><i/><i/><i/></span></div></footer>

    {toast && <div className="toast" role="status" aria-live="polite"><Check size={15}/><span>{toast}</span><button aria-label="Закрыть уведомление" onClick={() => setToast("")}><X size={13}/></button></div>}
    {(modal === "search" || modal === "add") && <SearchDialog onClose={closeModal} onSelect={symbol => { if (modal === "add" && !settings.watchlist.includes(symbol)) toggleWatch(symbol); selectSymbol(symbol); }} quotes={quotes} watchlist={settings.watchlist} onToggle={toggleWatch} addMode={modal === "add"}/>}
    {(modal === "market" || modal === "screener") && <MarketDialog onClose={closeModal} onSelect={selectSymbol} quotes={quotes} screener={modal === "screener"}/>}
    {modal === "settings" && <SettingsDialog onClose={closeModal} settings={settings} onChange={setSettings} onReset={() => { setSettings(structuredClone(DEFAULT_SETTINGS)); setLogarithmic(false); setTool("cursor"); notify("Рабочее пространство сброшено"); }} source={SOURCE_LABELS[source]} onRefresh={refreshData}/>}
    {modal === "account" && <AccountDialog snapshot={snapshot} account={account} onClose={closeModal} onClosePosition={id => { closeById(id); }} onSelect={symbol => { selectSymbol(symbol); closeModal(); }} onReset={() => { setAccount(emptyAccount()); notify("Виртуальный счёт сброшен до 10 000 000 ₽"); }} onExport={exportTrades}/>}
    {modal === "info" && <InstrumentDialog instrument={instrument} quote={quote} onClose={closeModal}/>}
    {modal === "help" && <HelpDialog onClose={closeModal}/>}
  </main>;
}
