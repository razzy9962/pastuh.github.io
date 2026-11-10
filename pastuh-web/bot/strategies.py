# -*- coding: utf-8 -*-
"""
МУЛЬТИСТРАТЕГИЙНЫЙ ДВИЖОК ДЛЯ investrobot.py  (14 независимых стратегий)
=======================================================================

Подключение — 3 правки в investrobot.py (см. README_PATCH.md):
    from strategies import STRATS_EXT, strategy_side_ext, strategy_risk, real_cvd

    STRATS = STRATS_EXT                                   # (1) заменить словарь
    def strategy_side(key, sig):                          # (2) заменить тело
        return strategy_side_ext(key, sig, ctx={"news": MARKET_NEWS_CACHE.get("items") or [],
                                                "iceberg_state": ICEBERG_STATE,
                                                "book_state": BOOK_STATE})

Модуль НИЧЕГО не импортирует из бота (нет циклов) и никогда не бросает исключений
наружу: любая ошибка внутри стратегии = «сигнала нет».

ВАЖНО ПРО «НАСТОЯЩИЙ CVD»
-------------------------
Настоящий CVD (real_cvd) берётся ТОЛЬКО из ленты реальных сделок:
агрессор-покупатель минус агрессор-продавец по полю direction каждого принта.
Это поля, которые уже считает твой бот в apply_real_trades_delta_to_df():
    tape_delta       — нетто лент.дельта за свечу (buy-aggr − sell-aggr)
    tape_cum_delta   — кумулятивная лент.дельта
    tape_cov         — доля свечи, реально покрытая лентой (0..1)
Свечной (аппроксимированный) CVD — bar_delta/cum_delta — используется ТОЛЬКО
как запасной вариант и всегда помечается флагом approx=True. Стратегии
с requires_real_cvd=True не входят, если покрытие ленты ниже порога.
"""

from __future__ import annotations

from typing import Any, Iterable

__all__ = [
    "STRATS_EXT",
    "STRAT_RISK",
    "strategy_side_ext",
    "strategy_risk",
    "strategy_targets",
    "real_cvd",
    "strategy_explain",
]

# =====================================================================
# 1. КАТАЛОГ СТРАТЕГИЙ
#    uid — отрицательный id виртуального счёта (не пересекается с Telegram id)
# =====================================================================
STRATS_EXT: dict[str, dict] = {
    # --- ядро: настоящий CVD по ленте ---
    "cvd_flow": {
        "uid": -9001,
        "name": "💧 Поток CVD",
        "desc": "Скрытый набор/раздача по реальной ленте: поглощение и давление дельтой",
    },
    "cvd_mtf": {
        "uid": -9011,
        "name": "🧬 MTF-дельта",
        "desc": "Совпадение направления реального CVD минимум на 3 из 5 таймфреймов",
    },
    "cvd_impulse": {
        "uid": -9012,
        "name": "⚡ Импульс дельты",
        "desc": "Резкий всплеск лент.дельты с подтверждением ценой и объёмом (RVOL)",
    },
    # --- дивергенции ---
    "divergence": {
        "uid": -9003,
        "name": "⚠️ Пивот-дивергенция",
        "desc": "Контртренд: цена делает экстремум, реальный CVD — нет (ловля пампов)",
    },
    "div_candle": {
        "uid": -9013,
        "name": "🕯 Ложная свеча",
        "desc": "Свеча врёт: зелёная при отрицательной дельте и наоборот (candle lies)",
    },
    # --- крупный капитал в ленте ---
    "big_prints": {
        "uid": -9004,
        "name": "🐋 Крупные принты",
        "desc": "Концентрация сделок ≥1 млн ₽ одной стороны в анонимной ленте",
    },
    "twap_algo": {
        "uid": -9005,
        "name": "⏲ TWAP / алго-исполнение",
        "desc": "Рост среднего чека и частоты крупных принтов — работает алгоритм набора",
    },
    "minute_press": {
        "uid": -9006,
        "name": "⏱ Минутное давление",
        "desc": "Большой нетто-объём съеден без движения цены — скрытое поглощение",
    },
    "robot_illiquid": {
        "uid": -9007,
        "name": "🔁 Роботы в неликвиде",
        "desc": "Повторяющиеся принты с равным шагом в бумагах 2-3 эшелона",
    },
    # --- стакан ---
    "iceberg": {
        "uid": -9008,
        "name": "🧊 Айсберги",
        "desc": "Скрытая лимитная заявка: объём на уровне восстанавливается после съедания",
    },
    "book_imbal": {
        "uid": -9014,
        "name": "📚 Дисбаланс стакана",
        "desc": "Перевес bid/ask ≥ порога плюс крупная стена-поддержка в топ-уровнях",
    },
    # --- уровни и цена ---
    "poc_revert": {
        "uid": -9009,
        "name": "🎯 Возврат к POC",
        "desc": "Магнит объёма: отклонение от POC с разворотной дельтой — вход к уровню",
    },
    "sr_break": {
        "uid": -9015,
        "name": "🧱 Пробой уровня",
        "desc": "Пробой ближайшего S/R с подтверждением объёмом и реальной дельтой",
    },
    "vwap_trend": {
        "uid": -9010,
        "name": "📈 VWAP-тренд",
        "desc": "Трендовая: цена над/под VWAP, стек EMA 9/20/50 и RVOL выше нормы",
    },
    "index_decouple": {
        "uid": -9016,
        "name": "🧭 Расхождение с IMOEX",
        "desc": "Бумага идёт против индекса на своей дельте — сила/слабость эмитента",
    },
}

