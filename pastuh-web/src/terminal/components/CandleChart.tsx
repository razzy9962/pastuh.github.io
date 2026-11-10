import { useEffect, useRef, useState } from "react";
import type { Candle, Stock, TrackedPos } from "../types";

interface Props {
  candles: Candle[];
  signal?: Stock | null;
  position?: TrackedPos | null;
  className?: string;
  height?: number;
  onLevelDragEnd?: (type: "tp" | "sl", price: number) => void;
}

interface Layers {
  poc: boolean;
  ema: boolean;
  tpsl: boolean;
  cumd: boolean;
}

const C = {
  bg: "#090d14",
  axisPanel: "rgba(11,16,26,0.96)",
  grid: "rgba(255,255,255,0.04)",
  tick: "rgba(255,255,255,0.16)",
  axisText: "#697b92",
  bull: "#00f076",
  bear: "#ff3358",
  cyan: "#38bdf8",
  amber: "#f59e0b",
  gray: "#cbd5e1",
  gold: "#facc15",
  purple: "#a855f7",
  mono: "'JetBrains Mono', monospace",
};

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const num = (v: unknown): number | null => (typeof v === "number" && isFinite(v) ? v : null);

const fmtLots = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return v.toFixed(0);
};

/**
 * График в точности по движку оригинала (drawSniperChart):
 * POC-профиль объёма, уровни S/R, EMA 20/50/200, зоны и бейджи TP/SL/ВХОД,
 * каскадные тейки, Б/У, трейлинг, cum-дельта на цене, нижняя панель CVD-свечей,
 * перекрестие, зум колесом, панорама и drag TP/SL.
 */
