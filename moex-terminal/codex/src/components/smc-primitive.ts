"use client";

// Примитив lightweight-charts: рисует зоны Order Blocks, FVG, линии уровней,
// подписи BOS/CHoCH и метки на ценовой шкале так же, как объекты box/line/label в Pine.
import type { ISeriesApi, ISeriesPrimitive, ISeriesPrimitiveAxisView, IPrimitivePaneRenderer, IPrimitivePaneView, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import type { SmcOverlay } from "@/lib/smc";

type Scope = SeriesAttachedParameter<Time, SeriesType>;

class SmcRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly owner: SmcPrimitive) {}
  drawBackground(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]): void { this.owner.paint(target, "boxes"); }
  draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]): void { this.owner.paint(target, "lines"); }
}

class SmcPaneView implements IPrimitivePaneView {
  private readonly own: SmcRenderer;
  constructor(private readonly owner: SmcPrimitive) { this.own = new SmcRenderer(owner); }
  zOrder(): "bottom" { return "bottom"; }
  renderer(): IPrimitivePaneRenderer { return this.own; }
}

export class SmcPrimitive implements ISeriesPrimitive<Time> {
  private scope: Scope | null = null;
  private readonly views: SmcPaneView[];
  private readonly axis: ISeriesPrimitiveAxisView[] = [];

  constructor(private readonly overlay: SmcOverlay) { this.views = [new SmcPaneView(this)]; }

  attached(param: Scope): void { this.scope = param; }
  detached(): void { this.scope = null; }
  updateAllViews(): void { /* Геометрия считается в момент отрисовки. */ }
  paneViews(): readonly IPrimitivePaneView[] { return this.views; }

  priceAxisViews(): readonly ISeriesPrimitiveAxisView[] {
    if (!this.scope) return this.axis;
    const series = this.scope.series as ISeriesApi<SeriesType>;
    this.axis.length = 0;
    // Показываем 4 ближайших к текущей цене подписи, чтобы шкала не превращалась в «столбик».
    const visiblePrice = this.overlay.lastPrice ?? this.overlay.lines[0]?.price ?? 0;
    const candidates = this.overlay.lines.filter(item => item.axisLabel)
      .sort((a, b) => Math.abs(a.price - visiblePrice) - Math.abs(b.price - visiblePrice));
    const labelled: typeof candidates = [];
    const taken: number[] = [];
    for (const line of candidates) {
      if (labelled.length >= 4) break;
      const position = series.priceToCoordinate(line.price);
      if (position == null) continue;
      if (taken.some(existing => Math.abs(existing - Number(position)) < 16)) continue;
      taken.push(Number(position));
      labelled.push(line);
    }
    for (const line of labelled.sort((a, b) => b.price - a.price)) {
      const current = series.priceToCoordinate(line.price);
      if (current == null) continue;
      this.axis.push({
        coordinate: () => Number(current),
        text: () => line.axisLabel ?? "",
        textColor: () => "#0b0e13",
        backColor: () => line.color,
        visible: () => true,
        tickVisible: () => true,
        fixedCoordinate: () => Number(current),
      });
    }
    return this.axis;
  }

  private x(time: number): number | null {
    if (!this.scope) return null;
    const coordinate = this.scope.chart.timeScale().timeToCoordinate(time as Time);
    return coordinate == null ? null : Number(coordinate);
  }

  private y(price: number): number | null {
    if (!this.scope) return null;
    const coordinate = (this.scope.series as ISeriesApi<SeriesType>).priceToCoordinate(price);
    return coordinate == null ? null : Number(coordinate);
  }

  paint(target: Parameters<IPrimitivePaneRenderer["draw"]>[0], layer: "boxes" | "lines"): void {
    if (!this.scope) return;
    const { boxes, lines, texts } = this.overlay;
    target.useBitmapCoordinateSpace(scope => {
      const ctx = scope.context;
      const hr = scope.horizontalPixelRatio, vr = scope.verticalPixelRatio;
      const width = scope.mediaSize.width * hr, height = scope.mediaSize.height * vr;
      const rightEdge = scope.bitmapSize.width;

      if (layer === "boxes") {
        for (const box of boxes) {
          const x1 = this.x(box.from);
          const y1 = this.y(box.top);
          const y2 = this.y(box.bottom);
          if (x1 == null || y1 == null || y2 == null) continue;
          const x2 = box.to == null ? rightEdge : this.x(box.to) ?? rightEdge;
          const left = Math.min(x1, x2) * hr;
          const boxWidth = Math.max(1, Math.abs(x2 - x1) * hr);
          const top = Math.min(y1, y2) * vr;
          const boxHeight = Math.max(1, Math.abs(y2 - y1) * vr);
          if (left > width || top > height) continue;
          ctx.fillStyle = box.fill;
          ctx.fillRect(left, top, boxWidth, boxHeight);
          ctx.strokeStyle = box.border;
          ctx.lineWidth = Math.max(1, (box.strong ? 2 : 1) * hr);
          ctx.strokeRect(left + ctx.lineWidth / 2, top + ctx.lineWidth / 2, boxWidth - ctx.lineWidth, boxHeight - ctx.lineWidth);
          if (box.label) {
            ctx.fillStyle = box.strong ? "#ffd400" : "#d1d4dc";
            ctx.font = `${Math.round(10 * hr)}px Inter, sans-serif`;
            ctx.textBaseline = "bottom";
            ctx.fillText(box.label, left + 4 * hr, top + (y1 > y2 ? boxHeight : 0) + (y1 > y2 ? -2 * hr : 10 * hr));
          }
        }
        return;
      }

      for (const line of lines) {
        const x1 = this.x(line.from);
        const y1 = this.y(line.price);
        if (x1 == null || y1 == null) continue;
        const x2 = line.to == null ? rightEdge : this.x(line.to) ?? rightEdge;
        ctx.strokeStyle = line.color;
        ctx.lineWidth = Math.max(1, line.width * hr);
        ctx.setLineDash(line.style === "solid" ? [] : line.style === "dashed" ? [5 * hr, 4 * hr] : [1 * hr, 3 * hr]);
        ctx.beginPath();
        ctx.moveTo(x1 * hr, y1 * vr);
        ctx.lineTo(Math.max(x1, x2) * hr, y1 * vr);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      for (const text of texts) {
        const x = this.x(text.time);
        const y = this.y(text.price);
        if (x == null || y == null) continue;
        ctx.fillStyle = text.color;
        ctx.font = `${Math.round(10 * hr)}px Inter, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = text.above ? "bottom" : "top";
        ctx.fillText(text.text, x * hr, text.above ? y * vr - 3 * vr : y * vr + 3 * vr);
      }
      ctx.textAlign = "start";
    });
  }
}