# =====================================================================
# 2. РИСК-ПРОФИЛЬ КАЖДОЙ СТРАТЕГИИ
#    tp_mult/sl_mult — множители ATR; max_pos — лимит одновременных позиций;
#    cooldown — пауза по тикеру, сек; min_rr — минимальное R/R для входа;
#    requires_real_cvd — не входить, если лента покрывает < min_tape_cov
# =====================================================================
STRAT_RISK: dict[str, dict] = {
    "cvd_flow":       {"tp_mult": 2.2, "sl_mult": 1.0, "max_pos": 5, "cooldown": 2400, "min_rr": 1.6, "requires_real_cvd": True,  "min_tape_cov": 45.0},
    "cvd_mtf":        {"tp_mult": 3.0, "sl_mult": 1.2, "max_pos": 4, "cooldown": 3600, "min_rr": 2.0, "requires_real_cvd": True,  "min_tape_cov": 50.0},
    "cvd_impulse":    {"tp_mult": 1.8, "sl_mult": 0.9, "max_pos": 4, "cooldown": 1800, "min_rr": 1.5, "requires_real_cvd": True,  "min_tape_cov": 55.0},
    "divergence":     {"tp_mult": 2.5, "sl_mult": 1.1, "max_pos": 4, "cooldown": 3600, "min_rr": 1.8, "requires_real_cvd": True,  "min_tape_cov": 40.0},
    "div_candle":     {"tp_mult": 1.6, "sl_mult": 0.8, "max_pos": 3, "cooldown": 2400, "min_rr": 1.5, "requires_real_cvd": True,  "min_tape_cov": 60.0},
    "big_prints":     {"tp_mult": 2.0, "sl_mult": 1.0, "max_pos": 5, "cooldown": 1800, "min_rr": 1.6, "requires_real_cvd": True,  "min_tape_cov": 35.0},
    "twap_algo":      {"tp_mult": 3.2, "sl_mult": 1.3, "max_pos": 3, "cooldown": 5400, "min_rr": 2.0, "requires_real_cvd": True,  "min_tape_cov": 35.0},
    "minute_press":   {"tp_mult": 1.7, "sl_mult": 0.85, "max_pos": 4, "cooldown": 1500, "min_rr": 1.5, "requires_real_cvd": True, "min_tape_cov": 50.0},
    "robot_illiquid": {"tp_mult": 2.4, "sl_mult": 1.2, "max_pos": 3, "cooldown": 3600, "min_rr": 1.7, "requires_real_cvd": True,  "min_tape_cov": 25.0},
    "iceberg":        {"tp_mult": 2.0, "sl_mult": 0.9, "max_pos": 4, "cooldown": 2400, "min_rr": 1.6, "requires_real_cvd": False, "min_tape_cov": 0.0},
    "book_imbal":     {"tp_mult": 1.5, "sl_mult": 0.8, "max_pos": 4, "cooldown": 1200, "min_rr": 1.4, "requires_real_cvd": False, "min_tape_cov": 0.0},
    "poc_revert":     {"tp_mult": 1.8, "sl_mult": 1.0, "max_pos": 4, "cooldown": 2400, "min_rr": 1.5, "requires_real_cvd": False, "min_tape_cov": 0.0},
    "sr_break":       {"tp_mult": 2.6, "sl_mult": 1.1, "max_pos": 4, "cooldown": 2400, "min_rr": 1.8, "requires_real_cvd": True,  "min_tape_cov": 40.0},
    "vwap_trend":     {"tp_mult": 2.8, "sl_mult": 1.2, "max_pos": 5, "cooldown": 3000, "min_rr": 1.8, "requires_real_cvd": False, "min_tape_cov": 0.0},
    "index_decouple": {"tp_mult": 2.2, "sl_mult": 1.1, "max_pos": 3, "cooldown": 3600, "min_rr": 1.7, "requires_real_cvd": True,  "min_tape_cov": 45.0},
}

