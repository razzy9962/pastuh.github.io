"use client";

import { useEffect, useRef, type RefObject } from "react";
import { createChart, CandlestickSeries, LineSeries, AreaSeries, HistogramSeries, ColorType, CrosshairMode, LineStyle, PriceScaleMode, createSeriesMarkers, type IChartApi, type ISeriesApi, type UTCTimestamp, type LogicalRange, type SeriesMarker, type Time } from "lightweight-charts";
import { formatPrice, type Candle, type Drawing } from "@/lib/market";
import { computeSmc, sanitizeSmcSettings, type SmcOverlay } from "@/lib/smc";
import { SmcPrimitive } from "./smc-primitive";

export type DrawingTool = "cursor" | "trend" | "horizontal" | "measure";
export type ChartHandle = { fit: () => void; zoom: (factor: number) => void; range: (days: number) => void; screenshot: () => void };
type Props = {
  candles: Candle[]; symbol: string; timeframe: string; chartType: "candles" | "line" | "area";
  showVolume: boolean; drawings: Drawing[]; tool: DrawingTool; magnet: boolean; locked: boolean; drawingsVisible: boolean; logarithmic: boolean;
  smc: SmcOverlay;
  apiRef: RefObject<ChartHandle | null>; onHover: (candle: Candle | null) => void; onDraw: (drawing: Drawing) => void; onMeasure: (message: string) => void;
};