export default function CandleChart({
  candles,
  signal,
  position,
  className,
  height = 400,
  onLevelDragEnd,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [layers, setLayers] = useState<Layers>({ poc: true, ema: true, tpsl: true, cumd: true });

  const layersRef = useRef(layers);
  layersRef.current = layers;

  // view-state в refs — пан/зум/курсор без React-рендеров
  const view = useRef({ first: NaN, count: 60 });
  const mouse = useRef<{ x: number; y: number } | null>(null);
  const dragLevel = useRef<null | { type: "tp" | "sl"; price: number; moved: boolean }>(null);
  const dragPan = useRef<null | { x: number; first: number }>(null);
  const hoverKind = useRef<null | "tp" | "sl">(null);
  const drawRef = useRef<() => void>(() => {});
  const geomRef = useRef<any>(null);

  // сброс вида при смене бумаги
  useEffect(() => {
    view.current = { first: NaN, count: 60 };
    mouse.current = null;
  }, [signal?.ticker]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let W = 0;
    let H = 0;

    const rr = (x: number, y: number, w: number, h: number, r: number) => {
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, r);
    };

    const draw = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = C.bg;
      ctx.fillRect(0, 0, W, H);
      ctx.lineWidth = 1;
      ctx.textAlign = "left";

      const total = candles.length;
      if (!total) {
        ctx.fillStyle = "#8b9bb4";
        ctx.font = `12px ${C.mono}`;
        ctx.textAlign = "center";
        ctx.fillText("Загрузка свечей, профиля объёма POC и ленты CVD…", W / 2, H / 2);
        ctx.textAlign = "left";
        return;
      }

      // ---- видимое окно (zoom/pan) ----
      const v = view.current;
      if (isNaN(v.first)) {
        v.count = Math.min(60, total);
        v.first = total - v.count;
      }
      v.count = clamp(v.count, 14, total + 40);
      v.first = clamp(v.first, -v.count * 0.6, Math.max(total - 4, total - v.count * 0.15));

      // ---- геометрия ----
      const padL = 46;
      const padR = 80;
      const padT = 14;
      const padB = 18;
      const availH = Math.max(240, H - padT - padB);
      const cvdH = clamp(Math.floor(availH * 0.26), 84, 150);
      const priceH = availH - cvdH - 16;
      const cvdTop = padT + priceH + 14;
      const plotW = W - padL - padR;

      const L = layersRef.current;
      const s = signal ?? null;
      const myPos = position ?? null;

      const tradeSide: "LONG" | "SHORT" = myPos
        ? (myPos.side as "LONG" | "SHORT")
        : s?.verdict === "SHORT"
          ? "SHORT"
          : ((s?.calc_side as "LONG" | "SHORT") || "LONG");
      const tradeEntry = myPos ? Number(myPos.entry || 0) : Number(s?.entry || s?.price || 0);
      let tradeTp = myPos ? Number(myPos.tp || 0) : Number(s?.tp || 0);
      let tradeSl = myPos ? Number(myPos.sl || 0) : Number(s?.sl || 0);
      if (dragLevel.current) {
        if (dragLevel.current.type === "tp") tradeTp = dragLevel.current.price;
        else tradeSl = dragLevel.current.price;
      }

      // видимые свечи со слотами
      const stepF = plotW / v.count;
      const cw = Math.max(1.4, stepF * 0.64);
      const vis: { c: Candle; slot: number }[] = [];
      for (let slot = 0; slot < v.count; slot++) {
        const idx = Math.round(v.first) + slot;
        if (idx >= 0 && idx < total) vis.push({ c: candles[idx], slot });
      }
      if (!vis.length) return;
      const visC = vis.map((x) => x.c);

      // диапазон цен
      const extra = L.tpsl ? [tradeEntry, tradeTp, tradeSl].filter((x) => x > 0) : [];
      const allP = visC.flatMap((c) => [c.low, c.high]).concat(extra).filter((x) => x > 0);
      let minP = Math.min(...allP);
      let maxP = Math.max(...allP);
      const pad = (maxP - minP || maxP * 0.02 || 1) * 0.045;
      minP -= pad;
      maxP += pad;

      const pToY = (p: number) => padT + priceH - ((p - minP) / Math.max(maxP - minP, 1e-9)) * priceH;
      const yToP = (y: number) => maxP - ((y - padT) / priceH) * (maxP - minP);
      const xOf = (slot: number) => padL + slot * stepF + stepF / 2;

      geomRef.current = { padL, padR, padT, padB, priceH, cvdTop, cvdH, plotW, pToY, yToP };

      // ================= ПРАВАЯ ШКАЛА ЦЕН (nice step) =================
      ctx.fillStyle = C.axisPanel;
      ctx.fillRect(W - padR, padT, padR, cvdTop + cvdH - padT);
      ctx.strokeStyle = "rgba(255,255,255,0.08)";
      ctx.beginPath();
      ctx.moveTo(W - padR, padT);
      ctx.lineTo(W - padR, cvdTop + cvdH);
      ctx.stroke();

      const range = maxP - minP;
      const target = clamp(Math.floor(priceH / 34), 6, 10);
      const rough = range / target;
      const mag = Math.pow(10, Math.floor(Math.log10(rough || 1)));
      const norm = rough / mag;
      const nice = norm >= 5 ? 5 * mag : norm >= 2 ? 2 * mag : norm >= 1 ? mag : 0.5 * mag;
      const firstTick = Math.ceil(minP / nice) * nice;
      ctx.font = `9.5px ${C.mono}`;
      for (let p = firstTick; p <= maxP; p += nice) {
        const y = pToY(p);
        if (y < padT + 6 || y > padT + priceH - 6) continue;
        ctx.strokeStyle = C.grid;
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(W - padR, y);
        ctx.stroke();
        ctx.strokeStyle = C.tick;
        ctx.beginPath();
        ctx.moveTo(W - padR, y);
        ctx.lineTo(W - padR + 4, y);
        ctx.stroke();
        ctx.fillStyle = C.axisText;
        ctx.fillText(p >= 1000 ? p.toFixed(1) : p.toFixed(2), W - padR + 7, y + 3.5);
      }

      // ================= РАЗДЕЛИТЕЛИ ДНЕЙ =================
      ctx.font = `700 9px ${C.mono}`;
      for (let i = 1; i < visC.length; i++) {
        const dp = (visC[i - 1].time || "").split(" ")[0];
        const dc = (visC[i].time || "").split(" ")[0];
        if (dc && dp && dc !== dp) {
          const x = xOf(vis[i].slot);
          ctx.strokeStyle = "rgba(56,189,248,0.28)";
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.moveTo(x, padT);
          ctx.lineTo(x, cvdTop + cvdH);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = C.cyan;
          ctx.fillText(dc, x + 4, padT + 10);
        }
      }

      // ================= ЦЕНОВАЯ ОБЛАСТЬ (клип) =================
      ctx.save();
      ctx.beginPath();
      ctx.rect(padL, padT, plotW, priceH);
      ctx.clip();

      // ---- POC + профиль объёма ----
      if (L.poc) {
        const bins = 26;
        const binVol = new Array(bins).fill(0) as number[];
        const binNet = new Array(bins).fill(0) as number[];
        visC.forEach((c) => {
          const idx = clamp(Math.floor(((c.close - minP) / (maxP - minP)) * bins), 0, bins - 1);
          binVol[idx] += c.vol || 0;
          binNet[idx] += num(c.delta) ?? 0;
        });
        const maxV = Math.max(...binVol, 1);
        const pocIdx = binVol.indexOf(maxV);
        const pocPrice = s?.sr_levels?.poc && s.sr_levels.poc > 0
          ? s.sr_levels.poc
          : minP + ((pocIdx + 0.5) / bins) * (maxP - minP);
        for (let b = 0; b < bins; b++) {
          const bw = (binVol[b] / maxV) * plotW * 0.22;
          if (bw < 0.5) continue;
          const by = padT + priceH - ((b + 1) / bins) * priceH;
          const bh = (priceH / bins) * 0.84;
          ctx.fillStyle =
            b === pocIdx
              ? "rgba(250,204,21,0.38)"
              : binNet[b] >= 0
                ? "rgba(0,240,118,0.16)"
                : "rgba(255,51,88,0.16)";
          ctx.fillRect(padL, by, bw, bh);
        }
        if (pocPrice >= minP && pocPrice <= maxP) {
          const y = pToY(pocPrice);
          ctx.strokeStyle = C.gold;
          ctx.lineWidth = 1.3;
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.moveTo(padL, y);
          ctx.lineTo(W - padR, y);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = C.gold;
          ctx.font = `700 9.5px ${C.mono}`;
          ctx.fillText(`POC ${pocPrice.toFixed(2)}`, padL + 5, y - 4);
        }
      }

      // ---- S/R уровни ----
      const sr = s?.sr_levels;
      if (sr?.res1_price && sr.res1_price > minP && sr.res1_price < maxP) {
        const y = pToY(sr.res1_price);
        ctx.strokeStyle = "rgba(255,51,88,0.6)";
        ctx.setLineDash([5, 3]);
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(W - padR, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#fda4af";
        ctx.font = `9.5px ${C.mono}`;
        ctx.fillText(`Сопр ${sr.res1_price}`, padL + plotW * 0.66, y - 4);
      }
      if (sr?.sup1_price && sr.sup1_price > minP && sr.sup1_price < maxP) {
        const y = pToY(sr.sup1_price);
        ctx.strokeStyle = "rgba(0,240,118,0.6)";
        ctx.setLineDash([5, 3]);
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(W - padR, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#6ee7b7";
        ctx.font = `9.5px ${C.mono}`;
        ctx.fillText(`Подд ${sr.sup1_price}`, padL + plotW * 0.66, y + 11);
      }

      // ---- объёмы ----
      const maxVol = Math.max(...visC.map((c) => c.vol || 0), 1);
      const volH = priceH * 0.15;
      for (const { c, slot } of vis) {
        const up = c.close >= c.open;
        const vh = ((c.vol || 0) / maxVol) * volH;
        ctx.fillStyle = up ? "rgba(0,240,118,0.22)" : "rgba(255,51,88,0.22)";
        ctx.fillRect(xOf(slot) - cw / 2, padT + priceH - vh, cw, vh);
      }

      // ---- свечи ----
      for (const { c, slot } of vis) {
        const x = xOf(slot);
        const up = c.close >= c.open;
        const col = up ? C.bull : C.bear;
        ctx.strokeStyle = col;
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.moveTo(x, pToY(c.high));
        ctx.lineTo(x, pToY(c.low));
        ctx.stroke();
        const t = pToY(Math.max(c.open, c.close));
        const b = pToY(Math.min(c.open, c.close));
        ctx.fillRect(x - cw / 2, t, cw, Math.max(1.4, b - t));
      }

      // ---- EMA 20/50/200 ----
      if (L.ema) {
        const line = (key: "ema20" | "ema50" | "ema200", alt: "EMA20" | "EMA50" | "EMA200", color: string, dashed = false) => {
          ctx.strokeStyle = color;
          ctx.lineWidth = 1.4;
          if (dashed) ctx.setLineDash([3, 3]);
          ctx.beginPath();
          let started = false;
          for (const { c, slot } of vis) {
            const val = num(c[key]) ?? num(c[alt]);
            if (val == null) continue;
            const x = xOf(slot);
            const y = pToY(val);
            if (!started) {
              ctx.moveTo(x, y);
              started = true;
            } else ctx.lineTo(x, y);
          }
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.lineWidth = 1;
        };
        line("ema20", "EMA20", C.cyan);
        line("ema50", "EMA50", C.amber);
        line("ema200", "EMA200", C.gray, true);
      }

      // ---- cum-дельта поверх цены ----
      if (L.cumd) {
        const cumVals = visC.flatMap((c) => [num(c.cum_delta) ?? 0, num(c.tape_cum_delta) ?? 0]);
        const cMin = Math.min(...cumVals, 0);
        const cMax = Math.max(...cumVals, 1);
        const cToY = (vv: number) => padT + priceH - ((vv - cMin) / Math.max(cMax - cMin, 1e-9)) * priceH;
        if (visC.some((c) => c.cum_delta != null)) {
          ctx.strokeStyle = C.purple;
          ctx.lineWidth = 1.7;
          ctx.beginPath();
          vis.forEach(({ c, slot }, i) => {
            const y = cToY(num(c.cum_delta) ?? 0);
            if (i === 0) ctx.moveTo(xOf(slot), y);
            else ctx.lineTo(xOf(slot), y);
          });
          ctx.stroke();
          ctx.lineWidth = 1;
        }
        if (visC.some((c) => c.tape_cum_delta != null)) {
          ctx.strokeStyle = C.gold;
          ctx.lineWidth = 1.1;
          ctx.setLineDash([4, 3]);
          ctx.beginPath();
          vis.forEach(({ c, slot }, i) => {
            const y = cToY(num(c.tape_cum_delta) ?? 0);
            if (i === 0) ctx.moveTo(xOf(slot), y);
            else ctx.lineTo(xOf(slot), y);
          });
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }

      // ================= TP / SL / ВХОД =================
      let tpY: number | null = null;
      let slY: number | null = null;
      const entryY = L.tpsl && tradeEntry > 0 ? pToY(tradeEntry) : null;
      if (entryY !== null) {
        if (tradeTp > 0) tpY = pToY(tradeTp);
        if (tradeSl > 0) slY = pToY(tradeSl);

        // зоны профита/убытка
        if (tpY !== null) {
          ctx.fillStyle = "rgba(0,240,118,0.08)";
          ctx.fillRect(padL, Math.min(entryY, tpY), plotW, Math.abs(entryY - tpY));
        }
        if (slY !== null) {
          ctx.fillStyle = "rgba(255,51,88,0.08)";
          ctx.fillRect(padL, Math.min(entryY, slY), plotW, Math.abs(entryY - slY));
        }

        // линия входа
        ctx.strokeStyle = C.cyan;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(padL, entryY);
        ctx.lineTo(W - padR, entryY);
        ctx.stroke();
        ctx.lineWidth = 1;
        ctx.fillStyle = C.cyan;
        ctx.font = `700 9.5px ${C.mono}`;
        ctx.fillText(`${myPos ? "МОЙ ВХОД" : "ВХОД"} ${tradeEntry.toFixed(2)} ₽`, padL + 8, entryY - 5);

        // бейджи TP/SL (drag-мишени)
        const badge = (
          y: number,
          color: string,
          dark: string,
          bright: string,
          hot: boolean,
          text: string
        ) => {
          ctx.strokeStyle = hot ? bright : color;
          ctx.lineWidth = hot ? 2.4 : 1.5;
          ctx.setLineDash([4, 3]);
          ctx.beginPath();
          ctx.moveTo(padL, y);
          ctx.lineTo(W - padR, y);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.lineWidth = 1;
          ctx.font = `700 9.5px ${C.mono}`;
          const tw = ctx.measureText(text).width;
          const bx = W - padR - tw - 14;
          ctx.fillStyle = hot ? color : dark;
          ctx.strokeStyle = color;
          rr(bx, y - 9.5, tw + 10, 19, 4);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = hot ? "#041008" : bright;
          ctx.fillText(text, bx + 5, y + 3.5);
          geomRef.current[`${text.startsWith("TP") ? "tp" : "sl"}Badge`] = { bx, by: y - 9.5, bw: tw + 10, y };
        };

        if (tpY !== null) {
          const dp = tradeEntry > 0 ? ((tradeTp - tradeEntry) / tradeEntry) * 100 * (tradeSide === "SHORT" ? -1 : 1) : 0;
          badge(
            tpY,
            C.bull,
            "rgba(10,28,18,0.92)",
            "#55ff99",
            hoverKind.current === "tp" || dragLevel.current?.type === "tp",
            `TP: ${tradeTp.toFixed(2)} ₽ (${dp >= 0 ? "+" : ""}${dp.toFixed(2)}%)`
          );
        }
        if (slY !== null) {
          const dp = tradeEntry > 0 ? ((tradeSl - tradeEntry) / tradeEntry) * 100 * (tradeSide === "SHORT" ? -1 : 1) : 0;
          badge(
            slY,
            C.bear,
            "rgba(35,12,18,0.92)",
            "#ff6685",
            hoverKind.current === "sl" || dragLevel.current?.type === "sl",
            `SL: ${tradeSl.toFixed(2)} ₽ (${dp >= 0 ? "+" : ""}${dp.toFixed(2)}%)`
          );
        }

        // каскадные тейки позиции
        const cascade = myPos?.take_profits?.filter((t) => Number(t.price) > 0) ?? [];
        cascade.forEach((t, i) => {
          const y = pToY(Number(t.price));
          const hit = Boolean(t.hit);
          ctx.strokeStyle = hit ? "rgba(0,240,118,0.45)" : C.bull;
          ctx.lineWidth = hit ? 1 : 1.4;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(padL, y);
          ctx.lineTo(W - padR, y);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = hit ? "#8b9bb4" : C.bull;
          ctx.font = `700 8.5px ${C.mono}`;
          ctx.fillText(`TP${i + 1} (${t.pct}%): ${Number(t.price).toFixed(2)} ₽`, padL + plotW * 0.4, y - 4);
        });

        // безубыток
        if (myPos && (myPos.is_be || myPos.partial_taken)) {
          ctx.strokeStyle = C.cyan;
          ctx.setLineDash([4, 2]);
          ctx.beginPath();
          ctx.moveTo(padL, entryY);
          ctx.lineTo(W - padR, entryY);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = C.cyan;
          ctx.font = `700 8.5px ${C.mono}`;
          ctx.fillText("Б/У (безубыток)", padL + plotW * 0.62, entryY + 12);
        }

        // трейлинг-стоп
        const trailStop = num(myPos?.trail_stop);
        if (myPos?.tp_trailed && trailStop && trailStop > 0) {
          const y = pToY(trailStop);
          ctx.strokeStyle = C.gold;
          ctx.lineWidth = 1.6;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(padL, y);
          ctx.lineTo(W - padR, y);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.lineWidth = 1;
          ctx.fillStyle = C.gold;
          ctx.font = `700 8.5px ${C.mono}`;
          ctx.fillText(`Трейлинг: ${trailStop.toFixed(2)} ₽`, padL + plotW * 0.55, y - 4);
        }
      }

      // ---- плашка позиции ----
      if (myPos && entryY !== null) {
        const pnl = myPos.pnl_pct ?? 0;
        const y0 = padT + 8;
        ctx.fillStyle = "rgba(15,23,42,0.9)";
        ctx.strokeStyle = "rgba(56,189,248,0.4)";
        rr(padL + 8, y0, 252, 24, 6);
        ctx.fill();
        ctx.stroke();
        ctx.font = `700 10px ${C.mono}`;
        ctx.fillStyle = "#ffffff";
        ctx.fillText("ПОЗИЦИЯ:", padL + 16, y0 + 15.5);
        ctx.fillStyle = myPos.side === "LONG" ? C.bull : C.bear;
        ctx.fillText(String(myPos.side), padL + 82, y0 + 15.5);
        ctx.fillStyle = "#8b9bb4";
        ctx.fillText("· PnL:", padL + 122, y0 + 15.5);
        ctx.fillStyle = pnl >= 0 ? C.bull : C.bear;
        ctx.fillText(`${pnl >= 0 ? "+" : ""}${Number(pnl).toFixed(2)}%`, padL + 162, y0 + 15.5);
      }

      ctx.restore(); // конец ценовой области

      // ================= ТЕКУЩАЯ ЦЕНА: линия + бейдж =================
      const last = visC[visC.length - 1];
      const curY = pToY(last.close);
      if (curY > padT && curY < padT + priceH) {
        const curCol = last.close >= last.open ? C.bull : C.bear;
        ctx.strokeStyle = curCol;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(padL, curY);
        ctx.lineTo(W - padR, curY);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = curCol;
        ctx.fillRect(W - padR, curY - 9, padR - 2, 18);
        ctx.fillStyle = "#041008";
        ctx.font = `700 10px ${C.mono}`;
        ctx.fillText(last.close.toFixed(2), W - padR + 6, curY + 3.5);
      }

      // ================= ПЕРЕКРЕСТИЕ =================
      const m = mouse.current;
      if (m && m.x >= padL && m.x <= W - padR && m.y >= padT && m.y <= cvdTop + cvdH) {
        ctx.strokeStyle = "rgba(255,255,255,0.4)";
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(padL, m.y);
        ctx.lineTo(W - padR, m.y);
        ctx.moveTo(m.x, padT);
        ctx.lineTo(m.x, cvdTop + cvdH);
        ctx.stroke();
        ctx.setLineDash([]);
        if (m.y <= padT + priceH) {
          const cp = yToP(m.y);
          ctx.fillStyle = C.cyan;
          ctx.fillRect(W - padR, m.y - 9, padR - 2, 18);
          ctx.fillStyle = "#041017";
          ctx.font = `700 10px ${C.mono}`;
          ctx.fillText(cp.toFixed(2), W - padR + 6, m.y + 3.5);
          // OHLC легенда сверху
          const slot = clamp(Math.round(((m.x - padL) / plotW) * v.count - 0.5), 0, v.count - 1);
          const item = vis.find((x) => x.slot === Math.round(slot)) ?? vis[vis.length - 1];
          if (item) {
            const c = item.c;
            const chg = ((c.close - c.open) / c.open) * 100;
            const t = `${c.time || ""}  O ${c.open.toFixed(2)}  H ${c.high.toFixed(2)}  L ${c.low.toFixed(2)}  C ${c.close.toFixed(2)}  ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`;
            ctx.font = `9.5px ${C.mono}`;
            const tw = ctx.measureText(t).width;
            ctx.fillStyle = "rgba(9,13,20,0.92)";
            ctx.fillRect(padL + 6, padT + 5, tw + 12, 16);
            ctx.strokeStyle = "rgba(255,255,255,0.12)";
            ctx.strokeRect(padL + 6, padT + 5, tw + 12, 16);
            ctx.fillStyle = chg >= 0 ? "#7dffb8" : "#ff9db2";
            ctx.fillText(t, padL + 12, padT + 16.5);
          }
        }
      }

      // ================= ПАНЕЛЬ CVD =================
      ctx.strokeStyle = "rgba(255,255,255,0.12)";
      ctx.beginPath();
      ctx.moveTo(padL, cvdTop - 6);
      ctx.lineTo(W - padR, cvdTop - 6);
      ctx.stroke();
      ctx.fillStyle = C.cyan;
      ctx.font = `700 9.5px ${C.mono}`;
      ctx.fillText("CVD ДЕЛЬТА", padL + 2, cvdTop + 6);
      ctx.fillStyle = C.axisText;
      ctx.font = `9px ${C.mono}`;
      ctx.fillText("свечной поток ордеров · серые = оценочные", padL + 78, cvdTop + 6);

      const cLows = visC.map((c) => num(c.cvd_low) ?? num(c.cvd_close) ?? 0);
      const cHighs = visC.map((c) => num(c.cvd_high) ?? num(c.cvd_close) ?? 0);
      const minC = Math.min(...cLows, -10);
      const maxC = Math.max(...cHighs, 10);
      const cToY = (vv: number) => cvdTop + 14 + (cvdH - 18) - ((vv - minC) / Math.max(maxC - minC, 1e-9)) * (cvdH - 18);

      // ноль
      const zy = cToY(0);
      ctx.strokeStyle = "rgba(56,189,248,0.35)";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(padL, zy);
      ctx.lineTo(W - padR, zy);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = `9px ${C.mono}`;
      ctx.fillStyle = C.cyan;
      ctx.fillText("0", W - padR + 6, zy + 3);
      ctx.fillStyle = C.bull;
      ctx.fillText(`+${fmtLots(maxC)}`, W - padR + 6, cvdTop + 24);
      ctx.fillStyle = C.bear;
      ctx.fillText(fmtLots(minC), W - padR + 6, cvdTop + cvdH - 2);

      // CVD-свечи
      ctx.save();
      ctx.beginPath();
      ctx.rect(padL, cvdTop, plotW, cvdH);
      ctx.clip();
      const covThr = 0.5; // как candle_cov_pct по умолчанию
      for (const { c, slot } of vis) {
        const co = num(c.cvd_open) ?? num(c.cvd_close) ?? 0;
        const cc = num(c.cvd_close) ?? co;
        const ch = num(c.cvd_high) ?? Math.max(co, cc);
        const cl = num(c.cvd_low) ?? Math.min(co, cc);
        const up = cc >= co;
        const lowCov = (num(c.tape_cov) ?? 1) < covThr;
        const col = lowCov ? (up ? "#64748b" : "#475569") : up ? C.bull : C.bear;
        const x = xOf(slot);
        ctx.strokeStyle = col;
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.moveTo(x, cToY(ch));
        ctx.lineTo(x, cToY(cl));
        ctx.stroke();
        const t = cToY(Math.max(co, cc));
        const b = cToY(Math.min(co, cc));
        ctx.fillRect(x - cw / 2, t, cw, Math.max(1.4, b - t));
      }
      ctx.restore();

      // ---- время снизу ----
      ctx.fillStyle = C.axisText;
      ctx.font = `9px ${C.mono}`;
      const ticks = Math.min(8, vis.length);
      for (let t = 0; t < ticks; t++) {
        const item = vis[Math.floor((t / Math.max(1, ticks - 1)) * (vis.length - 1))];
        if (!item) break;
        const x = xOf(item.slot);
        if (x > W - padR - 40) continue;
        ctx.fillText((item.c.time || "").split(" ").pop() || "", Math.max(padL, x - 14), H - 5);
      }
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const r = canvas.getBoundingClientRect();
      W = Math.max(1, r.width);
      H = Math.max(1, r.height);
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      draw();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    // ---------- анти-лаг: перерисовка только по необходимости через rAF ----------
    let raf = 0;
    const redraw = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        draw();
      });
    };

    const pos = (e: PointerEvent | WheelEvent) => {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };

    const overLevel = (p: { x: number; y: number }): "tp" | "sl" | null => {
      const g = geomRef.current;
      if (!g) return null;
      // магнит к линии по Y (±7px) в пределах ценовой области
      if (p.x < g.padL || p.x > g.padL + g.plotW) return null;
      for (const key of ["tp", "sl"] as const) {
        const b = g[`${key}Badge`];
        if (b && Math.abs(p.y - b.y) <= 8) return key;
      }
      return null;
    };

    const onDown = (e: PointerEvent) => {
      const p = pos(e);
      canvas.setPointerCapture(e.pointerId);
      const lvl = overLevel(p);
      if (lvl && onLevelDragEnd) {
        dragLevel.current = { type: lvl, price: 0, moved: false };
      } else {
        dragPan.current = { x: p.x, first: view.current.first };
      }
    };

    const onMove = (e: PointerEvent) => {
      const p = pos(e);
      mouse.current = p;
      const g = geomRef.current;
      if (dragLevel.current && g) {
        dragLevel.current.price = g.yToP(clamp(p.y, g.padT, g.padT + g.priceH));
        dragLevel.current.moved = true;
        canvas.style.cursor = "ns-resize";
      } else if (dragPan.current && g) {
        const dx = p.x - dragPan.current.x;
        const step = g.plotW / view.current.count;
        view.current.first = dragPan.current.first - dx / Math.max(step, 0.5);
        canvas.style.cursor = "grabbing";
      } else {
        hoverKind.current = overLevel(p);
        canvas.style.cursor = hoverKind.current && onLevelDragEnd ? "ns-resize" : "crosshair";
      }
      redraw();
    };

    const onUp = (e: PointerEvent) => {
      if (dragLevel.current) {
        const d = dragLevel.current;
        dragLevel.current = null;
        if (d.moved && onLevelDragEnd && d.price > 0) onLevelDragEnd(d.type, +d.price.toFixed(4));
      }
      dragPan.current = null;
      canvas.style.cursor = "crosshair";
      try {
        canvas.releasePointerCapture(e.pointerId);
      } catch {
        /* noop */
      }
      redraw();
    };

    const onLeave = () => {
      mouse.current = null;
      redraw();
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const g = geomRef.current;
      if (!g) return;
      const p = pos(e);
      const frac = clamp((p.x - g.padL) / g.plotW, 0, 1);
      const v = view.current;
      const anchor = v.first + frac * v.count;
      v.count = clamp(v.count * (e.deltaY > 0 ? 1.12 : 0.89), 14, candles.length + 40);
      v.first = anchor - frac * v.count;
      redraw();
    };

    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointerleave", onLeave);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    drawRef.current = draw;
    draw();

    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("wheel", onWheel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, signal, position, height, onLevelDragEnd]);

  const chip = (key: keyof Layers, label: string) => (
    <button
      key={key}
      onClick={() => {
        setLayers((l) => ({ ...l, [key]: !l[key] }));
        requestAnimationFrame(() => drawRef.current());
      }}
      className={`rounded-md border px-2.5 py-1 font-mono text-[9px] tracking-wider transition-colors ${
        layers[key]
          ? "border-neon/45 bg-neon/12 text-neon"
          : "border-line bg-white/[0.03] text-smoke hover:text-fog"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className={`relative ${className ?? ""}`} style={{ height }}>
      <canvas ref={canvasRef} className="block h-full w-full touch-none" style={{ cursor: "crosshair" }} />
      <div className="absolute right-[86px] top-2 flex gap-1">
        {chip("poc", "POC+Объём")}
        {chip("ema", "EMA")}
        {chip("tpsl", "TP/SL")}
        {chip("cumd", "CumΔ")}
      </div>
    </div>
  );
}