_DEFAULT_RISK = {
    "tp_mult": 2.0, "sl_mult": 1.0, "max_pos": 4, "cooldown": 2400,
    "min_rr": 1.6, "requires_real_cvd": False, "min_tape_cov": 0.0,
}


def strategy_risk(key: str) -> dict:
    """Риск-профиль стратегии (всегда валидный словарь)."""
    r = dict(_DEFAULT_RISK)
    r.update(STRAT_RISK.get(key, {}))
    return r


# =====================================================================
# 3. УТИЛИТЫ
# =====================================================================
def _f(v: Any, default: float = 0.0) -> float:
    """Безопасный float."""
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _d(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v: Any) -> list:
    return list(v) if isinstance(v, (list, tuple)) else []


def _side_from_sign(x: float, dead: float = 0.0) -> str | None:
    if x > dead:
        return "LONG"
    if x < -dead:
        return "SHORT"
    return None


def _norm_side(v: Any) -> str | None:
    """BUY/LONG -> LONG, SELL/SHORT -> SHORT."""
    s = str(v or "").upper().strip()
    if s in ("LONG", "BUY", "BID"):
        return "LONG"
    if s in ("SHORT", "SELL", "ASK"):
        return "SHORT"
    return None


# =====================================================================
# 4. НАСТОЯЩИЙ CVD (только лента реальных сделок)
# =====================================================================
def real_cvd(sig: dict) -> dict:
    """
    Достаёт ТОЛЬКО тейп-метрики (по реальным сделкам), без свечной аппроксимации.

    Возвращает:
        net        — нетто лент.дельта за окно (лоты): buy-агрессор − sell-агрессор
        cum        — кумулятивная лент.дельта
        cov        — покрытие ленты, % (насколько окну хватило реальных принтов)
        efficiency — «перевес» дельты к объёму окна, %
        approx     — True, если пришлось взять свечную аппроксимацию
        side       — LONG/SHORT по знаку нетто (или None)
    """
    cvd = _d(sig.get("cvd_data"))
    cov = _f(cvd.get("tape_cov_pct"))

    # приоритет: честные тейп-поля
    net = None
    for key in ("tape_net_lots", "tape_delta", "tape_cum_delta_window"):
        if cvd.get(key) is not None:
            net = _f(cvd.get(key))
            break

    approx = False
    if net is None:
        # запасной путь: свечная дельта (помечаем как приблизительную)
        net = _f(cvd.get("cum_delta_change_6"))
        approx = True

    cum = _f(cvd.get("tape_cum_delta"), _f(cvd.get("cum_delta")))
    eff = _f(cvd.get("delta_efficiency_6"))

    return {
        "net": net,
        "cum": cum,
        "cov": cov,
        "efficiency": eff,
        "approx": approx,
        "side": _side_from_sign(net),
    }


def _real_cvd_ok(sig: dict, risk: dict) -> tuple[bool, dict]:
    """Проверка, что реальной ленты достаточно для стратегии."""
    rc = real_cvd(sig)
    if not risk.get("requires_real_cvd"):
        return True, rc
    if rc["approx"]:
        return False, rc
    if rc["cov"] < _f(risk.get("min_tape_cov")):
        return False, rc
    return True, rc