export default function TradingChart(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const callbacks = useRef(props);
  callbacks.current = props;
  const visibleRange = useRef<LogicalRange | null>(null);
  const lastKey = useRef("");
  const lastCount = useRef(0);
  const pendingPoint = useRef<{ time: number; price: number } | null>(null);

  useEffect(() => { pendingPoint.current = null; }, [props.tool]);

  useEffect(() => {
    if (!container.current || !props.candles.length) return;
    const { candles, symbol, timeframe, chartType, showVolume, drawings, drawingsVisible, logarithmic, smc } = props;
    const chart = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#131722" }, textColor: "#b2b5be", fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", fontSize: 11, attributionLogo: false, panes: { separatorColor: "#2a2e39", separatorHoverColor: "#3c424d", enableResize: true } },
      grid: { vertLines: { color: "#1f2430" }, horzLines: { color: "#1f2430" } },
      crosshair: { mode: props.magnet ? CrosshairMode.Magnet : CrosshairMode.Normal, vertLine: { color: "#758696", width: 1, style: LineStyle.Dashed, labelBackgroundColor: "#363c4e" }, horzLine: { color: "#758696", width: 1, style: LineStyle.Dashed, labelBackgroundColor: "#363c4e" } },
      rightPriceScale: { borderVisible: true, borderColor: "#2a2e39", minimumWidth: 64, scaleMargins: { top: .18, bottom: showVolume ? .26 : .1 }, mode: logarithmic ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal },
      timeScale: { borderColor: "#2a2e39", timeVisible: !["1d", "1w"].includes(timeframe), secondsVisible: false, rightOffset: 6, barSpacing: 7, minBarSpacing: 3, fixLeftEdge: false },
      localization: { locale: "ru-RU", priceFormatter: (price: number) => formatPrice(price) },
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
      const line = chart.addSeries(LineSeries, { color: overlay.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "" });
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

    if (drawingsVisible) for (const drawing of drawings) {
      if (drawing.type === "horizontal") main.createPriceLine({ price: drawing.price, color: drawing.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "Уровень" });
      else if (drawing.endTime && drawing.endPrice) {
        const line = chart.addSeries(LineSeries, { color: drawing.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        const points = [{ time: drawing.time as UTCTimestamp, value: drawing.price }, { time: drawing.endTime as UTCTimestamp, value: drawing.endPrice }].sort((a, b) => a.time - b.time);
        if (points[0].time !== points[1].time) line.setData(points);
      }
    }

    requestAnimationFrame(layoutTags);
    const byTime = new Map(candles.map(c => [c.time, c]));
    chart.subscribeCrosshairMove(param => { callbacks.current.onHover(typeof param.time === "number" ? byTime.get(param.time) ?? null : null); });
    chart.subscribeClick(param => {
      const current = callbacks.current;
      if (current.tool === "cursor" || current.locked || !param.point || typeof param.time !== "number") return;
      const price = main.coordinateToPrice(param.point.y);
      if (price == null || price <= 0) return;
      if (current.tool === "horizontal") { current.onDraw({ id: crypto.randomUUID(), type: "horizontal", price, time: param.time, color: "#2962ff" }); return; }
      if (!pendingPoint.current) { pendingPoint.current = { time: param.time, price }; current.onMeasure(current.tool === "trend" ? "Выберите вторую точку линии" : "Выберите конечную точку измерения"); return; }
      const start = pendingPoint.current;
      pendingPoint.current = null;
      if (start.time === param.time) { current.onMeasure("Выберите точки на разных свечах"); return; }
      if (current.tool === "trend") current.onDraw({ id: crypto.randomUUID(), type: "trend", price: start.price, time: start.time, endPrice: price, endTime: param.time, color: "#2962ff" });
      else {
        const line = chart.addSeries(LineSeries, { color: "#f0b94a", lineWidth: 2, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
        line.setData([{ time: start.time as UTCTimestamp, value: start.price }, { time: param.time as UTCTimestamp, value: price }].sort((a, b) => a.time - b.time));
        const delta = price - start.price;
        const bars = Math.max(1, Math.abs(candles.findIndex(c => c.time === param.time) - candles.findIndex(c => c.time === start.time)));
        current.onMeasure(`${delta >= 0 ? "+" : ""}${formatPrice(delta)} ₽ (${delta >= 0 ? "+" : ""}${formatPrice(delta / start.price * 100)}%) · ${bars} свечей`);
      }
    });

    const key = `${symbol}:${timeframe}`;
    if (lastKey.current === key && visibleRange.current) {
      const shift = candles.length - lastCount.current;
      chart.timeScale().setVisibleLogicalRange({ from: visibleRange.current.from + shift, to: visibleRange.current.to + shift });
    } else chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, candles.length - 132), to: candles.length + 7 });
    lastKey.current = key;
    lastCount.current = candles.length;
    props.apiRef.current = {
      fit: () => chart.timeScale().fitContent(),
      zoom: factor => { const r = chart.timeScale().getVisibleLogicalRange(); if (r) { const middle = (r.from + r.to) / 2; const half = (r.to - r.from) / 2 * factor; chart.timeScale().setVisibleLogicalRange({ from: middle - half, to: middle + half }); } },
      range: days => { if (!days) { chart.timeScale().fitContent(); return; } const end = candles[candles.length - 1].time; const start = end - days * 86400; const first = candles.findIndex(c => c.time >= start); chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, first), to: candles.length + 4 }); },
      screenshot: () => { const canvas = chart.takeScreenshot(); const link = document.createElement("a"); link.download = `${symbol}-${timeframe}-${new Date().toISOString().slice(0, 10)}.png`; link.href = canvas.toDataURL("image/png"); link.click(); },
    };
    return () => { window.clearInterval(tagTimer); visibleRange.current = chart.timeScale().getVisibleLogicalRange(); emaTags.forEach(item => item.tag.remove()); chart.remove(); chartRef.current = null; seriesRef.current = null; props.apiRef.current = null; void smcSeries; };
  // Пересборка графика только при смене инструмента, интервала, типа, объёмов, логарифма и настроек SMC.
  // Котировки и рисунки обновляются ниже отдельными эффектами, чтобы график не терял прокрутку.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.symbol, props.timeframe, props.chartType, props.showVolume, props.logarithmic, props.smc, props.apiRef]);

  // Обновление данных без пересоздания графика: свечи и рисунки перерисовываются на месте.
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | ISeriesApi<"Area"> | null>(null);
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !props.candles.length) return;
    series.setData(props.candles.map(c => ({ ...c, time: c.time as UTCTimestamp, value: c.close })));
  }, [props.candles]);

  useEffect(() => { chartRef.current?.applyOptions({ crosshair: { mode: props.magnet ? CrosshairMode.Magnet : CrosshairMode.Normal }, handleScroll: { pressedMouseMove: props.tool === "cursor" } }); }, [props.magnet, props.tool]);

  return <div ref={container} className={`chart-canvas tool-${props.tool}`} aria-label={`Интерактивный график ${props.symbol}. Колесо мыши — масштаб, перетаскивание — прокрутка.`} />;
}
