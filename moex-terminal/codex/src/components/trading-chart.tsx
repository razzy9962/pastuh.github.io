"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, LineSeries, AreaSeries, HistogramSeries, ColorType, CrosshairMode, LineStyle, PriceScaleMode, createSeriesMarkers, TickMarkType, type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type UTCTimestamp, type LogicalRange, type SeriesMarker, type Time } from "lightweight-charts";
import { formatMsk, formatPrice, type Candle, type Drawing } from "@/lib/market";
import { computeSmc, sanitizeSmcSettings, type SmcOverlay } from "@/lib/smc";
import { buildTradeMarkers } from "@/lib/marks";
import { SmcPrimitive } from "./smc-primitive";
import ChartOverlays, { measureText, type MeasurePoints } from "./chart-overlays";

export type DrawingTool = "cursor" | "trend" | "horizontal" | "measure";
export type ChartHandle = { fit: () => void; zoom: (factor: number) => void; range: (days: number) => void; screenshot: () => void };
type Props = {
  candles: Candle[]; symbol: string; timeframe: string; chartType: "candles" | "line" | "area";
  showVolume: boolean; drawings: Drawing[]; tool: DrawingTool; magnet: boolean; locked: boolean; drawingsVisible: boolean; logarithmic: boolean;
  smc: SmcOverlay;
  marks: { side: "long" | "short"; price: number; time: number }[];
  onApi: (handle: ChartHandle | null) => void; onHover: (candle: Candle | null) => void; onDraw: (drawing: Drawing) => void; onMeasure: (message: string) => void;
};