# =====================================================================
# 5. ОБЩИЕ ФИЛЬТРЫ КАЧЕСТВА (анти-мусор)
# =====================================================================
def _base_guard(sig: dict) -> bool:
    """Базовые условия, без которых не входит ни одна стратегия."""
    if not isinstance(sig, dict):
        return False
    if sig.get("is_illiquid"):
        return False
    if sig.get("is_live_market") is False:
        return False
    if _f(sig.get("price")) <= 0:
        return False
    return True


def _spread_ok(sig: dict, max_spread_pct: float = 0.6) -> bool:
    """Отсекает бумаги с диким спредом (вход съест весь профит)."""
    bl = _d(sig.get("book_liquidity"))
    sp = _f(bl.get("spread_pct"), -1.0)
    return True if sp < 0 else sp <= max_spread_pct


def _dividend_guard(sig: dict) -> bool:
    """Не входим прямо перед дивидендной отсечкой (гэп ломает стопы)."""
    di = _d(sig.get("dividend_info"))
    return not bool(di.get("cutoff_soon"))


# =====================================================================
# 6. РЕАЛИЗАЦИЯ СТРАТЕГИЙ
#    Каждая: (sig, ctx) -> "LONG" | "SHORT" | None
# =====================================================================

def _s_cvd_flow(sig: dict, ctx: dict) -> str | None:
    """Поглощение/давление по реальной ленте (ядро order flow)."""
    cvd = _d(sig.get("cvd_data"))
    side = _norm_side(cvd.get("absorption_side")) or _norm_side(cvd.get("pressure_side"))
    if side is None:
        return None
    rc = real_cvd(sig)
    # дельта должна смотреть в ту же сторону, что и детектор
    if rc["side"] and rc["side"] != side:
        return None
    # «свеча врёт» — противоположный сигнал гасит вход
    if side == "LONG" and cvd.get("green_candle_lies"):
        return None
    if side == "SHORT" and cvd.get("red_candle_lies"):
        return None
    return side


def _s_cvd_mtf(sig: dict, ctx: dict) -> str | None:
    """Совпадение реального CVD минимум на 3 из 5 таймфреймов."""
    mtf = _d(sig.get("mtf_cvd"))
    if len(mtf) < 3:
        return None
    longs = shorts = 0
    for tf_data in mtf.values():
        d = _d(tf_data)
        s = _norm_side(d.get("absorption_side")) or _norm_side(d.get("pressure_side"))
        if s is None:
            # по знаку дельты окна
            s = _side_from_sign(_f(d.get("cum_delta_change_6")))
        if s == "LONG":
            longs += 1
        elif s == "SHORT":
            shorts += 1
    if longs >= 3 and shorts == 0:
        return "LONG"
    if shorts >= 3 and longs == 0:
        return "SHORT"
    return None


def _s_cvd_impulse(sig: dict, ctx: dict) -> str | None:
    """Резкий всплеск дельты + подтверждение объёмом и ценой."""
    rc = real_cvd(sig)
    if rc["side"] is None:
        return None
    cvd = _d(sig.get("cvd_data"))
    eff = abs(_f(cvd.get("delta_efficiency_6")))
    rvol = _f(sig.get("rvol"), 1.0)
    price_chg = _f(cvd.get("price_change_6_pct"))
    if eff < 18.0 or rvol < 1.3:
        return None
    # цена должна подтверждать импульс (не против дельты)
    if rc["side"] == "LONG" and price_chg < -0.15:
        return None
    if rc["side"] == "SHORT" and price_chg > 0.15:
        return None
    return rc["side"]


def _s_divergence(sig: dict, ctx: dict) -> str | None:
    """Пивот-дивергенция цена/CVD — контртренд."""
    cvd = _d(sig.get("cvd_data"))
    if cvd.get("pivot_bearish_div"):
        return "SHORT"
    if cvd.get("pivot_bullish_div"):
        return "LONG"
    return None


