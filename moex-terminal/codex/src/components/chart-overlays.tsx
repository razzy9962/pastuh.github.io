"use client";

/**
 * Оверлеи графика: линейка (измерение) и линия тренда.
 * Рисуются поверх canvas элементами DOM, поэтому подписи всегда читаемы,
 * а линия и маркеры не «прыгают» при прокрутке и масштабировании.
 */
import { useEffect, useRef } from "react";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import { formatMskFull, formatPrice, type Candle } from "@/lib/market";

export type MeasurePoints = { from: { time: number; price: number }; to: { time: number; price: number } };

// Время в МСК: линейка не должна показывать UTC, пока ось и часы живут по Москве.
const fmtTime = (time: number, intraday: boolean) => intraday ? formatMskFull(time) : formatMskFull(time).split(" ")[0];

/**
 * Длительность одного бара на текущем таймфрейме, секунды.
 * Берём медиану интервалов, а не последний интервал: на стыке сессий и выходных
 * последний зазор бывает в 3 дня, и линейка показывала «65 бар · 3 дн.» вместо «3 бар».
 */
const barSeconds = (candles: Candle[]) => {
  if (candles.length < 2) return 86400;
  const gaps: number[] = [];
  for (let i = Math.max(1, candles.length - 60); i < candles.length; i++) {
    const gap = candles[i].time - candles[i - 1].time;
    if (gap > 0 && gap <= 8 * 86400) gaps.push(gap);
  }
  if (!gaps.length) return 86400;
  gaps.sort((a, b) => a - b);
  return Math.max(60, gaps[Math.floor(gaps.length / 2)]);
};

export function measureText(points: MeasurePoints, candles: Candle[], intraday: boolean) {
  const delta = points.to.price - points.from.price;
  const percent = points.from.price ? delta / points.from.price * 100 : 0;
  const seconds = Math.abs(points.to.time - points.from.time);
  const bars = Math.max(1, Math.round(seconds / barSeconds(candles)));
  const days = seconds / 86400;
  const hours = Math.round(seconds / 3600);
  const duration = days >= 1
    ? Math.floor(days) + " дн." + (hours % 24 ? " " + (hours % 24) + " ч." : "")
    : Math.max(1, hours) + " ч.";
  const sign = delta >= 0 ? "+" : "−";
  return {
    delta, percent, bars, duration,
    text: sign + formatPrice(Math.abs(delta)) + " (" + sign + formatPrice(Math.abs(percent)) + "%) · " + bars + " бар · " + duration,
    fromLabel: fmtTime(points.from.time, intraday),
    toLabel: fmtTime(points.to.time, intraday),
  };
}

type Props = {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | ISeriesApi<"Area"> | null;
  candles: Candle[];
  measure: MeasurePoints | null;
  trend: MeasurePoints | null;
  intraday: boolean;
};

