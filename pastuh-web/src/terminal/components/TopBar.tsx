import { useState } from "react";
import { Terminal, RefreshCw, Eye, EyeOff, FlaskConical, LayoutPanelLeft, CircleDollarSign } from "lucide-react";
import { getSecret, setSecret } from "../api";
import { useClock } from "../hooks";
import { fmtRub } from "../utils";

interface Props {
  serverTime?: string;
  marketOpen?: boolean;
  isDemo: boolean;
  authError: boolean;
  deposit?: number;
  imoex?: { price?: number; change_pct?: number; change?: number } | null;
  onRefresh: () => void;
  onOpenBacktest: () => void;
  refreshSpin: boolean;
}

export default function TopBar({
  serverTime,
  marketOpen,
  isDemo,
  authError,
  deposit,
  imoex,
  onRefresh,
  onOpenBacktest,
  refreshSpin,
}: Props) {
  const time = useClock(serverTime);
  const [secret, setSecretState] = useState(getSecret() === "0000" ? "" : getSecret());
  const [showSecret, setShowSecret] = useState(false);

  const saveSecret = (v: string) => {
    setSecretState(v);
    setSecret(v);
  };

  return (
    <header className="glass sticky top-0 z-50 border-b border-line">
      <div className="mx-auto flex min-h-[58px] max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
        {/* лого */}
        <div className="flex items-center gap-2.5">
          <div className="relative grid h-8 w-8 place-items-center rounded-lg border border-line-2 bg-panel-2">
            <Terminal size={14} className="text-bull" />
            <span className="absolute -right-1 -top-1 h-2 w-2 animate-pulse-dot rounded-full bg-bull" />
          </div>
          <div className="leading-none">
            <div className="font-display text-[12px] font-800 text-white">
              TG<span className="text-bull">//</span>PRO TERMINAL
            </div>
            <div className="mt-0.5 font-mono text-[8px] uppercase tracking-[0.28em] text-smoke">moex · cvd · sniper</div>
          </div>
        </div>

        {/* рынок + часы + imoex */}
        <div className="flex items-center gap-2">
          <span
            className={`flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-[9px] font-700 uppercase tracking-wider ${
              marketOpen ? "bg-bull/10 text-bull" : "bg-bear/10 text-bear"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${marketOpen ? "animate-pulse-dot bg-bull" : "bg-bear"}`} />
            {marketOpen ? "торги идут" : "закрыто"}
          </span>
          <span className="rounded-md border border-line bg-abyss/70 px-2.5 py-1 font-mono text-[11px] font-600 tabular-nums text-white">
            {time} <span className="text-[8px] text-smoke">МСК</span>
          </span>
          {typeof imoex?.price === "number" && (
            <span className="hidden items-center gap-1.5 rounded-md border border-line bg-abyss/70 px-2.5 py-1 font-mono text-[10px] md:flex">
              <span className="text-smoke">IMOEX</span>
              <span className="font-600 text-white">{imoex.price.toLocaleString("ru-RU")}</span>
              {(imoex.change_pct ?? imoex.change) != null && (
                <span className={(imoex.change_pct ?? imoex.change ?? 0) >= 0 ? "text-bull" : "text-bear"}>
                  {((imoex.change_pct ?? imoex.change) ?? 0) >= 0 ? "+" : ""}
                  {((imoex.change_pct ?? imoex.change) ?? 0).toFixed(2)}%
                </span>
              )}
            </span>
          )}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {isDemo && (
            <span className="rounded-md border border-gold/35 bg-gold/10 px-2 py-1 font-mono text-[8.5px] uppercase tracking-wider text-gold">
              демо — нет связи с ботом
            </span>
          )}
          {authError && (
            <span className="rounded-md border border-bear/40 bg-bear/10 px-2 py-1 font-mono text-[8.5px] uppercase tracking-wider text-bear">
              401 · проверь пароль
            </span>
          )}
          {deposit != null && deposit > 0 && (
            <span className="hidden items-center gap-1.5 rounded-md border border-line bg-abyss/70 px-2.5 py-1 font-mono text-[10px] text-fog lg:flex">
              <CircleDollarSign size={11} className="text-gold" />
              {fmtRub(deposit)}
            </span>
          )}

          {/* пароль */}
          <div className="flex items-center gap-1 rounded-lg border border-line bg-abyss/70 px-2 py-1">
            <input
              type={showSecret ? "text" : "password"}
              value={secret}
              onChange={(e) => saveSecret(e.target.value)}
              placeholder="пароль"
              autoComplete="current-password"
              className="w-[86px] bg-transparent font-mono text-[11px] text-white outline-none placeholder:text-smoke/60"
            />
            <button onClick={() => setShowSecret(!showSecret)} className="text-smoke hover:text-fog" aria-label="Показать пароль">
              {showSecret ? <EyeOff size={12} /> : <Eye size={12} />}
            </button>
          </div>

          <button
            onClick={onOpenBacktest}
            className="flex items-center gap-1.5 rounded-lg border border-violet/40 bg-violet/10 px-3 py-1.5 font-mono text-[9.5px] uppercase tracking-wider text-violet transition-colors hover:bg-violet/20"
          >
            <FlaskConical size={12} />
            бэктест
          </button>
          <button
            onClick={onRefresh}
            className="flex items-center gap-1.5 rounded-lg border border-line-2 bg-panel-2 px-3 py-1.5 font-mono text-[9.5px] uppercase tracking-wider text-fog transition-colors hover:border-bull/40 hover:text-bull"
          >
            <RefreshCw size={12} className={refreshSpin ? "animate-spin" : ""} />
            <span className="hidden sm:inline">обновить</span>
          </button>
          <span className="hidden items-center gap-1 text-smoke xl:flex" title="Мобильная раскладка сохранена">
            <LayoutPanelLeft size={12} />
          </span>
        </div>
      </div>
    </header>
  );
}