def _s_div_candle(sig: dict, ctx: dict) -> str | None:
    """Ложная свеча: тело врёт относительно реальной дельты."""
    cvd = _d(sig.get("cvd_data"))
    rc = real_cvd(sig)
    if cvd.get("green_candle_lies") and rc["net"] < 0:
        return "SHORT"          # рост на продажах — слабость
    if cvd.get("red_candle_lies") and rc["net"] > 0:
        return "LONG"           # падение на покупках — скрытый набор
    # запасной путь: классическая барная дивергенция
    if cvd.get("bearish_divergence") and rc["net"] < 0:
        return "SHORT"
    if cvd.get("bullish_divergence") and rc["net"] > 0:
        return "LONG"
    return None


def _s_big_prints(sig: dict, ctx: dict) -> str | None:
    """Концентрация крупных принтов одной стороны."""
    bp = _d(sig.get("big_prints"))
    if not bp.get("detected"):
        return None
    side = _norm_side(bp.get("side"))
    if side is None:
        return None
    # свежесть: событие не старше 3 минут
    if _f(bp.get("last_big_age_sec"), 0.0) > 180.0:
        return None
    # доля крупных в обороте окна — не шум
    if _f(bp.get("share_of_window_rub")) < 12.0:
        return None
    rc = real_cvd(sig)
    if rc["side"] and rc["side"] != side:
        return None
    return side


def _s_twap_algo(sig: dict, ctx: dict) -> str | None:
    """TWAP/алго-набор: растут средний чек и частота крупных принтов."""
    tw = _d(sig.get("big_twap"))
    if not (tw.get("detected_size") or tw.get("detected_accel")):
        return None
    side = _norm_side(tw.get("side"))
    if side is None:
        return None
    rc = real_cvd(sig)
    if rc["side"] and rc["side"] != side:
        return None
    return side


def _s_minute_press(sig: dict, ctx: dict) -> str | None:
    """Минутное давление: объём есть, движения нет -> поглощение."""
    mp = _d(sig.get("minute_pressure"))
    if not mp.get("detected"):
        return None
    side = _norm_side(mp.get("side"))
    if side is None:
        return None
    # цена почти не сдвинулась — иначе это обычный импульс
    if abs(_f(mp.get("move_pct"))) > 0.5:
        return None
    return side


def _s_robot_illiquid(sig: dict, ctx: dict) -> str | None:
    """Роботы-исполнители в бумагах 2–3 эшелона (повторяющиеся принты)."""
    ra = _d(sig.get("robot_activity"))
    if not ra.get("pattern_detected"):
        return None
    side = _norm_side(ra.get("side")) or _norm_side(ra.get("dominant_side"))
    if side is None:
        rc = real_cvd(sig)
        side = rc["side"]
    if side is None:
        return None
    # стратегия заточена под НЕ самый ликвидный сегмент:
    # если бумага супер-ликвидная (огромный RVOL-оборот), пропускаем — там это шум
    turnover = _f(sig.get("turnover_rub"), 0.0)
    if turnover > 0 and turnover > 3_000_000_000:
        return None
    return side


def _s_iceberg(sig: dict, ctx: dict) -> str | None:
    """Айсберг: скрытая лимитка, объём восстанавливается после съедания."""
    events: Iterable[dict] = _l(sig.get("icebergs")) or _l(sig.get("iceberg_events"))
    if not events:
        st = _d(_d(ctx.get("iceberg_state")).get(sig.get("ticker")))
        events = _l(st.get("events"))
    if not events:
        return None
    buy = sum(1 for e in events if _norm_side(_d(e).get("side")) == "LONG")
    sell = sum(1 for e in events if _norm_side(_d(e).get("side")) == "SHORT")
    if buy > sell:
        return "LONG"      # айсберг на покупку = поддержка снизу
    if sell > buy:
        return "SHORT"
    return None


def _s_book_imbal(sig: dict, ctx: dict) -> str | None:
    """Дисбаланс стакана + крупная стена в нужную сторону."""
    bl = _d(sig.get("book_liquidity"))
    bm = _d(bl.get("metrics")) or bl
    if not bm.get("detected_imbalance"):
        return None
    imb = _f(bm.get("imbalance_pct"))
    side = _side_from_sign(imb, dead=0.0)
    if side is None:
        return None
    walls = _l(bm.get("big_walls"))
    want = "bid" if side == "LONG" else "ask"
    if walls and not any(str(_d(w).get("side")) == want for w in walls):
        return None            # стена есть, но с противоположной стороны
    rc = real_cvd(sig)
    if rc["side"] and rc["side"] != side:
        return None
    return side