export default function TradingChart(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | ISeriesApi<"Area"> | null>(null);
  const tradeMarkersApi = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const shownCount = useRef(0);
  // Актуальные колбэки и данные для подписчиков Lightweight Charts, которые живут
  // вне React: обновляем ref в эффекте, а не во время рендера.
  const callbacks = useRef(props);
  useEffect(() => { callbacks.current = props; });
  const visibleRange = useRef<LogicalRange | null>(null);
  const lastKey = useRef("");
  const lastCount = useRef(0);
  const pendingPoint = useRef<{ time: number; price: number } | null>(null);
  const [measurePoints, setMeasurePoints] = useState<MeasurePoints | null>(null);
  const [trendPoints, setTrendPoints] = useState<MeasurePoints | null>(null);
  const [hoverPoint, setHoverPoint] = useState<{ time: number; price: number } | null>(null);
  const [liveChart, setLiveChart] = useState<{ chart: IChartApi; series: ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | ISeriesApi<"Area"> } | null>(null);

  // Смена инструмента/интервала/инструмента рисования сбрасывает незавершённое измерение.
  // Это именно синхронизация состояния с props: без неё «хвост» старой линейки
  // остаётся на новом графике. Один лишний рендер здесь дешевле, чем неверный рисунок.
  useEffect(() => {
    pendingPoint.current = null;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMeasurePoints(null);
    setTrendPoints(null);
    setHoverPoint(null);
  }, [props.tool, props.symbol, props.timeframe]);

  useEffect(() => {
    if (!container.current || !props.candles.length) return;
    const drawingsMap = drawingSeries.current;
    const { candles, symbol, timeframe, chartType, showVolume, drawings, drawingsVisible, logarithmic, smc } = props;
    const chart = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#131722" }, textColor: "#b2b5be", fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", fontSize: 11, attributionLogo: false, panes: { separatorColor: "#2a2e39", separatorHoverColor: "#3c424d", enableResize: true } },
      grid: { vertLines: { color: "#1f2430" }, horzLines: { color: "#1f2430" } },
      // Магнит включается только для курсора: при рисовании он «прилипает» к OHLC
      // и мешает поставить точку туда, куда кликнул пользователь.
      crosshair: { mode: props.magnet && props.tool === "cursor" ? CrosshairMode.Magnet : CrosshairMode.Normal, vertLine: { color: "#758696", width: 1, style: LineStyle.Dashed, labelBackgroundColor: "#363c4e" }, horzLine: { color: "#758696", width: 1, style: LineStyle.Dashed, labelBackgroundColor: "#363c4e" } },
      rightPriceScale: { borderVisible: true, borderColor: "#2a2e39", minimumWidth: 64, scaleMargins: { top: .18, bottom: showVolume ? .26 : .1 }, mode: logarithmic ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal },
      timeScale: {
        borderColor: "#2a2e39", timeVisible: !["1d", "1w"].includes(timeframe), secondsVisible: false, rightOffset: 6, barSpacing: 7, minBarSpacing: 3, fixLeftEdge: false,
        tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => formatMsk(time as number, tickMarkType === TickMarkType.Time || tickMarkType === TickMarkType.TimeWithSeconds, tickMarkType),
      },
      localization: {
        locale: "ru-RU",
        priceFormatter: (price: number) => formatPrice(price),
        // Lightweight Charts печатает время в UTC. Биржа живёт по МСК, часы в статус-баре
        // тоже МСК, поэтому ось и подпись перекрестия переводим в UTC+3 — иначе
        // свеча 18:00 выглядит как «15:00» и кажется, что график отстал на три часа.
        timeFormatter: (time: Time) => formatMsk(time as number, true),
      },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: props.tool === "cursor", horzTouchDrag: true, vertTouchDrag: false },
    });
    chartRef.current = chart;
    let main: ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | ISeriesApi<"Area">;
    if (chartType === "candles") main = chart.addSeries(CandlestickSeries, { upColor: "#089981", downColor: "#f23645", borderVisible: false, wickUpColor: "#089981", wickDownColor: "#f23645", priceLineColor: "#787b86", priceLineWidth: 1, priceLineStyle: LineStyle.Dotted, lastValueVisible: true });
    else if (chartType === "line") main = chart.addSeries(LineSeries, { color: "#2962ff", lineWidth: 2, priceLineVisible: true, crosshairMarkerRadius: 4 });
    else main = chart.addSeries(AreaSeries, { lineColor: "#2962ff", topColor: "rgba(41,98,255,.16)", bottomColor: "rgba(41,98,255,0)", lineWidth: 2, priceLineVisible: true });
    main.setData(candles.map(c => ({ ...c, time: c.time as UTCTimestamp, value: c.close })));
    seriesRef.current = main;
    setLiveChart({ chart, series: main });

    if (showVolume) {
      const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false });
      volume.setData(candles.map(c => ({ time: c.time as UTCTimestamp, value: c.volume, color: c.close >= c.open ? "rgba(8,153,129,.32)" : "rgba(242,54,69,.32)" })));
      volume.priceScale().applyOptions({ scaleMargins: { top: .82, bottom: 0 }, visible: false });
    }

    // --- SMC Pro: Order Blocks, FVG, уровни, POC, подписи структуры ---
    const smcSeries: ISeriesApi<"Line">[] = [];
    const emaTags: { tag: HTMLDivElement; price: number; series: ISeriesApi<"Line"> }[] = [];
    // Подписи EMA раскладываем без наложений: близкие значения сдвигаются вниз шагом 13px.
    const layoutTags = () => {
      const placed = emaTags
        .map(item => ({ item, y: item.series.priceToCoordinate(item.price) }))
        .flatMap(row => row.y == null ? [] : [{ item: row.item, y: Number(row.y) }])
        .sort((a, b) => a.y - b.y);
      let previous = -Infinity;
      for (const row of placed) {
        const y = Math.max(row.y, previous + 13);
        row.item.tag.style.display = "block";
        row.item.tag.style.top = `${y - 8}px`;
        previous = y;
      }
      for (const item of emaTags) {
        if (!placed.some(row => row.item === item)) item.tag.style.display = "none";
      }
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(layoutTags);
    const tagTimer = window.setInterval(layoutTags, 400);
    if (smc.series.length) for (const overlay of smc.series) {
      // EMA не участвуют в автомасштабе цены. Иначе дальняя линия (дневная EMA 200
      // на минутном графике, где цена в разы ниже) растягивала шкалу, и свечи
      // превращались в тонкую полоску у нижнего края. Если EMA далеко от цены,
      // она просто уходит за пределы экрана — свечи остаются читаемыми.
      const line = chart.addSeries(LineSeries, {
        color: overlay.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, title: "", autoscaleInfoProvider: () => null,
      });
      line.setData(overlay.data.map(point => ({ time: point.time as UTCTimestamp, value: point.value })));
      // Подпись «15M EMA 20» — только у последнего бара, как в TradingView.
      const last = overlay.data.at(-1);
      if (last) {
        const tag = document.createElement("div");
        tag.className = "smc-ema-tag";
        tag.textContent = overlay.label;
        tag.style.color = overlay.color;
        container.current?.appendChild(tag);
        emaTags.push({ tag, price: last.value, series: line });
      }
      smcSeries.push(line);
    }
    if (smc.boxes.length || smc.lines.length || smc.texts.length) {
      main.attachPrimitive(new SmcPrimitive({ ...smc, series: [] }));
    }
    // Метки сделок виртуального счёта: зелёная стрелка — покупка, красная — продажа.
    // Время метки может прийти в миллисекундах (Date.now) или в секундах, а графику нужна
    // метка времени существующего бара — иначе стрелка молча не отрисовывается.
    tradeMarkersApi.current = createSeriesMarkers(main, buildTradeMarkers(callbacks.current.marks, candles));

    if (smc.markers.length) {
      const markers: SeriesMarker<Time>[] = smc.markers.slice(-24).map(marker => ({
        time: marker.time as UTCTimestamp,
        position: marker.bias === 1 ? "belowBar" : "aboveBar",
        shape: marker.bias === 1 ? "arrowUp" : "arrowDown",
        color: marker.bias === 1 ? "#089981" : "#f23645",
        text: marker.text,
        size: marker.strong ? 2 : 1,
      }));
      createSeriesMarkers(main, markers);
    }

    requestAnimationFrame(layoutTags);
    const byTime = new Map(candles.map(c => [Math.floor(c.time), c]));
    // Клик и наведение привязываем к индексу ближайшего бара: точное время свечи есть
    // в данных, но не гарантируется на выходных точках шкалы и при магните.
    const barCandle = (param: { time?: unknown; logical?: number }) => {
      if (typeof param.time === "number") return byTime.get(Math.floor(param.time)) ?? byTime.get(param.time) ?? null;
      const index = typeof param.logical === "number" ? Math.round(param.logical) : -1;
      return index >= 0 && index < candles.length ? candles[index] : null;
    };
    chart.subscribeCrosshairMove(param => {
      callbacks.current.onHover(barCandle(param as { time?: unknown; logical?: number }));
      // Живой предпросмотр линейки и линии тренда: вторая точка следует за курсором.
      const current = callbacks.current;
      const anchor = pendingPoint.current;
      const hovered = barCandle(param as { time?: unknown; logical?: number });
      if (!anchor || !param.point || !hovered) { setHoverPoint(null); return; }
      const value = main.coordinateToPrice(param.point.y);
      if (value == null) return;
      const preview = { from: anchor, to: { time: hovered.time, price: value } };
      setHoverPoint(preview.to);
      if (current.tool === "measure") setMeasurePoints(preview);
      if (current.tool === "trend") setTrendPoints(preview);
    });
    chart.subscribeClick(param => {
      const current = callbacks.current;
      if (current.tool === "cursor" || current.locked || !param.point) return;
      const bar = barCandle(param as { time?: unknown; logical?: number });
      if (!bar) return;
      const time = bar.time;
      const price = main.coordinateToPrice(param.point.y);
      if (price == null || price <= 0) return;
      if (current.tool === "horizontal") { current.onDraw({ id: crypto.randomUUID(), type: "horizontal", price, time, color: "#2962ff" }); return; }
      if (!pendingPoint.current) {
        pendingPoint.current = { time, price };
        setHoverPoint(null);
        setMeasurePoints(current.tool === "measure" ? { from: { time, price }, to: { time, price } } : null);
        setTrendPoints(current.tool === "trend" ? { from: { time, price }, to: { time, price } } : null);
        current.onMeasure(current.tool === "trend" ? "Ведите курсор ко второй точке линии и щёлкните" : "Ведите курсор к концу измерения — цифры обновляются на лету");
        return;
      }
      const start = pendingPoint.current;
      pendingPoint.current = null;
      if (start.time === time) { current.onMeasure("Выберите точки на разных свечах"); return; }
      if (current.tool === "trend") {
        current.onDraw({ id: crypto.randomUUID(), type: "trend", price: start.price, time: start.time, endPrice: price, endTime: time, color: "#26a69a" });
        setTrendPoints(null);
        current.onMeasure(`Линия тренда: ${formatPrice(start.price)} → ${formatPrice(price)}`);
      } else {
        // Линейка остаётся на графике, пока не начнут новое измерение или не переключат инструмент.
        const points = { from: start, to: { time, price } };
        setMeasurePoints(points);
        const info = measureText(points, candles, !["1d", "1w"].includes(timeframe));
        current.onMeasure(`${info.text} · ${formatPrice(start.price)} → ${formatPrice(price)}`);
      }
    });

    const key = `${symbol}:${timeframe}`;
    if (lastKey.current === key && visibleRange.current) {
      const shift = candles.length - lastCount.current;
      chart.timeScale().setVisibleLogicalRange({ from: visibleRange.current.from + shift, to: visibleRange.current.to + shift });
    } else chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, candles.length - 132), to: candles.length + 7 });
    lastKey.current = key;
    lastCount.current = candles.length;
    shownCount.current = candles.length;
    props.onApi({
      fit: () => chart.timeScale().fitContent(),
      zoom: factor => { const r = chart.timeScale().getVisibleLogicalRange(); if (r) { const middle = (r.from + r.to) / 2; const half = (r.to - r.from) / 2 * factor; chart.timeScale().setVisibleLogicalRange({ from: middle - half, to: middle + half }); } },
      range: days => {
        if (!days) { chart.timeScale().fitContent(); return; }
        const end = candles[candles.length - 1].time;
        const start = end - days * 86400;
        // findIndex возвращал -1, если окно короче одного бара (например, «1Д» на
        // недельном графике), и график оставался в прежнем масштабе.
        const found = candles.findIndex(c => c.time >= start);
        const first = found < 0 ? 0 : found;
        chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, first), to: candles.length + 4 });
      },
      screenshot: () => { const canvas = chart.takeScreenshot(); const link = document.createElement("a"); link.download = `${symbol}-${timeframe}-${new Date().toISOString().slice(0, 10)}.png`; link.href = canvas.toDataURL("image/png"); link.click(); },
    });
    return () => { window.clearInterval(tagTimer); visibleRange.current = chart.timeScale().getVisibleLogicalRange(); emaTags.forEach(item => item.tag.remove()); chart.remove(); chartRef.current = null; seriesRef.current = null; drawingsMap.clear(); tradeMarkersApi.current = null; setLiveChart(null); props.onApi(null); void smcSeries; };
  // Пересборка графика только при смене инструмента, интервала, типа, объёмов, логарифма и настроек SMC.
  // Котировки и рисунки обновляются ниже отдельными эффектами, чтобы график не терял прокрутку.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.symbol, props.timeframe, props.chartType, props.showVolume, props.logarithmic, props.smc, props.onApi]);

  // Метки сделок обновляются вместе со свечами, без пересоздания графика:
  // новая сделка появляется сразу, а старые остаются на своих барах.
  useEffect(() => {
    tradeMarkersApi.current?.setMarkers(buildTradeMarkers(props.marks, props.candles));
  }, [props.marks, props.candles]);

  // Обновление данных без пересоздания графика: свечи и рисунки перерисовываются на месте.
  // Если пользователь смотрел последние бары, после догрузки окно сдвигается на столько же
  // баров — иначе новая свеча оставалась за правым краем и график «замирал» на моменте открытия.
  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !props.candles.length) return;
    const added = shownCount.current ? props.candles.length - shownCount.current : 0;
    const range = chart?.timeScale().getVisibleLogicalRange() ?? null;
    const pinnedToRight = range ? range.to >= shownCount.current - 1.5 : true;
    series.setData(props.candles.map(c => ({ ...c, time: c.time as UTCTimestamp, value: c.close })));
    shownCount.current = props.candles.length;
    // Сдвигаем окно только когда пришли новые бары и пользователь был у правого края:
    // прокрутка в историю не сбрасывается.
    if (added > 0 && pinnedToRight && range && chart) chart.timeScale().setVisibleLogicalRange({ from: range.from + added, to: range.to + added });
  }, [props.candles]);

  // Рисунки синхронизируются отдельно: новый уровень или линия появляются сразу,
  // без пересоздания графика и потери позиции прокрутки.
  const drawingSeries = useRef(new Map<string, { series: ISeriesApi<"Line">; priceLine?: { price: number } }>());
  useEffect(() => {
    const chart = chartRef.current;
    const main = seriesRef.current;
    if (!chart || !main) return;
    const stroe = drawingSeries.current;
    const alive = new Set(props.drawings.map(drawing => drawing.id));
    for (const [id, entry] of stroe) {
      if (alive.has(id) && props.drawingsVisible) continue;
      if (entry.priceLine) main.removePriceLine(entry.priceLine as never);
      chart.removeSeries(entry.series);
      stroe.delete(id);
    }
    if (!props.drawingsVisible) return;
    for (const drawing of props.drawings) {
      if (stroe.has(drawing.id)) continue;
      if (drawing.type === "horizontal") {
        const priceLine = main.createPriceLine({ price: drawing.price, color: drawing.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "Уровень" });
        const holder = chart.addSeries(LineSeries, { color: drawing.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        holder.setData([]);
        stroe.set(drawing.id, { series: holder, priceLine: priceLine as unknown as { price: number } });
      } else if (drawing.endTime && drawing.endPrice) {
        const line = chart.addSeries(LineSeries, { color: drawing.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        const points = [{ time: drawing.time as UTCTimestamp, value: drawing.price }, { time: drawing.endTime as UTCTimestamp, value: drawing.endPrice }].sort((a, b) => a.time - b.time);
        if (points[0].time !== points[1].time) line.setData(points);
        stroe.set(drawing.id, { series: line });
      }
    }
  }, [props.drawings, props.drawingsVisible, liveChart]);

  // При активном инструменте рисования магнит выключается: он «прилипает» к OHLC и не
  // даёт поставить точку там, куда пользователь кликнул.
  useEffect(() => {
    chartRef.current?.applyOptions({
      crosshair: { mode: props.magnet && props.tool === "cursor" ? CrosshairMode.Magnet : CrosshairMode.Normal },
      handleScroll: { pressedMouseMove: props.tool === "cursor" },
    });
  }, [props.magnet, props.tool]);

  return <div className={`chart-stack tool-${props.tool}`}>
    <div ref={container} className="chart-canvas" aria-label={`Интерактивный график ${props.symbol}. Колесо мыши — масштаб, перетаскивание — прокрутка.`} />
    {liveChart && <ChartOverlays chart={liveChart.chart} series={liveChart.series} candles={props.candles} measure={measurePoints} trend={trendPoints} intraday={!["1d", "1w"].includes(props.timeframe)}/>}
  </div>;
}
