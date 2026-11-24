"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";
import { TIMEFRAMES } from "@/lib/market";
import { DEFAULT_SMC, SMC_PALETTE, type SmcSettings } from "@/lib/smc";

type Props = { open: boolean; settings: SmcSettings; overlay: { stats: Record<string, unknown> } | null; onChange: (settings: SmcSettings) => void; onClose: () => void };

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="smc-section"><h4>{title}</h4>{children}</section>;
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="smc-toggle"><input type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)}/><span/>{label}</label>;
}

function NumberField({ label, value, min, max, step = 1, onChange }: { label: string; value: number; min: number; max: number; step?: number; onChange: (value: number) => void }) {
  return <label className="smc-number"><span>{label}</span><input type="number" value={value} min={min} max={max} step={step} onChange={event => { const next = Number(event.target.value); if (Number.isFinite(next)) onChange(Math.min(max, Math.max(min, next))); }}/></label>;
}

export default function SmcPanel({ open, settings, overlay, onChange, onClose }: Props) {
  if (!open) return null;
  const patch = (change: (draft: SmcSettings) => void) => { const draft = structuredClone(settings); change(draft); onChange(draft); };
  const stats = (overlay?.stats ?? {}) as { bias?: number; premiumDiscountZone?: string | null; support?: number | null; resistance?: number | null; poc?: number | null; fvgCount?: number; obCount?: number; internalObCount?: number; aplusBuy?: { wins: number; losses: number }; aplusSell?: { wins: number; losses: number }; created?: number; removed?: number };

  return <aside className="smc-panel" aria-label="Настройки SMC Pro">
    <header className="smc-panel-head"><div><strong>SMC Pro</strong><span>Smart Money Concepts · LuxAlgo OB</span></div><button className="icon-button" aria-label="Закрыть настройки" onClick={onClose}><X size={15}/></button></header>
    <div className="smc-panel-body">
      <Section title="Отображение">
        <Toggle label="Индикатор включён" checked={settings.enabled} onChange={value => patch(draft => { draft.enabled = value; })}/>
        <div className="smc-chips">
          <button className={`smc-chip ${stats.bias === 1 ? "bull" : stats.bias === -1 ? "bear" : ""}`}>{stats.bias === 1 ? "▲ бычья структура" : stats.bias === -1 ? "▼ медвежья структура" : "— нет структуры"}</button>
          <button className="smc-chip">{stats.premiumDiscountZone === "premium" ? "премиум" : stats.premiumDiscountZone === "discount" ? "дисконт" : stats.premiumDiscountZone === "equilibrium" ? "равновесие" : "диапазон н/д"}</button>
        </div>
        <div className="smc-readout">
          <span>Поддержка<b>{stats.support != null ? stats.support.toFixed(2) : "—"}</b></span>
          <span>Сопротивление<b>{stats.resistance != null ? stats.resistance.toFixed(2) : "—"}</b></span>
          <span>POC<b>{stats.poc != null ? stats.poc.toFixed(2) : "—"}</b></span>
          <span>Зоны OB<b>{`${stats.obCount ?? 0}+${stats.internalObCount ?? 0}`}</b></span>
          <span>FVG<b>{stats.fvgCount ?? 0}</b></span>
          <span>A+ BUY / SELL<b>{`${stats.aplusBuy?.wins ?? 0}/${(stats.aplusBuy?.wins ?? 0) + (stats.aplusBuy?.losses ?? 0)} · ${stats.aplusSell?.wins ?? 0}/${(stats.aplusSell?.wins ?? 0) + (stats.aplusSell?.losses ?? 0)}`}</b></span>
          <span>Создано / снято<b>{`${stats.created ?? 0} / ${stats.removed ?? 0}`}</b></span>
        </div>
      </Section>

      <Section title="Структура BOS / CHoCH">
        <label className="smc-select"><span>Движок</span><select value={settings.structure.mode} onChange={event => patch(draft => { draft.structure.mode = event.target.value as SmcSettings["structure"]["mode"]; })}><option value="luxalgo">LuxAlgo (как у OB)</option><option value="pivot">Симметричные пивоты</option></select></label>
        <NumberField label="Swing: баров слева/справа" value={settings.structure.swingLegs} min={1} max={50} onChange={value => patch(draft => { draft.structure.swingLegs = value; })}/>
        <NumberField label="Internal: баров слева/справа" value={settings.structure.internalLegs} min={1} max={20} onChange={value => patch(draft => { draft.structure.internalLegs = value; })}/>
        <NumberField label="Мин. смещение пробоя, ATR" value={settings.structure.displacementAtr} min={0} max={2} step={0.05} onChange={value => patch(draft => { draft.structure.displacementAtr = value; })}/>
        <NumberField label="Держать последних структур" value={settings.structure.keep} min={1} max={10} onChange={value => patch(draft => { draft.structure.keep = value; })}/>
        <Toggle label="Swing-структура" checked={settings.structure.showSwing} onChange={value => patch(draft => { draft.structure.showSwing = value; })}/>
        <Toggle label="Internal-структура" checked={settings.structure.showInternal} onChange={value => patch(draft => { draft.structure.showInternal = value; })}/>
        <Toggle label="Подписи BOS / CHoCH" checked={settings.structure.showLabels} onChange={value => patch(draft => { draft.structure.showLabels = value; })}/>
        <Toggle label="Метки HH / HL / LH / LL" checked={settings.structure.swings} onChange={value => patch(draft => { draft.structure.swings = value; })}/>
        <Toggle label="Пробой по фитилю (иначе по close)" checked={settings.structure.wickBreak} onChange={value => patch(draft => { draft.structure.wickBreak = value; })}/>
      </Section>

      <Section title="Order Blocks">
        <Toggle label="Internal OB" checked={settings.ob.internal} onChange={value => patch(draft => { draft.ob.internal = value; })}/>
        <NumberField label="Internal OB, количество" value={settings.ob.maxInternal} min={1} max={20} onChange={value => patch(draft => { draft.ob.maxInternal = value; })}/>
        <Toggle label="Swing OB" checked={settings.ob.swing} onChange={value => patch(draft => { draft.ob.swing = value; })}/>
        <NumberField label="Swing OB, количество" value={settings.ob.maxSwing} min={1} max={20} onChange={value => patch(draft => { draft.ob.maxSwing = value; })}/>
        <NumberField label="Swing Length (LuxAlgo)" value={settings.ob.swingLength} min={10} max={200} onChange={value => patch(draft => { draft.ob.swingLength = value; })}/>
        <NumberField label="Internal Length (LuxAlgo)" value={settings.ob.internalLength} min={1} max={50} onChange={value => patch(draft => { draft.ob.internalLength = value; })}/>
        <label className="smc-select"><span>Order Block Filter</span><select value={settings.ob.filter} onChange={event => patch(draft => { draft.ob.filter = event.target.value as SmcSettings["ob"]["filter"]; })}><option value="atr">Atr</option><option value="mean">Cumulative Mean Range</option></select></label>
        <label className="smc-select"><span>Митигация</span><select value={settings.ob.mitigation} onChange={event => patch(draft => { draft.ob.mitigation = event.target.value as SmcSettings["ob"]["mitigation"]; })}><option value="hl">High / Low</option><option value="close">Close</option></select></label>
      </Section>

      <Section title="FVG и EQH / EQL">
        <Toggle label="Показывать FVG" checked={settings.fvg.show} onChange={value => patch(draft => { draft.fvg.show = value; })}/>
        <NumberField label="Мин. размер гэпа, ATR" value={settings.fvg.minAtr} min={0} max={3} step={0.05} onChange={value => patch(draft => { draft.fvg.minAtr = value; })}/>
        <NumberField label="Активных FVG" value={settings.fvg.max} min={1} max={40} onChange={value => patch(draft => { draft.fvg.max = value; })}/>
        <label className="smc-select"><span>FVG закрыт</span><select value={settings.fvg.mitigation} onChange={event => patch(draft => { draft.fvg.mitigation = event.target.value as SmcSettings["fvg"]["mitigation"]; })}><option value="full">Full</option><option value="half">50%</option></select></label>
        <Toggle label="EQH / EQL" checked={settings.eq.show} onChange={value => patch(draft => { draft.eq.show = value; })}/>
        <NumberField label="Допуск равенства, ATR" value={settings.eq.toleranceAtr} min={0} max={2} step={0.05} onChange={value => patch(draft => { draft.eq.toleranceAtr = value; })}/>
      </Section>

      <Section title="Уровни и профиль">
        <Toggle label="Ключевые уровни старшего ТФ" checked={settings.levels.show} onChange={value => patch(draft => { draft.levels.show = value; })}/>
        <Toggle label="PDH / PDL" checked={settings.levels.pd} onChange={value => patch(draft => { draft.levels.pd = value; })}/>
        <Toggle label="PWH / PWL" checked={settings.levels.pw} onChange={value => patch(draft => { draft.levels.pw = value; })}/>
        <Toggle label="Свинги 1H / 4H" checked={settings.levels.swings} onChange={value => patch(draft => { draft.levels.swings = value; })}/>
        <Toggle label="Premium / Discount зоны" checked={settings.premiumDiscount} onChange={value => patch(draft => { draft.premiumDiscount = value; })}/>
        <Toggle label="POC (профиль объёма)" checked={settings.poc.show} onChange={value => patch(draft => { draft.poc.show = value; })}/>
        <NumberField label="Value Area, %" value={settings.poc.valueArea} min={50} max={95} onChange={value => patch(draft => { draft.poc.valueArea = value; })}/>
      </Section>

      <Section title="A+ зоны и сигналы">
        <Toggle label="Выделять A+ зоны" checked={settings.aplus.enabled} onChange={value => patch(draft => { draft.aplus.enabled = value; })}/>
        <Toggle label="Показывать только A+" checked={settings.aplus.only} onChange={value => patch(draft => { draft.aplus.only = value; })}/>
        <NumberField label="Мин. конфлюенс, %" value={settings.aplus.minPercent} min={30} max={100} onChange={value => patch(draft => { draft.aplus.minPercent = value; })}/>
        <Toggle label="Метки BUY / SELL" checked={settings.signals.enabled} onChange={value => patch(draft => { draft.signals.enabled = value; })}/>
        <NumberField label="Мин. конфлюенс для метки, %" value={settings.signals.minScorePercent} min={30} max={100} onChange={value => patch(draft => { draft.signals.minScorePercent = value; })}/>
      </Section>

      <Section title="EMA со старших ТФ">
        {settings.emas.map((row, index) => <div className="smc-ema-row" key={`${row.timeframe}-${row.period}-${index}`}>
          <input type="checkbox" checked={row.enabled} aria-label="Включить EMA" onChange={event => patch(draft => { draft.emas[index].enabled = event.target.checked; })}/>
          <select value={row.timeframe} aria-label="Таймфрейм EMA" onChange={event => patch(draft => { draft.emas[index].timeframe = event.target.value as SmcSettings["emas"][number]["timeframe"]; })}>{TIMEFRAMES.map(tf => <option value={tf.value} key={tf.value}>{tf.label}</option>)}</select>
          <input type="number" value={row.period} min={2} max={400} aria-label="Период EMA" onChange={event => patch(draft => { const next = Number(event.target.value); if (Number.isFinite(next)) draft.emas[index].period = Math.min(400, Math.max(2, Math.round(next))); })}/>
          <input type="color" value={row.color} aria-label="Цвет EMA" onChange={event => patch(draft => { draft.emas[index].color = event.target.value; })}/>
        </div>)}
        <div className="smc-panel-actions">
          <button onClick={() => onChange(structuredClone(DEFAULT_SMC))}>Сбросить SMC</button>
          <button onClick={() => patch(draft => { draft.emas.push({ enabled: true, timeframe: "1d", period: 50, color: SMC_PALETTE.emaColors[draft.emas.length % SMC_PALETTE.emaColors.length] }); })}>+ EMA</button>
          {settings.emas.length > 1 && <button onClick={() => patch(draft => { draft.emas.pop(); })}>− EMA</button>}
        </div>
      </Section>
    </div>
  </aside>;
}