def _s_poc_revert(sig: dict, ctx: dict) -> str | None:
    """Возврат к POC: цена ушла от «магнита» объёма, дельта разворачивается."""
    sr = _d(sig.get("sr_levels"))
    poc = _f(sr.get("poc"))
    price = _f(sig.get("price"))
    atr = _f(sig.get("atr"))
    if poc <= 0 or price <= 0 or atr <= 0:
        return None
    dist = (price - poc) / price * 100.0
    atr_pct = atr / price * 100.0
    # отклонение должно быть заметным: не меньше 0.8 ATR и не больше 3 ATR
    if abs(dist) < atr_pct * 0.8 or abs(dist) > atr_pct * 3.0:
        return None
    side = "SHORT" if dist > 0 else "LONG"   # возврат к POC
    rc = real_cvd(sig)
    if rc["side"] and rc["side"] != side:
        return None                           # дельта ещё толкает прочь — рано
    return side


def _s_sr_break(sig: dict, ctx: dict) -> str | None:
    """Пробой ближайшего уровня с подтверждением объёмом и дельтой."""
    sr = _d(sig.get("sr_levels"))
    price = _f(sig.get("price"))
    rvol = _f(sig.get("rvol"), 1.0)
    if price <= 0 or rvol < 1.4:
        return None
    res = _f(sr.get("res1_price"))
    sup = _f(sr.get("sup1_price"))
    rc = real_cvd(sig)
    if rc["side"] is None:
        return None
    # пробой вверх: цена выше сопротивления, дельта покупная
    if res > 0 and price >= res and rc["side"] == "LONG":
        return "LONG"
    # пробой вниз
    if sup > 0 and price <= sup and rc["side"] == "SHORT":
        return "SHORT"
    return None


def _s_vwap_trend(sig: dict, ctx: dict) -> str | None:
    """Трендовая: VWAP + стек EMA + повышенный объём."""
    price = _f(sig.get("price"))
    vwap = _f(sig.get("vwap"))
    e9 = _f(sig.get("ema9"))
    e20 = _f(sig.get("ema20"))
    e50 = _f(sig.get("ema50"))
    rvol = _f(sig.get("rvol"), 1.0)
    if min(price, vwap, e9, e20, e50) <= 0 or rvol < 1.1:
        return None
    if price > vwap and e9 >= e20 >= e50:
        return "LONG"
    if price < vwap and e9 <= e20 <= e50:
        return "SHORT"
    return None


def _s_index_decouple(sig: dict, ctx: dict) -> str | None:
    """Расхождение с индексом: бумага сильнее/слабее рынка на своей дельте."""
    moex = _d(sig.get("moex_ctx"))
    idx_chg = _f(moex.get("change_pct"), _f(moex.get("change")))
    own_chg = _f(sig.get("change"))
    if abs(idx_chg) < 0.15:
        return None                      # индекс стоит — расхождения нет
    spread = own_chg - idx_chg
    if abs(spread) < 0.8:
        return None                      # расхождение незначимое
    side = "LONG" if spread > 0 else "SHORT"
    rc = real_cvd(sig)
    if rc["side"] != side:
        return None                      # сила должна подтверждаться деньгами
    return side


def _s_news_whale(sig: dict, ctx: dict) -> str | None:
    """Совместимость со старым ключом news_whale (новости + крупняк)."""
    news = _l(ctx.get("news"))
    ticker = str(sig.get("ticker") or "").upper()
    name = str(sig.get("name") or "").lower()
    hit = False
    for n in news[:15]:
        title = str(_d(n).get("title") or "")
        tl = title.lower()
        if (ticker and ticker.lower() in tl) or (len(name) > 3 and name in tl):
            hit = True
            break
        if _d(n).get("important") and ticker and ticker in title:
            hit = True
            break
    ice = _s_iceberg(sig, ctx)
    if not hit and ice is None:
        return None
    rc = real_cvd(sig)
    return ice or rc["side"]