export default function ChartOverlays({ chart, series, candles, measure, trend, intraday }: Props) {
  const root = useRef<HTMLDivElement>(null);
  const draw = useRef<() => void>(() => {});

  // Функция отрисовки обновляется после каждого рендера: во время рендера ref-ы
  // трогать нельзя (React Compiler), а актуальные measure/trend/candles нужны
  // подписчику прокрутки, который живёт вне React.
  useEffect(() => {
    draw.current = () => {
    const host = root.current;
    if (!host || !series) return;
    const box = host.getBoundingClientRect();
    const x = (time: number) => chart.timeScale().timeToCoordinate(time as Time);
    const y = (price: number) => series.priceToCoordinate(price);
    const parts: string[] = [];

    if (measure) {
      const x1 = x(measure.from.time), y1 = y(measure.from.price), x2 = x(measure.to.time), y2 = y(measure.to.price);
      if (x1 != null && y1 != null && x2 != null && y2 != null) {
        const info = measureText(measure, candles, intraday);
        const up = info.delta >= 0;
        const color = up ? "#089981" : "#f23645";
        const left = Math.min(x1, x2), top = Math.min(y1, y2), width = Math.abs(x2 - x1), height = Math.abs(y2 - y1);
        parts.push('<div class="meas-box" style="left:' + left + "px;top:" + top + "px;width:" + width + "px;height:" + height + "px;border-color:" + color + ";background:" + (up ? "rgba(8,153,129,.10)" : "rgba(242,54,69,.10)") + '"></div>');
        parts.push('<div class="meas-line" style="left:' + x1 + "px;top:" + y1 + "px;width:" + Math.hypot(x2 - x1, y2 - y1) + "px;transform:rotate(" + Math.atan2(y2 - y1, x2 - x1) + 'rad);background:' + color + '"></div>');
        parts.push('<div class="meas-dot" style="left:' + x1 + "px;top:" + y1 + "px;border-color:" + color + '"></div>');
        parts.push('<div class="meas-dot" style="left:' + x2 + "px;top:" + y2 + "px;border-color:" + color + ";background:" + color + '"></div>');
        // Направляющие к осям: сразу видно, откуда и куда тянется измерение.
        parts.push('<div class="meas-guide" style="left:' + x1 + "px;top:0;height:" + y1 + "px;background:" + color + '"></div>');
        parts.push('<div class="meas-guide" style="left:' + x2 + "px;top:" + y2 + "px;height:" + Math.max(0, box.height - y2) + "px;background:" + color + '"></div>');
        // Подпись держим у второй точки и не даём ей уехать за край.
        const tipWidth = 210;
        const anchorX = Math.min(Math.max(x2 - 6, 6), Math.max(6, box.width - tipWidth));
        const anchorY = y2 > 70 ? y2 - 56 : Math.min(box.height - 46, y2 + 16);
        parts.push('<div class="meas-tip" style="left:' + anchorX + "px;top:" + anchorY + "px;border-color:" + color + '"><strong style="color:' + color + '">' + info.text + "</strong><span>" + info.fromLabel + " → " + info.toLabel + "</span></div>");
        parts.push('<div class="meas-price" style="left:' + x2 + "px;top:" + y2 + "px;background:" + color + '">' + formatPrice(measure.to.price) + "</div>");
        parts.push('<div class="meas-price" style="left:' + x1 + "px;top:" + y1 + "px;background:" + color + '">' + formatPrice(measure.from.price) + "</div>");
      }
    }

    if (trend) {
      const x1 = x(trend.from.time), y1 = y(trend.from.price), x2 = x(trend.to.time), y2 = y(trend.to.price);
      if (x1 != null && y1 != null && x2 != null && y2 != null) {
        const color = y2 < y1 ? "#26a69a" : "#ef5350";
        parts.push('<div class="trend-line" style="left:' + x1 + "px;top:" + y1 + "px;width:" + Math.hypot(x2 - x1, y2 - y1) + "px;transform:rotate(" + Math.atan2(y2 - y1, x2 - x1) + 'rad);background:' + color + '"></div>');
        parts.push('<div class="trend-handle" style="left:' + x1 + "px;top:" + y1 + "px;border-color:" + color + '"></div>');
        parts.push('<div class="trend-handle" style="left:' + x2 + "px;top:" + y2 + "px;border-color:" + color + ";background:" + color + '"></div>');
        const change = trend.from.price ? (trend.to.price / trend.from.price - 1) * 100 : 0;
        const trendLabel = formatPrice(trend.to.price) + " · " + (change >= 0 ? "+" : "−") + formatPrice(Math.abs(change)) + "%";
        parts.push('<div class="meas-guide" style="left:' + x1 + "px;top:0;height:" + y1 + "px;background:" + color + '"></div>');
        parts.push('<div class="meas-guide" style="left:' + x2 + "px;top:" + y2 + "px;height:" + Math.max(0, box.height - y2) + "px;background:" + color + '"></div>');
        parts.push('<div class="trend-tip" style="left:' + Math.min(Math.max(x2 + 10, 6), Math.max(6, box.width - 150)) + "px;top:" + Math.max(6, y2 - 20) + "px;border-color:" + color + '">' + trendLabel + "</div>");
      }
    }

    host.innerHTML = parts.join("");
    };
  }, [chart, series, candles, measure, trend, intraday]);

  useEffect(() => {
    const host = root.current;
    if (!host) return;
    const schedule = () => requestAnimationFrame(() => draw.current());
    schedule();
    chart.timeScale().subscribeVisibleLogicalRangeChange(schedule);
    window.addEventListener("resize", schedule);
    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(schedule);
      window.removeEventListener("resize", schedule);
      host.innerHTML = "";
    };
  }, [chart, series]);

  useEffect(() => { const id = requestAnimationFrame(() => draw.current()); return () => cancelAnimationFrame(id); }, [measure, trend, candles]);

  return <div className="chart-overlays" ref={root} aria-hidden="true"/>;
}
