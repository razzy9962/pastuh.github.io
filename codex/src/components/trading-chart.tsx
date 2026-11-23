"use client";

import { useEffect, useRef, type RefObject } from "react";
import { createChart, CandlestickSeries, LineSeries, AreaSeries, HistogramSeries, ColorType, CrosshairMode, LineStyle, PriceScaleMode, type IChartApi, type ISeriesApi, type UTCTimestamp, type LogicalRange } from "lightweight-charts";
import { calculateIndicator, formatPrice, type Candle, type Drawing, type Indicator } from "@/lib/market";

export type DrawingTool = "cursor" | "trend" | "horizontal" | "measure";
export type ChartHandle = { fit: () => void; zoom: (factor: number) => void; range: (days: number) => void; screenshot: () => void };
type Props = {
  candles: Candle[]; symbol: string; timeframe: string; indicators: Indicator[]; chartType: "candles" | "line" | "area";
  showVolume: boolean; drawings: Drawing[]; tool: DrawingTool; magnet: boolean; locked: boolean; drawingsVisible: boolean; logarithmic: boolean;
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
    const { candles, symbol, timeframe, indicators, chartType, showVolume, drawings, drawingsVisible, logarithmic } = props;
    const chart = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#101318" }, textColor: "#737d8f", fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", fontSize: 10, attributionLogo: false, panes: { separatorColor: "#242a34", separatorHoverColor: "#36434b", enableResize: true } },
      grid: { vertLines: { color: "#1a1f27" }, horzLines: { color: "#1a1f27" } },
      crosshair: { mode: props.magnet ? CrosshairMode.Magnet : CrosshairMode.Normal, vertLine: { color: "#5b6576", width: 1, style: LineStyle.Dashed, labelBackgroundColor: "#303943" }, horzLine: { color: "#5b6576", width: 1, style: LineStyle.Dashed, labelBackgroundColor: "#303943" } },
      rightPriceScale: { borderVisible: false, minimumWidth: 73, scaleMargins: { top: .22, bottom: showVolume ? .23 : .1 }, mode: logarithmic ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal },
      timeScale: { borderColor: "#242a32", timeVisible: !["1d", "1w"].includes(timeframe), secondsVisible: false, rightOffset: 7, barSpacing: 7, minBarSpacing: 3, fixLeftEdge: false },
      localization: { locale: "ru-RU", priceFormatter: (price: number) => formatPrice(price) },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: props.tool === "cursor", horzTouchDrag: true, vertTouchDrag: false },
    });
    chartRef.current = chart;
    let main: ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | ISeriesApi<"Area">;
    if (chartType === "candles") main = chart.addSeries(CandlestickSeries, { upColor: "#35bd94", downColor: "#e1727c", borderVisible: false, wickUpColor: "#35bd94", wickDownColor: "#e1727c", priceLineColor: "#35bd94", priceLineWidth: 1, priceLineStyle: LineStyle.Dashed, lastValueVisible: true });
    else if (chartType === "line") main = chart.addSeries(LineSeries, { color: "#35c79b", lineWidth: 2, priceLineVisible: true, crosshairMarkerRadius: 4 });
    else main = chart.addSeries(AreaSeries, { lineColor: "#35c79b", topColor: "rgba(53,199,155,.22)", bottomColor: "rgba(53,199,155,0)", lineWidth: 2, priceLineVisible: true });
    main.setData(candles.map(c => ({ ...c, time: c.time as UTCTimestamp, value: c.close })));

    if (showVolume) {
      const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false });
      volume.setData(candles.map(c => ({ time: c.time as UTCTimestamp, value: c.volume, color: c.close >= c.open ? "rgba(53,189,148,.28)" : "rgba(225,114,124,.28)" })));
      volume.priceScale().applyOptions({ scaleMargins: { top: .82, bottom: 0 }, visible: false });
    }

    for (const indicator of indicators.filter(i => i.enabled)) {
      const isRsi = indicator.type === "rsi";
      const values = calculateIndicator(candles, indicator.type, indicator.period);
      const line = chart.addSeries(LineSeries, { color: indicator.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: isRsi, crosshairMarkerVisible: false, title: isRsi ? `RSI ${indicator.period}` : "" }, isRsi ? 1 : 0);
      line.setData(values.map(v => ({ ...v, time: v.time as UTCTimestamp })));
      if (isRsi) {
        line.createPriceLine({ price: 70, color: "#694b65", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" });
        line.createPriceLine({ price: 30, color: "#3a675a", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" });
        chart.panes()[1]?.setHeight(105);
      }
      if (indicator.type === "bb") {
        for (const sign of [-1, 1]) {
          const band = chart.addSeries(LineSeries, { color: `${indicator.color}90`, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
          band.setData(values.map((v, index) => {
            const position = index + indicator.period - 1;
            const slice = candles.slice(position - indicator.period + 1, position + 1);
            const variance = slice.reduce((sum, c) => sum + (c.close - v.value) ** 2, 0) / indicator.period;
            return { time: v.time as UTCTimestamp, value: v.value + sign * 2 * Math.sqrt(variance) };
          }));
        }
      }
    }

    if (drawingsVisible) for (const drawing of drawings) {
      if (drawing.type === "horizontal") main.createPriceLine({ price: drawing.price, color: drawing.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "Уровень" });
      else if (drawing.endTime && drawing.endPrice) {
        const line = chart.addSeries(LineSeries, { color: drawing.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        const points = [{ time: drawing.time as UTCTimestamp, value: drawing.price }, { time: drawing.endTime as UTCTimestamp, value: drawing.endPrice }].sort((a, b) => a.time - b.time);
        if (points[0].time !== points[1].time) line.setData(points);
      }
    }

    const byTime = new Map(candles.map(c => [c.time, c]));
    chart.subscribeCrosshairMove(param => { callbacks.current.onHover(typeof param.time === "number" ? byTime.get(param.time) ?? null : null); });
    chart.subscribeClick(param => {
      const current = callbacks.current;
      if (current.tool === "cursor" || current.locked || !param.point || typeof param.time !== "number") return;
      const price = main.coordinateToPrice(param.point.y);
      if (price == null || price <= 0) return;
      if (current.tool === "horizontal") { current.onDraw({ id: crypto.randomUUID(), type: "horizontal", price, time: param.time, color: "#7f9cf5" }); return; }
      if (!pendingPoint.current) { pendingPoint.current = { time: param.time, price }; current.onMeasure(current.tool === "trend" ? "Выберите вторую точку линии" : "Выберите конечную точку измерения"); return; }
      const start = pendingPoint.current;
      pendingPoint.current = null;
      if (start.time === param.time) { current.onMeasure("Выберите точки на разных свечах"); return; }
      if (current.tool === "trend") current.onDraw({ id: crypto.randomUUID(), type: "trend", price: start.price, time: start.time, endPrice: price, endTime: param.time, color: "#7f9cf5" });
      else {
        const line = chart.addSeries(LineSeries, { color: "#c8a46a", lineWidth: 2, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
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
    return () => { visibleRange.current = chart.timeScale().getVisibleLogicalRange(); chart.remove(); chartRef.current = null; props.apiRef.current = null; };
  }, [props.candles, props.symbol, props.timeframe, props.indicators, props.chartType, props.showVolume, props.drawings, props.drawingsVisible, props.logarithmic, props.apiRef]);

  useEffect(() => { chartRef.current?.applyOptions({ crosshair: { mode: props.magnet ? CrosshairMode.Magnet : CrosshairMode.Normal }, handleScroll: { pressedMouseMove: props.tool === "cursor" } }); }, [props.magnet, props.tool]);

  return <div ref={container} className={`chart-canvas tool-${props.tool}`} aria-label={`Интерактивный график ${props.symbol}. Колесо мыши — масштаб, перетаскивание — прокрутка.`} />;
}