_DISPATCH = {
    "cvd_flow": _s_cvd_flow,
    "cvd_mtf": _s_cvd_mtf,
    "cvd_impulse": _s_cvd_impulse,
    "divergence": _s_divergence,
    "div_candle": _s_div_candle,
    "big_prints": _s_big_prints,
    "twap_algo": _s_twap_algo,
    "minute_press": _s_minute_press,
    "robot_illiquid": _s_robot_illiquid,
    "iceberg": _s_iceberg,
    "book_imbal": _s_book_imbal,
    "poc_revert": _s_poc_revert,
    "sr_break": _s_sr_break,
    "vwap_trend": _s_vwap_trend,
    "index_decouple": _s_index_decouple,
    # legacy
    "news_whale": _s_news_whale,
    "levels": _s_sr_break,
}


# =====================================================================
# 7. ПУБЛИЧНЫЙ ВХОД
# =====================================================================
def strategy_side_ext(key: str, sig: dict, ctx: dict | None = None) -> str | None:
    """
    Сторона автовхода стратегии `key` по сигналу `sig`.
    Возвращает "LONG" / "SHORT" / None. Никогда не бросает исключений.

    ctx (необязательно):
        news          — MARKET_NEWS_CACHE["items"]
        iceberg_state — ICEBERG_STATE
        book_state    — BOOK_STATE
    """
    try:
        ctx = ctx or {}
        fn = _DISPATCH.get(key)
        if fn is None or not _base_guard(sig):
            return None

        risk = strategy_risk(key)

        # 1) достаточно ли настоящей ленты для этой стратегии
        ok, _rc = _real_cvd_ok(sig, risk)
        if not ok:
            return None

        # 2) общие фильтры качества
        if not _spread_ok(sig) or not _dividend_guard(sig):
            return None

        # 3) сама стратегия
        side = _norm_side(fn(sig, ctx))
        if side is None:
            return None

        # 4) проверка R/R по целям бота для выбранной стороны
        targets = _d(_d(sig.get("targets_by_side")).get(side))
        rr = _f(targets.get("rr_ratio"), _f(sig.get("rr_ratio")))
        if rr > 0 and rr < _f(risk.get("min_rr"), 1.5):
            return None

        return side
    except Exception:
        # стратегия не должна ронять торговый цикл
        return None


def strategy_targets(key: str, sig: dict, side: str) -> dict:
    """
    Цели входа с учётом риск-профиля стратегии.
    Если у бота уже есть targets_by_side — берём их, иначе считаем от ATR.
    """
    try:
        risk = strategy_risk(key)
        base = _d(_d(sig.get("targets_by_side")).get(side))
        entry = _f(base.get("entry"), _f(sig.get("price")))
        if entry <= 0:
            return {}
        atr = _f(sig.get("atr"))
        if atr <= 0:
            atr = entry * 0.01
        tp_d = atr * _f(risk["tp_mult"], 2.0)
        sl_d = atr * _f(risk["sl_mult"], 1.0)
        if side == "LONG":
            tp = _f(base.get("tp")) or entry + tp_d
            sl = _f(base.get("sl")) or entry - sl_d
        else:
            tp = _f(base.get("tp")) or entry - tp_d
            sl = _f(base.get("sl")) or entry + sl_d
        risk_abs = abs(entry - sl)
        return {
            "entry": round(entry, 4),
            "tp": round(tp, 4),
            "sl": round(sl, 4),
            "rr_ratio": round(abs(tp - entry) / risk_abs, 2) if risk_abs > 0 else 0.0,
            "max_pos": int(risk["max_pos"]),
            "cooldown": int(risk["cooldown"]),
        }
    except Exception:
        return {}


def strategy_explain(key: str, sig: dict, ctx: dict | None = None) -> str:
    """Человеческое объяснение, почему стратегия вошла (для Telegram/веба)."""
    try:
        rc = real_cvd(sig)
        meta = STRATS_EXT.get(key, {})
        side = strategy_side_ext(key, sig, ctx)
        if not side:
            return ""
        cov = f"{rc['cov']:.0f}%" if not rc["approx"] else "оценка"
        return (
            f"{meta.get('name', key)} → <b>{side}</b>\n"
            f"• {meta.get('desc', '')}\n"
            f"• реальный CVD: {rc['net']:+.0f} лот (покрытие ленты {cov})"
        )
    except Exception:
        return ""
