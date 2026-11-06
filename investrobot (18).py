
import asyncio
import os
import re
import signal
import ssl
import time
import json
import zlib
import base64
import logging
import io
import csv
import hmac
import sqlite3
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import aiohttp
from aiohttp import web
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
    BufferedInputFile,
    FSInputFile,
)

# =====================================================================
# 1. НАСТРОЙКИ И ТОКЕНЫ (РЕЖИМ ИНФОРМАТОРА CVD + СНАЙПЕР)
# =====================================================================
# ---------------------------------------------------------------------
# ВАЖНО: токены НИКОГДА не храним в коде. Только переменные окружения.
#   export BOT_TOKEN="123456:AAA..."
#   export T_INVEST_TOKEN="t.xxxxx"
# ---------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ВНИМАНИЕ: токены — только через переменные окружения, никогда в коде!
# (в одной из ранних версий файла они лежали прямо здесь — такие токены нужно отозвать и перевыпустить)
BOT_TOKEN = os.getenv("BOT_TOKEN", "9053021048:AAG8FabcIE71mLJE4qTga8_wbL51UReI43w").strip()
T_INVEST_TOKEN = os.getenv("T_INVEST_TOKEN", "t.i6C0j3srt3XuryO2E0SUL3pOJEF3qPFh-qDPhjBYJVDv1kC94-1iVNJVxfy-W081Qnx5dEi6CbATNhYQDmtZwQ").strip()
if not BOT_TOKEN or not T_INVEST_TOKEN:
    raise SystemExit(
        "Не заданы BOT_TOKEN и/или T_INVEST_TOKEN.\n"
        "Задайте их в переменных окружения, например:\n"
        '  export BOT_TOKEN="123456:AAA..."\n'
        '  export T_INVEST_TOKEN="t.xxxxx"'
    )

TELEGRAM_PROXY: str | None = os.getenv("TELEGRAM_PROXY") or None
T_API_BASE = "https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1"
WEB_SECRET = os.getenv("WEB_SECRET", "0000").strip()
WEB_USER_ID = int(os.getenv("WEB_USER_ID", "0") or 0)  # patch35: chat id владельца для веб-панели (0 = авто)
PORT = int(os.getenv("PORT", "10000"))

MIN_LIQUIDITY_RUB = 100_000_000
MIN_SCORE_FOR_ENTRY = 7
BOOK_DEPTH = 50
BOOK_WALL_MIN_RUB = float(os.getenv("BOOK_WALL_MIN_RUB", "1200000"))
BOOK_WALL_MIN_MULT = float(os.getenv("BOOK_WALL_MIN_MULT", "3.0"))

# Справочный детектор повторяющихся принтов в анонимной ленте. Он не определяет
# личность участника и ни при каких условиях не участвует в выборе стороны/сделки.
REPEAT_PATTERN_WINDOW_SECONDS = 300
REPEAT_PATTERN_MIN_TRADES = 5
REPEAT_PATTERN_MAX_INTERVAL_CV = 0.30
REPEAT_PATTERN_MAX_PRICE_SPAN_PCT = 0.05
REPEAT_PATTERN_MAX_LAST_AGE_SECONDS = 60
REPEAT_PATTERN_MAX_SEQUENCE = 12

# ==================== ДЕТЕКТОР КРУПНЫХ ПРИНТОВ (СПРАВОЧНО) ====================
# Крупный принт = одна сделка с рублёвым объёмом >= BIG_TRADE_MIN_RUB.
# Детектор НЕ идентифицирует участника: это концентрация крупных сделок одной
# стороны в анонимной ленте. Используется справочно (тексты/дашборд), а также
# как слабый гейт «давления» в информаторе CVD.
BIG_TRADE_MIN_RUB = float(os.getenv("BIG_TRADE_MIN_RUB", "1000000"))              # 1 млн ₽ за одну сделку
BIG_TRADE_WINDOW_SECONDS = int(os.getenv("BIG_TRADE_WINDOW_SECONDS", "300"))     # окно 5 минут
BIG_TRADE_MIN_COUNT = int(os.getenv("BIG_TRADE_MIN_COUNT", "3"))                 # минимум крупных сделок в окне
BIG_TRADE_MIN_TOTAL_RUB = float(os.getenv("BIG_TRADE_MIN_TOTAL_RUB", "5000000")) # нетто-объём крупных принтов за окно
# «Давление при стоящей цене»: CVD окна в рублях / (ATR свечи * число свечей окна).
# При флэте большое значение = большой объём прошёл почти без движения цены.
CVD_PER_ATR_MIN = float(os.getenv("CVD_PER_ATR_MIN", "2.5"))   # диагностика CVD/ATR (только в текстах)
# «Давление при стоящей цене»: price_impact = диапазон окна (%) / |перевес CVD| (%).
# Чем меньше — тем сильнее объём давит при почти неподвижной цене. Вменяемый порог ~0.05.
PRICE_IMPACT_MAX = float(os.getenv("PRICE_IMPACT_MAX", "0.05"))
# Если покрытие окна реальной лентой ниже этого % — CVD на графике рисуем серым + пометка «оценочный»
CHART_CVD_LOW_COV_PCT = float(os.getenv("CHART_CVD_LOW_COV_PCT", "10.0"))
CHART_CVD_CANDLE_COV_PCT = float(os.getenv("CHART_CVD_CANDLE_COV_PCT", "50.0"))  # порог tape_cov свечи: ниже — свеча CVD серая («оценочная»)

# ==================== МИНУТНОЕ ДАВЛЕНИЕ (крупный пассивный игрок) ====================
# За минуту прошёл большой нетто-объём в ₽ при почти неподвижной цене ->
# кто-то крупный, вероятно, забирает поток лимитками (CVD этого не видит).
MINUTE_PRESSURE_WINDOW_MIN = int(os.getenv("MINUTE_PRESSURE_WINDOW_MIN", "10"))          # окно, минут
MINUTE_PRESSURE_NET_RUB = float(os.getenv("MINUTE_PRESSURE_NET_RUB", "2000000"))           # нетто за минуту, ₽
MINUTE_PRESSURE_MAX_MOVE_PCT = float(os.getenv("MINUTE_PRESSURE_MAX_MOVE_PCT", "0.10"))    # цена за минуту почти стоит
MINUTE_PRESSURE_MIN_IMPACT = float(os.getenv("MINUTE_PRESSURE_MIN_IMPACT", "50000000"))     # ₽ нетто-объёма на 1% движения цены (раньше делили на ₽ движения — у дешёвых бумаг порог срабатывал всегда)

# ==================== TWAP среди крупных принтов ====================
TWAP_MIN_TRADES = int(os.getenv("TWAP_MIN_TRADES", "3"))
TWAP_MAX_INTERVAL_CV = float(os.getenv("TWAP_MAX_INTERVAL_CV", "0.30"))

# ==================== ICEBERG / «восстанавливающаяся стена» в стакане ====================
ICEBERG_ENABLED = os.getenv("ICEBERG_ENABLED", "1") == "1"
ICEBERG_WATCH_EVERY_SEC = int(os.getenv("ICEBERG_WATCH_EVERY_SEC", "45"))   # период опроса стаканов
ICEBERG_BATCH = int(os.getenv("ICEBERG_BATCH", "5"))                         # тикеров за заход (лимит API)
ICEBERG_MIN_LOTS = float(os.getenv("ICEBERG_MIN_LOTS", "3000"))              # «стена» от, лотов
ICEBERG_MIN_WALL_RUB = float(os.getenv("ICEBERG_MIN_WALL_RUB", "10000000"))  # ...и от ₽ (qty*lot*price): 3000 лотов PLZL — гигант, а 3000 лотов дешёвой бумаги — мелочь
ICEBERG_MIN_SEEN = int(os.getenv("ICEBERG_MIN_SEEN", "2"))                   # уровень должен продержаться N снапшотов до «исчезновения» (защита от переставления MM)
ICEBERG_DROP_PCT = float(os.getenv("ICEBERG_DROP_PCT", "0.5"))
# --- стакан: дисбаланс / big walls / плотность (patch19) ---
BOOK_TOP_LEVELS = int(os.getenv("BOOK_TOP_LEVELS", "20"))
BOOK_IMBALANCE_PCT = float(os.getenv("BOOK_IMBALANCE_PCT", "25.0"))   # |дисбаланс| bid/ask в ₽,% при котором событие
BOOK_WALL_RUB = float(os.getenv("BOOK_WALL_RUB", "5000000"))           # лимитка от 5 млн ₽ = «стена»
BOOK_CONC_PCT = float(os.getenv("BOOK_CONC_PCT", "55.0"))              # доля топ-5 уровней в топ-20 = концентрация
BOOK_STALE_SEC = float(os.getenv("BOOK_STALE_SEC", "600"))             # свежесть метрик стакана, с
# --- лента: средний чек сделки + ускорение частоты принтов (patch19) ---
AVG_TRADE_RUB_MIN = float(os.getenv("AVG_TRADE_RUB_MIN", "80000"))     # средний чек сделки в окне, ₽
AVG_TRADE_TREND_PCT = float(os.getenv("AVG_TRADE_TREND_PCT", "30.0"))  # рост среднего чека к прошлому окну, %
RATE_ACCEL_MIN = float(os.getenv("RATE_ACCEL_MIN", "2.0"))             # ускорение принтов/мин (раз)
# --- confluence-алерт 🐋🐋 (patch19) ---
WHALE_CONFLUENCE_MIN = int(os.getenv("WHALE_CONFLUENCE_MIN", "2"))
WHALE_ALERT_COOLDOWN = int(os.getenv("WHALE_ALERT_COOLDOWN", "1800"))
RI_FUTURES_TICKERS = [t.strip().upper() for t in os.getenv("RI_FUTURES_TICKERS", "RIZ6").split(",") if t.strip()]
RI_WATCH_EVERY_SEC = int(os.getenv("RI_WATCH_EVERY_SEC", "60"))               # снятие >=50% = «исчезла»
ICEBERG_RECOVER_PCT = float(os.getenv("ICEBERG_RECOVER_PCT", "0.8"))         # восстановление >=80% = iceberg
ICEBERG_LEVEL_TTL_SEC = int(os.getenv("ICEBERG_LEVEL_TTL_SEC", "300"))

# ==================== НАСТРОЙКИ ИНФОРМАТОРА CVD ====================
# Перевес = (сумма дельты за окно / сумма объёма за окно) * 100 %.
# Старый общий порог сохранён как fallback для неизвестных ТФ; для информатора
# используются отдельные, более строгие значения по каждому таймфрейму.
CVD_ABSORPTION_MIN_PCT = float(os.getenv("CVD_ABSORPTION_MIN_PCT", "26.0"))
_CVD_ABSORPTION_DEFAULTS = {
    "1m": 50.0,
    "5m": 45.0,
    "15m": 35.0,
    "30m": 30.0,
    "1h": 25.0,
    "4h": 25.0,
    "1d": 25.0,
}
CVD_ABSORPTION_MIN_PCT_BY_TF = {
    tf: float(os.getenv(f"CVD_ABSORPTION_MIN_PCT_{tf.upper()}", str(default)))
    for tf, default in _CVD_ABSORPTION_DEFAULTS.items()
}

def cvd_absorption_threshold(tf_key: str) -> float:
    return CVD_ABSORPTION_MIN_PCT_BY_TF.get(tf_key, CVD_ABSORPTION_MIN_PCT)

CVD_WINDOW = int(os.getenv("CVD_WINDOW", "6"))      # окно в свечах, по которому считаем перевес
CVD_MIN_VOL_RATIO = 0.80       # объём окна / средний объём: ниже — «мёртвый» флэт
# «График стоит?» определяется коэффициентом эффективности Кауфмана:
#   ER = |чистое движение за окно| / сумма |движений по свечам|
# ER ~ 1 — красивый тренд, ER ~ 0 — пила/флэт. Критерий безразмерный, поэтому
# не ломается ни на тихом, ни на волатильном дне (порог в процентах — ломается).
FLAT_MAX_ER = 0.34
FLAT_MAX_DRIFT_PCT = {   # страховка от «флэта» с диким размахом
    "1m": 0.22, "5m": 0.32, "15m": 0.42, "30m": 0.55,
    "1h": 0.70, "4h": 1.05, "1d": 1.70,
}
CVD_MIN_CONSISTENCY = 0.60     # доля свечей окна с дельтой в сторону сигнала
CVD_MIN_TAPE_COVERAGE_PCT = 15.0  # доля объёма окна, покрытая реальной лентой (по умолчанию)
# Технический факт T-Invest API: GetLastTrades гарантирует только ПОСЛЕДНИЙ ЧАС сделок.
# На 5м окно в 6 свечей = 30 мин, и лента покрывает его почти полностью,
# а на 4ч окно = 24 часа — покрытие физически меньше. Для 4ч оставлен минимум 5%,
# чтобы не выдавать оценку только по свечам за CVD-сигнал.
CVD_COVERAGE_GATE_PCT = {"1m": 15.0, "5m": 15.0, "15m": 15.0, "30m": 10.0, "1h": 5.0, "4h": 5.0, "1d": 0.0}
TAPE_WINDOW_MINUTES = 55
CVD_ALERT_COOLDOWN = int(os.getenv("CVD_ALERT_COOLDOWN", "1800"))

# ==================== ХРАНИЛИЩЕ CVD (SQLite + CSV) ====================
CVD_STORE_ENABLED = os.getenv("CVD_STORE_ENABLED", "1") == "1"
CVD_DB_PATH = os.getenv("CVD_DB_PATH", os.path.join(BASE_DIR, "cvd_data.db"))
CVD_ALERTS_CSV = os.getenv("CVD_ALERTS_CSV", os.path.join(BASE_DIR, "cvd_alerts.csv"))
CVD_STORE_DAYS = int(os.getenv("CVD_STORE_DAYS", "14"))      # ретеншн CVD-хранилища, дней (сверху обрезается — см. _cvd_clamp_days)
CVD_STORE_MAX_DAYS = int(os.getenv("CVD_STORE_MAX_DAYS", "90"))       # жёсткий потолок ретеншна, дней
CVD_MEM_BUDGET_MB = float(os.getenv("CVD_MEM_BUDGET_MB", "250"))      # бюджет RAM под минутную сетку CVD, МБ
CVD_MEM_BYTES_PER_MIN = 200.0   # одна минута в mem (dict[int, [buy, sell]]) ≈ 200 байт
CVD_MINUTES_PER_DAY = 1440      # считаем по полной сутке с запасом (торговых минут ~700)
TRADING_DEPOSIT_RUB = float(os.getenv("TRADING_DEPOSIT_RUB", "10000000"))  # депозит портфеля, ₽ (по умолчанию 10 млн)
TRADING_MAX_POSITIONS = int(os.getenv("TRADING_MAX_POSITIONS", "5"))       # на сколько равных позиций делим депозит
# Автосокращение части позиции на полпути к TP (>55%) и безубыток
AUTO_PARTIAL_ENABLED = os.getenv("AUTO_PARTIAL_ENABLED", "1").lower() not in ("0", "false", "no", "off")
AUTO_PARTIAL_TAKE_PCT = float(os.getenv("AUTO_PARTIAL_TAKE_PCT", "50.0"))     # сколько % позиции фиксировать (по умолч. 50%)
AUTO_PARTIAL_TRIGGER_PCT = float(os.getenv("AUTO_PARTIAL_TRIGGER_PCT", "55.0")) # рубеж пути до TP (по умолч. 55%)
# Трейлинг остатка 50% после частичной фиксации (patch26)
TRAIL_AFTER_PARTIAL = os.getenv("TRAIL_AFTER_PARTIAL", "1").lower() not in ("0", "false", "no", "off")
TRAIL_DROP_PCT = float(os.getenv("TRAIL_DROP_PCT", "1.5"))        # просадка от локального макс. после фиксации, % — тогда автозакрытие
TRAIL_CVD_MIN_LOTS = float(os.getenv("TRAIL_CVD_MIN_LOTS", "0"))  # мин. CVD за 6 свечей (лоты) для «продолжения»; 0 = любой нужный знак
# --- Виртуальные «счета» стратегий (patch30b): 3 независимых портфеля; реальных ордеров бот не выставляет ---
STRATS_ENABLED = os.getenv("STRATS_ENABLED", "1").lower() not in ("0", "false", "no", "off")
STRAT_DEPOSIT_RUB = float(os.getenv("STRAT_DEPOSIT_RUB", "10000000"))  # отдельный депозит 10 млн ₽ на каждый виртуальный портфель
STRAT_MAX_POSITIONS = int(os.getenv("STRAT_MAX_POSITIONS", "5"))       # макс. 5 позиций по 2 млн ₽ каждая
STRATS = {
    "cvd_flow":   {"uid": -9001, "name": "💧 Поток CVD",          "desc": "Скрытый набор/раздача крупняка по 5 ТФ дельты (order flow)"},
    "divergence": {"uid": -9003, "name": "⚠️ Дивергенция",        "desc": "Контртренд по пивот-дивергенции цена/CVD (ловля разворотов и пампов)"},
    "news_whale": {"uid": -9002, "name": "📰 Новости & Крупняк",   "desc": "Биржевые молнии MOEX, дискретные аукционы + айсберги и принты ≥1 млн ₽"},
}


def _cvd_clamp_days(requested: int, n_tickers: int) -> int:
    """Обрезает ретеншцию CVD, чтобы RAM под минутную сетку не превышал CVD_MEM_BUDGET_MB.

    Память ≈ n_tickers × days × CVD_MINUTES_PER_DAY × CVD_MEM_BYTES_PER_MIN.
    Диск (sqlite) ограничивается тем же self.days через prune() — отдельный лимит не нужен.
    """
    d = max(1, min(int(requested), CVD_STORE_MAX_DAYS))
    try:
        n_tickers = max(0, int(n_tickers))
    except (TypeError, ValueError):
        n_tickers = 0
    if n_tickers <= 0:
        return d
    per_day_mb = n_tickers * CVD_MINUTES_PER_DAY * CVD_MEM_BYTES_PER_MIN / 1e6
    if per_day_mb > 0:
        budget_days = int(CVD_MEM_BUDGET_MB / per_day_mb)
        if d > budget_days:
            logging.warning(
                f"CVD_STORE: запрошено {d} дн., но при {n_tickers} бумагах бюджет RAM "
                f"{CVD_MEM_BUDGET_MB:.0f} МБ позволяет максимум {max(1, budget_days)} дн. — ретеншн обрезана"
            )
            d = max(1, budget_days)
    return d
CVD_FLUSH_EVERY_SEC = int(os.getenv("CVD_FLUSH_EVERY_SEC", "60"))

SCAN_WINDOW_SECONDS = 180
SIGNAL_COOLDOWN_SECONDS = 2400
SCAN_CACHE_TTL = 45            # сек: один анализ на тикер+ТФ переиспользуется всеми
SCAN_BATCH_SIZE = 4
HTTP_CONCURRENCY = 6

HISTORY_RETENTION_DAYS = int(os.getenv('HISTORY_RETENTION_DAYS', '7'))
STATE_SAVE_DEBOUNCE = 3.0
# patch34: по умолчанию ВКЛ — на Render диск эфемерный, облако (bak_N) единственное,
# что переживает рестарт; без него винрейт и активные сделки теряются.
CLOUD_BACKUP_ENABLED = os.getenv("CLOUD_BACKUP_ENABLED", "1") == "1"
STATE_FORCE_SAVE_EVERY_SEC = int(os.getenv("STATE_FORCE_SAVE_EVERY_SEC", "60"))  # patch34: период force-сохранения в цикле монитора

ILLIQUID_BLACKLIST = {
    "UKUZ", "UWGN", "TGKN", "MRKP", "DIAS", "WUSH", "FEES",
    "TUZA", "KROT", "SARE", "VGSB", "MAGE", "KCHE", "YKEN",
    "LPSB", "KRKNP", "NKSH", "RUSI", "ZILL", "PRMB", "PAWB"
}

STATE_FILE = os.getenv("STATE_FILE", os.path.join(BASE_DIR, "bot_state.json"))
CLOUD_LANG_SLOT = "eo"
# Бэкап файла CVD-хранилища (cvd_data.db) Telegram-документом; file_id лежит в обычном стейте (bak_N).
CVD_FILE_BACKUP = os.getenv("CVD_FILE_BACKUP", "1") == "1"     # вкл/выкл; требует CLOUD_BACKUP_ENABLED=1
BACKUP_CHAT_ID = int(os.getenv("BACKUP_CHAT_ID", "0") or 0)     # чат для бэкапа; 0 = первый известный пользователь из стейта
CVD_FILE_BACKUP_EVERY_SEC = int(os.getenv("CVD_FILE_BACKUP_EVERY_SEC", "3600"))
_CVD_FILE_ID: str | None = None
_CVD_FILE_BACKUP_TS = 0.0

MSK_TZ = timezone(timedelta(hours=3))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

bot_session = AiohttpSession(proxy=TELEGRAM_PROXY) if TELEGRAM_PROXY else None
bot = Bot(token=BOT_TOKEN, session=bot_session)
dp = Dispatcher()

_TG_OWNER_UID = 0  # patch36: chat id владельца; выучивается из любого TG-апдейта и хранится в стейте


@dp.update.outer_middleware
async def _learn_owner_uid_mw(handler, event, data):
    """patch36: любой апдейт от живого TG-пользователя делает его владельцем — тогда веб-панель
    (пишет на _get_primary_user_id) и TG-меню работают с одним и тем же uid."""
    global _TG_OWNER_UID
    user = getattr(event, "from_user", None)
    if user is None:
        msg = getattr(event, "message", None)
        user = getattr(msg, "from_user", None) if msg is not None else None
    uid = int(getattr(user, "id", 0) or 0)
    if uid > 0:
        _TG_OWNER_UID = uid
    return await handler(event, data)

# =====================================================================
# 2. БАЗА ДАННЫХ, КЭШ И ОБЛАЧНОЕ СОХРАНЕНИЕ
# =====================================================================
INSTRUMENTS_CACHE: dict[str, dict] = {}
UID_TO_TICKER: dict[str, str] = {}

MOEX_INDEX_CACHE: dict = {"ts": 0.0, "data": None}

AUTO_SIGNAL_SUBSCRIBERS: dict[int, float] = {}
PRICE_HISTORY: dict[str, deque] = {}
LAST_SIGNAL_TIME: dict[tuple[int, str], float] = {}
LAST_CVD_ALERT_TIME: dict[str, float] = {}

TRACKED_SIGNALS: dict[int, dict[str, dict]] = {}
PENDING_OPEN_ORDERS: dict[str, dict] = {}  # отложенные ордера на открытие биржи
USER_STATS: dict[int, dict] = {}
ACTIVE_ROBOTS_REGISTRY: dict[str, dict] = {}

# Единый кэш сканера для Telegram-мониторинга и Веб-дашборда
WEB_SCAN_CACHE: dict[str, dict] = {}
WEB_SCAN_TS: float = 0.0

# Кэш результатов анализа по (тикер, ТФ) с TTL — убирает дублирующие запросы к API
SCAN_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_SCAN_INFLIGHT: dict[tuple[str, str], asyncio.Task] = {}   # защита от дублирующих анализов одного (тикер, ТФ)
_LAST_AUTH_ERR_TS: float = 0.0   # время последней 401/403 от T-Invest API — диагностика «не найдена»
_LAST_ANALYZE_ERR: dict[tuple[str, str], tuple[float, str]] = {}   # (ticker, tf) -> (ts, причина) последнего падения analyze_stock_signal
_LAST_TLS_ERR_TS: float = 0.0   # время последней ошибки проверки TLS-сертификата T-Invest API (MITM/DPI)
ICEBERG_STATE: dict[str, dict] = {}   # ticker -> {"events": [...], "levels": {...}, "last_check": ts} — эвристика iceberg по стакану
LAST_CVD_ALERT_CANDLE: dict[str, str] = {}

SCAN_LOCK = asyncio.Lock()          # один общий скан за раз (никаких параллельных сканов)
HTTP_SEMAPHORE = asyncio.Semaphore(HTTP_CONCURRENCY)
CHART_LOCK = threading.Lock()       # matplotlib НЕ потокобезопасен
CHART_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chart")
_STATE_SAVE_LOCK = asyncio.Lock()
_state_save_ts: float = 0.0
_state_save_pending: bool = False
SESSION: aiohttp.ClientSession | None = None
STOP_EVENT = asyncio.Event()

# Бумаги разбиты на эшелоны; активный набор для мониторинга — ACTIVE_TICKERS.
# LIQUID_WATCHLIST пересобирается из ACTIVE_TICKERS (rebuild_active_watchlist) после загрузки
# стейта и после переключения в меню «🎛 Бумаги»: скан/кнопки/🐋/радар/бэктест/iceberg работают по нему.
TIER_WATCHLISTS: dict[int, list[tuple[str, str]]] = {
    1: [  # Голубые фишки Мосбиржи (IMOEX, оборот от 300 млн до 5+ млрд ₽ в день)
        ("Сбербанк", "SBER"), ("Газпром", "GAZP"), ("Лукойл", "LKOH"), ("Яндекс", "YDEX"),
        ("Роснефть", "ROSN"), ("Новатэк", "NVTK"), ("Норникель", "GMKN"), ("Полюс", "PLZL"),
        ("Татнефть", "TATN"), ("Сургутнефтегаз-п", "SNGSP"), ("Сургутнефтегаз", "SNGS"),
        ("ВТБ", "VTBR"), ("Мосбиржа", "MOEX"), ("Т-Технологии", "T"), ("Магнит", "MGNT"),
        ("Транснефть-п", "TRNFP"), ("МТС", "MTSS"), ("Озон", "OZON"), ("Северсталь", "CHMF"),
        ("НЛМК", "NLMK"),
    ],
    2: [  # Высоколиквидный 2-й эшелон (оборот > 50-300 млн ₽ в день, включая POSI)
        ("Позитив", "POSI"), ("АФК Система", "AFKS"), ("Аэрофлот", "AFLT"), ("Совкомфлот", "FLOT"),
        ("ММК", "MAGN"), ("АЛРОСА", "ALRS"), ("ВК", "VKCO"), ("Хэдхантер", "HEAD"),
        ("Самолет", "SMLT"), ("Ростелеком", "RTKM"), ("РусГидро", "HYDR"), ("ФосАгро", "PHOR"),
        ("Русал", "RUAL"), ("ПИК", "PIK"), ("Интер РАО", "IRAO"), ("БСПБ", "BSPB"),
        ("ЮГК", "UGLD"), ("Селигдар", "SELG"), ("МКБ", "CBOM"), ("Группа Астра", "ASTR"),
        ("Мечел", "MTLR"), ("Распадская", "RASP"), ("Сбербанк-п", "SBERP"), ("Татнефть-п", "TATNP"),
    ],
    3: [  # 3-й эшелон с оборотом > 20 млн ₽ в день
        ("Европлан", "LEAS"), ("ЕвроТранс", "EUTR"), ("Whoosh", "WUSH"), ("Софтлайн", "SOFL"),
        ("Делимобиль", "DELI"), ("Ренессанс", "RENI"), ("Сегежа", "SGZH"), ("М.Видео", "MVID"),
        ("ДВМП", "FESH"), ("ТМК", "TRMK"), ("ЭН+ Груп", "ENPG"), ("Юнипро", "UPRO"),
        ("Мать и дитя", "MDMG"), ("НоваБев", "BELU"), ("Инарктика", "AQUA"), ("РуссНефть", "RNFT"),
        ("Башнефть-п", "BANEP"), ("Башнефть", "BANE"), ("Мечел-п", "MTLRP"), ("Черкизово", "GCHE"),
        ("ЛСР", "LSRG"), ("ЦИАН", "CIAN"), ("Русагро", "AGRO"),
    ],
}
ALL_TIER_ENTRIES: list[tuple[int, str, str]] = [
    (tier, name, ticker) for tier, lst in TIER_WATCHLISTS.items() for name, ticker in lst
]
TICKER_TO_NAME: dict[str, str] = {ticker: name for _, name, ticker in ALL_TIER_ENTRIES}
TICKER_TO_TIER: dict[str, int] = {ticker: tier for tier, _, ticker in ALL_TIER_ENTRIES}

LIQUID_WATCHLIST: list[tuple[str, str]] = []   # активный набор (пересобирается из ACTIVE_TICKERS)
LIQUID_AUTOTRADE_TICKERS: set[str] = set()     # активные тикеры освобождаются от фильтра ликвидности
ACTIVE_TICKERS: set[str] = {t for tier in (1, 2) for _, t in TIER_WATCHLISTS[tier]}  # по умолчанию 1-й + 2-й


def rebuild_active_watchlist() -> None:
    """Пересобирает LIQUID_WATCHLIST и LIQUID_AUTOTRADE_TICKERS из ACTIVE_TICKERS (защита от пустого выбора)."""
    global LIQUID_WATCHLIST, LIQUID_AUTOTRADE_TICKERS
    active = ACTIVE_TICKERS or {t for _, t in TIER_WATCHLISTS[1]}
    LIQUID_WATCHLIST = [
        (name, ticker)
        for tier in (1, 2, 3)
        for name, ticker in TIER_WATCHLISTS[tier]
        if ticker in active
    ]
    LIQUID_AUTOTRADE_TICKERS = {t for _, t in LIQUID_WATCHLIST}


rebuild_active_watchlist()

TIMEFRAMES = {
    "1m":  {"btn": "1м",  "interval": "CANDLE_INTERVAL_1_MIN",  "delta": timedelta(days=2),   "label": "1 мин",  "sec": 60},
    "5m":  {"btn": "5м",  "interval": "CANDLE_INTERVAL_5_MIN",  "delta": timedelta(days=5),   "label": "5 мин",  "sec": 300},
    "15m": {"btn": "15м", "interval": "CANDLE_INTERVAL_15_MIN", "delta": timedelta(days=12),  "label": "15 мин", "sec": 900},
    "30m": {"btn": "30м", "interval": "CANDLE_INTERVAL_30_MIN", "delta": timedelta(days=20),  "label": "30 мин", "sec": 1800},
    "1h":  {"btn": "1ч",  "interval": "CANDLE_INTERVAL_HOUR",   "delta": timedelta(days=35),  "label": "1 час",  "sec": 3600},
    "4h":  {"btn": "4ч",  "interval": "CANDLE_INTERVAL_4_HOUR", "delta": timedelta(days=90),  "label": "4 часа", "sec": 14400},
    "1d":  {"btn": "1д",  "interval": "CANDLE_INTERVAL_DAY",    "delta": timedelta(days=365), "label": "1 день", "sec": 86400},
}

INFORMANT_TIMEFRAMES = ("5m", "15m", "30m", "1h", "4h")


def get_allowed_history_dates() -> set[str]:
    today_msk = datetime.now(MSK_TZ).date()
    return {
        (today_msk - timedelta(days=i)).isoformat()
        for i in range(HISTORY_RETENTION_DAYS)
    }


def prune_old_history_items(history_seq, max_items: int = 300) -> deque:
    today_iso = datetime.now(MSK_TZ).date().isoformat()
    cleaned = deque()

    if not history_seq:
        return cleaned

    seen = set()
    for item in history_seq:
        if isinstance(item, dict):
            item_date = str(item.get("date", today_iso))
            item_text = str(item.get("text", "")).strip()
        elif isinstance(item, str):
            item_date = today_iso
            item_text = item.strip()
        else:
            continue

        if item_text and item_text not in seen:
            seen.add(item_text)
            cleaned.append({"date": item_date, "text": item_text})
            if len(cleaned) >= max_items:
                break

    return cleaned


def add_history_entry(user_id: int, entry_text: str):
    st = get_user_stats(user_id)
    now_msk = datetime.now(MSK_TZ)
    date_iso = now_msk.date().isoformat()
    time_label = now_msk.strftime("%d.%m %H:%M")
    st["history"].appendleft({
        "date": date_iso,
        "text": f"{entry_text} [{time_label}]",
    })


def serialize_state(for_cloud: bool = False) -> dict:
    stats_serializable = {}
    for uid, st in USER_STATS.items():
        cleaned_hist = prune_old_history_items(st.get("history", []), max_items=(50 if for_cloud else 300))
        st["history"] = cleaned_hist
        entry = {
            "wins": int(st.get("wins", 0)),
            "losses": int(st.get("losses", 0)),
            "be": int(st.get("be", 0)),
            "compound_mult": round(float(st.get("compound_mult", 1.0)), 6),
            "history": list(cleaned_hist),
        }
        stats_serializable[str(uid)] = entry
    tracked_serializable = {str(uid): sigs for uid, sigs in TRACKED_SIGNALS.items()}
    subs_serializable = {str(uid): th for uid, th in AUTO_SIGNAL_SUBSCRIBERS.items()}
    return {
        "saved_ts": round(time.time(), 1),
        "owner_uid": _get_primary_user_id(),  # patch36: чтобы после рестарта веб продолжал писать владельцу
        "cvd_file_id": _CVD_FILE_ID,
        "stats": stats_serializable,
        "tracked": tracked_serializable,
        "pending_orders": PENDING_OPEN_ORDERS,
        "subs": subs_serializable,
        "active_tickers": sorted(ACTIVE_TICKERS),
        "whale_stats": {str(k): {"events": int(v.get("events", 0)), "hits": int(v.get("hits", 0)), "avg_move_pct": float(v.get("avg_move_pct", 0.0))} for k, v in WHALE_STATS.items()},
    }


def apply_deserialized_state(data: dict):
    if not isinstance(data, dict):
        return
    global _TG_OWNER_UID
    _ow = int(data.get("owner_uid") or 0)
    if _ow > 0:  # patch36
        _TG_OWNER_UID = _ow
    for uid_str, st in data.get("stats", {}).items():
        uid = int(uid_str)
        old_net = st.get("net_pct", None)
        if old_net is not None:
            comp_m = 1.0 + (float(old_net) / 100.0)
        else:
            comp_m = float(st.get("compound_mult", 1.0))

        existing_st = USER_STATS.get(uid, {})
        existing_hist = list(existing_st.get("history", []))
        incoming_hist = list(st.get("history", []))

        merged_hist = incoming_hist
        if existing_hist:
            seen_texts = {h.get("text") if isinstance(h, dict) else str(h) for h in incoming_hist}
            for ex in existing_hist:
                ex_text = ex.get("text") if isinstance(ex, dict) else str(ex)
                if ex_text not in seen_texts:
                    seen_texts.add(ex_text)
                    merged_hist.append(ex)

        USER_STATS[uid] = {
            "wins": max(int(st.get("wins", 0)), int(existing_st.get("wins", 0))),
            "losses": max(int(st.get("losses", 0)), int(existing_st.get("losses", 0))),
            "be": max(int(st.get("be", 0)), int(existing_st.get("be", 0))),
            "compound_mult": comp_m,
            "history": prune_old_history_items(merged_hist),
        }
    PENDING_OPEN_ORDERS.clear()
    PENDING_OPEN_ORDERS.update(data.get("pending_orders", {}))
    for uid_str, sigs in data.get("tracked", {}).items():
        uid = int(uid_str)
        if isinstance(sigs, dict):
            TRACKED_SIGNALS[uid] = sigs
    for uid_str, th in data.get("subs", {}).items():
        uid = int(uid_str)
        AUTO_SIGNAL_SUBSCRIBERS[uid] = float(th)
    at = data.get("active_tickers")
    if isinstance(at, list) and at:
        known = {str(t).upper() for t in at if str(t).upper() in TICKER_TO_TIER}
        if known:
            ACTIVE_TICKERS.clear()
            ACTIVE_TICKERS.update(known)
            rebuild_active_watchlist()
    ws = data.get("whale_stats")
    if isinstance(ws, dict):
        for k, v in ws.items():
            if isinstance(v, dict):
                WHALE_STATS[str(k)] = {"events": int(v.get("events", 0)), "hits": int(v.get("hits", 0)),
                                       "avg_move_pct": float(v.get("avg_move_pct", 0.0))}
    global _CVD_FILE_ID
    _CVD_FILE_ID = data.get("cvd_file_id") or None


def _atomic_write(path: str, text: str) -> None:
    """Запись через временный файл + os.replace: файл не побьётся при падении процесса."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


async def _cloud_backup(raw_json: str) -> None:
    """Резервная копия состояния в описаниях команд Telegram (включается CLOUD_BACKUP_ENABLED=1).

    patch32: чанки по 250 симв. (лимит описания 256), до 99 команд; если полный стейт не влезает —
    повтор с обрезанной копией (без истории сделок), чтобы сделки/винрейт точно дошли до облака.
    """
    try:
        def _pack(text: str):
            compressed = zlib.compress(text.encode("utf-8"), level=9)
            b64_str = base64.urlsafe_b64encode(compressed).decode("ascii")
            return [b64_str[i : i + 250] for i in range(0, len(b64_str), 250)], len(b64_str)

        chunks, b64_len = _pack(raw_json)
        if len(chunks) > 99:
            trimmed = json.dumps(serialize_state(for_cloud=True), ensure_ascii=False)
            chunks, b64_len = _pack(trimmed)
            logging.warning(f"облачный бэкап большого стейта: обрезан до копии без истории ({b64_len} симв. b64, {len(chunks)} чанков)")
        if len(chunks) > 99:
            logging.error("Состояние не влезает даже в обрезанный облачный бэкап (>99 чанков) — бэкап пропущен")
            return
        commands = [BotCommand(command=f"bak_{i}", description=chunk) for i, chunk in enumerate(chunks)]
        await bot.set_my_commands(commands=commands, scope=BotCommandScopeDefault(), language_code=CLOUD_LANG_SLOT)
        logging.info(f"облачный бэкап обновлён: {len(raw_json)} Б сырых, {len(chunks)} чанков")
    except Exception as e:
        logging.error(f"Ошибка облачного бэкапа состояния: {e}")


def _backup_chat_id() -> int:
    """Куда слать бэкап-файл: BACKUP_CHAT_ID или первый известный пользователь из стейта."""
    if BACKUP_CHAT_ID:
        return BACKUP_CHAT_ID
    for uid in list(AUTO_SIGNAL_SUBSCRIBERS) + list(USER_STATS) + list(TRACKED_SIGNALS):
        if isinstance(uid, int) and uid > 0:
            return uid
    return 0


async def _backup_cvd_file_now(force: bool = False) -> None:
    """Бэкап cvd_data.db как Telegram-документа; file_id сохраняется в стейт (облако bak_N)."""
    global _CVD_FILE_ID, _CVD_FILE_BACKUP_TS
    if not (CLOUD_BACKUP_ENABLED and CVD_FILE_BACKUP and CVD_STORE_ENABLED):
        return
    now = time.time()
    if not force and now - _CVD_FILE_BACKUP_TS < CVD_FILE_BACKUP_EVERY_SEC:
        return
    chat = _backup_chat_id()
    if not chat or not os.path.exists(CVD_DB_PATH):
        return
    try:
        await asyncio.to_thread(CVD_STORE.flush)
        msg = await bot.send_document(
            chat, FSInputFile(CVD_DB_PATH, filename="cvd_data.db"),
            caption=f"cvd_data.db backup {datetime.now(MSK_TZ).strftime('%Y-%m-%d %H:%M')} MSK",
        )
        _CVD_FILE_ID = msg.document.file_id
        _CVD_FILE_BACKUP_TS = now
        logging.info(f"CVD file backup: cvd_data.db отправлен в чат {chat} (file_id в стейте)")
    except Exception as e:
        logging.warning(f"CVD file backup: {e}")


async def _restore_cvd_file_from_cloud() -> None:
    """Восстановление cvd_data.db из Telegram-документа при старте (до CVD_STORE.load())."""
    if not (CLOUD_BACKUP_ENABLED and CVD_FILE_BACKUP and _CVD_FILE_ID):
        return
    tmp = CVD_DB_PATH + ".cloud"
    try:
        f = await bot.get_file(_CVD_FILE_ID)
        await bot.download_file(f.file_path, tmp)
        if os.path.getsize(tmp) > 0 and (not os.path.exists(CVD_DB_PATH) or os.path.getsize(tmp) >= os.path.getsize(CVD_DB_PATH)):
            # сначала гасим старое соединение хранилища и sidecar-файлы WAL, иначе load() прочитает старый inode
            try:
                if CVD_STORE._conn is not None:
                    CVD_STORE._conn.close()
            except Exception:
                pass
            CVD_STORE._conn = None
            for ext in ("-wal", "-shm", "-journal"):
                side = CVD_DB_PATH + ext
                if os.path.exists(side):
                    try:
                        os.remove(side)
                    except OSError:
                        pass
            os.replace(tmp, CVD_DB_PATH)
            logging.info("CVD file restore: cvd_data.db восстановлен из облака (Telegram-документ)")
        elif os.path.exists(tmp):
            os.remove(tmp)
    except Exception as e:
        logging.warning(f"CVD file restore: {e}")


async def _save_bot_state_now() -> None:
    """Непосредственно сериализует и пишет состояние (локальный файл + опционально облако)."""
    global _state_save_ts, _state_save_pending
    _state_save_ts = time.time()
    _state_save_pending = False
    raw_json = json.dumps(serialize_state(), ensure_ascii=False)
    try:
        await asyncio.to_thread(_atomic_write, STATE_FILE, raw_json)
    except Exception:
        logging.exception("Ошибка записи локального файла состояния")
    if CLOUD_BACKUP_ENABLED:
        await _cloud_backup(raw_json)
        await _backup_cvd_file_now()


async def save_bot_state(force: bool = False) -> None:
    """Debounce с гарантией доставки: «съеденный» вызов не теряется, а пишется отложенно."""
    global _state_save_pending
    async with _STATE_SAVE_LOCK:
        now = time.time()
        if not force and (now - _state_save_ts) < STATE_SAVE_DEBOUNCE:
            if not _state_save_pending:
                _state_save_pending = True
                asyncio.get_running_loop().call_later(
                    STATE_SAVE_DEBOUNCE,
                    lambda: asyncio.ensure_future(save_bot_state(force=True)),
                )
            return
        await _save_bot_state_now()


async def load_bot_state():
    """patch32: читаем И облако, И локальный файл и применяем СВЕЖЕЕ по saved_ts —
    так «застрявшая» старая облачная копия больше не затирает свежий локальный файл и наоборот."""
    candidates: list[tuple[float, dict, str]] = []
    if CLOUD_BACKUP_ENABLED:
        try:
            cmds = await bot.get_my_commands(
                scope=BotCommandScopeDefault(),
                language_code=CLOUD_LANG_SLOT,
            )
            sorted_cmds = sorted(
                [c for c in cmds if c.command.startswith("bak_")],
                key=lambda x: int(x.command.split("_")[1]),
            )
            if sorted_cmds:
                b64_str = "".join(c.description for c in sorted_cmds)
                raw_json = zlib.decompress(base64.urlsafe_b64decode(b64_str.encode("ascii"))).decode("utf-8")
                data = json.loads(raw_json)
                candidates.append((float(data.get("saved_ts", 0) or 0), data, "облако"))
        except Exception as e:
            logging.error(f"Ошибка чтения облачного бэкапа: {e}")

    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            candidates.append((float(data.get("saved_ts", 0) or 0), data, "локальный файл"))
        except Exception as e:
            logging.error(f"Ошибка чтения локального файла: {e}")

    if candidates:
        candidates.sort(key=lambda c: c[0])
        for ts, data, source in candidates:
            apply_deserialized_state(data)
            logging.info(f"Стейт применён из: {source} (saved_ts={ts:.0f})")

        owner_id = _get_primary_user_id()
        owner_st = get_user_stats(owner_id)
        owner_hist = list(owner_st.get("history", []))
        owner_seen = {h.get("text") if isinstance(h, dict) else str(h) for h in owner_hist}
        for u_id, u_st in list(USER_STATS.items()):
            if u_id > 0 and u_id != owner_id:
                for h in u_st.get("history", []):
                    h_txt = h.get("text") if isinstance(h, dict) else str(h)
                    if h_txt not in owner_seen:
                        owner_seen.add(h_txt)
                        owner_hist.append(h)
        owner_st["history"] = prune_old_history_items(owner_hist)

        _moved = _migrate_orphan_trades()  # patch35: веб-сделки на «чужом» uid -> владельцу
        if _moved:
            logging.info(f"patch35: перенесено { _moved } веб-сделок на владельца (uid={_get_primary_user_id()})")
        await save_bot_state(force=True)
    else:
        logging.info("Сохранённого состояния нет — старт с нуля." + ("" if CLOUD_BACKUP_ENABLED else
            " (CLOUD_BACKUP_ENABLED=0 — облако не читается; на эфемерном диске Render это = потеря винрейта и сделок при рестарте)"))


def quotation_to_float(quotation: dict | None) -> float | None:
    if not quotation:
        return None
    units = int(quotation.get("units", 0))
    nano = int(quotation.get("nano", 0))
    if units == 0 and nano == 0:
        return None
    # Убрано округление для точности расчетов, округляем только при выводе (в format_...)
    return units + nano / 1_000_000_000


def format_lots_delta(lots_val: float) -> str:
    """Лоты со знаком (для дельты/CVD)."""
    abs_val = abs(lots_val)
    sign = "-" if lots_val < 0 else ("+" if lots_val > 0 else "")
    # Округляем только для вывода, чтобы не терять точность в расчетах
    val_rounded = round(abs_val, 4)
    if val_rounded >= 1_000_000:
        return f"{sign}{val_rounded / 1_000_000:.2f} млн лот."
    elif val_rounded >= 1_000:
        return f"{sign}{val_rounded / 1_000:.1f} тыс. лот."
    return f"{sign}{int(val_rounded)} лот."


def format_lots_abs(lots_val: float) -> str:
    """Лоты без знака (для объёмов)."""
    abs_val = abs(lots_val)
    val_rounded = round(abs_val, 4)
    if val_rounded >= 1_000_000:
        return f"{val_rounded / 1_000_000:.2f} млн лот."
    if val_rounded >= 1_000:
        return f"{val_rounded / 1_000:.1f} тыс. лот."
    return f"{int(val_rounded)} лот."


def format_rub_volume(value: float) -> str:
    """Компактное отображение рублёвого объёма уровня стакана."""
    value = abs(float(value or 0.0))
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} млрд ₽"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} млн ₽"
    if value >= 1_000:
        return f"{value / 1_000:.1f} тыс. ₽"
    return f"{value:.0f} ₽"



# =====================================================================
# ДИВИДЕНДНЫЙ И ЭКСПИРАЦИОННЫЙ КАЛЕНДАРЬ MOEX
# =====================================================================
MOEX_DIVIDEND_CALENDAR = {
    "SBER": {"date": "2026-11-12", "div_rub": 33.30, "yield_pct": 11.2},
    "SBERP": {"date": "2026-11-12", "div_rub": 33.30, "yield_pct": 11.2},
    "LKOH": {"date": "2026-11-20", "div_rub": 514.0, "yield_pct": 7.4},
    "TATN": {"date": "2026-11-18", "div_rub": 38.20, "yield_pct": 6.1},
    "TATNP": {"date": "2026-11-18", "div_rub": 38.20, "yield_pct": 6.2},
    "ROSN": {"date": "2026-12-05", "div_rub": 36.47, "yield_pct": 7.5},
    "NVTK": {"date": "2026-11-25", "div_rub": 35.50, "yield_pct": 3.8},
    "CHMF": {"date": "2026-12-10", "div_rub": 49.06, "yield_pct": 3.9},
    "NLMK": {"date": "2026-12-14", "div_rub": 12.80, "yield_pct": 7.1},
    "GMKN": {"date": "2026-12-22", "div_rub": 115.0, "yield_pct": 6.8},
    "FLOT": {"date": "2026-11-28", "div_rub": 11.27, "yield_pct": 10.5},
    "PLZL": {"date": "2026-12-08", "div_rub": 1301.75, "yield_pct": 9.1},
    "TRNFP": {"date": "2026-12-15", "div_rub": 177.2, "yield_pct": 12.8},
    "SNGSP": {"date": "2026-12-20", "div_rub": 12.29, "yield_pct": 21.0},
    "MGNT": {"date": "2026-12-18", "div_rub": 412.13, "yield_pct": 8.2},
}

def get_dividend_info(ticker: str) -> dict | None:
    t = str(ticker).upper().strip()
    data = MOEX_DIVIDEND_CALENDAR.get(t)
    if not data:
        return None
    try:
        div_d = datetime.strptime(data["date"], "%Y-%m-%d").date()
        today = datetime.now().date()
        days_left = (div_d - today).days
        cutoff_soon = 0 <= days_left <= 4
        return {
            "ticker": t,
            "date": data["date"],
            "div_rub": data["div_rub"],
            "yield_pct": data["yield_pct"],
            "days_left": days_left,
            "cutoff_soon": cutoff_soon,
            "warning": f"⚠️ Дивотсечка через {days_left} дн.! Риск дивгэпа, шорт запрещён/опасен." if cutoff_soon else f"📅 Дивиденды {data['date']}: {data['div_rub']} ₽ ({data['yield_pct']}%)"
        }
    except Exception:
        return None

def get_moex_dividend_calendar_summary() -> list[dict]:
    res = []
    today = datetime.now().date()
    for t, data in MOEX_DIVIDEND_CALENDAR.items():
        try:
            div_d = datetime.strptime(data["date"], "%Y-%m-%d").date()
            days_left = (div_d - today).days
            res.append({
                "ticker": t,
                "date": data["date"],
                "div_rub": data["div_rub"],
                "yield_pct": data["yield_pct"],
                "days_left": days_left,
                "cutoff_soon": 0 <= days_left <= 4,
                "risk": "ВЫСОКИЙ (Шорт запрещён)" if 0 <= days_left <= 4 else ("ВНИМАНИЕ" if days_left <= 10 else "УМЕРЕННЫЙ")
            })
        except Exception:
            pass
    res.sort(key=lambda x: x["days_left"])
    return res

def analyze_visible_liquidity(
    bids: list[dict] | None,
    asks: list[dict] | None,
    lot_size: int,
    current_price: float,
    min_tick: float | None = None,
) -> dict:
    """Извлекает крупные ВИДИМЫЕ уровни стакана; участников/роботов не классифицирует."""
    def parse_side(rows: list[dict] | None) -> list[dict]:
        parsed = []
        for row in rows or []:
            price = quotation_to_float(row.get("price"))
            try:
                quantity = int(row.get("quantity", 0))
            except (TypeError, ValueError):
                quantity = 0
            if price is None or price <= 0 or quantity <= 0:
                continue
            parsed.append({
                "price": float(price),
                "quantity": quantity,
                "rub": float(price) * quantity * max(int(lot_size or 1), 1),
            })
        return parsed

    bid_levels = parse_side(bids)
    ask_levels = parse_side(asks)
    bid_total = sum(row["quantity"] for row in bid_levels)
    ask_total = sum(row["quantity"] for row in ask_levels)
    total = bid_total + ask_total
    bid_share_pct = (100.0 * bid_total / total) if total else 50.0

    def find_wall(levels: list[dict], side: str) -> dict | None:
        if not levels:
            return None
        median_qty = float(np.median([row["quantity"] for row in levels]))
        if median_qty <= 0:
            return None
        candidates = []
        for row in levels:
            if side == "bid" and row["price"] >= current_price:
                continue
            if side == "ask" and row["price"] <= current_price:
                continue
            multiple = row["quantity"] / median_qty
            if multiple >= BOOK_WALL_MIN_MULT and row["rub"] >= BOOK_WALL_MIN_RUB:
                candidates.append({**row, "multiple": multiple})
        if not candidates:
            return None
        # Ближайший уровень к цене важнее более дальних крупных объёмов.
        return max(candidates, key=lambda row: row["price"]) if side == "bid" else min(candidates, key=lambda row: row["price"])

    bid_wall = find_wall(bid_levels, "bid")
    ask_wall = find_wall(ask_levels, "ask")

    iceberg_orders = []
    for side_name, levels in (("SELL", ask_levels), ("BUY", bid_levels)):
        if not levels:
            continue
        med_q = float(np.median([r["quantity"] for r in levels])) or 1.0
        for r in levels[:8]:
            mult = r["quantity"] / med_q
            if mult >= 3.0 and r["rub"] >= 2_000_000:
                est_hidden = int(r["quantity"] * 3.5)
                est_rub = float(r["rub"] * 3.5)
                iceberg_orders.append({
                    "side": side_name,
                    "price": round(r["price"], 4),
                    "visible_qty": int(r["quantity"]),
                    "est_hidden_qty": est_hidden,
                    "visible_rub": round(r["rub"], 1),
                    "est_total_rub": round(est_rub, 1),
                    "multiple": round(mult, 1),
                    "confidence": "ВЫСОКАЯ" if mult >= 5.0 else "СРЕДНЯЯ"
                })

    iceberg_alert = None
    if iceberg_orders:
        top_ice = max(iceberg_orders, key=lambda x: x["visible_rub"])
        action_word = "продажу" if top_ice["side"] == "SELL" else "покупку"
        iceberg_alert = f"🧊 Айсберг на {action_word}: {top_ice['price']:.2f} ₽ (~{format_lots_abs(top_ice['est_hidden_qty'])} лот., {format_rub_volume(top_ice['est_total_rub'])})"


    try:
        tick = float(min_tick or 0.0)
    except (TypeError, ValueError):
        tick = 0.0
    if tick <= 0:
        prices = sorted({round(row["price"], 8) for row in bid_levels + ask_levels})
        gaps = [b - a for a, b in zip(prices, prices[1:]) if b - a > 1e-7]
        tick = min(gaps) if gaps else max(abs(float(current_price or 0.0)) * 0.0001, 0.001)

    def wall_string(wall: dict | None) -> str:
        if not wall:
            return "не найдено"
        return (
            f"{wall['price']:.4f} ₽ · {format_lots_abs(wall['quantity'])} · "
            f"{format_rub_volume(wall['rub'])} · {wall['multiple']:.1f}× медианы"
        )

    return {
        "available": bool(bid_levels or ask_levels),
        "bid_share_pct": round(bid_share_pct, 1),
        "top_bids": bid_levels[:12],
        "top_asks": ask_levels[:12],
        "bid_volume_lots": int(bid_total),
        "ask_volume_lots": int(ask_total),
        "bid_wall_price": round(bid_wall["price"], 6) if bid_wall else None,
        "bid_wall_quantity": bid_wall["quantity"] if bid_wall else 0,
        "bid_wall_rub": round(bid_wall["rub"], 2) if bid_wall else 0.0,
        "bid_wall_mult": round(bid_wall["multiple"], 1) if bid_wall else 1.0,
        "bid_wall_str": wall_string(bid_wall),
        "ask_wall_price": round(ask_wall["price"], 6) if ask_wall else None,
        "ask_wall_quantity": ask_wall["quantity"] if ask_wall else 0,
        "ask_wall_rub": round(ask_wall["rub"], 2) if ask_wall else 0.0,
        "ask_wall_mult": round(ask_wall["multiple"], 1) if ask_wall else 1.0,
        "ask_wall_str": wall_string(ask_wall),
        "tick_size": round(tick, 8),
        "icebergs": iceberg_orders,
        "iceberg_alert": iceberg_alert,
    }


def api_headers() -> dict:
    return {
        "Authorization": f"Bearer {T_INVEST_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def get_session() -> aiohttp.ClientSession:
    """Одна общая сессия на всё приложение (с поддержкой сертификатов РФ без падения TLS)."""
    global SESSION
    if SESSION is None or SESSION.closed:
        ca_bundle = os.getenv("T_INVEST_CA_BUNDLE", "").strip()
        proxy_url = os.getenv("T_INVEST_PROXY", "").strip() or None
        # По умолчанию отключаем проверку CA, так как сертификат Минцифры РФ (tbank.ru)
        # не входит в базовый пакет certifi на Render / Windows
        conn_kwargs: dict = {"limit": 64, "ttl_dns_cache": 300, "ssl": False}
        if ca_bundle and os.path.exists(ca_bundle):
            conn_kwargs["ssl"] = ssl.create_default_context(cafile=ca_bundle)
            logging.info(f"TLS: доп. CA-bundle {ca_bundle} (проверка сертификатов включена)")
        connector = aiohttp.TCPConnector(**conn_kwargs)
        SESSION = aiohttp.ClientSession(
            headers=api_headers(),
            connector=connector,
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=20),
        )
    return SESSION


def _log_transport_error(method: str, e: Exception) -> None:
    """Логирует транспортную ошибку; при TLS-ошибке даёт понятную подсказку (но проверку НЕ отключает)."""
    global _LAST_TLS_ERR_TS
    msg = str(e)
    if "CERTIFICATE_VERIFY_FAILED" in msg or isinstance(e, aiohttp.ClientConnectorCertificateError):
        _LAST_TLS_ERR_TS = time.time()
        logging.error(
            f"{method}: TLS-сертификат T-Invest API не доверен на этом хосте (перехват трафика DPI/прокси или старый CA-bundle). "
            f"Проверьте: дата/время хоста (date -u), пакет ca-certificates, pip install -U certifi; "
            f"либо задайте T_INVEST_CA_BUNDLE=<pem-bundle с корневым CA перехватчика> или T_INVEST_PROXY. "
            f"Проверку сертификата отключать НЕЛЬЗЯ — иначе токен уйдёт посреднику (MITM)."
        )
    else:
        logging.warning(f"{method}: {e}")


async def api_post(method: str, payload: dict, timeout: float = 10.0):
    """POST к T-Invest API с ограничением параллелизма. Возвращает dict или {} при ошибке."""
    session = await get_session()
    async with HTTP_SEMAPHORE:
        try:
            async with session.post(
                f"{T_API_BASE}.{method}", json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    if resp.status in (401, 403):
                        global _LAST_AUTH_ERR_TS
                        _LAST_AUTH_ERR_TS = time.time()
                        logging.error(f"{method}: авторизация T-Invest отклонена (проверьте T_INVEST_TOKEN)")
                    return {}
                return await resp.json()
        except asyncio.TimeoutError:
            logging.warning(f"{method}: таймаут")
            return {}
        except Exception as e:
            _log_transport_error(method, e)
            return {}


def get_user_stats(user_id: int) -> dict:
    if user_id not in USER_STATS:
        USER_STATS[user_id] = {
            "wins": 0,
            "losses": 0,
            "be": 0,
            "compound_mult": 1.0,
            "history": deque(),
        }
    USER_STATS[user_id].setdefault("be", 0)
    if "compound_mult" not in USER_STATS[user_id]:
        old_net = USER_STATS[user_id].get("net_pct", 0.0)
        USER_STATS[user_id]["compound_mult"] = 1.0 + (old_net / 100.0)

    USER_STATS[user_id]["history"] = prune_old_history_items(USER_STATS[user_id].get("history", []))
    return USER_STATS[user_id]


def calc_winrate_str(user_id: int | None) -> str:
    if not user_id:
        return "0% (0/0)"
    st = get_user_stats(user_id)
    total = st["wins"] + st["losses"]
    wr = (st["wins"] / total * 100) if total > 0 else 0.0
    return f"{wr:.0f}% ({st['wins']}В/{st['losses']}С)"


def position_amount_rub() -> float:
    """Сумма одной позиции: депозит делится на TRADING_MAX_POSITIONS равных частей."""
    return TRADING_DEPOSIT_RUB / max(1, TRADING_MAX_POSITIONS)


def portfolio_rub(user_id: int) -> tuple[float, float]:
    """(стоимость портфеля ₽, накопленный PnL ₽) относительно депозита TRADING_DEPOSIT_RUB (сложные проценты сделок)."""
    st = get_user_stats(user_id)
    mult = float(st.get("compound_mult", 1.0))
    return TRADING_DEPOSIT_RUB * mult, TRADING_DEPOSIT_RUB * (mult - 1.0)


def portfolio_line(user_id: int) -> str:
    """Строка «Портфель: X ₽ (депозит 10 млн, PnL ±Y ₽ / ±Z%)» для карточек/статистики."""
    val, pnl = portfolio_rub(user_id)
    pct = (pnl / TRADING_DEPOSIT_RUB * 100.0) if TRADING_DEPOSIT_RUB > 0 else 0.0
    return (f"💼 <b>Портфель:</b> {val:,.0f} ₽ (депозит {TRADING_DEPOSIT_RUB:,.0f} ₽, "
            f"PnL <b>{pnl:+,.0f} ₽ / {pct:+.2f}%</b>, сложными)")


def get_account_margin_summary(user_id: int | None = None) -> dict:
    """Сводка маржи пользователя (ручные позиции). Позиции алгоритмических стратегий изолированы и учитываются отдельно."""
    uid = user_id or _get_primary_user_id()
    deposit = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 10_000_000.0
    used_margin = 0.0
    used_buying_power = 0.0

    strat_uids = {st["uid"] for st in STRATS.values()}

    for u, sigs in TRACKED_SIGNALS.items():
        # Счета стратегий изолированы в свои субсчета и не съедают ручной лимит маржи пользователя
        if u in strat_uids:
            continue
        if isinstance(sigs, dict):
            for tk, s in sigs.items():
                if s.get("strategy"):
                    continue
                m_rub = float(s.get("margin_rub") or (float(s.get("real_amount_rub") or s.get("amount_rub") or 0.0) / max(float(s.get("leverage") or 1.0), 1.0)))
                used_margin += m_rub
                used_buying_power += float(s.get("real_amount_rub") or s.get("amount_rub") or 0.0)

    free_margin = max(0.0, deposit - used_margin)
    margin_level_pct = round((used_margin / deposit) * 100.0, 1) if deposit > 0 else 0.0

    return {
        "deposit_rub": round(deposit, 0),
        "used_margin_rub": round(used_margin, 0),
        "free_margin_rub": round(free_margin, 0),
        "used_buying_power_rub": round(used_buying_power, 0),
        "margin_level_pct": margin_level_pct,
    }


# =====================================================================
# 3. ИНЛАЙН-КЛАВИАТУРЫ (С ВЫБОРОМ 5м/15м/30м/1ч/4ч И РУЧНЫМ ВХОДОМ)
# =====================================================================
def get_main_keyboard(
    active_ticker: str | None = None,
    active_tf: str = "15m",
    user_id: int | None = None,
) -> InlineKeyboardMarkup:
    buttons = []

    if active_ticker:
        buttons.append([
            InlineKeyboardButton(
                text=f"📈 График {active_ticker} ({TIMEFRAMES.get(active_tf, TIMEFRAMES['15m'])['btn']}) + POC + CVD",
                callback_data=f"chart_{active_ticker}_{active_tf}"
            )
        ])

        if active_ticker != "IMOEX":
            is_already_tracked = active_ticker in TRACKED_SIGNALS.get(user_id or 0, {})
            if is_already_tracked:
                buttons.append([
                    InlineKeyboardButton(text=f"✅ {active_ticker} в сделке", callback_data="show_tracked"),
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"tf_{active_ticker}_{active_tf}"),
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(text="🟢 Взять LONG", callback_data=f"manual_track_{active_ticker}_{active_tf}_LONG"),
                    InlineKeyboardButton(text="🔴 Взять SHORT", callback_data=f"manual_track_{active_ticker}_{active_tf}_SHORT"),
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"tf_{active_ticker}_{active_tf}"),
                ])

        tf_row_1 = []
        tf_row_2 = []
        for idx, (tf_key, cfg) in enumerate(TIMEFRAMES.items()):
            prefix = "✅ " if tf_key == active_tf else ""
            btn = InlineKeyboardButton(
                text=f"{prefix}{cfg['btn']}",
                callback_data=f"tf_{active_ticker}_{tf_key}",
            )
            if idx < 4:
                tf_row_1.append(btn)
            else:
                tf_row_2.append(btn)
        buttons.append(tf_row_1)
        buttons.append(tf_row_2)

    eff_uid = user_id if (user_id and user_id in USER_STATS) else _get_primary_user_id()  # patch36
    tracked_cnt = len(TRACKED_SIGNALS.get(eff_uid, {})) if eff_uid else 0
    wr_text = calc_winrate_str(eff_uid)

    buttons.append([
        InlineKeyboardButton(text="🏛 Индекс Мосбиржи (IMOEX)", callback_data="ticker_IMOEX"),
    ])
    buttons.append([
        InlineKeyboardButton(text="📡 Информатор / Снайпер / Роботы", callback_data="show_active_robots"),
        InlineKeyboardButton(text="🐋 Крупняк", callback_data="show_whales"),
    ])
    buttons.append([
        InlineKeyboardButton(text=f"👁 В сделке ({tracked_cnt})", callback_data="show_tracked"),
        InlineKeyboardButton(text=f"📊 Винрейт: {wr_text}", callback_data="show_stats"),
    ])
    buttons.append([
        InlineKeyboardButton(text="📥 Журнал CVD (CSV)", callback_data="export_cvd"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🧪 Бэктест 60д", callback_data="backtest_60"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🎛 Бумаги: 1/2/3 эшелон", callback_data="stocks_menu"),
    ])
    buttons.append([
        InlineKeyboardButton(text="💼 Счета стратегий (3)", callback_data="show_strats"),
    ])

    row = []
    for name, ticker in LIQUID_WATCHLIST[:6]:
        row.append(InlineKeyboardButton(text=f"{name} ({ticker})", callback_data=f"ticker_{ticker}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =====================================================================
# 4. РАСЧЁТ ИНДИКАТОРОВ, РЕСЕМПЛИНГ ТФ, POC, УРОВНЕЙ И РЕАЛЬНОГО CVD
# =====================================================================
# MOEX calendar 2026: weekends without DSV and official non-trading holidays.
# Keep these dates updated from the exchange calendar each year; for an
# unconfigured future year we fail closed on weekends rather than assume DSV.
MOEX_2026_DSV_CLOSED_DATES = {
    "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-07",
    "2026-01-10", "2026-01-11", "2026-02-14", "2026-02-15",
    "2026-03-07", "2026-03-08", "2026-03-21", "2026-03-22",
    "2026-05-09", "2026-05-10", "2026-06-20", "2026-06-21",
    "2026-08-01", "2026-08-02", "2026-08-15", "2026-08-16",
    "2026-09-12", "2026-09-13", "2026-10-24", "2026-10-25",
    "2026-12-05", "2026-12-06", "2026-12-31",
}
MOEX_2026_DSV_EXTRA_SESSION_DATES = {
    "2026-01-05", "2026-01-06", "2026-01-08", "2026-01-09",
    "2026-02-23", "2026-03-09", "2026-05-01", "2026-05-11",
    "2026-06-12", "2026-11-04",
}


def is_moex_trading_hours(now_msk: datetime | None = None) -> bool:
    """Approximate MOEX stock-market session gate (MSK); weekend DSV is calendar-based."""
    now_msk = now_msk or datetime.now(MSK_TZ)
    if now_msk.tzinfo is None:
        now_msk = now_msk.replace(tzinfo=MSK_TZ)
    else:
        now_msk = now_msk.astimezone(MSK_TZ)

    cur_minutes = now_msk.hour * 60 + now_msk.minute
    date_key = now_msk.date().isoformat()
    weekday_start = 6 * 60 + 55
    weekday_end = 23 * 60 + 50
    dsv_start = 9 * 60 + 50
    dsv_end = 19 * 60

    if now_msk.year == 2026:
        if date_key in MOEX_2026_DSV_CLOSED_DATES:
            return False
        if date_key in MOEX_2026_DSV_EXTRA_SESSION_DATES:
            return dsv_start <= cur_minutes < dsv_end
        if now_msk.weekday() >= 5:
            # Обычные выходные закрыты; DSV-торги только в даты из EXTRA_SESSION (обработаны выше)
            return False
        return weekday_start <= cur_minutes < weekday_end

    # Do not assume every weekend has a special session if this year's calendar
    # has not yet been added. Weekday hours remain a fallback approximation.
    if now_msk.weekday() >= 5:
        return False
    return weekday_start <= cur_minutes < weekday_end


def signal_data_is_live(
    sig: dict | None,
    now_ts: float | None = None,
    require_candle: bool = False,
    market_open: bool | None = None,
) -> bool:
    """Expire cached live flags using the age of the underlying market data."""
    if not sig:
        return False
    if market_open is None:
        market_open = is_moex_trading_hours()
    if not market_open:
        return False

    try:
        checked_ts = float(sig.get("data_checked_ts") or 0.0)
        if checked_ts <= 0:
            return False
        now_ts = time.time() if now_ts is None else now_ts
        elapsed_min = max(0.0, now_ts - checked_ts) / 60.0
        age_key = "last_candle_age_min" if require_candle else "last_activity_age_min"
        base_age = sig.get(age_key)
        if base_age is None:
            return False
        return float(base_age) + elapsed_min <= 20.0
    except (TypeError, ValueError):
        return False


def get_last_candle_age_minutes(candles: list[dict]) -> float:
    if not candles:
        return 99999.0
    t_str = candles[-1].get("time", "")
    if not t_str:
        return 99999.0
    try:
        dt_utc = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
        now_utc = datetime.now(timezone.utc)
        return max(0.0, (now_utc - dt_utc).total_seconds() / 60.0)
    except Exception:
        return 99999.0


def candles_to_df(candles: list[dict], fallback_price: float = 0.0) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    rows = []
    for c in candles:
        t_str = c.get("time", "")
        try:
            dt_msk = datetime.fromisoformat(t_str.replace("Z", "+00:00")).astimezone(MSK_TZ)
            date_msk = dt_msk.date()
        except Exception:
            # Пропускаем невалидную свечу
            continue

        def _px(key: str) -> float:
            v = quotation_to_float(c.get(key))
            # Если v=0, используем fallback_price, но если v=None (ошибка), тоже fallback
            return float(v) if (v is not None and v > 0) else float(fallback_price)

        rows.append({
            "dt_msk": dt_msk,
            "date_msk": date_msk,
            "Open": _px("open"),
            "High": _px("high"),
            "Low": _px("low"),
            "Close": _px("close"),
            "Volume": int(c.get("volume", 0)),
        })
    return pd.DataFrame(rows)


def resample_candles_df(df_source: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Формирует 30m из 15m или 4h из 1h без лишних HTTP-запросов к API."""
    if df_source.empty:
        return pd.DataFrame()
    try:
        tmp = df_source.copy().set_index("dt_msk")
        agg = tmp.resample(rule, label="left", closed="left").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna(subset=["Open", "Close"])
        agg = agg[agg["Volume"] > 0].reset_index()
        agg["date_msk"] = agg["dt_msk"].dt.date
        return agg[["dt_msk", "date_msk", "Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        logging.error(f"Ошибка ресемплинга свечей ({rule}): {e}")
        return pd.DataFrame()


def compute_tf_emas(df: pd.DataFrame) -> dict | None:
    if df.empty or len(df) < 5:
        return None
    close_s = df["Close"]
    price = float(close_s.iloc[-1])
    ema9 = float(close_s.ewm(span=9, adjust=False).mean().iloc[-1])
    ema20 = float(close_s.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close_s.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = float(close_s.ewm(span=200, adjust=False).mean().iloc[-1])

    if price > ema20 and ema9 >= ema20 and ema20 >= ema50:
        trend = "BULL"
        badge = "🟢 Бычий"
    elif price < ema20 and ema9 <= ema20 and ema20 <= ema50:
        trend = "BEAR"
        badge = "🔴 Медвежий"
    else:
        trend = "FLAT"
        badge = "⚪ Боковик"

    above_ema200 = price >= ema200
    return {
        "price": price,
        "ema9": round(ema9, 4),
        "ema20": round(ema20, 4),
        "ema50": round(ema50, 4),
        "ema200": round(ema200, 4),
        "trend": trend,
        "badge": badge,
        "above_ema200": above_ema200,
    }


def compute_poc_price(df: pd.DataFrame, num_bins: int = 35) -> float | None:
    if df.empty:
        return None
    price_min = float(df["Low"].min())
    price_max = float(df["High"].max())
    # Если диапазон слишком мал (меньше минимального шага цены), возвращаем None
    tick_estimate = (price_max - price_min) / len(df) if len(df) > 0 else 0
    if price_max <= price_min or (price_max - price_min) < (tick_estimate * 0.1):
        return None
    bin_edges = [price_min + i * (price_max - price_min) / num_bins for i in range(num_bins + 1)]
    vp_total = [0.0] * num_bins
    for _, row in df.iterrows():
        h, l, v = float(row["High"]), float(row["Low"]), float(row["Volume"])
        if v <= 0:
            continue
        if h == l:
            b_idx = min(int((h - price_min) / (price_max - price_min) * num_bins), num_bins - 1)
            vp_total[b_idx] += v
        else:
            for b in range(num_bins):
                overlap = max(0.0, min(h, bin_edges[b + 1]) - max(l, bin_edges[b]))
                if overlap > 0:
                    vp_total[b] += v * (overlap / (h - l))
    max_idx = max(range(num_bins), key=lambda i: vp_total[i])
    return round((bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2, 4)


def compute_sr_levels(
    current_price: float,
    df_main: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_1d: pd.DataFrame,
    mtf_emas: dict[str, dict],
) -> dict:
    candidates = []

    def extract_pivots(df: pd.DataFrame, tf_label: str):
        if df.empty or len(df) < 10:
            return
        tail_25 = df.tail(25)
        candidates.append((float(tail_25["High"].max()), f"Макс ({tf_label})"))
        candidates.append((float(tail_25["Low"].min()), f"Мин ({tf_label})"))

        if len(df) >= 60:
            tail_60 = df.tail(60)
            candidates.append((float(tail_60["High"].max()), f"Сильный уровень ({tf_label})"))
            candidates.append((float(tail_60["Low"].min()), f"Сильный уровень ({tf_label})"))

        highs = df["High"].values
        lows = df["Low"].values
        for i in range(max(3, len(df) - 50), len(df) - 3):
            h_max = max(highs[i - 3 : i + 4])
            l_min = min(lows[i - 3 : i + 4])
            # Используем np.isclose для сравнения float цен
            if np.isclose(highs[i], h_max, atol=0.0001):
                candidates.append((float(highs[i]), f"Пик ({tf_label})"))
            if np.isclose(lows[i], l_min, atol=0.0001):
                candidates.append((float(lows[i]), f"Дно ({tf_label})"))

    extract_pivots(df_main, "тек. ТФ")
    extract_pivots(df_1h, "1ч")
    if not df_1d.empty and len(df_1d) >= 2:
        prev_day = df_1d.iloc[-2]
        candidates.append((float(prev_day["High"]), "Макс вчера (1д)"))
        candidates.append((float(prev_day["Low"]), "Мин вчера (1д)"))
        if len(df_1d) >= 20:
            candidates.append((float(df_1d["High"].tail(20).max()), "Макс месяца (1д)"))
            candidates.append((float(df_1d["Low"].tail(20).min()), "Мин месяца (1д)"))

    poc_main = compute_poc_price(df_main)
    if poc_main:
        candidates.append((poc_main, "POC объёма"))

    for tf_k in ("15m", "30m", "1h", "4h", "1d"):
        e_info = mtf_emas.get(tf_k)
        if e_info and e_info.get("ema200"):
            candidates.append((e_info["ema200"], f"EMA200 ({TIMEFRAMES[tf_k]['btn']})"))

    resistances = []
    supports = []
    for lvl_price, label in candidates:
        if lvl_price <= 0:
            continue
        # Динамический порог: минимум 2% или 0.5% от цены, если цена низкая
        # Порог — строго в процентах (было max(2.0, цена*0.005): для бумаги по 7000 ₽ порог улетал до 35% и уровни терялись)
        dist_threshold = 2.0
        dist_pct = (lvl_price - current_price) / current_price * 100
        if dist_pct > dist_threshold:
            resistances.append((lvl_price, label, dist_pct))
        elif dist_pct < -dist_threshold:
            supports.append((lvl_price, label, abs(dist_pct)))

    resistances.sort(key=lambda x: x[0])
    supports.sort(key=lambda x: x[0], reverse=True)

    def cluster_levels(lvls: list[tuple]) -> list[tuple]:
        clustered = []
        for p, lbl, d_pct in lvls:
            if not clustered:
                clustered.append((p, lbl, d_pct))
            else:
                prev_p, prev_lbl, prev_d = clustered[-1]
                if abs(p - prev_p) / current_price * 100 < 0.25:
                    if "POC" in lbl or "1д" in lbl or "1ч" in lbl or "4ч" in lbl:
                        clustered[-1] = (p, f"{prev_lbl} + {lbl}", d_pct)
                else:
                    clustered.append((p, lbl, d_pct))
        return clustered

    res_clustered = cluster_levels(resistances)
    sup_clustered = cluster_levels(supports)

    nearest_res = res_clustered[0] if res_clustered else (round(current_price * 1.015, 4), "Расчётный (+1.5%)", 1.5)
    second_res = res_clustered[1] if len(res_clustered) > 1 else None
    nearest_sup = sup_clustered[0] if sup_clustered else (round(current_price * 0.985, 4), "Расчётный (-1.5%)", 1.5)
    second_sup = sup_clustered[1] if len(sup_clustered) > 1 else None

    return {
        "poc": poc_main,
        "res1_price": round(nearest_res[0], 4),
        "res1_label": nearest_res[1],
        "res1_dist_pct": round(nearest_res[2], 2),
        "res2_price": round(second_res[0], 4) if second_res else None,
        "res2_label": second_res[1] if second_res else None,
        "sup1_price": round(nearest_sup[0], 4),
        "sup1_label": nearest_sup[1],
        "sup1_dist_pct": round(nearest_sup[2], 2),
        "sup2_price": round(second_sup[0], 4) if second_sup else None,
        "sup2_label": second_sup[1] if second_sup else None,
    }


# =====================================================================
# 4.0. ХРАНИЛИЩЕ CVD: НАКОПЛЕНИЕ РЕАЛЬНОЙ ЛЕНТЫ ПО СВЕЧАМ + ЖУРНАЛ СИГНАЛОВ
# =====================================================================
# Зачем это нужно.
# T-Invest отдаёт GetLastTrades только за последний час. Поэтому на 1ч/4ч «CVD по ленте»
# физически не мог быть настоящим. Решение: каждый опрос ленты складывается в файл
# (SQLite) с привязкой к свече и слиянием по МАКСИМУМУ — опрос всегда отдаёт накопленную
# дельту свечи целиком, поэтому max() не даёт двойного счёта. Через несколько часов
# аптайма реальная дельта есть уже по всем таймфреймам, и она переживает рестарт.
#
# Плюс второй файл — CSV с журналом сигналов информатора: по нему потом можно считать,
# сколько сигналов было и чем они заканчивались.

CVD_ALERT_FIELDS = [
    "ts_msk", "ticker", "name", "tf", "side", "price", "change_pct",
    "eff_pct", "cvd_lots", "window_volume", "bar_delta", "tape_cov_pct",
    "consistency", "vol_ratio", "eff_ratio", "drift_pct", "range_pct", "atr_pct",
    "res1", "sup1", "poc", "tp", "sl", "users",
]

_CVD_SCHEMA = """
-- Базовая единица хранения — МИНУТА (в UTC минуты всегда совпадают с началом свечи
-- любого ТФ >= 1м). Свечи Мосбиржи на 4ч/1д не выровнены по UTC, поэтому хранить
-- сразу «по свечам ТФ» нельзя: сделки падали бы в чужую свечу.
CREATE TABLE IF NOT EXISTS tape (
    ticker     TEXT    NOT NULL,
    ts_min     INTEGER NOT NULL,   -- начало минуты, unix seconds UTC
    buy        REAL    NOT NULL,
    sell       REAL    NOT NULL,
    updated_ts REAL    NOT NULL,
    PRIMARY KEY (ticker, ts_min)
);
CREATE INDEX IF NOT EXISTS idx_tape_min ON tape(ts_min);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_msk      TEXT, ticker TEXT, name TEXT, tf TEXT, side TEXT,
    price       REAL, change_pct REAL,
    eff_pct     REAL, cvd_lots REAL, window_volume REAL, bar_delta REAL,
    tape_cov_pct REAL, consistency REAL, vol_ratio REAL, eff_ratio REAL,
    drift_pct   REAL, range_pct REAL, atr_pct REAL,
    res1        REAL, sup1 REAL, poc REAL, tp REAL, sl REAL, users INTEGER
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts_msk);
"""


def _candle_starts(df: pd.DataFrame) -> np.ndarray:
    """Начала свечей df в unix-секундах UTC (ровно те же числа, что в таблице tape)."""
    return (
        pd.DatetimeIndex(df["dt_msk"])
        .tz_convert("UTC")
        .tz_localize(None)
        .to_numpy()
        .astype("datetime64[s]")
        .astype("int64")
    )


class CvdStore:
    """
    Накопление РЕАЛЬНОЙ дельты по минутам + журнал сигналов.

    Почему по минутам, а не «по свечам ТФ»: GetLastTrades отдаёт окно ~55 минут,
    и для 4ч свечи один опрос видит только последний кусок свечи. Если складывать
    сразу в свечу через max(), мы потеряли бы 3/4 объёма. Минутная сетка решает:
      * минута, по которой опрос уже прошёл, больше не меняется → слияние по max()
        идемпотентно и не даёт двойного счёта при повторных опросах;
      * из минут любая свеча (5м/15м/30м/1ч/4ч) собирается точным суммированием.

    Горячий путь — в памяти; запись на диск пачками (CVD_FLUSH_EVERY_SEC) и на выходе.
    """

    def __init__(self, db_path: str = CVD_DB_PATH, csv_path: str = CVD_ALERTS_CSV, days: int = CVD_STORE_DAYS):
        self.db_path = db_path
        self.csv_path = csv_path
        self.days = _cvd_clamp_days(days, len(LIQUID_WATCHLIST))
        if self.days != days:
            logging.info(f"CVD_STORE: ретеншн {days} дн. обрезана до {self.days} дн. "
                         f"(бюджет RAM {CVD_MEM_BUDGET_MB:.0f} МБ, активных бумаг {len(LIQUID_WATCHLIST)})")
        self.mem: dict[str, dict[int, list[float]]] = {}   # ticker -> {minute_ts: [buy, sell]}
        self.dirty: set[str] = set()
        self._cache: dict[str, tuple[int, np.ndarray, np.ndarray, np.ndarray]] = {}
        self._lock = threading.RLock()
        self._db_lock = threading.RLock()   # единый lock на все операции с sqlite/CSV (conn шарится между потоками)
        self._conn: sqlite3.Connection | None = None
        self.alerts_total = 0
        self.last_flush_ts = 0.0

    # ---------- подключение ----------
    def _conn_get(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_CVD_SCHEMA)
            self._conn.commit()
        return self._conn

    # ---------- накопление ----------
    def absorb(self, ticker: str, tape: dict | None, frames: dict | None = None) -> None:
        """Кладёт сделки опроса в минутные корзины, слияние с накопленным по max()."""
        if not tape or not tape.get("count"):
            return
        ts, qty, side = tape["ts"], tape["qty"], tape["side"]
        if ts.size == 0:
            return

        minutes = (ts // 60) * 60
        uniq, inv = np.unique(minutes, return_inverse=True)
        buy = np.bincount(inv, weights=np.where(side > 0, qty, 0.0))
        sell = np.bincount(inv, weights=np.where(side < 0, qty, 0.0))

        with self._lock:
            slot = self.mem.setdefault(ticker, {})
            for minute_ts, b, s_ in zip(uniq.tolist(), buy.tolist(), sell.tolist()):
                cur = slot.get(minute_ts)
                if cur is None:
                    slot[minute_ts] = [b, s_]
                else:                       # опрос отдаёт накопленное за минуту → max
                    cur[0] = max(cur[0], b)
                    cur[1] = max(cur[1], s_)
            self._cache.pop(ticker, None)
            self.dirty.add(ticker)

    def _sorted(self, ticker: str):
        """Отсортированные минуты и префиксные суммы (кэш, чтобы не сортировать каждый раз)."""
        slot = self.mem.get(ticker)
        if not slot:
            return None
        minutes = np.fromiter(slot.keys(), dtype="int64", count=len(slot))
        order = np.argsort(minutes)
        minutes = minutes[order]
        buy = np.fromiter((slot[m][0] for m in minutes.tolist()), dtype=float, count=len(minutes))
        sell = np.fromiter((slot[m][1] for m in minutes.tolist()), dtype=float, count=len(minutes))
        return minutes, np.concatenate([[0.0], np.cumsum(buy)]), np.concatenate([[0.0], np.cumsum(sell)])

    def history_arrays(self, ticker: str, tf_key: str, df: pd.DataFrame):
        """
        Возвращает (buy, sell) по свечам df, собранные из накопленных минут,
        или None, если по тикеру ещё ничего не накоплено.
        """
        if df.empty:
            return None
        with self._lock:
            slot = self.mem.get(ticker)
            if not slot:
                return None
            cached = self._cache.get(ticker)
            if cached is None or cached[0] != len(slot):
                minutes, cum_b, cum_s = self._sorted(ticker)
                self._cache[ticker] = (len(slot), minutes, cum_b, cum_s)
            else:
                _, minutes, cum_b, cum_s = cached

        sec = TIMEFRAMES.get(tf_key, TIMEFRAMES["15m"])["sec"]
        starts = _candle_starts(df)
        lo = np.searchsorted(minutes, starts, side="left")
        hi = np.searchsorted(minutes, starts + sec, side="left")
        buy = cum_b[hi] - cum_b[lo]
        sell = cum_s[hi] - cum_s[lo]
        if not buy.any() and not sell.any():
            return None
        return buy, sell

    # ---------- работа с диском ----------
    def load(self) -> int:
        """Поднимает накопленную историю из файла в память (на старте бота)."""
        try:
            conn = self._conn_get()
            since = int(time.time()) - self.days * 86400
            with self._db_lock:
                rows = conn.execute(
                    "SELECT ticker, ts_min, buy, sell FROM tape WHERE ts_min >= ?", (since,)
                ).fetchall()
            with self._lock:
                for ticker, ts_min, buy, sell in rows:
                    self.mem.setdefault(ticker, {})[int(ts_min)] = [float(buy), float(sell)]
                self._cache.clear()
            logging.info(f"CVD-хранилище: загружено {len(rows)} минут ленты из {self.db_path}")
            return len(rows)
        except Exception as e:
            logging.error(f"CVD-хранилище: ошибка загрузки ({e})")
            return 0

    def flush(self) -> int:
        """Сбрасывает накопленное в памяти на диск одной транзакцией."""
        with self._lock:
            if not self.dirty:
                return 0
            now = time.time()
            payload = []
            for ticker in list(self.dirty):
                for ts_min, (buy, sell) in self.mem.get(ticker, {}).items():
                    payload.append((ticker, int(ts_min), float(buy), float(sell), now))
            self.dirty.clear()

        if not payload:
            return 0
        try:
            conn = self._conn_get()
            with self._db_lock:
                conn.executemany(
                    """INSERT INTO tape (ticker, ts_min, buy, sell, updated_ts)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(ticker, ts_min) DO UPDATE SET
                           buy = MAX(tape.buy, excluded.buy),
                           sell = MAX(tape.sell, excluded.sell),
                           updated_ts = excluded.updated_ts""",
                    payload,
                )
                conn.commit()
            self.last_flush_ts = now
            return len(payload)
        except Exception as e:
            logging.error(f"CVD-хранилище: ошибка записи ({e})")
            return 0

    def prune(self) -> None:
        """Удаляет старые минуты из памяти и файла."""
        cutoff = int(time.time()) - self.days * 86400
        with self._lock:
            for ticker in list(self.mem.keys()):
                slot = self.mem[ticker]
                for ts_min in [m for m in slot if m < cutoff]:
                    slot.pop(ts_min, None)
                if not slot:
                    self.mem.pop(ticker, None)
                self._cache.pop(ticker, None)
        try:
            conn = self._conn_get()
            with self._db_lock:
                conn.execute("DELETE FROM tape WHERE ts_min < ?", (cutoff,))
                conn.commit()
        except Exception as e:
            logging.error(f"CVD-хранилище: ошибка очистки ({e})")

    # ---------- журнал сигналов ----------
    def log_alert(self, row: dict) -> None:
        """Пишет сигнал информатора в SQLite и в CSV (append). Вызывается один раз на сигнал.
        Все операции под _db_lock: соединение шарится между event loop и thread pool."""
        clean = {k: row.get(k) for k in CVD_ALERT_FIELDS}
        clean["users"] = int(clean.get("users") or 0)
        with self._db_lock:
            try:
                conn = self._conn_get()
                conn.execute(
                    f"INSERT INTO alerts ({', '.join(CVD_ALERT_FIELDS)}) "
                    f"VALUES ({', '.join('?' for _ in CVD_ALERT_FIELDS)})",
                    [clean[k] for k in CVD_ALERT_FIELDS],
                )
                conn.commit()
                self.alerts_total += 1
            except Exception as e:
                logging.error(f"CVD-журнал: ошибка записи в БД ({e})")

            try:
                need_header = not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0
                with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=CVD_ALERT_FIELDS, delimiter=";")
                    if need_header:
                        writer.writeheader()
                    writer.writerow(clean)
            except Exception as e:
                logging.error(f"CVD-журнал: ошибка записи в CSV ({e})")

    def stats(self) -> dict:
        with self._lock:
            minutes = sum(len(v) for v in self.mem.values())
        return {
            "enabled": True,
            "db": self.db_path,
            "csv": self.csv_path,
            "minutes_in_memory": minutes,
            "tickers": len(self.mem),
            "alerts_total": self.alerts_total,
            "days": self.days,
            "mem_est_mb": round(minutes * CVD_MEM_BYTES_PER_MIN / 1e6, 1),
            "mem_budget_mb": CVD_MEM_BUDGET_MB,
            "max_days": CVD_STORE_MAX_DAYS,
        }

    def close(self) -> None:
        self.flush()
        with self._db_lock:
            with self._lock:
                if self._conn is not None:
                    try:
                        self._conn.close()
                    finally:
                        self._conn = None


CVD_STORE = CvdStore()


async def cvd_store_flush_async() -> None:
    if CVD_STORE_ENABLED:
        await asyncio.to_thread(CVD_STORE.flush)


def cvd_store_history(ticker: str, tf_key: str, df: pd.DataFrame):
    """История накопленной ленты для расчёта (или None, если хранилище выключено)."""
    if not CVD_STORE_ENABLED:
        return None
    return CVD_STORE.history_arrays(ticker, tf_key, df)


def prepare_tape(raw_trades: list[dict] | None) -> dict:
    """
    Разбирает GetLastTrades один раз: timestamps -> np.int64, объём, знак.
    В исходном коде лента парсилась заново для каждого из 5 таймфреймов
    (datetime.fromisoformat на каждую сделку) — на ликвидной бумаге это
    десятки тысяч разборов строк за один анализ.
    """
    ts_list, precise_ts_list, qty_list, side_list, price_list = [], [], [], [], []
    for t in raw_trades or []:
        qty = int(t.get("quantity", 0) or 0)
        d = t.get("direction", "")
        if qty <= 0 or d not in ("TRADE_DIRECTION_BUY", "TRADE_DIRECTION_SELL"):
            continue
        t_str = t.get("time", "")
        if not t_str:
            continue
        try:
            trade_dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
            if trade_dt.tzinfo is None:
                trade_dt = trade_dt.replace(tzinfo=timezone.utc)
            ts_precise = trade_dt.timestamp()
        except Exception:
            continue
        price = quotation_to_float(t.get("price")) or 0.0
        # Целые секунды оставляем для прежнего CVD-кода; точное время и цену
        # используем только в справочном анализе повторяющихся принтов.
        ts_list.append(int(ts_precise))
        precise_ts_list.append(ts_precise)
        qty_list.append(qty)
        side_list.append(1.0 if d == "TRADE_DIRECTION_BUY" else -1.0)
        price_list.append(float(price))
    return {
        "ts": np.asarray(ts_list, dtype="int64"),
        "ts_precise": np.asarray(precise_ts_list, dtype="float64"),
        "qty": np.asarray(qty_list, dtype=float),
        "side": np.asarray(side_list, dtype=float),
        "price": np.asarray(price_list, dtype=float),
        "count": len(ts_list),
    }


def detect_repeated_trade_pattern(
    tape: dict | None,
    tick_size: float | None = None,
    now_ts: float | None = None,
) -> dict:
    """Ищет регулярные серии одинакового объёма/стороны/ценового диапазона.

    Это индикатор повторяющегося исполнения, а не идентификация робота или участника.
    Используются биржевые времена из GetLastTrades, а не время получения HTTP-ответа.
    """
    now_ts = float(now_ts if now_ts is not None else time.time())
    base = {
        "pattern_detected": False,
        "window_seconds": REPEAT_PATTERN_WINDOW_SECONDS,
        "trades_in_window": 0,
    }
    if not tape or not tape.get("count"):
        return base

    ts_arr = np.asarray(tape.get("ts_precise", []), dtype=float)
    qty_arr = np.asarray(tape.get("qty", []), dtype=float)
    side_arr = np.asarray(tape.get("side", []), dtype=float)
    price_arr = np.asarray(tape.get("price", []), dtype=float)
    n = min(len(ts_arr), len(qty_arr), len(side_arr), len(price_arr))
    if n == 0:
        return base

    lower_ts = now_ts - REPEAT_PATTERN_WINDOW_SECONDS
    groups: dict[tuple[int, int], list[tuple[float, float]]] = {}
    trades_in_window = 0
    for i in range(n):
        ts = float(ts_arr[i])
        qty = int(qty_arr[i])
        side = int(side_arr[i])
        price = float(price_arr[i])
        if ts < lower_ts or ts > now_ts + 2.0 or qty <= 0 or side not in (-1, 1) or price <= 0:
            continue
        trades_in_window += 1
        groups.setdefault((side, qty), []).append((ts, price))

    base["trades_in_window"] = trades_in_window
    if not groups:
        return base

    candidates = []
    for (side, qty), events in groups.items():
        events.sort(key=lambda event: event[0])
        # Ограничиваем перебор хвостом: нас интересует повторяющийся паттерн,
        # который проявляется сейчас, а не давно завершившаяся серия.
        events = events[-24:]
        max_seq = min(REPEAT_PATTERN_MAX_SEQUENCE, len(events))
        for end in range(REPEAT_PATTERN_MIN_TRADES - 1, len(events)):
            last_ts = events[end][0]
            last_age = max(0.0, now_ts - last_ts)
            if last_age > REPEAT_PATTERN_MAX_LAST_AGE_SECONDS:
                continue
            for count in range(REPEAT_PATTERN_MIN_TRADES, max_seq + 1):
                start = end - count + 1
                if start < 0:
                    continue
                run = events[start : end + 1]
                times = np.asarray([event[0] for event in run], dtype=float)
                prices = np.asarray([event[1] for event in run], dtype=float)
                intervals = np.diff(times)
                if len(intervals) != count - 1 or np.any(intervals <= 0):
                    continue

                median_interval = float(np.median(intervals))
                mean_interval = float(np.mean(intervals))
                if median_interval <= 0 or mean_interval <= 0:
                    continue
                # Обычный коэффициент вариации строже робастного: один выбивающийся
                # интервал снижает шанс принять случайную серию за регулярное исполнение.
                interval_cv = float(np.std(intervals) / mean_interval)
                if interval_cv > REPEAT_PATTERN_MAX_INTERVAL_CV:
                    continue
                if float(np.max(intervals)) > max(5.0, median_interval * 2.5):
                    continue

                median_price = float(np.median(prices))
                if median_price <= 0:
                    continue
                try:
                    tick = float(tick_size or 0.0)
                except (TypeError, ValueError):
                    tick = 0.0
                if tick <= 0:
                    tick = max(median_price * 0.0001, 0.001)
                allowed_span = max(
                    tick * 2,
                    median_price * REPEAT_PATTERN_MAX_PRICE_SPAN_PCT / 100.0,
                )
                price_span = float(np.max(prices) - np.min(prices))
                if price_span > allowed_span:
                    continue
                price_span_pct = price_span / median_price * 100.0
                span_seconds = float(times[-1] - times[0])
                candidates.append({
                    "pattern_detected": True,
                    "window_seconds": REPEAT_PATTERN_WINDOW_SECONDS,
                    "trades_in_window": trades_in_window,
                    "side": "BUY" if side > 0 else "SELL",
                    "quantity_lots": qty,
                    "trade_count": count,
                    "span_seconds": round(span_seconds, 2),
                    "median_interval_seconds": round(median_interval, 3),
                    "interval_cv": round(interval_cv, 3),
                    "price_span_pct": round(price_span_pct, 5),
                    "last_trade_age_seconds": round(last_age, 2),
                })

    if not candidates:
        return base
    # Сначала предпочитаем более длинную серию, затем более ровный интервал.
    best = max(
        candidates,
        key=lambda item: (
            item["trade_count"],
            -item["interval_cv"],
            -item["price_span_pct"],
        ),
    )
    return best


def detect_big_prints(
    tape: dict | None,
    price: float,
    lot: int = 1,
    now_ts: float | None = None,
) -> dict:
    """
    Справочный детектор крупных принтов в анонимной ленте.

    Крупный принт — сделка с рублёвым объёмом >= BIG_TRADE_MIN_RUB. Считаем
    концентрацию крупных сделок по сторонам за окно BIG_TRADE_WINDOW_SECONDS.
    Это НЕ идентификация участника и НЕ доказательство робота: лента анонимна,
    крупные сделки могли пройти разными игроками. Не влияет на score/вердикт.
    """
    now_ts = float(now_ts if now_ts is not None else time.time())
    base = {
        "detected": False,
        "window_seconds": BIG_TRADE_WINDOW_SECONDS,
        "trades_in_window": 0,
        "big_count": 0,
        "side": None,
        "big_buy_lots": 0.0, "big_sell_lots": 0.0,
        "big_buy_rub": 0.0, "big_sell_rub": 0.0,
        "net_lots": 0.0, "net_rub": 0.0, "total_rub": 0.0,
        "median_big_rub": 0.0, "last_big_age_sec": None, "share_of_window_rub": 0.0,
    }
    if not tape or not tape.get("count") or not price or price <= 0:
        return base
    ts = np.asarray(tape.get("ts_precise", []), dtype=float)
    qty = np.asarray(tape.get("qty", []), dtype=float)
    side = np.asarray(tape.get("side", []), dtype=float)
    pr = np.asarray(tape.get("price", []), dtype=float)
    n = min(len(ts), len(qty), len(side), len(pr))
    if n == 0:
        return base
    lot = max(int(lot or 1), 1)
    lower = now_ts - BIG_TRADE_WINDOW_SECONDS
    in_win = (ts[:n] >= lower) & (ts[:n] <= now_ts + 2.0)
    base["trades_in_window"] = int(in_win.sum())
    rub = pr[:n] * qty[:n] * lot
    big = in_win & (rub >= BIG_TRADE_MIN_RUB) & (qty[:n] > 0)
    if not bool(big.any()):
        return base
    buy_m = big & (side[:n] > 0)
    sell_m = big & (side[:n] < 0)
    b_lots = float(qty[:n][buy_m].sum())
    s_lots = float(qty[:n][sell_m].sum())
    b_rub = float(rub[buy_m].sum())
    s_rub = float(rub[sell_m].sum())
    cnt = int(big.sum())
    net_rub = b_rub - s_rub
    total_rub = b_rub + s_rub
    base.update({
        "big_count": cnt,
        "big_buy_lots": b_lots, "big_sell_lots": s_lots,
        "big_buy_rub": b_rub, "big_sell_rub": s_rub,
        "net_lots": b_lots - s_lots, "net_rub": net_rub, "total_rub": total_rub,
        "median_big_rub": float(np.median(rub[big])),
        "last_big_age_sec": round(float((now_ts - ts[:n][big]).min()), 1),
    })
    win_rub = float(rub[in_win].sum())
    base["share_of_window_rub"] = round(total_rub / win_rub * 100.0, 1) if win_rub > 0 else 0.0
    if cnt < BIG_TRADE_MIN_COUNT or abs(net_rub) < BIG_TRADE_MIN_TOTAL_RUB:
        return base  # статистика собрана, но порог «события» не пройден
    base["detected"] = True
    base["side"] = "BUY" if net_rub > 0 else "SELL"
    return base


def detect_minute_pressure(
    tape: dict | None,
    price: float,
    lot: int = 1,
    now_ts: float | None = None,
) -> dict:
    """
    Минутное давление по ленте: за минуту прошёл большой нетто-объём в ₽ при почти
    стоящей цене. Это ловит пассивный (лимитный) набор крупного игрока, который
    обычный CVD (агрессор) почти не видит. Эвристика, не доказательство.
    """
    now_ts = float(now_ts if now_ts is not None else time.time())
    base = {
        "detected": False, "window_min": MINUTE_PRESSURE_WINDOW_MIN, "minutes_checked": 0,
        "side": None, "net_rub": 0.0, "move_pct": 0.0, "impact": 0.0, "minute": None,
    }
    if not tape or not tape.get("count") or not price or price <= 0:
        return base
    ts = np.asarray(tape.get("ts_precise", []), dtype=float)
    qty = np.asarray(tape.get("qty", []), dtype=float)
    side = np.asarray(tape.get("side", []), dtype=float)
    pr = np.asarray(tape.get("price", []), dtype=float)
    n = min(len(ts), len(qty), len(side), len(pr))
    if n == 0:
        return base
    lot = max(int(lot or 1), 1)
    lower = now_ts - MINUTE_PRESSURE_WINDOW_MIN * 60
    m = (ts[:n] >= lower) & (ts[:n] <= now_ts + 2.0)
    if not m.any():
        return base
    t_m, q_m, s_m, p_m = ts[:n][m], qty[:n][m], side[:n][m], pr[:n][m]
    minutes = (t_m // 60).astype("int64")
    uniq, inv = np.unique(minutes, return_inverse=True)
    per_min = []
    for k, minu in enumerate(uniq):
        sel = inv == k
        q, s, p, t = q_m[sel], s_m[sel], p_m[sel], t_m[sel]
        net_lots = float((q * s).sum())
        avg_p = float(np.average(p, weights=q)) if float(q.sum()) > 0 else float(p.mean())
        last_p = float(p[int(np.argmax(t))])
        per_min.append({
            "minute": int(minu), "net_lots": net_lots,
            "net_rub": net_lots * lot * avg_p, "last_price": last_p,
        })
    base["minutes_checked"] = len(per_min)
    best = None
    for i in range(1, len(per_min)):
        prev, cur = per_min[i - 1], per_min[i]
        if prev["last_price"] <= 0:
            continue
        move_rub = cur["last_price"] - prev["last_price"]
        move_pct = move_rub / prev["last_price"] * 100.0
        # impact — ₽ нетто-объёма на 1% движения цены. Делить на move_rub (₽) нельзя:
        # у дешёвых бумаг 0.1% = доли рубля, и порог impact срабатывал бы всегда.
        impact = abs(cur["net_rub"]) / max(abs(move_pct), 1e-9)
        if (abs(cur["net_rub"]) >= MINUTE_PRESSURE_NET_RUB
                and abs(move_pct) <= MINUTE_PRESSURE_MAX_MOVE_PCT
                and impact >= MINUTE_PRESSURE_MIN_IMPACT):
            if best is None or abs(cur["net_rub"]) > abs(best["net_rub"]):
                best = {**cur, "move_pct": move_pct, "impact": impact}
    if best:
        base.update(
            detected=True,
            side="BUY" if best["net_lots"] > 0 else "SELL",
            net_rub=round(best["net_rub"], 0),
            move_pct=round(best["move_pct"], 4),
            impact=round(best["impact"], 1),
            minute=best["minute"],
        )
    return base


def detect_big_twap(
    tape: dict | None,
    price: float,
    lot: int = 1,
    now_ts: float | None = None,
) -> dict:
    """
    TWAP-паттерн среди крупных принтов: >= TWAP_MIN_TRADES сделок ОДНОГО объёма
    одной стороны с ровными интервалами (CV <= TWAP_MAX_INTERVAL_CV) на суммарный
    объём >= BIG_TRADE_MIN_TOTAL_RUB. Возможное алгоритмическое исполнение.
    Эвристика, не идентификация участника.
    """
    now_ts = float(now_ts if now_ts is not None else time.time())
    base = {
        "detected": False, "window_seconds": BIG_TRADE_WINDOW_SECONDS, "side": None,
        "qty": 0, "count": 0, "interval_cv": 0.0, "total_rub": 0.0,
    }
    if not tape or not tape.get("count") or not price or price <= 0:
        return base
    ts = np.asarray(tape.get("ts_precise", []), dtype=float)
    qty = np.asarray(tape.get("qty", []), dtype=float)
    side = np.asarray(tape.get("side", []), dtype=float)
    pr = np.asarray(tape.get("price", []), dtype=float)
    n = min(len(ts), len(qty), len(side), len(pr))
    if n == 0:
        return base
    lot = max(int(lot or 1), 1)
    lower = now_ts - BIG_TRADE_WINDOW_SECONDS
    m = (ts[:n] >= lower) & (ts[:n] <= now_ts + 2.0)
    rub = pr[:n] * qty[:n] * lot
    big = m & (rub >= BIG_TRADE_MIN_RUB) & (qty[:n] > 0)
    if not bool(big.any()):
        return base
    groups: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for t, q, s, r in zip(ts[:n][big], qty[:n][big], side[:n][big], rub[big]):
        groups.setdefault((int(s), int(q)), []).append((float(t), float(r)))
    for (s, q), evs in groups.items():
        if len(evs) < TWAP_MIN_TRADES:
            continue
        evs.sort(key=lambda e: e[0])
        times = np.asarray([e[0] for e in evs], dtype=float)
        total_rub = float(sum(e[1] for e in evs))
        if total_rub < BIG_TRADE_MIN_TOTAL_RUB:
            continue
        intervals = np.diff(times)
        if len(intervals) == 0 or np.any(intervals <= 0):
            continue
        mean_i = float(intervals.mean())
        if mean_i <= 0:
            continue
        cv = float(intervals.std() / mean_i)
        if cv <= TWAP_MAX_INTERVAL_CV:
            base.update(
                detected=True, side="BUY" if s > 0 else "SELL", qty=q, count=len(evs),
                interval_cv=round(cv, 3), total_rub=round(total_rub, 0),
            )
            break
    return base


BOOK_STATE: dict[str, dict] = {}    # ticker -> метрики стакана (обновляет iceberg_watcher_cycle)
RI_STATE: dict = {"ts": 0.0, "detected": False, "side": None, "net_rub": 0.0, "big_count": 0, "ticker": "", "price": 0.0}
LAST_WHALE_ALERT: dict[str, float] = {}


def detect_tape_size_metrics(tape: dict | None, price: float, lot: int = 1, now_ts: float | None = None) -> dict:
    """Средний размер сделки в окне + ускорение частоты крупных принтов (эвристика крупняка, лента)."""
    now_ts = float(now_ts if now_ts is not None else time.time())
    base = {"detected_size": False, "detected_accel": False, "avg_trade_rub": 0.0,
            "avg_trade_rub_prev": 0.0, "avg_trend_pct": 0.0, "big_rate_per_min": 0.0,
            "big_rate_per_min_prev": 0.0, "rate_accel": 0.0, "side": None}
    if not tape or not tape.get("count") or not price or price <= 0:
        return base
    ts = np.asarray(tape.get("ts_precise", []), dtype=float)
    qty = np.asarray(tape.get("qty", []), dtype=float)
    side = np.asarray(tape.get("side", []), dtype=float)
    pr = np.asarray(tape.get("price", []), dtype=float)
    n = min(len(ts), len(qty), len(side), len(pr))
    if n == 0:
        return base
    lot = max(int(lot or 1), 1)
    w = float(BIG_TRADE_WINDOW_SECONDS)
    rub = pr[:n] * qty[:n] * lot
    win = (ts[:n] >= now_ts - w) & (ts[:n] <= now_ts + 2.0)
    prev = (ts[:n] >= now_ts - 2 * w) & (ts[:n] < now_ts - w)
    if win.any():
        w_rub = float(rub[win].sum())
        w_cnt = int(win.sum())
        base["avg_trade_rub"] = round(w_rub / w_cnt, 0) if w_cnt else 0.0
        big = win & (rub >= BIG_TRADE_MIN_RUB)
        base["big_rate_per_min"] = round(float(big.sum()) / (w / 60.0), 2)
        net = float((qty[:n] * side[:n] * pr[:n] * lot)[win].sum())
        base["side"] = "BUY" if net > 0 else "SELL"
    if prev.any():
        p_rub = float(rub[prev].sum())
        p_cnt = int(prev.sum())
        base["avg_trade_rub_prev"] = round(p_rub / p_cnt, 0) if p_cnt else 0.0
        bigp = prev & (rub >= BIG_TRADE_MIN_RUB)
        base["big_rate_per_min_prev"] = round(float(bigp.sum()) / (w / 60.0), 2)
    if base["avg_trade_rub_prev"] > 0:
        base["avg_trend_pct"] = round((base["avg_trade_rub"] / base["avg_trade_rub_prev"] - 1.0) * 100.0, 1)
    if base["big_rate_per_min_prev"] > 0:
        base["rate_accel"] = round(base["big_rate_per_min"] / base["big_rate_per_min_prev"], 2)
    elif base["big_rate_per_min"] > 0:
        base["rate_accel"] = 99.0
    base["detected_size"] = bool(base["avg_trade_rub"] >= AVG_TRADE_RUB_MIN and base["avg_trend_pct"] >= AVG_TRADE_TREND_PCT)
    base["detected_accel"] = bool(base["big_rate_per_min"] >= 1.0 and base["rate_accel"] >= RATE_ACCEL_MIN)
    return base


def compute_book_metrics(bids, asks, lot: int = 1) -> dict:
    """Метрики стакана по снапшоту: дисбаланс bid/ask в ₽, крупные лимитки, плотность топ-5. Эвристика."""
    lot = max(int(lot or 1), 1)

    def _rows(rows):
        out = []
        for r in rows or []:
            p = quotation_to_float(r.get("price"))
            try:
                q = float(r.get("quantity", 0) or 0)
            except (TypeError, ValueError):
                q = 0.0
            if p and p > 0 and q > 0:
                out.append((float(p), q, float(p) * q * lot))
        return out

    b = _rows(bids)[:BOOK_TOP_LEVELS]
    a = _rows(asks)[:BOOK_TOP_LEVELS]
    bid_rub = float(sum(x[2] for x in b))
    ask_rub = float(sum(x[2] for x in a))
    total = bid_rub + ask_rub
    imb = round((bid_rub - ask_rub) / total * 100.0, 1) if total > 0 else 0.0
    walls = []
    for side_name, rows in (("bid", b), ("ask", a)):
        for p, q, rub in rows:
            if rub >= BOOK_WALL_RUB:
                walls.append({"side": side_name, "price": round(p, 4), "qty": q, "rub": round(rub, 0)})
    walls.sort(key=lambda w: w["rub"], reverse=True)
    top5 = float(sum(x[2] for x in (b[:5] + a[:5])))
    conc = round(top5 / total * 100.0, 1) if total > 0 else 0.0
    return {
        "imbalance_pct": imb,
        "imbalance_side": "bid" if imb > 0 else "ask",
        "detected_imbalance": abs(imb) >= BOOK_IMBALANCE_PCT,
        "big_walls": walls[:6],
        "detected_wall": bool(walls),
        "depth_conc_pct": conc,
        "detected_conc": conc >= BOOK_CONC_PCT,
        "bid_rub": round(bid_rub, 0),
        "ask_rub": round(ask_rub, 0),
    }


def whale_confluence_kinds(sig: dict, now_ts: float | None = None) -> list[str]:
    """Список сработавших признаков крупняка (для confluence-алерта 🐋🐋, 🐋-списка и маркеров на графике)."""
    now_ts = float(now_ts if now_ts is not None else time.time())
    kinds: list[str] = []
    if (sig.get("big_prints") or {}).get("detected"):
        kinds.append("🐋 крупные принты")
    if (sig.get("minute_pressure") or {}).get("detected"):
        kinds.append("⏱ минутное давление")
    if (sig.get("big_twap") or {}).get("detected"):
        kinds.append("⏲ TWAP")
    if (sig.get("robot_activity") or {}).get("pattern_detected"):
        kinds.append("🔁 повторы")
    t = sig.get("ticker")
    if t and any(now_ts - float(e.get("ts", 0) or 0.0) <= 300 for e in (ICEBERG_STATE.get(t) or {}).get("events", [])):
        kinds.append("🧊 iceberg")
    bk = BOOK_STATE.get(t) or {}
    if t and now_ts - float(bk.get("ts", 0) or 0.0) <= BOOK_STALE_SEC:
        if bk.get("detected_imbalance"):
            kinds.append(f"⚖️ дисбаланс стакана {float(bk.get('imbalance_pct', 0.0)):+.0f}%")
        if bk.get("detected_wall"):
            kinds.append("🧱 big wall")
    tm = sig.get("tape_metrics") or {}
    if tm.get("detected_size"):
        kinds.append("📏 рост среднего чека")
    if tm.get("detected_accel"):
        kinds.append("🚀 ускорение принтов")
    return kinds


WHALE_EVENTS: list[dict] = []       # события в ПАМЯТИ (ничего на диске): ts, ticker, detector, side, strength, price, bucket, hit, pct
WHALE_STATS: dict[str, dict] = {}   # detector -> {"events", "hits", "avg_move_pct"} — уходит в state + облако
WHALE_MARK_AFTER_SEC = int(os.getenv("WHALE_MARK_AFTER_SEC", "900"))   # исход считаем через 15 мин
WHALE_HIT_PCT = float(os.getenv("WHALE_HIT_PCT", "0.2"))                # движение в сторону сигнала для hit, %
WHALE_EVENTS_CAP = int(os.getenv("WHALE_EVENTS_CAP", "3000"))          # кап списка событий в памяти


def record_whale_event(ticker: str, detector: str, side, strength: float, price: float, now_ts: float) -> None:
    """Записывает сработавшее событие крупняка (дедуп по (тикер, детектор, 5-мин корзина)). Только в память."""
    if not ticker or not price or price <= 0:
        return
    bucket = int(now_ts // 300)
    for ev in WHALE_EVENTS[-400:]:
        if ev["ticker"] == ticker and ev["detector"] == detector and ev["bucket"] == bucket:
            return
    WHALE_EVENTS.append({"ts": float(now_ts), "ticker": ticker, "detector": detector, "side": side,
                         "strength": float(strength or 0.0), "price": float(price),
                         "bucket": bucket, "hit": None, "pct": None})
    if len(WHALE_EVENTS) > WHALE_EVENTS_CAP:
        del WHALE_EVENTS[: len(WHALE_EVENTS) - WHALE_EVENTS_CAP]


def mark_whale_outcomes(live_prices: dict, now_ts: float) -> int:
    """Отмечает исходы событий старше WHALE_MARK_AFTER_SEC по текущей цене и копит WHALE_STATS. Возвращает число отметок."""
    marked = 0
    for ev in WHALE_EVENTS:
        if ev.get("hit") is not None:
            continue
        age = now_ts - float(ev["ts"])
        if age < WHALE_MARK_AFTER_SEC:
            continue
        if age > 4 * 3600:
            ev["hit"] = False
            ev["pct"] = 0.0
        else:
            px = live_prices.get(ev["ticker"])
            if not px or float(px) <= 0:
                continue
            pct = (float(px) - ev["price"]) / ev["price"] * 100.0
            if ev.get("side") == "BUY":
                ev["hit"] = pct >= WHALE_HIT_PCT
            elif ev.get("side") == "SELL":
                ev["hit"] = pct <= -WHALE_HIT_PCT
            else:
                ev["hit"] = False
            ev["pct"] = round(pct, 3)
        st = WHALE_STATS.setdefault(ev["detector"], {"events": 0, "hits": 0, "avg_move_pct": 0.0})
        st["events"] += 1
        st["hits"] += 1 if ev.get("hit") else 0
        p = float(ev.get("pct") or 0.0)
        st["avg_move_pct"] = round(st["avg_move_pct"] + (p - st["avg_move_pct"]) / st["events"], 3)
        marked += 1
    if marked:
        WHALE_EVENTS[:] = [e for e in WHALE_EVENTS if e.get("hit") is None or (now_ts - float(e["ts"])) < 1800]
    return marked


def whale_stats_text() -> str:
    """Блок hit-rate детекторов крупняка (событий >=5) для статистики и 🐋."""
    rows = [(k, v) for k, v in WHALE_STATS.items() if int(v.get("events", 0)) >= 5]
    if not rows:
        return ""
    rows.sort(key=lambda kv: kv[1]["events"], reverse=True)
    parts = []
    for k, v in rows[:6]:
        ev = int(v["events"])
        hits = int(v["hits"])
        parts.append(f"{k}: {hits}/{ev} ({hits / ev * 100:.0f}%), ход {float(v.get('avg_move_pct', 0.0)):+.2f}%")
    return "\n🐋 <b>Hit-rate детекторов крупняка (событий ≥5):</b>\n" + "\n".join(f"• {p}" for p in parts) + "\n"


def apply_real_trades_delta_to_df(
    df: pd.DataFrame,
    trades: list[dict] | None = None,
    tf_key: str = "15m",
    hist: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[pd.DataFrame, int, int]:
    """
    Считает дельту каждой свечи как смесь двух источников:

    1) "синтетика" по свече: объём * f(положение закрытия, тело) — есть всегда,
       но у неё есть системная ошибка (доджи-свечи дают ~0, хотя внутри был перевес);
    2) реальная лента сделок (GetLastTrades): перевес покупок/продаж, привязанный
       к свечам по времени.

    Вес реальной ленты = sqrt(покрытие объёма свечи лентой) и НЕ форсируется снизу
    (в исходном коде было max(0.65, coverage) — из-за этого 30 минут ленты
    «переписывали» суточную свечу и рождались ложные всплески CVD).
    """
    if df.empty:
        return df, 0, 0

    df = df.copy().reset_index(drop=True)
    n = len(df)

    hi = df["High"].to_numpy(dtype=float)
    lo = df["Low"].to_numpy(dtype=float)
    op = df["Open"].to_numpy(dtype=float)
    cl = df["Close"].to_numpy(dtype=float)
    vol = df["Volume"].to_numpy(dtype=float)
    vol_safe = np.where(vol > 0, vol, np.nan)

    rng = hi - lo
    rng_safe = np.where(rng > 0, rng, np.nan)
    close_pos = ((cl - lo) - (hi - cl)) / rng_safe          # -1..+1
    body_ratio = (cl - op) / rng_safe
    synth_ratio = np.clip(0.6 * close_pos + 0.4 * body_ratio, -1.0, 1.0)
    synth_ratio = np.where(np.isnan(synth_ratio), 0.0, synth_ratio)

    buy = np.zeros(n)
    sell = np.zeros(n)
    tape_buy_total = 0
    tape_sell_total = 0

    tape = trades if isinstance(trades, dict) else prepare_tape(trades)

    if tape and tape.get("count", 0):
        tf_sec = TIMEFRAMES.get(tf_key, TIMEFRAMES["15m"])["sec"]
        starts = (
            pd.DatetimeIndex(df["dt_msk"])
            .tz_convert("UTC")
            .tz_localize(None)
            .to_numpy()
            .astype("datetime64[s]")
            .astype("int64")
        )

        ts_arr = tape["ts"]
        qty_arr = tape["qty"]
        side_arr = tape["side"]

        idx = np.searchsorted(starts, ts_arr, side="right") - 1
        valid = (idx >= 0) & (idx < n)
        idx_c = np.clip(idx, 0, n - 1)
        valid &= (ts_arr >= starts[idx_c]) & (ts_arr < starts[idx_c] + tf_sec)

        idx_ok = idx_c[valid]
        q_ok = qty_arr[valid]
        s_ok = side_arr[valid]

        buy = np.bincount(idx_ok[s_ok > 0], weights=q_ok[s_ok > 0], minlength=n)[:n]
        sell = np.bincount(idx_ok[s_ok < 0], weights=q_ok[s_ok < 0], minlength=n)[:n]
        tape_buy_total = int(buy.sum())
        tape_sell_total = int(sell.sum())

    # Накопленная история (CvdStore): для свечей старше часа опрос ленты уже ничего
    # не отдаёт, а реальная дельта этих свечей лежит в файле. Слияние по максимуму.
    if hist is not None:
        h_buy, h_sell = hist
        if len(h_buy) == n and len(h_sell) == n:
            buy = np.maximum(buy, h_buy)
            sell = np.maximum(sell, h_sell)
            tape_buy_total = int(buy.sum())
            tape_sell_total = int(sell.sum())

    # Лента может дать больше объёма, чем свеча (свеча ещё формируется / рассинхрон).
    # Для расчётов обрезаем по объёму свечи, иначе «покрытие» улетает за 100 %.
    tape_vol_raw = buy + sell
    tape_vol = np.minimum(tape_vol_raw, np.where(np.isnan(vol_safe), tape_vol_raw, vol))
    real_ratio = np.where(tape_vol_raw > 0, (buy - sell) / np.where(tape_vol_raw > 0, tape_vol_raw, 1.0), 0.0)
    coverage = np.clip(tape_vol / np.where(np.isnan(vol_safe), 1.0, vol_safe), 0.0, 1.0)
    weight = np.sqrt(coverage)          # 25 % покрытия -> вес 0.5; 100 % -> вес 1.0

    delta = (1.0 - weight) * (vol * synth_ratio) + weight * (vol * real_ratio)
    delta = np.where(tape_vol > 0, delta, vol * synth_ratio)

    df["delta"] = delta
    df["tape_vol"] = tape_vol
    df["tape_vol_raw"] = tape_vol_raw
    df["tape_cov"] = coverage
    df["cum_delta"] = df["delta"].cumsum()
    df["cvd"] = df.groupby("date_msk")["delta"].cumsum()
    # Дельта ТОЛЬКО по реальной ленте/истории (без синтетики по свече) — чтобы видеть,
    # quanto della divergenza: на младших ТФ при полном покрытии совпадает с delta,
    # на старших ТФ (1h/4h/1d) показывает, что синтетика вносила основной вклад.
    df["tape_delta"] = buy - sell
    df["tape_cum_delta"] = df["tape_delta"].cumsum()
    return df, tape_buy_total, tape_sell_total


def _atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    """ATR в процентах от цены — чтобы «стоящий график» не зависел от волатильности дня."""
    if df.empty or len(df) < 3:
        return 0.0
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift()
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(period, min_periods=3).mean().iloc[-1])
    price = float(close.iloc[-1])
    if price <= 0 or np.isnan(atr):
        return 0.0
    return atr / price * 100.0


def _empty_cvd_result(tf_key: str = "15m") -> dict:
    return {
        "bar_delta": 0.0, "bar_delta_pct": 0.0, "cvd_today": 0.0, "cvd_change_3": 0.0,
        "cum_delta": 0.0, "cum_delta_change_6": 0.0, "window_volume_6": 0.0,
        "delta_efficiency_6": 0.0, "price_change_6_pct": 0.0, "window_range_pct": 0.0,
        "green_candle_lies": False, "red_candle_lies": False,
        "bearish_divergence": False, "bullish_divergence": False,
        "pivot_bearish_div": False, "pivot_bullish_div": False, "pivot_div_note": "",
        "absorption_side": None, "absorption_desc": None,
        "candle_key": "", "tape_cov_pct": 0.0, "consistency_6": 0.0, "efficiency_ratio": 0.0,
        "flat_ok": False, "volume_ok": False, "efficiency_ok": False,
        "coverage_ok": False,
        "coverage_min": CVD_COVERAGE_GATE_PCT.get(tf_key, CVD_MIN_TAPE_COVERAGE_PCT),
        "threshold_pct": cvd_absorption_threshold(tf_key), "is_alert": False,
        "atr_pct": 0.0, "vol_ratio": 0.0,
        "atr_abs": 0.0, "cvd_rub_window": 0.0, "cvd_per_atr": 0.0,
        "pressure_side": None, "pressure_desc": None,
        "price_impact": 999.0,
    }


def detect_pivot_divergence(df: "pd.DataFrame", window: int = 60, swing: int = 3,
                            min_move_pct: float = 0.3) -> dict:
    """Дивергенция по пивотам цены vs кум. дельты (безопасная HTML-разметка для Telegram)."""
    out = {"pivot_bearish_div": False, "pivot_bullish_div": False, "pivot_div_note": ""}
    try:
        n = len(df)
        if n < 2 * swing + 6:
            return out
        w = min(window, n)
        seg = df.iloc[-w:]
        close = seg["Close"].to_numpy(dtype=float)
        cd = seg["cum_delta"].to_numpy(dtype=float)
        m = len(close)
        highs, lows = [], []
        for i in range(swing, m - swing):
            if close[i] >= close[i - swing:i + swing + 1].max() and close[i] > close[i - 1] and close[i] >= close[i + 1]:
                highs.append(i)
            if close[i] <= close[i - swing:i + swing + 1].min() and close[i] < close[i - 1] and close[i] <= close[i + 1]:
                lows.append(i)
        notes = []
        if len(highs) >= 2:
            i1, i2 = highs[-2], highs[-1]
            h1, h2 = float(close[i1]), float(close[i2])
            if h2 > h1 * (1.0 + min_move_pct / 100.0) and float(cd[i2]) < float(cd[i1]):
                out["pivot_bearish_div"] = True
                notes.append(f"медвежья: макс цены {h2:.2f} &gt; {h1:.2f}, а кум. дельта {cd[i2]:.0f} &lt; {cd[i1]:.0f} прошлого пика")
        if len(lows) >= 2:
            i1, i2 = lows[-2], lows[-1]
            l1, l2 = float(close[i1]), float(close[i2])
            if l2 < l1 * (1.0 - min_move_pct / 100.0) and float(cd[i2]) > float(cd[i1]):
                out["pivot_bullish_div"] = True
                notes.append(f"бычья: мин цены {l2:.2f} &lt; {l1:.2f}, а кум. дельта {cd[i2]:.0f} &gt; {cd[i1]:.0f} прошлого минимума")
        out["pivot_div_note"] = "; ".join(notes)
    except Exception:
        pass
    return out


def calc_cvd_and_cum_delta(
    df: pd.DataFrame,
    trades: list[dict] | None = None,
    tf_key: str = "15m",
    window: int = CVD_WINDOW,
    hist: tuple[np.ndarray, np.ndarray] | None = None,
) -> dict:
    """
    Считает ОБА показателя одновременно:
      * cum_delta_change_6 — CVD в лотах за окно (6 свечей);
      * delta_efficiency_6 — перевес в % от объёма окна (порог задаётся отдельно для ТФ).

    Сигнал «скрытый набор/раздача» требует ОДНОВРЕМЕННО:
      1) график стоит (диапазон окна <= 2.2 * ATR и дрейф <= 0.9 * ATR);
      2) перевес строго больше индивидуального порога для таймфрейма;
      3) 60 %+ свечей окна с дельтой в сторону сигнала (устойчивость);
      4) объём окна не меньше 80 % нормы (не «мёртвый» рынок);
      5) покрытие реальной лентой не ниже порога для таймфрейма.
    """
    if df.empty or len(df) < window + 1:
        return _empty_cvd_result(tf_key)

    df, tape_buy_vol, tape_sell_vol = apply_real_trades_delta_to_df(df, trades, tf_key, hist)

    last = df.iloc[-1]
    bar_delta = float(last["delta"])
    last_vol = max(1.0, float(last["Volume"]))
    bar_delta_pct = round(bar_delta / last_vol * 100, 1)
    cvd_today = float(last["cvd"])

    today_df = df[df["date_msk"] == last["date_msk"]]
    if len(today_df) >= 4:
        cvd_change_3 = float(today_df["cvd"].iloc[-1] - today_df["cvd"].iloc[-4])
    elif len(today_df) >= 2:
        cvd_change_3 = float(today_df["cvd"].iloc[-1] - today_df["cvd"].iloc[0])
    else:
        cvd_change_3 = bar_delta

    window_df = df.iloc[-window:]
    d_ser = window_df["delta"].to_numpy(dtype=float)
    v_ser = window_df["Volume"].to_numpy(dtype=float)
    cum_delta_window = float(d_ser.sum())
    window_volume = float(v_ser.sum())
    # Проверка на минимальный объем для расчета эффективности (не менее 50% от нормы)
    avg_candle_vol = float(df["Volume"].tail(max(25, window)).mean()) if len(df) >= 10 else 0.0
    min_vol_for_eff = avg_candle_vol * window * 0.5
    if window_volume >= min_vol_for_eff and window_volume > 0:
        delta_efficiency = round(cum_delta_window / window_volume * 100, 1)
    else:
        delta_efficiency = 0.0

    avg_candle_vol = float(df["Volume"].tail(max(25, window)).mean()) if len(df) >= 10 else 0.0
    vol_ratio = window_volume / max(1.0, avg_candle_vol * window)

    base_price = float(df["Close"].iloc[-(window + 1)])
    cur_price = float(last["Close"])
    price_change_pct = ((cur_price - base_price) / base_price * 100) if base_price > 0 else 0.0
    window_high = float(window_df["High"].max())
    window_low = float(window_df["Low"].min())
    window_range_pct = ((window_high - window_low) / base_price * 100) if base_price > 0 else 0.0

    # --- «график стоит»: нет направленного движения, а не просто узкий диапазон ---
    closes_w = np.concatenate([[base_price], window_df["Close"].to_numpy(dtype=float)])
    path = float(np.abs(np.diff(closes_w)).sum())
    net = abs(float(closes_w[-1] - closes_w[0]))
    eff_ratio = (net / path) if path > 0 else 0.0     # 0 = пила, 1 = тренд

    atr_pct = _atr_pct(df)
    # «Давление объёмом»: сколько ATR-эквивалентов окна прошло в CVD (в рублях)
    atr_abs = (atr_pct / 100.0 * cur_price) if cur_price > 0 else 0.0
    cvd_rub_window = abs(cum_delta_window) * cur_price
    cvd_per_atr = (cvd_rub_window / (atr_abs * window)) if (atr_abs > 0 and window > 0) else 0.0
    # price impact: сколько % диапазона окна приходится на 1% перевеса CVD (в %)
    price_impact = (window_range_pct / (abs(delta_efficiency) + 1e-9)) if delta_efficiency != 0 else 999.0
    # Исправление: порог 0.42% был слишком мал, меняем на 42.0% (если цена в %) или корректируем логику
    # Если price_change_pct в %, то порог должен быть в процентах (например, 2.0% для дрейфа)
    hard_drift = FLAT_MAX_DRIFT_PCT.get(tf_key, 2.0) # 2% дрейфа
    drift_pct_abs = abs(price_change_pct)
    flat_ok = (
        eff_ratio <= FLAT_MAX_ER
        and drift_pct_abs <= hard_drift
        and window_range_pct <= hard_drift * 2.35
    )

    sign = 1.0 if cum_delta_window >= 0 else -1.0
    consistency = float(np.mean(np.sign(d_ser) == sign)) if window else 0.0
    if np.count_nonzero(d_ser) == 0:
        consistency = 0.0

    tape_cov_pct = (
        float(min(1.0, window_df["tape_vol"].sum() / window_volume) * 100) if window_volume > 0 else 0.0
    )

    coverage_min = CVD_COVERAGE_GATE_PCT.get(tf_key, CVD_MIN_TAPE_COVERAGE_PCT)
    threshold_pct = cvd_absorption_threshold(tf_key)
    efficiency_ok = abs(delta_efficiency) > threshold_pct
    volume_ok = vol_ratio >= CVD_MIN_VOL_RATIO
    consistency_ok = consistency >= CVD_MIN_CONSISTENCY
    coverage_ok = tape_cov_pct >= coverage_min
    direction_ok = (cum_delta_window > 0) or (cum_delta_window < 0)

    absorption_side = None
    absorption_desc = None
    tf_btn = TIMEFRAMES.get(tf_key, TIMEFRAMES["15m"])["btn"]

    if flat_ok and efficiency_ok and volume_ok and consistency_ok and coverage_ok and direction_ok:
        cov_note = f"покрытие лентой {tape_cov_pct:.0f}%"
        if cum_delta_window > 0:
            absorption_side = "LONG"
            absorption_desc = (
                f"🟢 <b>Скрытый набор на {tf_btn}:</b> график стоит "
                f"(дрейф <b>{price_change_pct:+.2f}%</b>, диапазон <b>{window_range_pct:.2f}%</b>), "
                f"а CVD вырос на <b>{format_lots_delta(cum_delta_window)}</b> "
                f"(перевес покупателей <b>+{delta_efficiency:.1f}%</b> от объёма, {cov_note})"
            )
        else:
            absorption_side = "SHORT"
            absorption_desc = (
                f"🔴 <b>Скрытая раздача на {tf_btn}:</b> график стоит "
                f"(дрейф <b>{price_change_pct:+.2f}%</b>, диапазон <b>{window_range_pct:.2f}%</b>), "
                f"а CVD упал на <b>{format_lots_delta(cum_delta_window)}</b> "
                f"(перевес продавцов <b>{delta_efficiency:.1f}%</b> от объёма, {cov_note})"
            )

    # «Давление при стоящей цене»: большой CVD при флэте, даже если перевес чуть ниже
    # основного порога absorption. Тоже эвристика, не доказательство игрока.
    pressure_side = None
    pressure_desc = None
    if absorption_side is None and flat_ok and volume_ok and coverage_ok and direction_ok:
        if price_impact <= PRICE_IMPACT_MAX and abs(delta_efficiency) > threshold_pct * 0.5 and consistency >= 0.5:
            pressure_side = "LONG" if cum_delta_window > 0 else "SHORT"
            pressure_desc = (
                f"🐋 <b>Давление объёмом на {tf_btn}:</b> график стоит (дрейф <b>{price_change_pct:+.2f}%</b>), "
                f"а CVD за окно <b>{format_lots_delta(cum_delta_window)}</b> при диапазоне окна {window_range_pct:.2f}% "
                f"(impact {price_impact:.3f} ≤ {PRICE_IMPACT_MAX}, перевес {delta_efficiency:+.1f}% при пороге {threshold_pct:.0f}%, лента {tape_cov_pct:.0f}%)"
            )

    tape_total = tape_buy_vol + tape_sell_vol
    is_green = cur_price >= float(last["Open"])
    is_red = cur_price < float(last["Open"])
    green_lies = is_green and (bar_delta < 0 or (tape_total >= 30 and tape_sell_vol > tape_buy_vol * 1.15))
    red_lies = is_red and (bar_delta > 0 or (tape_total >= 30 and tape_buy_vol > tape_sell_vol * 1.15))

    bearish_div = (price_change_pct > 0.25) and (cum_delta_window < 0 or cvd_change_3 < 0)
    bullish_div = (price_change_pct < -0.25) and (cum_delta_window > 0 or cvd_change_3 > 0)

    candle_key = last["dt_msk"].strftime("%Y%m%d%H%M")

    pdiv = detect_pivot_divergence(df)
    return {
        # --- совместимые имена (используются в текстах/дашборде) ---
        "bar_delta": bar_delta,
        "bar_delta_pct": bar_delta_pct,
        "cvd_today": cvd_today,
        "cvd_change_3": cvd_change_3,
        "cum_delta": float(last["cum_delta"]),
        "cum_delta_change_6": cum_delta_window,
        "window_volume_6": window_volume,
        "delta_efficiency_6": delta_efficiency,
        "price_change_6_pct": price_change_pct,
        "window_range_pct": window_range_pct,
        "green_candle_lies": green_lies,
        "red_candle_lies": red_lies,
        "bearish_divergence": bearish_div,
        "bullish_divergence": bullish_div,
        "pivot_bearish_div": pdiv["pivot_bearish_div"],
        "pivot_bullish_div": pdiv["pivot_bullish_div"],
        "pivot_div_note": pdiv["pivot_div_note"],
        "absorption_side": absorption_side,
        "absorption_desc": absorption_desc,
        # --- диагностика ---
        "candle_key": candle_key,
        "tape_cov_pct": round(tape_cov_pct, 1),
        "consistency_6": round(consistency, 2),
        "efficiency_ratio": round(eff_ratio, 3),
        "flat_ok": flat_ok,
        "volume_ok": volume_ok,
        "efficiency_ok": efficiency_ok,
        "coverage_ok": coverage_ok,
        "coverage_min": coverage_min,
        "threshold_pct": threshold_pct,
        "is_alert": absorption_side is not None or pressure_side is not None,
        "atr_pct": round(atr_pct, 3),
        "vol_ratio": round(vol_ratio, 2),
        "atr_abs": round(atr_abs, 4),
        "cvd_rub_window": round(cvd_rub_window, 0),
        "cvd_per_atr": round(cvd_per_atr, 2),
        "price_impact": round(price_impact, 4),
        "pressure_side": pressure_side,
        "pressure_desc": pressure_desc,
    }


# =====================================================================
# 5. ЗАГРУЗКА АКЦИЙ И ИНДЕКСА МОСБИРЖИ (IMOEX)
# =====================================================================
async def resolve_moex_index_instrument(session: aiohttp.ClientSession):
    for query_str in ("IMOEX", "IMOEXF", "TMOS"):
        try:
            async with session.post(
                f"{T_API_BASE}.InstrumentsService/FindInstrument",
                json={"query": query_str},
                timeout=10,
            ) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json()
                instruments = data.get("instruments", [])
                for item in instruments:
                    t_up = item.get("ticker", "").upper()
                    uid = item.get("uid")
                    if t_up in ("IMOEX", "IMOEXF", "TMOS") and uid:
                        now_utc = datetime.now(timezone.utc)
                        async with session.post(
                            f"{T_API_BASE}.MarketDataService/GetCandles",
                            json={
                                "instrumentId": uid,
                                "from": (now_utc - timedelta(days=5)).isoformat(),
                                "to": now_utc.isoformat(),
                                "interval": "CANDLE_INTERVAL_HOUR",
                            },
                            timeout=8,
                        ) as c_resp:
                            if c_resp.status == 200:
                                c_data = await c_resp.json()
                                if c_data.get("candles"):
                                    INSTRUMENTS_CACHE["IMOEX"] = {
                                        "uid": uid,
                                        "name": f"Индекс Мосбиржи ({t_up})",
                                        "lot": 1,
                                        "is_index": True,
                                    }
                                    UID_TO_TICKER[uid] = "IMOEX"
                                    return
        except Exception as e:
            logging.error(f"Ошибка поиска индекса {query_str}: {e}")


async def load_all_moex_shares():
    session = await get_session()
    data = await api_post(
        "InstrumentsService/Shares",
        {"instrumentStatus": "INSTRUMENT_STATUS_BASE"},
        timeout=20,
    )
    for item in data.get("instruments", []):
        if item.get("classCode") == "TQBR" and item.get("apiTradeAvailableFlag"):
            ticker = item["ticker"].upper()
            uid = item["uid"]
            dlong = float(quotation_to_float(item.get("dlong")) or 0.0)
            dshort = float(quotation_to_float(item.get("dshort")) or 0.0)
            lev_long = round(1.0 / dlong, 2) if dlong > 0 else 1.0
            lev_short = round(1.0 / dshort, 2) if dshort > 0 else 1.0
            INSTRUMENTS_CACHE[ticker] = {
                "uid": uid,
                "name": item.get("name", ticker),
                "lot": int(item.get("lot", 1)),
                "min_price_increment": quotation_to_float(item.get("minPriceIncrement")) or 0.0,
                "dlong": dlong,
                "dshort": dshort,
                "leverage_long": lev_long,
                "leverage_short": lev_short,
                "short_enabled": bool(item.get("shortEnabledFlag", True)),
            }
            UID_TO_TICKER[uid] = ticker

    await resolve_moex_index_instrument(session)

    logging.info(f"Загружено {len(INSTRUMENTS_CACHE)} инструментов Мосбиржи (включая плечи T-Invest).")


def get_instrument_leverage(ticker: str, side: str = "LONG") -> tuple[float, float]:
    """Возвращает (leverage, discount_rate) для тикера и стороны из актуальных данных T-Invest."""
    inst = INSTRUMENTS_CACHE.get(ticker.upper()) or {}
    side = side.upper()
    if side == "LONG":
        d = float(inst.get("dlong") or 0.0)
        lev = float(inst.get("leverage_long") or (round(1.0 / d, 2) if d > 0 else 1.0))
    else:
        d = float(inst.get("dshort") or 0.0)
        lev = float(inst.get("leverage_short") or (round(1.0 / d, 2) if d > 0 else 1.0))
    if lev <= 0:
        lev = 1.0
    return lev, d


async def ensure_instrument_loaded(session: aiohttp.ClientSession, ticker: str) -> dict | None:
    ticker = ticker.upper().strip()
    if ticker == "YNDX":
        ticker = "YDEX"
    if ticker in ("IMOEX", "ИНДЕКС", "ММВБ", "MOEXINDEX"):
        ticker = "IMOEX"
        if "IMOEX" not in INSTRUMENTS_CACHE:
            await resolve_moex_index_instrument(session)
        return INSTRUMENTS_CACHE.get("IMOEX")

    if ticker in INSTRUMENTS_CACHE:
        return INSTRUMENTS_CACHE[ticker]

    payload = {"idType": "INSTRUMENT_ID_TYPE_TICKER", "classCode": "TQBR", "id": ticker}
    async with session.post(f"{T_API_BASE}.InstrumentsService/ShareBy", json=payload, timeout=10) as resp:
        if resp.status != 200:
            if resp.status in (401, 403):
                global _LAST_AUTH_ERR_TS
                _LAST_AUTH_ERR_TS = time.time()
                logging.error(f"ShareBy {ticker}: авторизация T-Invest отклонена (проверьте T_INVEST_TOKEN)")
            return None
        data = await resp.json()
    inst = data.get("instrument")
    if not inst:
        return None

    dlong = float(quotation_to_float(inst.get("dlong")) or 0.0)
    dshort = float(quotation_to_float(inst.get("dshort")) or 0.0)
    lev_long = round(1.0 / dlong, 2) if dlong > 0 else 1.0
    lev_short = round(1.0 / dshort, 2) if dshort > 0 else 1.0
    info = {
        "uid": inst["uid"],
        "name": inst.get("name", ticker),
        "lot": int(inst.get("lot", 1)),
        "min_price_increment": quotation_to_float(inst.get("minPriceIncrement")) or 0.0,
        "dlong": dlong,
        "dshort": dshort,
        "leverage_long": lev_long,
        "leverage_short": lev_short,
        "short_enabled": bool(inst.get("shortEnabledFlag", True)),
    }
    INSTRUMENTS_CACHE[ticker] = info
    UID_TO_TICKER[inst["uid"]] = ticker
    return info


async def fetch_candles_for_tf(
    session: aiohttp.ClientSession,
    uid: str,
    tf_key: str,
    fallback_price: float = 0.0,
) -> pd.DataFrame:
    """Загружает свечи выбранного ТФ (включая 30m и 4h) с резервным ресемплингом из 15m/1h."""
    tf_cfg = TIMEFRAMES.get(tf_key, TIMEFRAMES["15m"])
    now_utc = datetime.now(timezone.utc)
    try:
        async with session.post(
            f"{T_API_BASE}.MarketDataService/GetCandles",
            json={
                "instrumentId": uid,
                "from": (now_utc - tf_cfg["delta"]).isoformat(),
                "to": now_utc.isoformat(),
                "interval": tf_cfg["interval"],
            },
            timeout=10,
        ) as resp:
            if resp.status == 200:
                c_list = (await resp.json()).get("candles", [])
                if len(c_list) >= 10:
                    return candles_to_df(c_list, fallback_price)
    except Exception:
        pass

    # Если API не вернуло 30m или 4h напрямую — агрегируем из 15m или 1h
    if tf_key == "30m":
        base_cfg = TIMEFRAMES["15m"]
        rule = "30min"
    elif tf_key == "4h":
        base_cfg = TIMEFRAMES["1h"]
        rule = "4h"
    else:
        return pd.DataFrame()

    try:
        async with session.post(
            f"{T_API_BASE}.MarketDataService/GetCandles",
            json={
                "instrumentId": uid,
                "from": (now_utc - base_cfg["delta"]).isoformat(),
                "to": now_utc.isoformat(),
                "interval": base_cfg["interval"],
            },
            timeout=10,
        ) as resp:
            if resp.status == 200:
                c_list = (await resp.json()).get("candles", [])
                df_base = candles_to_df(c_list, fallback_price)
                return resample_candles_df(df_base, rule)
    except Exception:
        pass

    return pd.DataFrame()


async def get_moex_index_context(session: aiohttp.ClientSession, force: bool = False) -> dict | None:
    now_ts = time.time()
    if not force and MOEX_INDEX_CACHE["data"] and (now_ts - MOEX_INDEX_CACHE["ts"]) < 60:
        return MOEX_INDEX_CACHE["data"]

    inst = await ensure_instrument_loaded(session, "IMOEX")
    if not inst:
        return None

    uid = inst["uid"]
    now_utc = datetime.now(timezone.utc)

    try:
        r_last, r_close, r_5m, r_15m, r_1h, r_1d = await asyncio.gather(
            session.post(f"{T_API_BASE}.MarketDataService/GetLastPrices", json={"instrumentId": [uid], "lastPriceType": "LAST_PRICE_EXCHANGE"}, timeout=8),
            session.post(f"{T_API_BASE}.MarketDataService/GetClosePrices", json={"instruments": [{"instrumentId": uid}]}, timeout=8),
            session.post(f"{T_API_BASE}.MarketDataService/GetCandles", json={"instrumentId": uid, "from": (now_utc - TIMEFRAMES["5m"]["delta"]).isoformat(), "to": now_utc.isoformat(), "interval": TIMEFRAMES["5m"]["interval"]}, timeout=8),
            session.post(f"{T_API_BASE}.MarketDataService/GetCandles", json={"instrumentId": uid, "from": (now_utc - TIMEFRAMES["15m"]["delta"]).isoformat(), "to": now_utc.isoformat(), "interval": TIMEFRAMES["15m"]["interval"]}, timeout=8),
            session.post(f"{T_API_BASE}.MarketDataService/GetCandles", json={"instrumentId": uid, "from": (now_utc - TIMEFRAMES["1h"]["delta"]).isoformat(), "to": now_utc.isoformat(), "interval": TIMEFRAMES["1h"]["interval"]}, timeout=8),
            session.post(f"{T_API_BASE}.MarketDataService/GetCandles", json={"instrumentId": uid, "from": (now_utc - TIMEFRAMES["1d"]["delta"]).isoformat(), "to": now_utc.isoformat(), "interval": TIMEFRAMES["1d"]["interval"]}, timeout=8),
        )

        last_d = await r_last.json() if r_last.status == 200 else {}
        close_d = await r_close.json() if r_close.status == 200 else {}
        c_5m = (await r_5m.json()).get("candles", []) if r_5m.status == 200 else []
        c_15m = (await r_15m.json()).get("candles", []) if r_15m.status == 200 else []
        c_1h = (await r_1h.json()).get("candles", []) if r_1h.status == 200 else []
        c_1d = (await r_1d.json()).get("candles", []) if r_1d.status == 200 else []
    except Exception as e:
        logging.error(f"Ошибка анализа IMOEX: {e}")
        return MOEX_INDEX_CACHE["data"]

    df_5m = candles_to_df(c_5m)
    df_15m = candles_to_df(c_15m)
    df_1h = candles_to_df(c_1h)
    df_1d = candles_to_df(c_1d)

    last_prices = last_d.get("lastPrices", [])
    close_prices = close_d.get("closePrices", [])
    cur_p = quotation_to_float(last_prices[0].get("price")) if last_prices else None
    prev_p = quotation_to_float(close_prices[0].get("price")) if close_prices else None

    if not cur_p:
        for df_tmp in (df_5m, df_15m, df_1h, df_1d):
            if not df_tmp.empty:
                cur_p = float(df_tmp["Close"].iloc[-1])
                break
    if not cur_p:
        return None

    if not prev_p and not df_1d.empty and len(df_1d) >= 2:
        prev_p = float(df_1d["Close"].iloc[-2])

    change_pct = ((cur_p - prev_p) / prev_p * 100) if (cur_p and prev_p) else 0.0

    mtf_emas = {}
    for k, d_frame in (("5m", df_5m), ("15m", df_15m), ("1h", df_1h), ("1d", df_1d)):
        e_res = compute_tf_emas(d_frame)
        if e_res:
            mtf_emas[k] = e_res

    main_df = df_15m if not df_15m.empty else df_1h
    sr_info = compute_sr_levels(cur_p, main_df, df_1h, df_1d, mtf_emas)
    cvd_info = calc_cvd_and_cum_delta(main_df, None, "15m")

    bull_cnt = sum(1 for v in mtf_emas.values() if v["trend"] == "BULL")
    bear_cnt = sum(1 for v in mtf_emas.values() if v["trend"] == "BEAR")

    if bull_cnt >= 2 and bear_cnt == 0:
        bias = "BULL"
        summary_badge = "🟢 Позитивный (Рост)"
    elif bear_cnt >= 2 and bull_cnt == 0:
        bias = "BEAR"
        summary_badge = "🔴 Негативный (Давление)"
    elif bull_cnt > bear_cnt:
        bias = "MILD_BULL"
        summary_badge = "🟢 Умеренно бычий"
    elif bear_cnt > bull_cnt:
        bias = "MILD_BEAR"
        summary_badge = "🔴 Умеренно медвежий"
    else:
        bias = "FLAT"
        summary_badge = "⚪ Нейтральный (Боковик)"

    idx_result = {
        "price": cur_p,
        "change_pct": change_pct,
        "bias": bias,
        "summary_badge": summary_badge,
        "mtf_emas": mtf_emas,
        "sr": sr_info,
        "cvd": cvd_info,
    }
    MOEX_INDEX_CACHE["ts"] = now_ts
    MOEX_INDEX_CACHE["data"] = idx_result
    return idx_result


# =====================================================================
# 6. ЯДРО АНАЛИЗА (5 ТАЙМФРЕЙМОВ ИНФОРМАТОРА CVD + СНАЙПЕР)
# =====================================================================
def calculate_trade_targets(
    side: str,
    display_price: float,
    atr_val: float,
    recent_low: float,
    recent_high: float,
    sr_levels: dict,
    bid_wall_p: float | None,
    ask_wall_p: float | None,
    tick_size: float | None = None,
) -> dict:
    min_stop_dist = max(atr_val * 1.35, display_price * 0.006)
    max_stop_dist = display_price * 0.020
    book_stop_floor = min(min_stop_dist, max_stop_dist)
    tick = float(tick_size or 0.0)
    if tick <= 0:
        tick = max(display_price * 0.0001, 0.001)

    sup1_p = sr_levels["sup1_price"]
    res1_p = sr_levels["res1_price"]
    tp_reason = "по ATR и R/R 1:1.9"

    if side == "LONG":
        structural_sl = min(recent_low, display_price - min_stop_dist)
        if bid_wall_p and bid_wall_p < display_price and (display_price - bid_wall_p) <= max_stop_dist:
            stop_loss = round(min(bid_wall_p - tick, display_price - book_stop_floor), 4)
            sl_reason = f"за видимый Bid-объём ({bid_wall_p} ₽)"
        elif sup1_p < display_price and (display_price - sup1_p) <= max_stop_dist * 0.9:
            stop_loss = round(sup1_p * 0.998, 4)
            sl_reason = f"за уровень поддержки ({sup1_p} ₽)"
        else:
            stop_loss = round(max(structural_sl - atr_val * 0.25, display_price - max_stop_dist), 4)
            sl_reason = "за локальный минимум + ATR"
        # Защита от ошибки: стоп не может быть выше цены для LONG
        stop_loss = min(stop_loss, display_price - display_price * 0.005)
        risk = max(display_price - stop_loss, display_price * 0.005)
        take_profit = round(display_price + risk * 1.9, 4)
        if ask_wall_p and ask_wall_p > display_price:
            before_wall = round(ask_wall_p - tick, 4)
            min_target_distance = max(display_price * 0.003, tick * 2)
            if display_price + min_target_distance < before_wall < take_profit:
                # клампим TP к стене, только если R/R при этом >= 1.5 — иначе сделка математически невыгодна
                rr_wall = abs(before_wall - display_price) / max(abs(display_price - stop_loss), 1e-9)
                if rr_wall >= 1.5:
                    take_profit = before_wall
                    tp_reason = f"перед видимым Ask-объёмом {ask_wall_p:.4f} ₽"
                else:
                    tp_reason = f"по ATR и R/R 1:1.9 (стена {ask_wall_p:.4f} ₽ слишком близко: R/R был бы {rr_wall:.2f} &lt; 1.5 — кламп отменён)"
    else:
        structural_sl = max(recent_high, display_price + min_stop_dist)
        if ask_wall_p and ask_wall_p > display_price and (ask_wall_p - display_price) <= max_stop_dist:
            stop_loss = round(max(ask_wall_p + tick, display_price + book_stop_floor), 4)
            sl_reason = f"за видимый Ask-объём ({ask_wall_p} ₽)"
        elif res1_p > display_price and (res1_p - display_price) <= max_stop_dist * 0.9:
            stop_loss = round(res1_p * 1.002, 4)
            sl_reason = f"за уровень сопротивления ({res1_p} ₽)"
        else:
            stop_loss = round(min(structural_sl + atr_val * 0.25, display_price + max_stop_dist), 4)
            sl_reason = "за локальный максимум + ATR"
        # Защита от ошибки: стоп не может быть ниже цены для SHORT
        stop_loss = max(stop_loss, display_price + display_price * 0.005)
        risk = max(stop_loss - display_price, display_price * 0.005)
        take_profit = round(display_price - risk * 1.9, 4)
        if bid_wall_p and bid_wall_p < display_price:
            before_wall = round(bid_wall_p + tick, 4)
            min_target_distance = max(display_price * 0.003, tick * 2)
            if take_profit < before_wall < display_price - min_target_distance:
                rr_wall = abs(display_price - before_wall) / max(abs(stop_loss - display_price), 1e-9)
                if rr_wall >= 1.5:
                    take_profit = before_wall
                    tp_reason = f"перед видимым Bid-объёмом {bid_wall_p:.4f} ₽"
                else:
                    tp_reason = f"по ATR и R/R 1:1.9 (стена {bid_wall_p:.4f} ₽ слишком близко: R/R был бы {rr_wall:.2f} &lt; 1.5 — кламп отменён)"

    profit_pct = abs(take_profit - display_price) / display_price * 100
    risk_pct = abs(display_price - stop_loss) / display_price * 100
    rr_ratio = round(profit_pct / risk_pct, 1) if risk_pct > 0 else 1.9

    return {
        "entry": display_price,
        "tp": take_profit,
        "sl": stop_loss,
        "sl_reason": sl_reason,
        "tp_reason": tp_reason,
        "profit_pct": profit_pct,
        "risk_pct": risk_pct,
        "rr_ratio": rr_ratio,
    }


async def analyze_stock_signal(ticker: str, tf_key: str = "15m") -> dict | None:
    ticker = ticker.upper().strip()
    if ticker == "YNDX":
        ticker = "YDEX"
    if ticker in ("ИНДЕКС", "ММВБ"):
        ticker = "IMOEX"

    if ticker in ILLIQUID_BLACKLIST:
        info = INSTRUMENTS_CACHE.get(ticker, {})
        return {"is_illiquid": True, "ticker": ticker, "name": info.get("name", ticker)}

    session = await get_session()   # одна сессия приложения: без TLS-хендшейка на каждый запрос
    try:
        inst = await ensure_instrument_loaded(session, ticker)
        if not inst:
            _LAST_ANALYZE_ERR[(ticker, tf_key)] = (time.time(), "инструмент не найден: каталог пуст и ShareBy вернул не 200 (выше в логах — 401/403 или сетевая ошибка)")
            return None
        uid, name, lot = inst["uid"], inst["name"], inst["lot"]
        is_index_inst = inst.get("is_index", False) or ticker == "IMOEX"

        now_utc = datetime.now(timezone.utc)

        # Стакан запрашиваем один раз на анализ только для видимых уровней ликвидности/TP;
        # классификатор роботов и повторяющихся сделок остаётся отключённым.
        tasks = [
            session.post(f"{T_API_BASE}.MarketDataService/GetLastPrices", json={"instrumentId": [uid], "lastPriceType": "LAST_PRICE_EXCHANGE"}, timeout=10),
            session.post(f"{T_API_BASE}.MarketDataService/GetClosePrices", json={"instruments": [{"instrumentId": uid}]}, timeout=10),
            (session.post(f"{T_API_BASE}.MarketDataService/GetOrderBook", json={"instrumentId": uid, "depth": BOOK_DEPTH}, timeout=10) if not is_index_inst else asyncio.sleep(0, result=None)),
            session.post(f"{T_API_BASE}.MarketDataService/GetLastTrades", json={"instrumentId": uid, "from": (now_utc - timedelta(minutes=TAPE_WINDOW_MINUTES)).isoformat(), "to": now_utc.isoformat()}, timeout=10),
            session.post(f"{T_API_BASE}.MarketDataService/GetCandles", json={"instrumentId": uid, "from": (now_utc - TIMEFRAMES["5m"]["delta"]).isoformat(), "to": now_utc.isoformat(), "interval": TIMEFRAMES["5m"]["interval"]}, timeout=10),
            session.post(f"{T_API_BASE}.MarketDataService/GetCandles", json={"instrumentId": uid, "from": (now_utc - TIMEFRAMES["15m"]["delta"]).isoformat(), "to": now_utc.isoformat(), "interval": TIMEFRAMES["15m"]["interval"]}, timeout=10),
            session.post(f"{T_API_BASE}.MarketDataService/GetCandles", json={"instrumentId": uid, "from": (now_utc - TIMEFRAMES["1h"]["delta"]).isoformat(), "to": now_utc.isoformat(), "interval": TIMEFRAMES["1h"]["interval"]}, timeout=10),
            session.post(f"{T_API_BASE}.MarketDataService/GetCandles", json={"instrumentId": uid, "from": (now_utc - TIMEFRAMES["1d"]["delta"]).isoformat(), "to": now_utc.isoformat(), "interval": TIMEFRAMES["1d"]["interval"]}, timeout=10),
        ]
        if tf_key == "1m":
            tasks.append(
                session.post(f"{T_API_BASE}.MarketDataService/GetCandles", json={"instrumentId": uid, "from": (now_utc - TIMEFRAMES["1m"]["delta"]).isoformat(), "to": now_utc.isoformat(), "interval": TIMEFRAMES["1m"]["interval"]}, timeout=10)
            )

        responses = await asyncio.gather(*tasks)
        last_resp, close_resp, book_resp, trades_resp, c5m_resp, c15m_resp, c1h_resp, c1d_resp = responses[:8]
        c1m_resp = responses[8] if len(responses) > 8 else None

        last_data = await last_resp.json() if last_resp.status == 200 else {}
        close_data = await close_resp.json() if close_resp.status == 200 else {}
        book_data = await book_resp.json() if book_resp is not None and book_resp.status == 200 else {}
        trades_data = await trades_resp.json() if trades_resp.status == 200 else {}

        c_5m = (await c5m_resp.json()).get("candles", []) if c5m_resp.status == 200 else []
        c_15m = (await c15m_resp.json()).get("candles", []) if c15m_resp.status == 200 else []
        c_1h = (await c1h_resp.json()).get("candles", []) if c1h_resp.status == 200 else []
        c_1d = (await c1d_resp.json()).get("candles", []) if c1d_resp.status == 200 else []
        c_1m = (await c1m_resp.json()).get("candles", []) if (c1m_resp and c1m_resp.status == 200) else []

        moex_ctx = await get_moex_index_context(session, force=(ticker == "IMOEX"))
    except Exception as e:
        _log_transport_error(ticker, e)
        logging.exception(f"Ошибка анализа {ticker}: {e}")
        _LAST_ANALYZE_ERR[(ticker, tf_key)] = (time.time(), f"исключение при загрузке рыночных данных: {type(e).__name__}: {e}")
        return None

    candle_age_5m = get_last_candle_age_minutes(c_5m if c_5m else c_15m)
    last_candle_time_str = (c_5m[-1].get("time", "") if c_5m else (c_15m[-1].get("time", "") if c_15m else ""))
    market_open_now = is_moex_trading_hours()
    is_live_market = market_open_now and (candle_age_5m <= 20.0)

    last_prices = last_data.get("lastPrices", [])
    close_prices = close_data.get("closePrices", [])
    current_price = quotation_to_float(last_prices[0].get("price")) if last_prices else None
    prev_close = quotation_to_float(close_prices[0].get("price")) if close_prices else None
    display_price = current_price or prev_close

    if not display_price and c_15m:
        display_price = quotation_to_float(c_15m[-1].get("close"))
    if not display_price:
        _LAST_ANALYZE_ERR[(ticker, tf_key)] = (time.time(), "нет цены: GetLastPrices, GetClosePrices и свечи вернули пустые ответы")
        return None

    book_liquidity = analyze_visible_liquidity(
        book_data.get("bids", []),
        book_data.get("asks", []),
        lot,
        display_price,
        inst.get("min_price_increment"),
    )

    days_span = max(1.0, TIMEFRAMES["15m"]["delta"].total_seconds() / 86400.0)
    total_period_volume = sum(int(c.get("volume", 0)) for c in c_15m) if c_15m else 0
    daily_turnover_rub = (total_period_volume * lot * display_price) / days_span
    if not is_index_inst and daily_turnover_rub < MIN_LIQUIDITY_RUB and ticker not in LIQUID_AUTOTRADE_TICKERS:
        return {"is_illiquid": True, "ticker": ticker, "name": name}

    if not prev_close and c_1d and len(c_1d) >= 2:
        prev_close = quotation_to_float(c_1d[-2].get("close"))
    change_pct = ((display_price - prev_close) / prev_close * 100) if (display_price and prev_close) else 0.0

    raw_trades = trades_data.get("trades", [])

    # Свежесть ленты по конкретной бумаге: тонкие бумаги могут не иметь свечей 5м 20 минут
    last_trade_age_min = 99999.0
    for t in reversed(raw_trades):
        t_str = t.get("time", "")
        if not t_str:
            continue
        try:
            last_trade_age_min = (datetime.now(timezone.utc)
                                  - datetime.fromisoformat(t_str.replace("Z", "+00:00"))).total_seconds() / 60.0
        except Exception:
            last_trade_age_min = 99999.0
        break
    last_activity_age_min = min(candle_age_5m, last_trade_age_min)
    ticker_live = market_open_now and (last_activity_age_min <= 20.0)

    # Роботный детектор удалён. Стакан используется только для уровней ликвидности
    # и расчёта целей/стопов; его объёмный дисбаланс не влияет на направленный score.
    micro = {
        "robots": [], "algo_score": 0, "buy_vol": 0, "sell_vol": 0,
        "buy_pct": 50.0, "bid_ratio": 50.0,
        "bid_wall_price": book_liquidity["bid_wall_price"],
        "bid_wall_mult": book_liquidity["bid_wall_mult"],
        "bid_wall_str": book_liquidity["bid_wall_str"],
        "ask_wall_price": book_liquidity["ask_wall_price"],
        "ask_wall_mult": book_liquidity["ask_wall_mult"],
        "ask_wall_str": book_liquidity["ask_wall_str"],
    }
    robots_list = []
    ACTIVE_ROBOTS_REGISTRY.pop(ticker, None)

    df_5m = candles_to_df(c_5m, display_price)
    df_15m = candles_to_df(c_15m, display_price)
    df_30m = resample_candles_df(df_15m, "30min")
    df_1h = candles_to_df(c_1h, display_price)
    df_4h = resample_candles_df(df_1h, "4h")
    df_1d = candles_to_df(c_1d, display_price)
    df_1m = candles_to_df(c_1m, display_price) if c_1m else pd.DataFrame()

    tf_df_map = {
        "1m": df_1m,
        "5m": df_5m,
        "15m": df_15m,
        "30m": df_30m,
        "1h": df_1h,
        "4h": df_4h,
        "1d": df_1d,
    }
    df = tf_df_map.get(tf_key, df_15m)
    if df.empty or len(df) < 10:
        df = df_15m if not df_15m.empty else df_1h
        tf_key = "15m" if not df_15m.empty else "1h"

    mtf_emas: dict[str, dict] = {}
    for k, d_frame in (
        ("5m", df_5m),
        ("15m", df_15m),
        ("30m", df_30m),
        ("1h", df_1h),
        ("4h", df_4h),
        ("1d", df_1d),
    ):
        e_res = compute_tf_emas(d_frame)
        if e_res:
            mtf_emas[k] = e_res

    # Ленту разбираем ОДИН раз и переиспользуем на всех 5 ТФ (было: 5 полных разборов)
    tape = prepare_tape(raw_trades)
    # Только справочная метрика: не передавать её в score, verdict, стопы или цели.
    robot_activity = detect_repeated_trade_pattern(
        tape,
        tick_size=inst.get("min_price_increment"),
        now_ts=datetime.now(timezone.utc).timestamp(),
    )
    # Справочный детектор крупных принтов (анонимная лента; не влияет на score/вердикт)
    big_prints = detect_big_prints(
        tape,
        display_price,
        lot,
        now_ts=datetime.now(timezone.utc).timestamp(),
    )
    # Минутное давление (пассивный крупный набор) и TWAP среди крупных принтов — справочно
    minute_pressure = detect_minute_pressure(tape, display_price, lot, now_ts=datetime.now(timezone.utc).timestamp())
    big_twap = detect_big_twap(tape, display_price, lot, now_ts=datetime.now(timezone.utc).timestamp())
    tape_metrics = detect_tape_size_metrics(tape, display_price, lot, now_ts=datetime.now(timezone.utc).timestamp())

    # Эвристические записи детекторов крупняка в радар «Роботы» (справочно, не идентификация участника)
    if big_prints.get("detected"):
        robots_list.append({
            "type": "🐋 Крупные принты",
            "detail": f"{big_prints.get('big_count')} сделок {big_prints.get('side')} на нетто {format_rub_volume(abs(float(big_prints.get('net_rub') or 0.0)))} за {BIG_TRADE_WINDOW_SECONDS} с",
            "heuristic": True,
        })
    if minute_pressure.get("detected"):
        robots_list.append({
            "type": "⏱ Минутное давление",
            "detail": f"нетто {minute_pressure.get('side')} {format_rub_volume(abs(float(minute_pressure.get('net_rub') or 0.0)))} при движении цены {minute_pressure.get('move_pct', 0.0):+.3f}%",
            "heuristic": True,
        })
    if big_twap.get("detected"):
        robots_list.append({
            "type": "⏲ TWAP-паттерн",
            "detail": f"{big_twap.get('count')} сделок по {big_twap.get('qty')} лот. {big_twap.get('side')}, сумма {format_rub_volume(big_twap.get('total_rub') or 0.0)}",
            "heuristic": True,
        })
    _ice_ts = datetime.now(timezone.utc).timestamp()
    for _e in ICEBERG_STATE.get(ticker, {}).get("events", []):
        if _ice_ts - float(_e.get("ts", 0)) <= 300:
            robots_list.append({
                "type": "🧊 Iceberg-стена",
                "detail": f"уровень {float(_e.get('price', 0)):.4f} ₽ ({_e.get('side')}): {float(_e.get('qty', 0)):.0f} → {float(_e.get('recovered_qty', 0)):.0f} лот. восстановилось",
                "heuristic": True,
            })
            break
    _bk = BOOK_STATE.get(ticker) or {}
    if _bk and (datetime.now(timezone.utc).timestamp() - float(_bk.get("ts", 0) or 0.0)) <= BOOK_STALE_SEC:
        if _bk.get("detected_imbalance"):
            robots_list.append({
                "type": "⚖️ Дисбаланс стакана",
                "detail": f"bid/ask {float(_bk.get('imbalance_pct', 0.0)):+.0f}% ({_bk.get('imbalance_side')}), плотность топ-5 {float(_bk.get('depth_conc_pct', 0.0)):.0f}%",
                "heuristic": True,
            })
        for _w in (_bk.get("big_walls") or [])[:2]:
            robots_list.append({
                "type": "🧱 Крупная лимитка в стакане",
                "detail": f"{_w.get('side')} {float(_w.get('price', 0)):.4f} ₽ — {float(_w.get('qty', 0)):.0f} лот. ({format_rub_volume(float(_w.get('rub', 0.0)))})",
                "heuristic": True,
            })
    if tape_metrics.get("detected_size"):
        robots_list.append({
            "type": "📏 Рост среднего чека сделок",
            "detail": f"средний чек {format_rub_volume(float(tape_metrics.get('avg_trade_rub') or 0.0))} (было {format_rub_volume(float(tape_metrics.get('avg_trade_rub_prev') or 0.0))}, {float(tape_metrics.get('avg_trend_pct') or 0.0):+.0f}%)",
            "heuristic": True,
        })
    if tape_metrics.get("detected_accel"):
        robots_list.append({
            "type": "🚀 Ускорение крупных принтов",
            "detail": f"{float(tape_metrics.get('big_rate_per_min') or 0.0):.1f} принт/мин сейчас против {float(tape_metrics.get('big_rate_per_min_prev') or 0.0):.1f} (x{float(tape_metrics.get('rate_accel') or 0.0):.1f})",
            "heuristic": True,
        })
    # Пункт 7: записываем сработавшие события крупняка (исход отметит монитор через 15 мин)
    _now_ev = datetime.now(timezone.utc).timestamp()
    _fires = []
    if big_prints.get("detected"):
        _fires.append(("🐋 крупные принты", big_prints.get("side"), float(big_prints.get("net_rub") or 0.0)))
    if minute_pressure.get("detected"):
        _fires.append(("⏱ минутное давление", minute_pressure.get("side"), float(minute_pressure.get("net_rub") or 0.0)))
    if big_twap.get("detected"):
        _fires.append(("⏲ TWAP", big_twap.get("side"), float(big_twap.get("total_rub") or 0.0)))
    if robot_activity.get("pattern_detected"):
        _fires.append(("🔁 повторы", robot_activity.get("side"), float(robot_activity.get("trade_count") or 0.0)))
    for _e in ICEBERG_STATE.get(ticker, {}).get("events", []):
        if _now_ev - float(_e.get("ts", 0)) <= 300:
            _fires.append(("🧊 iceberg", "BUY" if _e.get("side") == "bid" else "SELL", float(_e.get("qty") or 0.0) * float(_e.get("price") or 0.0)))
            break
    _bk3 = BOOK_STATE.get(ticker) or {}
    if _bk3 and (_now_ev - float(_bk3.get("ts", 0) or 0.0)) <= BOOK_STALE_SEC:
        if _bk3.get("detected_imbalance"):
            _fires.append(("⚖️ дисбаланс стакана", "BUY" if _bk3.get("imbalance_side") == "bid" else "SELL",
                           float(_bk3.get("bid_rub") or 0.0) + float(_bk3.get("ask_rub") or 0.0)))
        if _bk3.get("detected_wall"):
            _w0 = (_bk3.get("big_walls") or [{}])[0]
            _fires.append(("🧱 big wall", "BUY" if _w0.get("side") == "bid" else "SELL", float(_w0.get("rub") or 0.0)))
    if tape_metrics.get("detected_size"):
        _fires.append(("📏 рост среднего чека", tape_metrics.get("side"), float(tape_metrics.get("avg_trade_rub") or 0.0)))
    if tape_metrics.get("detected_accel"):
        _fires.append(("🚀 ускорение принтов", tape_metrics.get("side"), float(tape_metrics.get("rate_accel") or 0.0)))
    for _d, _s, _st in _fires:
        record_whale_event(ticker, _d, _s, _st, display_price, _now_ev)

    # Складываем ленту в хранилище (память + файл): так реальная дельта копится по свечам
    # и на 1ч/4ч перестаёт быть «оценкой по свечам» через несколько часов работы.
    if CVD_STORE_ENABLED:
        CVD_STORE.absorb(ticker, tape)

    # Проверяем реальный CVD и скрытое накопление сразу на всех 5 таймфреймах (5m, 15m, 30m, 1h, 4h)
    mtf_cvd: dict[str, dict] = {}
    for k in INFORMANT_TIMEFRAMES:
        d_frame = tf_df_map.get(k, pd.DataFrame())
        mtf_cvd[k] = calc_cvd_and_cum_delta(
            d_frame, tape, k, hist=cvd_store_history(ticker, k, d_frame)
        )

    rsi_val = 50.0
    ema9_val = display_price
    ema20_val = display_price
    ema50_val = display_price
    ema200_val = display_price
    vwap_val = display_price
    atr_val = display_price * 0.007
    rvol_val = 1.0
    recent_low = display_price * 0.99
    recent_high = display_price * 1.01
    cvd_data = mtf_cvd.get(tf_key) or calc_cvd_and_cum_delta(
        df, tape, tf_key, hist=cvd_store_history(ticker, tf_key, df)
    )

    if not df.empty:
        df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
        df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
        ema9_val = float(df["EMA9"].iloc[-1])
        ema20_val = float(df["EMA20"].iloc[-1])
        ema50_val = float(df["EMA50"].iloc[-1])
        ema200_val = float(df["EMA200"].iloc[-1])

        today_mask = df["date_msk"] == df["date_msk"].iloc[-1]
        today_slice = df[today_mask] if today_mask.any() else df
        typical_price = (today_slice["High"] + today_slice["Low"] + today_slice["Close"]) / 3
        cum_vol = today_slice["Volume"].replace(0, 1).cumsum()
        vwap_series = (typical_price * today_slice["Volume"]).cumsum() / cum_vol
        vwap_val = float(vwap_series.iloc[-1])

        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr_series = tr.rolling(14, min_periods=1).mean()
        atr_val = float(atr_series.iloc[-1]) if float(atr_series.iloc[-1]) > 0 else display_price * 0.007

        delta_p = df["Close"].diff()
        gain = delta_p.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta_p.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs = gain / loss.replace(0, 1e-10)
        df["RSI"] = 100 - (100 / (1 + rs))
        rsi_val = float(df["RSI"].iloc[-1])

        avg_vol = df["Volume"].tail(20).mean()
        rvol_val = round(float(df["Volume"].iloc[-1] / avg_vol), 2) if avg_vol > 0 else 1.0

        recent_low = float(df["Low"].tail(6).min())
        recent_high = float(df["High"].tail(6).max())

    sr_levels = compute_sr_levels(display_price, df, df_1h, df_1d, mtf_emas)

    score = micro["algo_score"]
    factors = []
    block_reasons = []

    # Эвристические надбавки от детекторов крупняка (справочно; не доказательство участника)
    if big_prints.get("detected"):
        _w = 1 if big_prints.get("side") == "BUY" else -1
        score += _w
        factors.append(f"🐋 <b>Крупные принты (эвристика):</b> {big_prints.get('big_count')} сделок на нетто {format_rub_volume(abs(float(big_prints.get('net_rub') or 0.0)))} {big_prints.get('side')} — {_w:+d}")
    if minute_pressure.get("detected"):
        _w = 2 if minute_pressure.get("side") == "BUY" else -2
        score += _w
        factors.append(f"⏱ <b>Минутное давление (эвристика):</b> нетто {format_rub_volume(abs(float(minute_pressure.get('net_rub') or 0.0)))} при стоящей цене — {_w:+d}")
    if big_twap.get("detected"):
        _w = 1 if big_twap.get("side") == "BUY" else -1
        score += _w
        factors.append(f"⏲ <b>TWAP-паттерн (эвристика):</b> {big_twap.get('count')}×{big_twap.get('qty')} лот. — {_w:+d}")
    _ice_ts = datetime.now(timezone.utc).timestamp()
    for _e in ICEBERG_STATE.get(ticker, {}).get("events", []):
        if _ice_ts - float(_e.get("ts", 0)) <= 300:
            _w = 1 if _e.get("side") == "bid" else -1
            score += _w
            factors.append(f"🧊 <b>Iceberg-стена (эвристика):</b> уровень {float(_e.get('price', 0)):.4f} восстановился — {_w:+d}")
            break
    _bk2 = BOOK_STATE.get(ticker) or {}
    if _bk2 and (_ice_ts - float(_bk2.get("ts", 0) or 0.0)) <= BOOK_STALE_SEC:
        if _bk2.get("detected_imbalance"):
            _w = 1 if _bk2.get("imbalance_side") == "bid" else -1
            score += _w
            factors.append(f"⚖️ <b>Дисбаланс стакана (эвристика):</b> {float(_bk2.get('imbalance_pct', 0.0)):+.0f}% в сторону {_bk2.get('imbalance_side')} — {_w:+d}")
        if _bk2.get("detected_wall"):
            _wall = (_bk2.get("big_walls") or [{}])[0]
            _w = 1 if _wall.get("side") == "bid" else -1
            score += _w
            factors.append(f"🧱 <b>Big wall в стакане (эвристика):</b> {float(_wall.get('price', 0.0)):.4f} ₽ {_wall.get('side')} — {_w:+d}")
    if tape_metrics.get("detected_size"):
        _w = 1 if tape_metrics.get("side") == "BUY" else -1
        score += _w
        factors.append(f"📏 <b>Рост среднего чека (эвристика):</b> {float(tape_metrics.get('avg_trend_pct') or 0.0):+.0f}% — {_w:+d}")
    if tape_metrics.get("detected_accel"):
        _w = 1 if tape_metrics.get("side") == "BUY" else -1
        score += _w
        factors.append(f"🚀 <b>Ускорение принтов (эвристика):</b> x{float(tape_metrics.get('rate_accel') or 0.0):.1f} — {_w:+d}")

    if not is_live_market:
        block_reasons.append("Биржа сейчас закрыта (или нет свежих сделок за последние 20 мин) — сигналы на вход заблокированы до открытия торгов")

    if display_price > vwap_val and ema20_val >= ema50_val:
        score += 2
        factors.append(f"🟢 <b>Тренд и VWAP:</b> Цена выше VWAP ({vwap_val:.2f}) и связки EMA 9/20/50")
    elif display_price < vwap_val and ema20_val <= ema50_val:
        score -= 2
        factors.append(f"🔴 <b>Тренд и VWAP:</b> Цена под давлением ниже VWAP ({vwap_val:.2f}) и EMA 9/20/50")
    else:
        factors.append(f"⚪ <b>VWAP ({vwap_val:.2f}):</b> Консолидация между скользящими EMA")

    bull_tfs = [TIMEFRAMES[k]["btn"] for k, v in mtf_emas.items() if v["trend"] == "BULL"]
    bear_tfs = [TIMEFRAMES[k]["btn"] for k, v in mtf_emas.items() if v["trend"] == "BEAR"]

    if len(bull_tfs) >= 3:
        score += 2
        factors.append(f"🟢 <b>MTF EMA ({', '.join(bull_tfs)}):</b> Выстроены по бычьему тренду")
    elif len(bear_tfs) >= 3:
        score -= 2
        factors.append(f"🔴 <b>MTF EMA ({', '.join(bear_tfs)}):</b> Синхронный медвежий тренд")
    elif len(bull_tfs) == 2 and not bear_tfs:
        score += 1
        factors.append(f"🟢 <b>MTF EMA ({', '.join(bull_tfs)}):</b> Локальный перевес покупателей")
    elif len(bear_tfs) == 2 and not bull_tfs:
        score -= 1
        factors.append(f"🔴 <b>MTF EMA ({', '.join(bear_tfs)}):</b> Локальный перевес продавцов")

    if moex_ctx and not is_index_inst:
        idx_bias = moex_ctx["bias"]
        idx_p = moex_ctx["price"]
        idx_ch = moex_ctx["change_pct"]
        if idx_bias in ("BULL", "MILD_BULL"):
            score += 1
            factors.append(f"🏛 <b>Индекс МБ ({idx_p:.1f}, {idx_ch:+.2f}%):</b> {moex_ctx['summary_badge']} — поддерживает LONG")
        elif idx_bias in ("BEAR", "MILD_BEAR"):
            score -= 1
            factors.append(f"🏛 <b>Индекс МБ ({idx_p:.1f}, {idx_ch:+.2f}%):</b> {moex_ctx['summary_badge']} — поддерживает SHORT")
        else:
            factors.append(f"🏛 <b>Индекс МБ ({idx_p:.1f}, {idx_ch:+.2f}%):</b> {moex_ctx['summary_badge']}")

    bar_d = cvd_data["bar_delta"]
    cvd_today = cvd_data["cvd_today"]
    cvd_ch3 = cvd_data["cvd_change_3"]
    d_eff = cvd_data["delta_efficiency_6"]

    if cvd_today > 0 and cvd_ch3 > 0 and bar_d > 0:
        score += 2
        factors.append(
            f"🟢 <b>CVD и Дельта:</b> Покупки ({format_lots_delta(bar_d)}, перевес {d_eff:+.1f}% от объёма), CVD дня растёт ({format_lots_delta(cvd_today)})"
        )
    elif cvd_today < 0 and cvd_ch3 < 0 and bar_d < 0:
        score -= 2
        factors.append(
            f"🔴 <b>CVD и Дельта:</b> Продажи ({format_lots_delta(bar_d)}, перевес {d_eff:+.1f}% от объёма), CVD дня падает ({format_lots_delta(cvd_today)})"
        )
    else:
        factors.append(
            f"⚪ <b>CVD дня ({format_lots_delta(cvd_today)}):</b> Дельта свечи {format_lots_delta(bar_d)} (перевес 6 св.: {d_eff:+.1f}%)"
        )

    # Учитываем сигналы Информатора в баллах только при свежих данных по бумаге.
    if ticker_live:
        for tf_k, c_inf in mtf_cvd.items():
            inf_side = c_inf.get("absorption_side") or c_inf.get("pressure_side")
            inf_desc = c_inf.get("absorption_desc") or c_inf.get("pressure_desc")
            if inf_side == "LONG":
                score += 2
                factors.append(inf_desc)
            elif inf_side == "SHORT":
                score -= 2
                factors.append(inf_desc)

    # Доля Bid/Ask доступна для справки в деталях, но не меняет сигнал.

    if rvol_val >= 1.3:
        if bar_d > 0 and display_price >= vwap_val:
            score += 1
            factors.append(f"🔥 <b>Объём (RVOL {rvol_val}x):</b> Всплеск объёма на реальных покупках")
        elif bar_d < 0 and display_price <= vwap_val:
            score -= 1
            factors.append(f"🔥 <b>Объём (RVOL {rvol_val}x):</b> Всплеск объёма на продажах")

    if score > 0:
        if cvd_data["green_candle_lies"]:
            score = min(score, 2)
            block_reasons.append(f"Зелёная свеча врёт! Внутри продавали больше (дельта {format_lots_delta(bar_d)})")
        if cvd_ch3 <= 0 or (cvd_today < 0 and bar_d <= 0):
            score = min(score, 2)
            block_reasons.append("CVD показывает перевес продавцов — вход в LONG заблокирован")
        if cvd_data["bearish_divergence"]:
            score = min(score, 2)
            block_reasons.append("Медвежья дивергенция: цена растёт, а Кум. Дельта уходит вниз")
        if cvd_data.get("pivot_bearish_div"):
            score = min(score, 2)
            block_reasons.append("⚠️ Дивергенция по пивотам: новый максимум цены выше, а CVD ниже прошлого пика — возможен разворот после пампа (эвристика)")
        if rvol_val < 0.65:
            score = min(score, 3)
            block_reasons.append(f"Слишком низкий объём на свече (RVOL {rvol_val}x менее нормы)")
        if sr_levels["res1_dist_pct"] < 0.30 and ("1ч" in sr_levels["res1_label"] or "1д" in sr_levels["res1_label"] or "Сильный" in sr_levels["res1_label"]):
            score = min(score, 3)
            block_reasons.append(
                f"Цена упёрлась в уровень сопротивления {sr_levels['res1_price']} ({sr_levels['res1_label']}, до него всего {sr_levels['res1_dist_pct']:.2f}%)"
            )
        if moex_ctx and not is_index_inst and moex_ctx["bias"] == "BEAR" and moex_ctx["change_pct"] < -0.5:
            score = min(score, 3)
            block_reasons.append(f"Индекс Мосбиржи (IMOEX) в активном снижении ({moex_ctx['change_pct']:+.2f}%) — риск лонга высокий")

    elif score < 0:
        if cvd_data["red_candle_lies"]:
            score = max(score, -2)
            block_reasons.append(f"Красная свеча врёт! Внутри выкупали (дельта {format_lots_delta(bar_d)})")
        if cvd_ch3 >= 0 or (cvd_today > 0 and bar_d >= 0):
            score = max(score, -2)
            block_reasons.append("CVD растёт — вход в SHORT заблокирован")
        if cvd_data["bullish_divergence"]:
            score = max(score, -2)
            block_reasons.append("Бычья дивергенция: цена снижается, но Кум. Дельта растёт")
        if cvd_data.get("pivot_bullish_div"):
            score = max(score, -2)
            block_reasons.append("⚠️ Дивергенция по пивотам: новый минимум цены ниже, а CVD выше прошлого минимума (эвристика)")
        if rvol_val < 0.65:
            score = max(score, -3)
            block_reasons.append(f"Слишком низкий объём на свече (RVOL {rvol_val}x менее нормы)")
        if sr_levels["sup1_dist_pct"] < 0.30 and ("1ч" in sr_levels["sup1_label"] or "1д" in sr_levels["sup1_label"] or "Сильный" in sr_levels["sup1_label"]):
            score = max(score, -3)
            block_reasons.append(
                f"Цена прямо на сильной поддержке {sr_levels['sup1_price']} ({sr_levels['sup1_label']}, до неё {sr_levels['sup1_dist_pct']:.2f}%)"
            )
        if moex_ctx and not is_index_inst and moex_ctx["bias"] == "BULL" and moex_ctx["change_pct"] > 0.5:
            score = max(score, -3)
            block_reasons.append(f"Индекс Мосбиржи (IMOEX) уверенно растёт ({moex_ctx['change_pct']:+.2f}%) — шорт против рынка опасен")

    if score > 0 and rsi_val > 70:
        score = min(score, 2)
        block_reasons.append(f"RSI перегрет ({rsi_val:.1f})")
    elif score < 0 and rsi_val < 30:
        score = max(score, -2)
        block_reasons.append(f"RSI перепродан ({rsi_val:.1f})")
    else:
        factors.append(f"📊 <b>RSI ({rsi_val:.1f}):</b> В рабочей зоне")

    # Крупные видимые уровни не классифицируются и не блокируют направление сигнала.
    # Они используются только при построении плановых SL/TP ниже.
    ask_wall_p = book_liquidity["ask_wall_price"]
    bid_wall_p = book_liquidity["bid_wall_price"]

    if score >= MIN_SCORE_FOR_ENTRY and not block_reasons and is_live_market:
        verdict = "LONG"
    elif score <= -MIN_SCORE_FOR_ENTRY and not block_reasons and is_live_market:
        verdict = "SHORT"
    else:
        verdict = "WAIT"

    calc_side = "LONG" if score >= 0 else "SHORT"

    targets = calculate_trade_targets(
        calc_side, display_price, atr_val, recent_low, recent_high, sr_levels,
        bid_wall_p, ask_wall_p, book_liquidity["tick_size"],
    )

    # patch30a: VKCO-сценарий — медвежья пивот-дивергенция у свежего максимума после пампа → предложение ШОРТА
    short_proposal = False
    if (is_live_market and not is_index_inst and cvd_data.get("pivot_bearish_div")
            and recent_high > 0 and display_price >= recent_high * (1.0 - 0.03)):
        short_proposal = True
        verdict = "SHORT"
        calc_side = "SHORT"
        targets = calculate_trade_targets(
            "SHORT", display_price, atr_val, recent_low, recent_high, sr_levels,
            bid_wall_p, ask_wall_p, book_liquidity["tick_size"],
        )
        block_reasons.append("⚠️ <b>ПРЕДЛОЖЕНИЕ ШОРТА</b>: медвежья дивергенция по пивотам у максимума после пампа — "
                             + str(cvd_data.get("pivot_div_note") or "цена выше, CVD ниже") + " (эвристика, не доказательство)")
    targets_long = calculate_trade_targets(
        "LONG", display_price, atr_val, recent_low, recent_high, sr_levels,
        bid_wall_p, ask_wall_p, book_liquidity["tick_size"],
    )
    targets_short = calculate_trade_targets(
        "SHORT", display_price, atr_val, recent_low, recent_high, sr_levels,
        bid_wall_p, ask_wall_p, book_liquidity["tick_size"],
    )

    if robots_list and not is_index_inst and is_live_market:
        existing = ACTIVE_ROBOTS_REGISTRY.get(ticker, {})
        start_ts = existing.get("start_ts", time.time())
        ACTIVE_ROBOTS_REGISTRY[ticker] = {
            "ticker": ticker,
            "name": name,
            "price": display_price,
            "verdict": verdict,
            "side": calc_side,
            "tp": targets["tp"],
            "sl": targets["sl"],
            "robots": robots_list,
            "start_ts": start_ts,
            "updated_ts": time.time(),
        }
    elif ticker in ACTIVE_ROBOTS_REGISTRY:
        del ACTIVE_ROBOTS_REGISTRY[ticker]

    result_sig = {
        "is_illiquid": False,
        "is_live_market": is_live_market,
        "ticker_live": ticker_live,
        "last_trade_age_min": round(last_trade_age_min, 1),
        "last_activity_age_min": round(last_activity_age_min, 1),
        "last_candle_age_min": round(candle_age_5m, 1),
        "data_checked_ts": time.time(),
        "last_candle_time": last_candle_time_str,
        "ticker": ticker,
        "name": name,
        "price": display_price,
        "change": change_pct,
        "tf_key": tf_key,
        "score": score,
        "verdict": verdict,
        "calc_side": calc_side,
        "short_proposal": short_proposal,
        "factors": factors,
        "block_reasons": block_reasons,
        "robots": robots_list,
        "robot_activity": robot_activity,
        "big_prints": big_prints,
        "minute_pressure": minute_pressure,
        "big_twap": big_twap,
        "tape_metrics": tape_metrics,
        "cvd_data": cvd_data,
        "mtf_cvd": mtf_cvd,
        "mtf_emas": mtf_emas,
        "sr_levels": sr_levels,
        "book_liquidity": book_liquidity,
        "moex_ctx": moex_ctx,
        "ema9": ema9_val,
        "ema20": ema20_val,
        "ema50": ema50_val,
        "ema200": ema200_val,
        "entry": targets["entry"],
        "tp": targets["tp"],
        "sl": targets["sl"],
        "sl_reason": targets["sl_reason"],
        "tp_reason": targets["tp_reason"],
        "atr": round(atr_val, 4),
        "atr_pct": round(atr_val / max(display_price, 1e-9) * 100, 2),
        "day_range_pct": round((recent_high - recent_low) / max(display_price, 1e-9) * 100, 2),
        "atr_consumed_pct": round(((recent_high - recent_low) / max(atr_val, 1e-9)) * 100, 1),
        "profit_pct": targets["profit_pct"],
        "risk_pct": targets["risk_pct"],
        "rr_ratio": targets["rr_ratio"],
        "targets_by_side": {"LONG": targets_long, "SHORT": targets_short},
        "vwap": vwap_val,
        "rvol": rvol_val,
        "dividend_info": get_dividend_info(ticker),
        "icebergs": book_liquidity.get("icebergs", []),
        "iceberg_alert": book_liquidity.get("iceberg_alert"),
        "bid_wall_str": micro["bid_wall_str"],
        "ask_wall_str": micro["ask_wall_str"],
    }

    if tf_key == "15m":
        global WEB_SCAN_TS
        WEB_SCAN_CACHE[ticker] = result_sig
        WEB_SCAN_TS = time.time()

    result_sig["whale_kinds"] = whale_confluence_kinds(result_sig)
    return result_sig


def _prune_scan_cache() -> None:
    now = time.time()
    for k in [k for k, (ts, _) in SCAN_CACHE.items() if (now - ts) > 300]:
        SCAN_CACHE.pop(k, None)


async def get_signal_cached(
    ticker: str,
    tf_key: str = "15m",
    ttl: float = SCAN_CACHE_TTL,
    force: bool = False,
) -> dict | None:
    """
    Единая точка получения сигнала для ВСЕХ потребителей (монитор, кнопки, веб-дашборд).
    Раньше фоновый монитор и дашборд дёргали API независимо друг от друга —
    теперь один расчёт на пару (тикер, ТФ) живёт SCAN_CACHE_TTL секунд.
    """
    ticker = ticker.upper().strip()
    key = (ticker, tf_key)
    now = time.time()
    if not force:
        hit = SCAN_CACHE.get(key)
        if hit and (now - hit[0]) < ttl:
            return hit[1]

    # In-flight дедупликация: пока анализ (тикер, ТФ) уже идёт, ждём его вместо второго запуска
    task = _SCAN_INFLIGHT.get(key)
    if task is None or force:
        task = asyncio.create_task(analyze_stock_signal(ticker, tf_key))
        _SCAN_INFLIGHT[key] = task
        try:
            sig = await task
        finally:
            if _SCAN_INFLIGHT.get(key) is task:
                _SCAN_INFLIGHT.pop(key, None)
    else:
        sig = await task
    if sig and not sig.get("is_illiquid"):
        SCAN_CACHE[key] = (time.time(), sig)
        if tf_key == "15m":
            WEB_SCAN_CACHE[ticker] = sig
            global WEB_SCAN_TS
            WEB_SCAN_TS = time.time()
    return sig


def format_cvd_section(cvd_data: dict, mtf_cvd: dict | None = None, ticker_live: bool = True) -> str:
    bar_d = cvd_data.get("bar_delta", 0.0)
    bar_d_pct = cvd_data.get("bar_delta_pct", 0.0)
    cvd_today = cvd_data.get("cvd_today", 0.0)
    cum_d_ch = cvd_data.get("cum_delta_change_6", 0.0)
    d_eff_6 = cvd_data.get("delta_efficiency_6", 0.0)
    p_ch_6 = cvd_data.get("price_change_6_pct", 0.0)

    if cvd_data.get("green_candle_lies"):
        candle_check = f"⚠️ <b>Зелёная свеча врёт (внутри продавали: {format_lots_delta(bar_d)} / {bar_d_pct:+.1f}%)</b>"
    elif cvd_data.get("red_candle_lies"):
        candle_check = f"⚠️ <b>Красная свеча врёт (внутри выкупали: {format_lots_delta(bar_d)} / {bar_d_pct:+.1f}%)</b>"
    elif bar_d > 0:
        candle_check = f"🟢 Покупатели сильнее (<b>{format_lots_delta(bar_d)}</b> | <b>{bar_d_pct:+.1f}%</b> от объёма)"
    elif bar_d < 0:
        candle_check = f"🔴 Продавцы сильнее (<b>{format_lots_delta(bar_d)}</b> | <b>{bar_d_pct:+.1f}%</b> от объёма)"
    else:
        candle_check = "⚪ Равновесие в свече"

    cvd_status = "🟢 Давят покупатели" if cvd_today > 0 else ("🔴 Давят продавцы" if cvd_today < 0 else "⚪ Нейтрально")
    cum_status = "📈 Накопление (покупки)" if cum_d_ch > 0 else ("📉 Распределение (продажи)" if cum_d_ch < 0 else "⚪ Баланс")

    lines = [
        "📊 <b>Кластерный фильтр CVD (Лоты + % перевеса от объёма):</b>",
    ]
    if not ticker_live:
        lines.append("⚠️ Нет свежих сделок/рынок закрыт: CVD-паттерны ниже показаны справочно и не считаются активными сигналами.")
    lines.extend([
        f"• Текущая свеча: {candle_check}",
        f"• CVD (с начала дня): <b>{format_lots_delta(cvd_today)}</b> ({cvd_status})",
        f"• За 6 свечей: <b>{format_lots_delta(cum_d_ch)}</b> | Перевес: <b>{d_eff_6:+.1f}%</b> от объёма | Цена: <b>{p_ch_6:+.2f}%</b> ({cum_status})",
        f"• Давление объёмом: диапазон окна / |перевес CVD| = <b>{float(cvd_data.get('price_impact', 999.0)):.3f}</b> (порог ≤ {PRICE_IMPACT_MAX}: чем меньше, тем сильнее давят при стоящей цене)",
    ])
    if cvd_data.get("pivot_div_note"):
        lines.append(f"• ⚠️ <b>Дивергенция цена/CVD по пивотам:</b> {cvd_data['pivot_div_note']} (эвристика, не доказательство)")

    if mtf_cvd:
        tf_summary = []
        for tf_k in INFORMANT_TIMEFRAMES:
            c_i = mtf_cvd.get(tf_k)
            if not c_i:
                continue
            eff = c_i.get("delta_efficiency_6", 0.0)
            lots_6 = c_i.get("cum_delta_change_6", 0.0)
            abs_flag = (" 🔥" if ticker_live else " (исторический)") if (c_i.get("absorption_side") or c_i.get("pressure_side")) else ""
            cov = c_i.get("tape_cov_pct", 0.0)
            threshold = c_i.get("threshold_pct", cvd_absorption_threshold(tf_k))
            tf_summary.append(
                f"<b>{TIMEFRAMES[tf_k]['btn']}:</b> {format_lots_delta(lots_6)} "
                f"({eff:+.0f}%, порог >{threshold:.0f}%, лента {cov:.0f}%){abs_flag}"
            )
        if tf_summary:
            lines.append("• <b>CVD (6 св.) по ТФ:</b> " + " | ".join(tf_summary))

    return "\n".join(lines)


def format_mtf_sr_and_index_section(sig: dict) -> str:
    sr = sig.get("sr_levels", {})
    mtf = sig.get("mtf_emas", {})
    moex = sig.get("moex_ctx")
    book = sig.get("book_liquidity", {}) or {}

    poc_str = f"{sr.get('poc'):.2f}" if sr.get("poc") else "—"
    res2_str = f" | след: <b>{sr['res2_price']}</b>" if sr.get("res2_price") else ""
    sup2_str = f" | след: <b>{sr['sup2_price']}</b>" if sr.get("sup2_price") else ""

    sr_block = (
        f"🧱 <b>Уровни сопротивления и поддержки:</b>\n"
        f"• 🔴 Сопротивление: <b>{sr.get('res1_price')}</b> (+{sr.get('res1_dist_pct')}% — <i>{sr.get('res1_label')}</i>){res2_str}\n"
        f"• 🟢 Поддержка: <b>{sr.get('sup1_price')}</b> (-{sr.get('sup1_dist_pct')}% — <i>{sr.get('sup1_label')}</i>){sup2_str}\n"
        f"• 🟡 POC (макс. объём): <b>{poc_str}</b>"
    )

    book_lines = []
    if book.get("available"):
        if book.get("ask_wall_price"):
            book_lines.append(
                f"• 🔴 Ask: <b>{book['ask_wall_price']:.4f} ₽</b> — "
                f"{format_lots_abs(book.get('ask_wall_quantity', 0))}, {format_rub_volume(book.get('ask_wall_rub', 0))} "
                f"({book.get('ask_wall_mult', 1):.1f}× медианы)"
            )
        if book.get("bid_wall_price"):
            book_lines.append(
                f"• 🟢 Bid: <b>{book['bid_wall_price']:.4f} ₽</b> — "
                f"{format_lots_abs(book.get('bid_wall_quantity', 0))}, {format_rub_volume(book.get('bid_wall_rub', 0))} "
                f"({book.get('bid_wall_mult', 1):.1f}× медианы)"
            )
        if not book_lines:
            book_lines.append("• Значимые объёмные уровни не найдены по текущему фильтру")
        book_lines.append(
            f"• Доля Bid в топ-{BOOK_DEPTH}: {book.get('bid_share_pct', 50):.0f}% "
            "(справочно, не меняет направление сигнала)"
        )
        book_lines.append("• <i>Это снимок стакана: заявки могут измениться или быть сняты.</i>")
    else:
        book_lines.append("• Стакан недоступен; цели рассчитаны по ATR/R:R и тех. уровням")
    book_block = "📚 <b>Видимая ликвидность в стакане:</b>\n" + "\n".join(book_lines)

    ema_lines = [
        f"• Текущий ТФ ({TIMEFRAMES[sig['tf_key']]['btn']}): EMA9 <b>{sig.get('ema9', 0):.2f}</b> | EMA20 <b>{sig.get('ema20', 0):.2f}</b> | EMA50 <b>{sig.get('ema50', 0):.2f}</b> | EMA200 <b>{sig.get('ema200', 0):.2f}</b>"
    ]
    tf_badges = []
    for k in ("5m", "15m", "30m", "1h", "4h", "1d"):
        if k in mtf:
            info = mtf[k]
            e200_tag = "выше EMA200" if info["above_ema200"] else "ниже EMA200"
            tf_badges.append(f"<b>{TIMEFRAMES[k]['btn']}:</b> {info['badge']} ({e200_tag})")
    if tf_badges:
        ema_lines.append("• По таймфреймам: " + " | ".join(tf_badges))

    ema_block = "📈 <b>Карта EMA (9 / 20 / 50 / 200) на разных ТФ:</b>\n" + "\n".join(ema_lines)

    if moex and sig.get("ticker") != "IMOEX":
        m_sr = moex.get("sr", {})
        m_mtf = moex.get("mtf_emas", {})
        m_tf_str = ", ".join(
            f"{TIMEFRAMES[k]['btn']}: {m_mtf[k]['badge']}"
            for k in ("15m", "1h", "1d")
            if k in m_mtf
        )
        index_block = (
            f"🏛 <b>Поводырь — Индекс Мосбиржи (IMOEX):</b>\n"
            f"• Значение: <b>{moex['price']:.2f} п.</b> ({moex['change_pct']:+.2f}%) — {moex['summary_badge']}\n"
            f"• Уровни IMOEX: 🔴 Сопр. <b>{m_sr.get('res1_price')}</b> | 🟢 Подд. <b>{m_sr.get('sup1_price')}</b>\n"
            f"• Тренд IMOEX по ТФ: {m_tf_str}"
        )
        return f"{sr_block}\n\n{book_block}\n\n{ema_block}\n\n{index_block}"

    return f"{sr_block}\n\n{book_block}\n\n{ema_block}"


def format_repeated_trade_pattern_section(activity: dict | None) -> str:
    """Форматирует наблюдаемую серию сделок без утверждения, что найден робот."""
    if not activity or not activity.get("pattern_detected"):
        return ""
    side_text = "покупки" if activity.get("side") == "BUY" else "продажи"
    return (
        "🔎 <b>Повторяющийся паттерн в обезличенной ленте (эвристика):</b>\n"
        f"• {side_text}: {activity.get('trade_count')} сделок по "
        f"{activity.get('quantity_lots')} лот. за {activity.get('span_seconds'):.1f} с; "
        f"медианный интервал {activity.get('median_interval_seconds'):.2f} с "
        f"(CV {activity.get('interval_cv'):.2f}), разброс цены {activity.get('price_span_pct'):.3f}%.\n"
        "• <i>Это может быть алгоритмическое исполнение, но не подтверждает робота "
        "и не влияет на score/вердикт/цели.</i>\n\n"
    )


def format_big_prints_section(bp: dict | None) -> str:
    """Крупные принты в ленте — справочно, без идентификации участника."""
    if not bp or not bp.get("detected"):
        return ""
    side_text = "покупки" if bp.get("side") == "BUY" else "продажи"
    return (
        f"🐋 <b>Крупные принты за {BIG_TRADE_WINDOW_SECONDS} с (эвристика):</b>\n"
        f"• {bp.get('big_count')} сделок ≥ {format_rub_volume(BIG_TRADE_MIN_RUB)}: {side_text} нетто "
        f"<b>{format_rub_volume(abs(float(bp.get('net_rub') or 0.0)))}</b> "
        f"(buy {format_rub_volume(bp.get('big_buy_rub') or 0.0)} / sell {format_rub_volume(bp.get('big_sell_rub') or 0.0)}), "
        f"медиана {format_rub_volume(bp.get('median_big_rub') or 0.0)}, доля окна ленты {bp.get('share_of_window_rub') or 0.0:.0f}%\n"
        f"• <i>Концентрация крупных сделок одной стороны — возможный крупный игрок, но не доказательство: "
        f"лента анонимна, сделки могли пройти разными участниками.</i>\n\n"
    )


def format_minute_pressure_section(mp: dict | None) -> str:
    """Минутное давление: большой нетто-объём при стоящей цене — возможный лимитный набор."""
    if not mp or not mp.get("detected"):
        return ""
    side_txt = "покупки" if mp.get("side") == "BUY" else "продажи"
    return (
        f"⏱ <b>Минутное давление (возможный крупный пассивный игрок):</b>\n"
        f"• за минуту нетто {side_txt} <b>{format_rub_volume(abs(float(mp.get('net_rub') or 0.0)))}</b>, "
        f"а цена сдвинулась лишь на <b>{mp.get('move_pct', 0.0):+.3f}%</b> (impact {mp.get('impact', 0.0):.0f} ₽ объёма на 1% движения)\n"
        f"• <i>Большой объём при стоящей цене = возможен лимитный набор. Эвристика, не доказательство.</i>\n\n"
    )


def format_twap_section(tw: dict | None) -> str:
    """TWAP-паттерн среди крупных принтов (алгоритмическое исполнение)."""
    if not tw or not tw.get("detected"):
        return ""
    side_txt = "покупки" if tw.get("side") == "BUY" else "продажи"
    return (
        f"⏲ <b>TWAP-паттерн крупных принтов:</b> {tw.get('count')} сделок по {tw.get('qty')} лот. ({side_txt}), "
        f"сумма {format_rub_volume(tw.get('total_rub') or 0.0)}, CV интервалов {tw.get('interval_cv', 0.0):.2f}\n"
        f"• <i>Ровные интервалы одного объёма одной стороны — возможное алгоритмическое исполнение. Эвристика.</i>\n\n"
    )


def format_signal_caption(sig: dict, is_auto_alert: bool = False) -> str:
    change = sig["change"] or 0.0
    ch_emoji = "🟢" if change > 0 else ("🔴" if change < 0 else "⚪")
    ch_sign = "+" if change > 0 else ""

    factors_block = "\n".join(f"• {f}" for f in sig["factors"])
    cvd_block = format_cvd_section(
        sig.get("cvd_data", {}), sig.get("mtf_cvd"), signal_data_is_live(sig),
    )
    effective_verdict = sig.get("verdict", "WAIT")
    if not signal_data_is_live(sig, require_candle=True):
        effective_verdict = "WAIT"
    mtf_sr_idx_block = format_mtf_sr_and_index_section(sig)
    robot_activity_block = format_repeated_trade_pattern_section(sig.get("robot_activity"))
    big_prints_block = format_big_prints_section(sig.get("big_prints"))
    minute_pressure_block = format_minute_pressure_section(sig.get("minute_pressure"))
    twap_block = format_twap_section(sig.get("big_twap"))

    if effective_verdict in ("LONG", "SHORT"):
        side_header = (
            "🟢 <b>СИГНАЛ СНАЙПЕРА: ВХОД В LONG 📈</b>"
            if effective_verdict == "LONG"
            else "🔴 <b>СИГНАЛ СНАЙПЕРА: ВХОД В SHORT 📉</b>"
        )
        auto_badge = "⚡ <b>НАЙДЕН СИГНАЛ СНАЙПЕРА (ПРОВЕРЬ ГРАФИК ПЕРЕД ВХОДОМ)!</b>\n" if is_auto_alert else ""
        confidence = min(98, 65 + abs(sig["score"]) * 4)

        return (
            f"{auto_badge}{'⚠️ <b>ДИВЕРГЕНЦИЯ-ПАМП: предлагается ШОРТ (эвристика)</b>\n' if sig.get('short_proposal') else ''}{side_header}\n"
            f"🏢 Инструмент: <b>{sig['name']} ({sig['ticker']})</b> | ТФ: <b>{TIMEFRAMES[sig['tf_key']]['btn']}</b>\n"
            f"💰 Цена: <b>{sig['price']} ₽</b> ({ch_emoji} {ch_sign}{change:.2f}%)\n"
            f"🧠 Осмысленность: <b>{abs(sig['score'])}/10 баллов (~{confidence}%)</b>\n\n"
            f"{robot_activity_block}"
            f"{big_prints_block}"
            f"{minute_pressure_block}"
            f"{twap_block}"
            f"🎯 <b>РАСЧЁТНЫЕ УРОВНИ СДЕЛКИ (R/R 1:{sig['rr_ratio']}):</b>\n"
            f"• Точка входа: <b>{sig['entry']} ₽</b>\n"
            f"• ✅ <b>Take-Profit: {sig['tp']} ₽</b> (+{sig['profit_pct']:.2f}%) — <i>{sig.get('tp_reason', 'расчётная цель')}</i>\n"
            f"• 🛡 <b>Stop-Loss: {sig['sl']} ₽</b> (-{sig['risk_pct']:.2f}% — <i>{sig['sl_reason']}</i>)\n\n"
            f"{mtf_sr_idx_block}\n\n"
            f"{cvd_block}\n\n"
            f"📋 <b>Факторы:</b>\n"
            f"{factors_block}\n\n"
            f"👇 <i>Посмотри график по кнопке ниже и нажми «🎯 Взять в сделку», если подтверждаешь вход!</i>"
        )

    reasons_list = sig["block_reasons"] or [f"Недостаточно перевеса для авто-сигнала (набрано {abs(sig['score'])} из {MIN_SCORE_FOR_ENTRY})"]
    reasons_str = "\n".join(f"• ⚠️ {r}" for r in reasons_list)

    return (
        f"⏸ <b>ОБЗОР ИНСТРУМЕНТА (РЕЖИМ НАБЛЮДЕНИЯ)</b>\n"
        f"🏢 Инструмент: <b>{sig['name']} ({sig['ticker']})</b> | ТФ: <b>{TIMEFRAMES[sig['tf_key']]['btn']}</b>\n"
        f"💰 Цена: <b>{sig['price']} ₽</b> ({ch_emoji} {ch_sign}{change:.2f}%)\n"
        f"📐 Расчётный приоритет ({sig['calc_side']}): Вход <b>{sig['entry']} ₽</b> | TP <b>{sig['tp']} ₽</b> ({sig.get('tp_reason', 'по ATR/R:R')}) | SL <b>{sig['sl']} ₽</b>\n\n"
        f"{robot_activity_block}"
        f"{big_prints_block}"
        f"{minute_pressure_block}"
        f"{twap_block}"
        f"🛑 <b>Фильтры Снайпера:</b>\n"
        f"{reasons_str}\n\n"
        f"{mtf_sr_idx_block}\n\n"
        f"{cvd_block}\n\n"
    )


async def send_signal_response(target_message: Message, ticker: str, tf_key: str = "15m", user_id: int | None = None):
    sig = await get_signal_cached(ticker, tf_key)
    if not sig:
        if 0.0 < _LAST_AUTH_ERR_TS and (time.time() - _LAST_AUTH_ERR_TS) < 600:
            await target_message.answer(
                f"❌ Данные по <b>{ticker}</b> не получены: T-Invest API вернул 401/403 — "
                f"проверьте <code>T_INVEST_TOKEN</code> на хосте, где запущен бот "
                f"(токен отозван, просрочен или не задан; в логах ищите «авторизация T-Invest отклонена»).",
                reply_markup=get_main_keyboard(user_id=user_id),
                parse_mode="HTML",
            )
            return
        err = _LAST_ANALYZE_ERR.get((ticker.upper().strip(), tf_key))
        reason = ""
        if err and (time.time() - err[0]) < 600:
            reason = f"\n\n🔎 Последняя причина: <code>{err[1][:180].replace('<', '&lt;')}</code>"
        if 0.0 < _LAST_TLS_ERR_TS and (time.time() - _LAST_TLS_ERR_TS) < 600:
            reason += ("\n\n🔐 TLS: сертификат invest-public-api.tbank.ru не доверен на этом хосте (возможен перехват трафика). "
                       "Задайте <code>T_INVEST_CA_BUNDLE</code> (pem-bundle с корневым CA, напр. Минцифры) или <code>T_INVEST_PROXY</code>. "
                       "Проверку сертификата отключать нельзя.")
        await target_message.answer(
            f"❌ Акция <b>{ticker}</b> не найдена на Мосбирже или нет рыночных данных.{reason}"
            f"\nВ логах бота ищите «Ошибка анализа {ticker}» / «Каталог инструментов пуст».",
            reply_markup=get_main_keyboard(user_id=user_id),
            parse_mode="HTML",
        )
        return

    if sig.get("is_illiquid"):
        await target_message.answer(
            f"⚠️ Акция <b>{sig['name']} ({sig['ticker']})</b> заблокирована фильтром ликвидности.",
            reply_markup=get_main_keyboard(user_id=user_id),
            parse_mode="HTML",
        )
        return

    # Сделка НЕ добавляется автоматически при простом просмотре — решение принимает пользователь по кнопке
    caption = format_signal_caption(sig)
    kb = get_main_keyboard(active_ticker=sig["ticker"], active_tf=sig["tf_key"], user_id=user_id)
    await target_message.answer(caption, reply_markup=kb, parse_mode="HTML")


async def dispatch_auto_signal(sig: dict, now_ts: float):
    if (
        not sig
        or sig.get("is_illiquid")
        or not signal_data_is_live(sig, require_candle=True)
        or sig["verdict"] not in ("LONG", "SHORT")
        or sig["ticker"] == "IMOEX"
    ):
        return

    ticker = sig["ticker"]
    caption = format_signal_caption(sig, is_auto_alert=True)

    for u_id in list(AUTO_SIGNAL_SUBSCRIBERS.keys()):
        if ticker in TRACKED_SIGNALS.get(u_id, {}):
            continue
        if (now_ts - LAST_SIGNAL_TIME.get((u_id, ticker), 0)) <= SIGNAL_COOLDOWN_SECONDS:
            continue

        kb = get_main_keyboard(active_ticker=ticker, active_tf=sig["tf_key"], user_id=u_id)
        try:
            await bot.send_message(u_id, caption, reply_markup=kb, parse_mode="HTML")
            # Cooldown помечаем только после успешной отправки, иначе при ошибке сигнал «сгорит» на 40 минут
            LAST_SIGNAL_TIME[(u_id, ticker)] = now_ts
        except Exception as e:
            logging.error(f"Ошибка отправки авто-сигнала пользователю {u_id}: {e}")


async def dispatch_cvd_informant_alerts(sig: dict, now_ts: float):
    """Собирает новые CVD-сигналы по ТФ в одно компактное сообщение на тикер."""
    if not sig or sig.get("is_illiquid") or sig.get("ticker") == "IMOEX":
        return
    if not signal_data_is_live(sig):
        return
    if not AUTO_SIGNAL_SUBSCRIBERS:
        return

    ticker = sig["ticker"]
    mtf_cvd = sig.get("mtf_cvd", {})
    sr = sig.get("sr_levels", {})
    book = sig.get("book_liquidity", {}) or {}
    eligible_alerts: list[dict] = []

    # Сначала применяем прежние ограничения по свече и cooldown, но накапливаем
    # подходящие ТФ, чтобы вместо нескольких сообщений отправить один дайджест.
    for tf_check in INFORMANT_TIMEFRAMES:
        c_info = mtf_cvd.get(tf_check)
        if not c_info:
            continue
        abs_side = c_info.get("absorption_side") or c_info.get("pressure_side")
        alert_kind = "absorption" if c_info.get("absorption_side") else "pressure"
        if abs_side not in ("LONG", "SHORT"):
            continue

        alert_key = f"{ticker}_{tf_check}"
        candle_key = c_info.get("candle_key", "")
        if candle_key and LAST_CVD_ALERT_CANDLE.get(alert_key) == candle_key:
            continue
        if (now_ts - LAST_CVD_ALERT_TIME.get(alert_key, 0)) < CVD_ALERT_COOLDOWN:
            continue

        LAST_CVD_ALERT_CANDLE[alert_key] = candle_key
        LAST_CVD_ALERT_TIME[alert_key] = now_ts
        side_targets = sig.get("targets_by_side", {}).get(abs_side, sig)
        eligible_alerts.append({
            "tf": tf_check,
            "info": c_info,
            "side": abs_side,
            "targets": side_targets,
            "kind": alert_kind,
        })

        # Журнал по-прежнему хранит отдельную запись для каждого ТФ-сигнала.
        if CVD_STORE_ENABLED:
            await asyncio.to_thread(CVD_STORE.log_alert, {
                "ts_msk": datetime.now(MSK_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": ticker,
                "name": sig.get("name"),
                "tf": tf_check,
                "side": abs_side,
                "price": sig.get("price"),
                "change_pct": round(float(sig.get("change") or 0.0), 3),
                "eff_pct": round(float(c_info.get("delta_efficiency_6") or 0.0), 2),
                "cvd_lots": round(float(c_info.get("cum_delta_change_6") or 0.0), 1),
                "window_volume": round(float(c_info.get("window_volume_6") or 0.0), 1),
                "bar_delta": round(float(c_info.get("bar_delta") or 0.0), 1),
                "tape_cov_pct": round(float(c_info.get("tape_cov_pct") or 0.0), 1),
                "consistency": round(float(c_info.get("consistency_6") or 0.0), 2),
                "vol_ratio": round(float(c_info.get("vol_ratio") or 0.0), 2),
                "eff_ratio": round(float(c_info.get("efficiency_ratio") or 0.0), 3),
                "drift_pct": round(float(c_info.get("price_change_6_pct") or 0.0), 3),
                "range_pct": round(float(c_info.get("window_range_pct") or 0.0), 3),
                "atr_pct": round(float(c_info.get("atr_pct") or 0.0), 3),
                "res1": sr.get("res1_price"),
                "sup1": sr.get("sup1_price"),
                "poc": sr.get("poc"),
                "tp": side_targets.get("tp"),
                "sl": side_targets.get("sl"),
                "users": len(AUTO_SIGNAL_SUBSCRIBERS),
            })

    if not eligible_alerts:
        return

    tf_icons = {"5m": "⚡", "15m": "🔹", "30m": "🟠", "1h": "🕐", "4h": "🧭"}
    sides = {item["side"] for item in eligible_alerts}
    if sides == {"LONG"}:
        overview = "🟢 CVD указывает на скрытый набор"
    elif sides == {"SHORT"}:
        overview = "🔴 CVD указывает на скрытую раздачу"
    else:
        overview = "⚠️ На разных ТФ направления расходятся — смотри каждую строку отдельно"

    tf_lines = []
    low_coverage = False
    for item in eligible_alerts:
        tf_check = item["tf"]
        c_info = item["info"]
        side = item["side"]
        cov = float(c_info.get("tape_cov_pct", 0.0) or 0.0)
        coverage_min = float(c_info.get("coverage_min", CVD_MIN_TAPE_COVERAGE_PCT) or 0.0)
        low_coverage = low_coverage or cov < coverage_min
        side_icon = "🟢" if side == "LONG" else "🔴"
        eff = float(c_info.get("delta_efficiency_6", 0.0) or 0.0)
        threshold = float(c_info.get("threshold_pct", cvd_absorption_threshold(tf_check)))
        delta = c_info.get("cum_delta_change_6", 0.0)
        kind_note = " · 🐋 давление CVD/ATR" if item.get("kind") == "pressure" else ""
        tf_lines.append(
            f"• {tf_icons.get(tf_check, '▫️')} <b>{TIMEFRAMES[tf_check]['btn']} · {side_icon} {side}</b>{kind_note}: "
            f"изменение CVD за {CVD_WINDOW} свечей <b>{format_lots_delta(delta)}</b> "
            f"| перевес <b>{eff:+.1f}%</b> (порог >{threshold:.0f}%) | impact <b>{float(c_info.get('price_impact', 999.0)):.3f}</b> (≤{PRICE_IMPACT_MAX}) | лента {cov:.0f}%"
        )

    change = float(sig.get("change") or 0.0)
    lines = [
        f"📡 <b>СВОДКА CVD ПО ТАЙМФРЕЙМАМ — {sig.get('name', ticker)} ({ticker})</b>",
        overview,
        f"💰 Цена: <b>{sig.get('price')} ₽</b> ({change:+.2f}% за день)",
        "",
        *tf_lines,
    ]
    if low_coverage:
        lines.extend([
            "",
            "⚠️ Покрытие реальной лентой указано отдельно для каждого ТФ; на старших ТФ оно может быть низким, поэтому сигнал — оценочный.",
        ])

    bp = sig.get("big_prints") or {}
    if bp.get("detected"):
        bp_side_txt = "покупки" if bp.get("side") == "BUY" else "продажи"
        lines.extend([
            "",
            f"🐋 <b>Крупные принты за {BIG_TRADE_WINDOW_SECONDS} с:</b> {bp.get('big_count')} сделок ≥ {format_rub_volume(BIG_TRADE_MIN_RUB)}, "
            f"{bp_side_txt} нетто <b>{format_rub_volume(abs(float(bp.get('net_rub', 0.0))))}</b> "
            f"(доля объёма ленты окна {bp.get('share_of_window_rub', 0.0):.0f}%) — возможный крупный игрок, но лента анонимна.",
        ])

    mp = sig.get("minute_pressure") or {}
    if mp.get("detected"):
        mp_side_txt = "покупки" if mp.get("side") == "BUY" else "продажи"
        lines.extend([
            "",
            f"⏱ <b>Минутное давление:</b> нетто {mp_side_txt} <b>{format_rub_volume(abs(float(mp.get('net_rub') or 0.0)))}</b> за минуту "
            f"при движении цены {mp.get('move_pct', 0.0):+.3f}% (impact {mp.get('impact', 0.0):.0f}) — возможен крупный лимитный набор.",
        ])

    tw = sig.get("big_twap") or {}
    if tw.get("detected"):
        tw_side_txt = "покупки" if tw.get("side") == "BUY" else "продажи"
        lines.extend([
            "",
            f"⏲ <b>TWAP-паттерн крупных принтов:</b> {tw.get('count')}×{tw.get('qty')} лот. ({tw_side_txt}), "
            f"сумма {format_rub_volume(tw.get('total_rub') or 0.0)}, CV интервалов {tw.get('interval_cv', 0.0):.2f}.",
        ])

    ice = ICEBERG_STATE.get(ticker) or {}
    fresh_ev = [e for e in ice.get("events", []) if now_ts - e.get("ts", 0) < 180]
    if fresh_ev:
        ev = fresh_ev[-1]
        ice_side = "Bid" if ev.get("side") == "bid" else "Ask"
        lines.extend([
            "",
            f"🧊 <b>Возможный iceberg в стакане:</b> уровень {ice_side} {ev.get('price')} ₽ (~{format_lots_abs(ev.get('qty', 0))}) "
            f"исчез и восстановился (~{format_lots_abs(ev.get('recovered_qty', 0))}) за последние 3 мин — справочно, заявку могли снять вручную.",
        ])

    if sr:
        lines.extend([
            "",
            f"🧱 Уровни: сопротивление <b>{sr.get('res1_price')} ₽</b> | "
            f"поддержка <b>{sr.get('sup1_price')} ₽</b> | POC <b>{sr.get('poc')} ₽</b>",
        ])

    # Цели показаны отдельно для каждого направления, если ТФ не согласны между собой.
    for side in ("LONG", "SHORT"):
        if side not in sides:
            continue
        targets = sig.get("targets_by_side", {}).get(side, sig)
        tp_reason = targets.get("tp_reason", "по ATR/R:R")
        side_label = "LONG" if side == "LONG" else "SHORT"
        lines.append(
            f"🎯 {side_label}: TP <b>{targets.get('tp')} ₽</b> ({tp_reason}) "
            f"| SL <b>{targets.get('sl')} ₽</b>"
        )
        book_side = "ask" if side == "LONG" else "bid"
        book_label = "Ask" if side == "LONG" else "Bid"
        wall_price = book.get(f"{book_side}_wall_price")
        if wall_price:
            lines.append(
                f"📚 Встречный видимый объём {book_label}: <b>{wall_price:.4f} ₽</b> "
                f"(~{format_rub_volume(book.get(f'{book_side}_wall_rub', 0))}); "
                "снимок может измениться, заявки могут быть сняты."
            )

    lines.extend([
        "",
        "<i>Это не команда на вход: перед решением проверь график. CVD не определяет личности участников.</i>",
    ])
    informant_msg = "\n".join(lines)

    # Кнопки соответствуют именно тем ТФ, которые перечислены в дайджесте.
    informant_kb_rows = []
    for item in eligible_alerts:
        tf_check = item["tf"]
        tf_btn = TIMEFRAMES[tf_check]["btn"]
        informant_kb_rows.append([
            InlineKeyboardButton(
                text=f"📈 График {tf_btn}",
                callback_data=f"chart_{ticker}_{tf_check}",
            ),
            InlineKeyboardButton(
                text=f"📊 Разбор {tf_btn}",
                callback_data=f"tf_{ticker}_{tf_check}",
            ),
        ])

    trade_buttons = []
    for side in ("LONG", "SHORT"):
        item = next((entry for entry in eligible_alerts if entry["side"] == side), None)
        if item:
            tf_check = item["tf"]
            trade_buttons.append(InlineKeyboardButton(
                text=f"🎯 Взять {side} ({TIMEFRAMES[tf_check]['btn']})",
                callback_data=f"manual_track_{ticker}_{tf_check}_{side}",
            ))
    if trade_buttons:
        informant_kb_rows.append(trade_buttons)
    informant_kb = InlineKeyboardMarkup(inline_keyboard=informant_kb_rows)

    for u_id in list(AUTO_SIGNAL_SUBSCRIBERS.keys()):
        try:
            await bot.send_message(u_id, informant_msg, reply_markup=informant_kb, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Ошибка отправки CVD-сводки пользователю {u_id}: {e}")


async def dispatch_whale_confluence_alert(sig: dict, now_ts: float) -> None:
    """🐋🐋-алерт: одновременно >= WHALE_CONFLUENCE_MIN признаков крупняка по бумаге (cooldown на тикер)."""
    kinds = sig.get("whale_kinds") or whale_confluence_kinds(sig, now_ts)
    if len(kinds) < WHALE_CONFLUENCE_MIN:
        return
    t = sig.get("ticker")
    if not t or not signal_data_is_live(sig, now_ts=now_ts):
        return
    if now_ts - LAST_WHALE_ALERT.get(t, 0.0) < WHALE_ALERT_COOLDOWN:
        return
    LAST_WHALE_ALERT[t] = now_ts
    text = (
        f"🐋🐋 <b>СИЛЬНАЯ АКТИВНОСТЬ КРУПНЯКА: {sig.get('name')} ({t})</b> — {len(kinds)} признаков одновременно:\n"
        + "\n".join(f"• {k}" for k in kinds)
        + f"\n💰 Цена: <b>{float(sig.get('price') or 0.0):.2f} ₽</b> ({float(sig.get('change') or 0.0):+.2f}%)"
        + "\n⚠️ <i>Эвристика по анонимным данным — не доказательство участника; проверь график перед входом.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"📈 График {t}", callback_data=f"chart_{t}_15m"),
        InlineKeyboardButton(text=f"🔎 Разбор {t}", callback_data=f"ticker_{t}"),
    ]])
    for u_id in list(AUTO_SIGNAL_SUBSCRIBERS.keys()):
        try:
            await bot.send_message(u_id, text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    logging.info(f"🐋🐋 confluence {t}: {kinds}")


async def scan_market_sniper() -> list[dict]:
    """
    Полный скан watchlist. Защищён SCAN_LOCK: два пользователя, нажавшие «Пересканировать»
    одновременно, больше не удваивают нагрузку на API. Внутри — параллельные чанки по 4
    тикера и кэш (ttl=20 c), чтобы не дублировать работу фонового монитора.
    """
    tickers = [t for _, t in LIQUID_WATCHLIST]
    try:
        await asyncio.wait_for(SCAN_LOCK.acquire(), timeout=45)
    except asyncio.TimeoutError:
        logging.warning("Скан уже идёт — отдаю последние данные из кэша")
        cached = [v for (_, tf), (_, v) in list(SCAN_CACHE.items()) if tf == "15m"]
        return sorted(cached, key=lambda x: abs(x.get("score", 0)), reverse=True)[:8]

    try:
        results: list[dict] = []
        now_ts = time.time()
        for i in range(0, len(tickers), SCAN_BATCH_SIZE):
            chunk = tickers[i : i + SCAN_BATCH_SIZE]
            sigs = await asyncio.gather(
                *(get_signal_cached(t, "15m", ttl=20) for t in chunk),
                return_exceptions=True,
            )
            for sig in sigs:
                if isinstance(sig, BaseException):
                    logging.warning(f"Ошибка сканирования: {sig}")
                    continue
                if not sig or sig.get("is_illiquid"):
                    continue
                results.append(sig)
                await dispatch_cvd_informant_alerts(sig, now_ts)
                if sig.get("verdict") in ("LONG", "SHORT"):
                    await dispatch_auto_signal(sig, now_ts)
                await dispatch_whale_confluence_alert(sig, now_ts)
            await asyncio.sleep(0.1)

        results.sort(
            key=lambda x: (
                bool(x.get("ticker_live")) and any(v.get("absorption_side") or v.get("pressure_side") for v in x.get("mtf_cvd", {}).values()),
                x.get("verdict") in ("LONG", "SHORT"),
                abs(x.get("score", 0)),
            ),
            reverse=True,
        )
        return results
    finally:
        SCAN_LOCK.release()


async def iceberg_watcher_cycle(session, tickers: list[str], now_ts: float) -> None:
    """Снапшоты стаканов (по batch) + эвристика «стена исчезла и восстановилась» (возможный iceberg).

    Справочно: восстановление уровня могло быть и ручным снятием/перевыставлением заявки.
    """
    if not ICEBERG_ENABLED:
        return
    for ticker in tickers:
        if ticker in ILLIQUID_BLACKLIST:
            continue
        inst = INSTRUMENTS_CACHE.get(ticker)
        if not inst:
            continue
        data = await api_post("MarketDataService/GetOrderBook", {"instrumentId": inst["uid"], "depth": 20}, timeout=8)
        if not data:
            continue
        snap: dict[tuple[str, float], float] = {}
        for side_name, rows in (("bid", data.get("bids", [])), ("ask", data.get("asks", []))):
            for row in rows or []:
                p = quotation_to_float(row.get("price"))
                try:
                    q = float(row.get("quantity", 0) or 0)
                except (TypeError, ValueError):
                    q = 0.0
                if p and p > 0 and q > 0:
                    snap[(side_name, round(float(p), 4))] = q
        if not snap:
            continue
        lot_i = max(int(inst.get("lot", 1) or 1), 1)
        bm = compute_book_metrics(data.get("bids", []), data.get("asks", []), lot_i)
        bm["ts"] = now_ts
        BOOK_STATE[ticker] = bm
        st = ICEBERG_STATE.setdefault(ticker, {"events": [], "levels": {}, "last_check": 0.0})
        st["last_check"] = now_ts
        levels = st["levels"]
        for key in list(levels.keys()):
            lv = levels[key]
            if now_ts - lv.get("ts", 0) > ICEBERG_LEVEL_TTL_SEC:
                levels.pop(key, None)
                continue
            side_name, old_p = key
            old_qty = float(lv.get("qty", 0.0))
            lot = max(int(inst.get("lot", 1) or 1), 1)
            if old_qty < ICEBERG_MIN_LOTS or old_qty * lot * old_p < ICEBERG_MIN_WALL_RUB:
                levels.pop(key, None)
                continue
            cur = max(
                (q for (s2, p2), q in snap.items() if s2 == side_name and abs(p2 - old_p) <= old_p * 0.002),
                default=0.0,
            )
            # «исчезновение» ловим только у уровня, виденного >= ICEBERG_MIN_SEEN снапшотов,
            # иначе это обычное переставление котировок маркет-мейкером
            if int(lv.get("seen", 1)) < ICEBERG_MIN_SEEN:
                lv["seen"] = int(lv.get("seen", 1)) + 1
                lv["qty"] = max(old_qty, cur)
                lv["ts"] = now_ts
                continue
            if cur <= old_qty * ICEBERG_DROP_PCT and not lv.get("dropped"):
                lv["dropped"] = True
                lv["dropped_ts"] = now_ts
            elif cur >= old_qty * ICEBERG_RECOVER_PCT and lv.get("dropped"):
                st["events"].append({
                    "side": side_name, "price": old_p, "qty": old_qty,
                    "recovered_qty": cur, "ts": now_ts,
                })
                if len(st["events"]) > 20:
                    st["events"] = st["events"][-20:]
                lv["dropped"] = False
            lv["qty"] = max(old_qty, cur)
            lv["ts"] = now_ts
        for key, q in snap.items():
            side_name, p = key
            lot = max(int(inst.get("lot", 1) or 1), 1)
            if q >= ICEBERG_MIN_LOTS and q * lot * p >= ICEBERG_MIN_WALL_RUB and key not in levels:
                levels[key] = {"qty": q, "ts": now_ts, "dropped": False, "seen": 1}
        await asyncio.sleep(0.15)


async def ensure_futures_instrument(session, ticker: str):
    """Резолвит фьючерс по тикеру через FindInstrument (ShareBy — только акции). Кэшируется."""
    ticker = ticker.upper().strip()
    if ticker in INSTRUMENTS_CACHE:
        return INSTRUMENTS_CACHE[ticker]
    data = await api_post("InstrumentsService/FindInstrument", {"query": ticker, "limit": 10})
    if not isinstance(data, dict):
        return None
    for it in data.get("instruments", []) or []:
        if (it.get("ticker") or "").upper() == ticker and it.get("instrumentType") == "future":
            info = {
                "uid": it["uid"], "name": it.get("name", ticker), "lot": int(it.get("lot", 1) or 1),
                "min_price_increment": quotation_to_float(it.get("minPriceIncrement")) or 0.0, "is_future": True,
            }
            INSTRUMENTS_CACHE[ticker] = info
            UID_TO_TICKER[it["uid"]] = ticker
            return info
    return None


async def ri_futures_watcher(session, now_ts: float) -> None:
    """Лента ближайшего фьючерса на индекс MOEX (RI): крупные принты там — опережающий сигнал для акций.

    Эвристика: 1 пункт RI ≈ 1 ₽, считаем рубли как цена × лоты. Limit — тот же MarketDataService,
    отдельного доступа не требуется; если фьючерс не резолвится — тихо пропускаем.
    """
    global RI_STATE
    for t in RI_FUTURES_TICKERS:
        try:
            inst = await ensure_futures_instrument(session, t)
            if not inst:
                continue
            now_utc = datetime.now(timezone.utc)
            trades = await api_post("MarketDataService/GetLastTrades", {
                "instrumentId": inst["uid"],
                "from": (now_utc - timedelta(minutes=30)).isoformat(),
                "to": now_utc.isoformat(),
            }, timeout=10)
            if not isinstance(trades, dict):
                continue
            tape = prepare_tape(trades.get("trades", []))
            px = 0.0
            if tape and tape.get("count"):
                px = float(np.median(np.asarray(tape["price"], dtype=float)))
            if px <= 0:
                px = 1.0  # для RI 1 пункт ≈ 1 ₽
            bp = detect_big_prints(tape, px, lot=1, now_ts=now_ts)
            RI_STATE = {
                "ts": now_ts, "ticker": t, "price": px,
                "big_count": int(bp.get("big_count", 0)), "net_rub": float(bp.get("net_rub", 0.0) or 0.0),
                "detected": bool(bp.get("detected")), "side": bp.get("side"),
            }
            if bp.get("detected"):
                logging.info(f"RI {t}: крупные принты {bp.get('side')} нетто {float(bp.get('net_rub') or 0.0):.0f}, {bp.get('big_count')} шт. за 5 мин")
        except Exception as e:
            logging.warning(f"RI watcher {t}: {e}")


# =====================================================================
# 7. ЕДИНЫЙ ФОНОВЫЙ МОНИТОРИНГ (СДЕЛКИ + ИНФОРМАТОР 5 ТФ + КЭШ ВЕБА)
# =====================================================================
def _prune_runtime_dicts(now_ts: float) -> None:
    """Чистит служебные словари, иначе они растут бесконечно на длинной дистанции."""
    for k in [k for k, ts in LAST_SIGNAL_TIME.items() if (now_ts - ts) > 86400]:
        LAST_SIGNAL_TIME.pop(k, None)
    for k in [k for k, ts in LAST_CVD_ALERT_TIME.items() if (now_ts - ts) > 7 * 86400]:
        LAST_CVD_ALERT_TIME.pop(k, None)
        LAST_CVD_ALERT_CANDLE.pop(k, None)
    for t in [t for t, dq in PRICE_HISTORY.items() if not dq]:
        PRICE_HISTORY.pop(t, None)
    for t in [t for t, st in ICEBERG_STATE.items() if (now_ts - st.get("last_check", 0)) > 3600]:
        ICEBERG_STATE.pop(t, None)
    for t in [t for t, d in BOOK_STATE.items() if (now_ts - float(d.get("ts", 0) or 0.0)) > 2 * BOOK_STALE_SEC]:
        BOOK_STATE.pop(t, None)
    for t in [t for t, ts in LAST_WHALE_ALERT.items() if (now_ts - ts) > 7 * 86400]:
        LAST_WHALE_ALERT.pop(t, None)
    for st in ICEBERG_STATE.values():
        st["events"] = [e for e in st.get("events", []) if now_ts - e.get("ts", 0) < 600]
    _prune_scan_cache()



def strategy_side(key: str, sig: dict) -> str | None:
    """Сторона автовхода стратегии по сигналу (patch30b) или None, если условие не выполнено."""
    cvd = sig.get("cvd_data") or {}
    if key == "divergence":
        if cvd.get("pivot_bearish_div"):
            return "SHORT"   # VKCO-сценарий: памп при слабеющей дельте
        if cvd.get("pivot_bullish_div"):
            return "LONG"
        return None
    if key == "cvd_flow":
        side = cvd.get("absorption_side") or cvd.get("pressure_side")
        return side if side in ("LONG", "SHORT") else None
    if key in ("news_whale", "levels"):
        # Новостная стратегия & Охотник за крупным капиталом:
        # Проверяем биржевые молнии MOEX, аукционы, расширения лимитов риска + крупные принты >=1 млн ₽ и айсберги
        news_items = MARKET_NEWS_CACHE.get("items") or []
        ticker_upper = sig.get("ticker", "").upper()
        name_lower = (sig.get("name") or "").lower()
        has_news_trigger = False
        for n in news_items[:15]:
            t_lower = n.get("title", "").lower()
            if ticker_upper.lower() in t_lower or (len(name_lower) > 3 and name_lower in t_lower):
                has_news_trigger = True
                break
            if n.get("important") and ticker_upper in n.get("title", ""):
                has_news_trigger = True
                break

        whales = sig.get("iceberg_events") or []
        has_whale_buy = any(e.get("side") == "BUY" for e in whales)
        has_whale_sell = any(e.get("side") == "SELL" for e in whales)

        if has_news_trigger or has_whale_buy or has_whale_sell:
            bar_delta = float(cvd.get("bar_delta") or 0.0)
            cum_d = float(cvd.get("cum_delta_change_6") or 0.0)
            if (has_whale_buy or cum_d > 0 or bar_delta > 0) and not cvd.get("red_candle_lies"):
                return "LONG"
            if (has_whale_sell or cum_d < 0 or bar_delta < 0) and not cvd.get("green_candle_lies"):
                return "SHORT"
        return None
    return None


def maybe_auto_enter_strats(sig: dict, now_ts: float) -> bool:
    """Автовход виртуальных счетов стратегий по условию сигнала (patch30b). True, если стейт изменился."""
    if not STRATS_ENABLED or not sig or sig.get("is_illiquid") or not sig.get("is_live_market"):
        return False
    ticker = sig.get("ticker")
    if not ticker or ticker == "IMOEX" or ticker in ILLIQUID_BLACKLIST:
        return False
    changed = False
    targets = sig.get("targets_by_side") or {}
    share = STRAT_DEPOSIT_RUB                                 # отдельный независимый депозит 10 млн ₽ на счёт
    per_pos = share / max(1, STRAT_MAX_POSITIONS)               # ровно 2 млн ₽ на позицию (5 шт)
    for key, st in STRATS.items():
        uid = st["uid"]
        side = strategy_side(key, sig)
        if side not in ("LONG", "SHORT"):
            continue
        user_sigs = TRACKED_SIGNALS.setdefault(uid, {})
        if ticker in user_sigs or len(user_sigs) >= STRAT_MAX_POSITIONS:
            continue
        if now_ts - LAST_SIGNAL_TIME.get((uid, ticker), 0) <= SIGNAL_COOLDOWN_SECONDS:
            continue
        t = targets.get(side) or {}
        entry = float(t.get("entry") or sig.get("price") or 0.0)
        if entry <= 0:
            continue
        tp = float(t.get("tp") or (entry * 1.03 if side == "LONG" else entry * 0.97))
        sl = float(t.get("sl") or (entry * 0.985 if side == "LONG" else entry * 1.015))
        inst = INSTRUMENTS_CACHE.get(ticker) or {}
        lot = max(int(inst.get("lot", 1) or 1), 1)
        lots = max(1, int(per_pos / max(entry * lot, 1e-9)))
        user_sigs[ticker] = {
            "ticker": ticker, "name": sig.get("name") or ticker, "side": side,
            "entry": entry, "tp": tp, "sl": sl,
            "opened_at": datetime.now(MSK_TZ).strftime("%H:%M"),
            "partial_taken": False, "strategy": key,
            "amount_rub": round(per_pos, 0), "lots": lots, "lot": lot,
            "real_amount_rub": round(lots * lot * entry, 0),
        }
        LAST_SIGNAL_TIME[(uid, ticker)] = now_ts
        logging.info(f"стратегия {key} ({st['name']}): автовход {ticker} {side} @ {entry:.2f} (позиция ~{per_pos:,.0f} ₽)")
        changed = True
    return changed


async def _manage_tracked_signal(user_id: int, user_signals: dict, ticker: str, s_info: dict,
                                 cur_price: float, now_ts: float) -> bool:
    """Сопровождение одной ручной сделки (вызывается из цикла мониторинга по живой цене).

    Каскад (patch28): при преодолении >55% пути до TP фиксируем 50% остатка и SL→безубыток;
    по TP фиксируем ещё половину остатка (25% от первоначала, если полпути уже было) и остаток
    (25% или 50%) тянем в трейлинге, пока цена не ушла под стоп от экстремума и CVD за 6 свечей
    в нужную сторону; при остановке импульса остаток автозакрывается. Если трейлинг выключен
    (TRAIL_AFTER_PARTIAL=0) — по TP закрывается весь остаток. Возвращает True, если стейт изменился.
    """
    state_changed = False
    side, tp, sl, entry = s_info["side"], s_info["tp"], s_info["sl"], s_info["entry"]
    partial_taken = s_info.get("partial_taken", False)
    if "remaining_frac" not in s_info:  # миграция старых записей
        s_info["remaining_frac"] = 0.5 if partial_taken else 1.0
    remaining_frac = float(s_info["remaining_frac"])

    # --- Уведомление о приближении к Take-Profit (в шаге <= 0.35% от цели) ---
    if tp > 0 and not s_info.get("near_tp_alert_sent"):
        dist_tp_pct = ((tp - cur_price) / entry * 100.0) if side == "LONG" else ((cur_price - tp) / entry * 100.0)
        if 0 < dist_tp_pct <= 0.35:
            s_info["near_tp_alert_sent"] = True
            state_changed = True
            try:
                asyncio.create_task(bot.send_message(
                    user_id,
                    f"🎯 <b>ВНИМАНИЕ: {s_info.get('name', ticker)} ({ticker}) В ШАГЕ ОТ ТЕЙК-ПРОФИТА!</b>\n\n"
                    f"• Текущая цена: <b>{cur_price:.2f} ₽</b> ➔ Цель TP: <b>{tp:.2f} ₽</b>\n"
                    f"• До исполнения цели осталось всего: <b>{dist_tp_pct:.2f}%</b>!\n"
                    f"💡 <i>Рекомендуется подтянуть Stop-Loss в безубыток или активировать трейлинг.</i>",
                    parse_mode="HTML"
                ))
            except Exception:
                pass

    # --- Уведомление о приближении к Stop-Loss (в шаге <= 0.35% от стопа) ---
    if sl > 0 and not s_info.get("near_sl_alert_sent"):
        dist_sl_pct = ((cur_price - sl) / entry * 100.0) if side == "LONG" else ((sl - cur_price) / entry * 100.0)
        if 0 < dist_sl_pct <= 0.35:
            s_info["near_sl_alert_sent"] = True
            state_changed = True
            try:
                asyncio.create_task(bot.send_message(
                    user_id,
                    f"⚠️ <b>ВНИМАНИЕ: {s_info.get('name', ticker)} ({ticker}) ПРИБЛИЖАЕТСЯ К СТОП-ЛОССУ!</b>\n\n"
                    f"• Текущая цена: <b>{cur_price:.2f} ₽</b> ➔ Стоп SL: <b>{sl:.2f} ₽</b>\n"
                    f"• До стопа осталось: <b>{dist_sl_pct:.2f}%</b>\n"
                    f"🛡 <i>Контролируйте позицию или пересмотрите уровень риска.</i>",
                    parse_mode="HTML"
                ))
            except Exception:
                pass

    # --- Ступень 1: настраиваемый рубеж до TP (по умолч. >55%) — фиксация доли и SL в безубыток ---
    auto_part_enabled = bool(s_info.get("auto_partial_enabled", True)) and bool(AUTO_PARTIAL_ENABLED)
    trigger_ratio = float(s_info.get("partial_trigger_pct", AUTO_PARTIAL_TRIGGER_PCT)) / 100.0
    take_fraction = float(s_info.get("partial_take_pct", AUTO_PARTIAL_TAKE_PCT)) / 100.0

    if auto_part_enabled and take_fraction > 0 and not partial_taken and tp > 0:
        half_way_target = entry + (tp - entry) * trigger_ratio if side == "LONG" else entry - (entry - tp) * trigger_ratio
        hit_half = (side == "LONG" and cur_price >= half_way_target) or (side == "SHORT" and cur_price <= half_way_target)
        if hit_half:
            half_move_pct = abs(half_way_target - entry) / entry * 100 if entry > 0 else 0.0
            gain = half_move_pct * take_fraction
            stats = get_user_stats(user_id)
            leverage = float(s_info.get("leverage") or 1.0)
            pos_rub = float(s_info.get("real_amount_rub") or s_info.get("amount_rub") or 0.0)
            pnl_rub = (pos_rub * take_fraction * (half_move_pct / 100.0)) if pos_rub > 0 else (position_amount_rub() * take_fraction * (half_move_pct / 100.0))
            dep = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 1.0
            stats["compound_mult"] *= (1.0 + pnl_rub / dep)
            net_pct_val = (stats["compound_mult"] - 1.0) * 100.0
            s_info["remaining_frac"] = max(0.0, remaining_frac * (1.0 - take_fraction))
            s_info["partial_taken"] = True
            s_info["sl"] = entry
            state_changed = True
            lev_str = f" [плечо {leverage:.1f}x: +{half_move_pct * leverage:.2f}%]" if leverage > 1.05 else ""
            rub_str = f" ({pnl_rub:+,.0f} ₽)" if pos_rub > 0 else ""
            add_history_entry(user_id, f"📌 {ticker} ({side}) автофиксация {take_fraction*100:.0f}% позиции +{half_move_pct:.2f}%{lev_str}{rub_str} [безубыток]")
            try:
                await bot.send_message(
                    user_id,
                    f"📌 <b>ЧАСТИЧНАЯ ФИКСАЦИЯ {take_fraction*100:.0f}% ПОЗИЦИИ ({ticker} | {side})!</b>\n\n"
                    f"• Цена прошла >{trigger_ratio*100:.0f}% пути до TP: <b>{cur_price:.2f} ₽</b> (цель рубежа {half_way_target:.2f} ₽)\n"
                    f"• Зафиксировано {take_fraction*100:.0f}% позиции: <b>+{half_move_pct:.2f}%</b>{rub_str}\n"
                    f"• 🛡 <b>SL перенесён в безубыток: {entry} ₽</b> | остаток {s_info['remaining_frac'] * 100:.0f}% ждёт TP/трейлинг\n"
                    f"💰 Накопленный результат (сложный %): <b>{net_pct_val:+.2f}%</b>\n" + portfolio_line(user_id),
                    parse_mode="HTML",
                )
            except Exception:
                pass
            partial_taken = True
            remaining_frac = float(s_info["remaining_frac"])

    # --- Трейлинг остатка (активен только после TP, patch27) ---
    trail_on = bool(TRAIL_AFTER_PARTIAL) and bool(s_info.get("tp_trailed"))
    trail_exit = False
    if trail_on:
        if side == "LONG":
            old_ext = float(s_info.get("trail_max") or 0.0)
            t_ext = max(old_ext, cur_price)
            if t_ext != old_ext:
                s_info["trail_max"] = t_ext
                state_changed = True
            t_stop = t_ext * (1.0 - TRAIL_DROP_PCT / 100.0)
        else:
            old_ext = float(s_info.get("trail_min") or cur_price)
            t_ext = min(old_ext, cur_price)
            if t_ext != old_ext:
                s_info["trail_min"] = t_ext
                state_changed = True
            t_stop = t_ext * (1.0 + TRAIL_DROP_PCT / 100.0)
        s_info["trail_stop"] = t_stop
        sig_now = WEB_SCAN_CACHE.get(ticker) or {}
        cvd6 = (sig_now.get("cvd") or {}).get("cum_delta_change_6")
        if cvd6 is None:
            mom_ok = True
        else:
            mom_ok = (cvd6 > TRAIL_CVD_MIN_LOTS) if side == "LONG" else (cvd6 < -TRAIL_CVD_MIN_LOTS)
        trail_exit = (not mom_ok) or (side == "LONG" and cur_price <= t_stop) or (side == "SHORT" and cur_price >= t_stop)

        # --- Ступень 1b: Каскадные тейк-профиты (Multi-Take-Profit) ---
    tps_list = s_info.get("take_profits")
    if tps_list and isinstance(tps_list, list):
        for idx_tp, tp_item in enumerate(tps_list, 1):
            if tp_item.get("hit"):
                continue
            tp_price = float(tp_item.get("price") or 0.0)
            if tp_price <= 0:
                continue
            hit_this = (side == "LONG" and cur_price >= tp_price) or (side == "SHORT" and cur_price <= tp_price)
            if hit_this:
                tp_pct = float(tp_item.get("pct") or 50.0)
                frac_to_close = min(remaining_frac, (tp_pct / 100.0))
                move_pct = abs(tp_price - entry) / entry * 100 if entry > 0 else 0.0
                stats = get_user_stats(user_id)
                leverage = float(s_info.get("leverage") or 1.0)
                pos_rub = float(s_info.get("real_amount_rub") or s_info.get("amount_rub") or 0.0)
                pnl_rub = (pos_rub * frac_to_close * (move_pct / 100.0)) if pos_rub > 0 else (position_amount_rub() * frac_to_close * (move_pct / 100.0))
                pnl_margin_pct = move_pct * leverage
                dep = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 1.0
                stats["compound_mult"] *= (1.0 + pnl_rub / dep)
                net_pct_val = (stats["compound_mult"] - 1.0) * 100.0
                tp_item["hit"] = True
                s_info["remaining_frac"] = max(0.0, remaining_frac - frac_to_close)
                remaining_frac = float(s_info["remaining_frac"])
                s_info["sl"] = entry  # переносим в безубыток
                s_info["partial_taken"] = True
                state_changed = True

                lev_str = f" [плечо {leverage:.1f}x: +{pnl_margin_pct:.2f}%]" if leverage > 1.05 else ""
                rub_str = f" ({pnl_rub:+,.0f} ₽)" if pos_rub > 0 else ""
                add_history_entry(user_id, f"🎯 {ticker} ({side}) взят TP{idx_tp} {tp_price:.2f} ₽: фикс {tp_pct:.0f}% позиции +{move_pct:.2f}%{lev_str}{rub_str} [Б/У]")
                try:
                    asyncio.create_task(bot.send_message(
                        user_id,
                        f"🎯 <b>ВЗЯТ ТЕЙК-ПРОФИТ TP{idx_tp} ({ticker} | {side})!</b>\n\n"
                        f"• Цель: <b>{tp_price:.2f} ₽</b> (зафиксировано <b>{tp_pct:.0f}%</b> позиции: +{move_pct:.2f}%){rub_str}\n"
                        f"• 🛡 <b>Стоп перенесён в безубыток: {entry:.2f} ₽</b>\n"
                        f"• Остаток позиции: <b>{remaining_frac * 100:.0f}%</b>\n"
                        f"💰 Накопленный результат: <b>{net_pct_val:+.2f}%</b>",
                        parse_mode="HTML"
                    ))
                except Exception:
                    pass

                # Если позиция исчерпана или все TP взяты
                if remaining_frac <= 0.05 or all(t.get("hit") for t in tps_list):
                    del user_signals[ticker]
                    LAST_SIGNAL_TIME[(user_id, ticker)] = now_ts
                    stats["wins"] += 1
                    await save_bot_state(force=True)
                    return True

    hit_tp = (tp > 0) and ((side == "LONG" and cur_price >= tp) or (side == "SHORT" and cur_price <= tp))
    hit_sl = (sl > 0) and ((side == "LONG" and cur_price <= sl) or (side == "SHORT" and cur_price >= sl))

    # --- Ступень 2: TP — фиксируем половину остатка, остальное в трейлинг (или закрываем при выкл. трейлинге) ---
    if hit_tp and not s_info.get("tp_trailed"):
        move_pct = abs(tp - entry) / entry * 100 if entry > 0 else 0.0
        stats = get_user_stats(user_id)
        if TRAIL_AFTER_PARTIAL:
            gain_tp = move_pct * remaining_frac * 0.5   # половина остатка: 50% от первоначала или 25%
            stats["compound_mult"] *= (1.0 + gain_tp / 100.0)
            net_pct_val = (stats["compound_mult"] - 1.0) * 100.0
            s_info["remaining_frac"] = remaining_frac * 0.5
            if not partial_taken:
                s_info["sl"] = entry
            s_info["partial_taken"] = True
            s_info["tp_trailed"] = True
            if side == "LONG":
                s_info["trail_max"] = cur_price
                s_info["trail_stop"] = cur_price * (1.0 - TRAIL_DROP_PCT / 100.0)
            else:
                s_info["trail_min"] = cur_price
                s_info["trail_stop"] = cur_price * (1.0 + TRAIL_DROP_PCT / 100.0)
            state_changed = True
            add_history_entry(user_id, f"🎯 {ticker} ({side}) фиксация по TP +{gain_tp:.2f}% (остаток {s_info['remaining_frac'] * 100:.0f}% в трейлинге)")
            try:
                await bot.send_message(
                    user_id,
                    f"🎯 <b>TP {ticker} ({side}) достигнут: фиксируем ещё {gain_tp:.2f}% (половина остатка)!</b>\n\n"
                    f"• Остаток <b>{s_info['remaining_frac'] * 100:.0f}%</b> первоначальной позиции переведён в трейлинг: стоп <b>{s_info['trail_stop']:.2f} ₽</b> (−{TRAIL_DROP_PCT:.1f}% от текущей цены)\n"
                    f"• Держим, пока цена не ушла под стоп и CVD за 6 свечей в нужную сторону; при остановке импульса — автозакрытие остатка.\n"
                    f"• 🛡 SL в безубытке: <b>{entry} ₽</b>\n"
                    f"💰 Накопленный результат (сложный %): <b>{net_pct_val:+.2f}%</b>\n" + portfolio_line(user_id),
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return state_changed
        # трейлинг выключен — закрываем весь остаток по TP
        del user_signals[ticker]
        LAST_SIGNAL_TIME[(user_id, ticker)] = now_ts
        stats["wins"] += 1
        leverage = float(s_info.get("leverage") or 1.0)
        pos_rub = float(s_info.get("real_amount_rub") or s_info.get("amount_rub") or 0.0)
        pnl_rub = (pos_rub * remaining_frac * (move_pct / 100.0)) if pos_rub > 0 else (position_amount_rub() * remaining_frac * (move_pct / 100.0))
        pnl_margin_pct = move_pct * leverage
        dep = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 1.0
        stats["compound_mult"] *= (1.0 + pnl_rub / dep)
        net_pct_val = (stats["compound_mult"] - 1.0) * 100.0
        lev_str = f" [плечо {leverage:.1f}x: +{pnl_margin_pct:.2f}%]" if leverage > 1.05 else ""
        rub_str = f" ({pnl_rub:+,.0f} ₽)" if pos_rub > 0 else ""
        add_history_entry(user_id, f"✅ {ticker} ({side}) +{move_pct:.2f}%{lev_str}{rub_str}")
        msg = (
            f"✅ <b>СДЕЛКА ЗАКРЫТА ПО TAKE-PROFIT! (+{move_pct * remaining_frac:.2f}%)</b>\n\n"
            f"🏢 Акция: <b>{s_info['name']} ({ticker})</b> | {side}\n"
            f"🔹 Вход: <b>{entry} ₽</b> ➔ Цель: <b>{tp} ₽</b>\n"
            f"📊 <b>Винрейт: {calc_winrate_str(user_id)}</b>\n"
            f"💰 Накопленный результат (сложный %): <b>{net_pct_val:+.2f}%</b>\n" + portfolio_line(user_id)
        )
        try:
            await bot.send_message(user_id, msg, reply_markup=get_main_keyboard(active_ticker=ticker, user_id=user_id), parse_mode="HTML")
        except Exception:
            pass
        return True

    if trail_on and trail_exit:
        # автозакрытие остатка по трейлингу: цена ушла под стоп от экстремума или CVD сменил знак
        del user_signals[ticker]
        LAST_SIGNAL_TIME[(user_id, ticker)] = now_ts
        stats = get_user_stats(user_id)
        move_pct = abs(cur_price - entry) / entry * 100 if entry > 0 else 0.0
        won = (side == "LONG" and cur_price > entry) or (side == "SHORT" and cur_price < entry)
        rem_gain = move_pct * remaining_frac
        if won:
            stats["wins"] += 1
            leverage = float(s_info.get("leverage") or 1.0)
            pos_rub = float(s_info.get("real_amount_rub") or s_info.get("amount_rub") or 0.0)
            pnl_rub = (pos_rub * remaining_frac * (move_pct / 100.0)) if pos_rub > 0 else (position_amount_rub() * remaining_frac * (move_pct / 100.0))
            pnl_margin_pct = move_pct * leverage
            dep = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 1.0
            stats["compound_mult"] *= (1.0 + pnl_rub / dep)
            net_pct_val = (stats["compound_mult"] - 1.0) * 100.0
            lev_str = f" [плечо {leverage:.1f}x: +{pnl_margin_pct:.2f}%]" if leverage > 1.05 else ""
            rub_str = f" ({pnl_rub:+,.0f} ₽)" if pos_rub > 0 else ""
            add_history_entry(user_id, f"🎯 {ticker} ({side}) трейлинг +{move_pct:.2f}%{lev_str}{rub_str} (остаток {remaining_frac * 100:.0f}%)")
            msg = (
                f"🎯 <b>ТРЕЙЛИНГ: остаток {remaining_frac * 100:.0f}% закрыт по {cur_price:.2f} ₽ (+{rem_gain:.2f}%)</b>\n\n"
                f"🏢 Акция: <b>{s_info['name']} ({ticker})</b> | {side}\n"
                f"🔹 Вход: <b>{entry} ₽</b> | экстр. трейлинга: <b>{(s_info.get('trail_max') or s_info.get('trail_min') or cur_price):.2f} ₽</b> | стоп: <b>{s_info.get('trail_stop', 0.0):.2f} ₽</b>\n"
                f"📊 <b>Винрейт: {calc_winrate_str(user_id)}</b>\n"
                f"💰 Накопленный результат (сложный %): <b>{net_pct_val:+.2f}%</b>\n" + portfolio_line(user_id)
            )
        else:
            stats["be"] += 1
            net_pct_val = (stats["compound_mult"] - 1.0) * 100.0
            add_history_entry(user_id, f"🎯 {ticker} ({side}) трейлинг — безубыток")
            msg = (
                f"🎯 <b>ТРЕЙЛИНГ: остаток {remaining_frac * 100:.0f}% закрыт в безубыток по {cur_price:.2f} ₽</b>\n\n"
                f"🏢 Акция: <b>{s_info['name']} ({ticker})</b> | {side}\n"
                f"🔹 Вход: <b>{entry} ₽</b> | экстр. трейлинга: <b>{(s_info.get('trail_max') or s_info.get('trail_min') or cur_price):.2f} ₽</b>\n"
                f"📊 <b>Винрейт: {calc_winrate_str(user_id)}</b>\n"
                f"💰 Накопленный результат (сложный %): <b>{net_pct_val:+.2f}%</b>\n" + portfolio_line(user_id)
            )
        try:
            await bot.send_message(user_id, msg, reply_markup=get_main_keyboard(active_ticker=ticker, user_id=user_id), parse_mode="HTML")
        except Exception:
            pass
        return True

    if hit_tp and trail_on:
        # TP уже пройден в трейлинге — остаток не закрываем, тянем дальше, пока жив импульс
        return state_changed

    if hit_tp or hit_sl:
        # закрытие остатка по TP (без трейлинга) либо по SL/безубыток
        del user_signals[ticker]
        LAST_SIGNAL_TIME[(user_id, ticker)] = now_ts
        stats = get_user_stats(user_id)
        fill_price = tp if hit_tp else sl
        move_pct = abs(fill_price - entry) / entry * 100 if entry > 0 else 0.0
        is_be_hit = (not hit_tp) and (abs(sl - entry) / max(entry, 1e-9) < 0.0005)

        if hit_tp:
            stats["wins"] += 1
            leverage = float(s_info.get("leverage") or 1.0)
            pos_rub = float(s_info.get("real_amount_rub") or s_info.get("amount_rub") or 0.0)
            pnl_rub = (pos_rub * remaining_frac * (move_pct / 100.0)) if pos_rub > 0 else (position_amount_rub() * remaining_frac * (move_pct / 100.0))
            pnl_margin_pct = move_pct * leverage
            dep = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 1.0
            stats["compound_mult"] *= (1.0 + pnl_rub / dep)
            net_pct_val = (stats["compound_mult"] - 1.0) * 100.0
            lev_str = f" [плечо {leverage:.1f}x: +{pnl_margin_pct:.2f}%]" if leverage > 1.05 else ""
            rub_str = f" ({pnl_rub:+,.0f} ₽)" if pos_rub > 0 else ""
            add_history_entry(user_id, f"✅ {ticker} ({side}) +{move_pct:.2f}%{lev_str}{rub_str}")
            be_note = f" | 🤝 безубытков: {stats.get('be', 0)}" if stats.get("be") else ""
            msg = (
                f"✅ <b>СДЕЛКА ЗАКРЫТА ПО TAKE-PROFIT! (+{move_pct:.2f}%)</b>\n\n"
                f"🏢 Акция: <b>{s_info['name']} ({ticker})</b> | {side}\n"
                f"🔹 Вход: <b>{entry} ₽</b> ➔ Цель: <b>{fill_price} ₽</b>\n"
                f"📊 <b>Винрейт: {calc_winrate_str(user_id)}</b>{be_note}\n"
                f"💰 Накопленный результат (сложный %): <b>{net_pct_val:+.2f}%</b>\n" + portfolio_line(user_id)
            )
        elif is_be_hit:
            stats["be"] += 1
            net_pct_val = (stats["compound_mult"] - 1.0) * 100.0
            add_history_entry(user_id, f"🤝 {ticker} ({side}) безубыток (0.00%)")
            msg = (
                f"🤝 <b>СДЕЛКА ЗАКРЫТА В БЕЗУБЫТОК</b>\n\n"
                f"🏢 Акция: <b>{s_info['name']} ({ticker})</b> | {side}\n"
                f"🔹 Вход: <b>{entry} ₽</b> ➔ Выход: <b>{fill_price} ₽</b>\n"
                f"📊 <b>Винрейт: {calc_winrate_str(user_id)}</b>\n"
                f"💰 Накопленный результат (сложный %): <b>{net_pct_val:+.2f}%</b>\n" + portfolio_line(user_id)
            )
        else:
            stats["losses"] += 1
            leverage = float(s_info.get("leverage") or 1.0)
            pos_rub = float(s_info.get("real_amount_rub") or s_info.get("amount_rub") or 0.0)
            pnl_rub = (pos_rub * remaining_frac * (move_pct / 100.0)) if pos_rub > 0 else (position_amount_rub() * remaining_frac * (move_pct / 100.0))
            pnl_margin_pct = move_pct * leverage
            dep = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 1.0
            stats["compound_mult"] = max(0.0, stats["compound_mult"] * (1.0 - pnl_rub / dep))
            net_pct_val = (stats["compound_mult"] - 1.0) * 100.0
            lev_str = f" [плечо {leverage:.1f}x: -{pnl_margin_pct:.2f}%]" if leverage > 1.05 else ""
            rub_str = f" (-{pnl_rub:,.0f} ₽)" if pos_rub > 0 else ""
            add_history_entry(user_id, f"🛡 {ticker} ({side}) -{move_pct:.2f}%{lev_str}{rub_str}")
            msg = (
                f"🛡 <b>СРАБОТАЛ СТОП-ЛОСС (-{move_pct:.2f}%)</b>\n\n"
                f"🏢 Акция: <b>{s_info['name']} ({ticker})</b> | {side}\n"
                f"🔹 Вход: <b>{entry} ₽</b> ➔ Стоп: <b>{fill_price} ₽</b>\n"
                f"📊 <b>Винрейт: {calc_winrate_str(user_id)}</b>\n"
                f"💰 Накопленный результат (сложный %): <b>{net_pct_val:+.2f}%</b>\n" + portfolio_line(user_id)
            )
        try:
            await bot.send_message(user_id, msg, reply_markup=get_main_keyboard(active_ticker=ticker, user_id=user_id), parse_mode="HTML")
        except Exception:
            pass
        return True

    return state_changed


async def realtime_market_monitor():
    watchlist_idx = 0
    last_cleanup_date = datetime.now(MSK_TZ).date()
    last_instr_reload = 0.0
    iceberg_idx = 0
    last_iceberg_check = 0.0
    last_ri_check = 0.0
    last_whale_mark = 0.0
    _last_force_save = 0.0  # patch34

    while True:
        try:
            await asyncio.wait_for(STOP_EVENT.wait(), timeout=15)
            logging.info("Фоновый монитор остановлен")
            return
        except asyncio.TimeoutError:
            pass

        # patch34: force-сохран каждые STATE_FORCE_SAVE_EVERY_SEC — облачный бэкап (bak_N)
        # остаётся свежим даже если процесс убьют SIGKILL-ом до сохранения при остановке
        _now_fs = time.time()
        if _now_fs - _last_force_save >= STATE_FORCE_SAVE_EVERY_SEC:
            _last_force_save = _now_fs
            await save_bot_state(force=True)

        cur_date_msk = datetime.now(MSK_TZ).date()
        if cur_date_msk != last_cleanup_date:
            last_cleanup_date = cur_date_msk
            cleaned_any = False
            for uid, st in list(USER_STATS.items()):
                before_len = len(st.get("history", []))
                st["history"] = prune_old_history_items(st.get("history", []))
                if len(st["history"]) != before_len:
                    cleaned_any = True
            if cleaned_any:
                await save_bot_state()

        if not UID_TO_TICKER:
            # Каталог инструментов не загрузился на старте (API был недоступен) —
            # повторяем загрузку раз в минуту вместо бесконечного простоя.
            now_ts0 = time.time()
            if now_ts0 - last_instr_reload >= 60:
                last_instr_reload = now_ts0
                logging.warning("Каталог инструментов пуст — повторная загрузка списка акций MOEX")
                await load_all_moex_shares()
            continue

        # Обновляем единый кэш сканера по батчам бумаг (4 тикера за цикл)
        batch_size = 4
        total_wl = len(LIQUID_WATCHLIST)
        batch_tickers = [
            LIQUID_WATCHLIST[(watchlist_idx + i) % total_wl][1]
            for i in range(batch_size)
        ]
        watchlist_idx = (watchlist_idx + batch_size) % total_wl

        if not is_moex_trading_hours():
            # Если биржа закрыта, обновляем только кэш для веб-терминала раз в цикл
            for ticker in batch_tickers:
                if ticker not in WEB_SCAN_CACHE:
                    await get_signal_cached(ticker, "15m")
                    await asyncio.sleep(0.2)
            continue

        data = await api_post(
            "MarketDataService/GetLastPrices",
            {"instrumentId": list(UID_TO_TICKER.keys()), "lastPriceType": "LAST_PRICE_EXCHANGE"},
            timeout=15,
        )
        if not data:
            continue

        now_ts = time.time()
        live_prices: dict[str, float] = {}
        for lp in data.get("lastPrices", []):
            ticker = UID_TO_TICKER.get(lp.get("instrumentUid"))
            price = quotation_to_float(lp.get("price"))
            if ticker and price and price > 0:
                live_prices[ticker] = price

        state_changed = False
        # patch: исполнение отложенных ордеров на открытии биржи (гэп-фильтр)
        if PENDING_OPEN_ORDERS and live_prices:
            for p_tk, p_ord in list(PENDING_OPEN_ORDERS.items()):
                p_cur_price = live_prices.get(p_tk)
                if not p_cur_price or p_cur_price <= 0:
                    continue
                ref_p = float(p_ord.get("ref_price") or p_cur_price)
                max_gap = float(p_ord.get("max_gap_pct", 1.0))
                gap_pct = abs(p_cur_price - ref_p) / max(ref_p, 1e-6) * 100.0

                p_uid = int(p_ord.get("user_id") or _get_primary_user_id())
                p_side = str(p_ord.get("side", "LONG")).upper()

                if max_gap <= 0 or gap_pct <= max_gap:
                    dep_p = float(p_ord.get("dep_pct") or 20.0)
                    use_l = bool(p_ord.get("use_leverage", True))
                    _inst = INSTRUMENTS_CACHE.get(p_tk) or {}
                    dlong = float(_inst.get("dlong") or 0.0)
                    dshort = float(_inst.get("dshort") or 0.0)
                    lev = (round(1.0 / dlong, 2) if dlong > 0 else 1.0) if p_side == "LONG" else (round(1.0 / dshort, 2) if dshort > 0 else 1.0)
                    leverage = lev if use_l else 1.0

                    dep_tot = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 10000000.0
                    margin_rub = max(1000.0, dep_tot * (dep_p / 100.0))
                    position_power_rub = margin_rub * leverage

                    lot_s = max(int(_inst.get("lot", 1) or 1), 1)
                    one_lot_rub = max(p_cur_price * lot_s, 1e-6)
                    target_lots = max(1, int(position_power_rub / one_lot_rub))
                    real_amount_rub = target_lots * lot_s * p_cur_price

                    c_tp = float(p_ord.get("custom_tp") or 0.0)
                    c_sl = float(p_ord.get("custom_sl") or 0.0)
                    tp_price = c_tp if c_tp > 0 else (p_cur_price * 1.025 if p_side == "LONG" else p_cur_price * 0.975)
                    sl_price = c_sl if c_sl > 0 else (p_cur_price * 0.985 if p_side == "LONG" else p_cur_price * 1.015)

                    u_sigs = TRACKED_SIGNALS.setdefault(p_uid, {})
                    u_sigs[p_tk] = {
                        "ticker": p_tk,
                        "name": _inst.get("name") or p_tk,
                        "side": p_side,
                        "entry": round(p_cur_price, 4),
                        "tp": round(tp_price, 4),
                        "sl": round(sl_price, 4),
                        "opened_at": datetime.now(MSK_TZ).strftime("%H:%M"),
                        "partial_taken": False,
                        "amount_rub": round(margin_rub, 0),
                        "margin_rub": round(margin_rub, 0),
                        "real_amount_rub": round(real_amount_rub, 0),
                        "use_leverage": bool(use_leverage and leverage > 1.05),
                "leverage": round(leverage if use_leverage else 1.0, 2),
                        "dep_pct": round(dep_p, 1),
                        "lots": target_lots,
                        "lot": lot_s,
                        "auto_partial_enabled": bool(p_ord.get("auto_partial", True)),
                        "partial_take_pct": float(AUTO_PARTIAL_TAKE_PCT),
                        "partial_trigger_pct": float(AUTO_PARTIAL_TRIGGER_PCT),
                    }
                    del PENDING_OPEN_ORDERS[p_tk]
                    state_changed = True
                    add_history_entry(p_uid, f"⚡ {p_tk} ({p_side}) автозаход на открытии: {p_cur_price:.2f} ₽ (гэп {gap_pct:.2f}% ≤ {max_gap:.1f}%)")
                    try:
                        asyncio.create_task(bot.send_message(
                            p_uid,
                            f"⚡ <b>АВТОЗАХОД НА ОТКРЫТИИ БИРЖИ СРАБОТАЛ!</b>\n\n"
                            f"🏢 Бумага: <b>{p_tk}</b> | Сторона: <b>{p_side}</b>\n"
                            f"🔹 Вход: <b>{p_cur_price:.2f} ₽</b> (гэп <b>{gap_pct:.2f}%</b> ≤ лимита {max_gap:.1f}%)\n"
                            f"🎯 TP: <b>{tp_price:.2f} ₽</b> | 🛡 SL: <b>{sl_price:.2f} ₽</b>\n"
                            f"💰 Маржа: <b>{margin_rub:,.0f} ₽</b> (плечо {leverage:.1f}x ➔ {real_amount_rub:,.0f} ₽)",
                            parse_mode="HTML"
                        ))
                    except Exception:
                        pass
                else:
                    del PENDING_OPEN_ORDERS[p_tk]
                    state_changed = True
                    add_history_entry(p_uid, f"⚠️ {p_tk} ({p_side}) отменён вход на открытии: гэп {gap_pct:.2f}% > лимита {max_gap:.1f}%")
                    try:
                        asyncio.create_task(bot.send_message(
                            p_uid,
                            f"⚠️ <b>ВХОД НА ОТКРЫТИИ ОТМЕНЁН (ЗАЩИТА ОТ ГЭПА)!</b>\n\n"
                            f"🏢 Бумага: <b>{p_tk}</b>\n"
                            f"• Цена открытия: <b>{p_cur_price:.2f} ₽</b> (гэп <b>{gap_pct:.2f}%</b>)\n"
                            f"• Ваш лимит гэпа: <b>{max_gap:.1f}%</b>\n"
                            f"🛡 Ордер отменён, депозит защищён от проскальзывания.",
                            parse_mode="HTML"
                        ))
                    except Exception:
                        pass


        # Сопровождение открытых пользователем сделок: TP → фиксация 50% + трейлинг остатка, SL/безубыток (patch27)
        for user_id, user_signals in list(TRACKED_SIGNALS.items()):
            for ticker, s_info in list(user_signals.items()):
                cur_price = live_prices.get(ticker)
                if not cur_price:
                    continue
                if await _manage_tracked_signal(user_id, user_signals, ticker, s_info, cur_price, now_ts):
                    state_changed = True

        if state_changed:
            await save_bot_state(force=True)

        # Проверка импульсов + плановое сканирование 5 ТФ Информатора CVD
        for ticker in LIQUID_AUTOTRADE_TICKERS:
            price = live_prices.get(ticker)
            if not price or ticker in ILLIQUID_BLACKLIST:
                continue

            if ticker not in PRICE_HISTORY:
                PRICE_HISTORY[ticker] = deque()
            history = PRICE_HISTORY[ticker]
            history.append((now_ts, price))
            while history and (now_ts - history[0][0]) > SCAN_WINDOW_SECONDS:
                history.popleft()
            if len(history) < 2:
                continue

            old_ts, old_price = history[0]
            change_pct = ((price - old_price) / old_price) * 100

            waiting_users = [
                u_id
                for u_id, th in AUTO_SIGNAL_SUBSCRIBERS.items()
                if abs(change_pct) >= th
                and (now_ts - LAST_SIGNAL_TIME.get((u_id, ticker), 0)) > SIGNAL_COOLDOWN_SECONDS
                and ticker not in TRACKED_SIGNALS.get(u_id, {})
            ]
            if not waiting_users:
                continue

            sig = await get_signal_cached(ticker, "15m")
            if sig and not sig.get("is_illiquid"):
                await dispatch_cvd_informant_alerts(sig, now_ts)
                if sig.get("verdict") in ("LONG", "SHORT"):
                    await dispatch_auto_signal(sig, now_ts)
                await dispatch_whale_confluence_alert(sig, now_ts)

        # Плановый обход батча: один запрос analyze_stock_signal проверяет сразу 5m, 15m, 30m, 1h и 4h
        for ticker in batch_tickers:
            if ticker in ILLIQUID_BLACKLIST:
                continue

            sig = await get_signal_cached(ticker, "15m")
            if sig and not sig.get("is_illiquid"):
                await dispatch_cvd_informant_alerts(sig, now_ts)
                if sig.get("verdict") in ("LONG", "SHORT"):
                    await dispatch_auto_signal(sig, now_ts)
                await dispatch_whale_confluence_alert(sig, now_ts)
                if maybe_auto_enter_strats(sig, now_ts):
                    state_changed = True

            await asyncio.sleep(0.2)

        # Iceberg-вотчер: стаканы по кругу, ICEBERG_BATCH тикеров за заход (лимитируем нагрузку на API)
        if ICEBERG_ENABLED and is_moex_trading_hours() and (now_ts - last_iceberg_check) >= ICEBERG_WATCH_EVERY_SEC:
            last_iceberg_check = now_ts
            session = await get_session()
            batch = [LIQUID_WATCHLIST[(iceberg_idx + i) % total_wl][1] for i in range(ICEBERG_BATCH)]
            iceberg_idx = (iceberg_idx + ICEBERG_BATCH) % total_wl
            await iceberg_watcher_cycle(session, batch, now_ts)

        # Фьючерс RI: опережающий индикатор крупняка на рынке (в часы торгов)
        if RI_FUTURES_TICKERS and is_moex_trading_hours() and (now_ts - last_ri_check) >= RI_WATCH_EVERY_SEC:
            last_ri_check = now_ts
            try:
                await ri_futures_watcher(session, now_ts)
            except Exception as e:
                logging.warning(f"RI watcher: {e}")

        # Пункт 7: исходы событий крупняка по текущим ценам -> WHALE_STATS (в state/облако)
        if (now_ts - last_whale_mark) >= 60:
            last_whale_mark = now_ts
            try:
                n_marked = mark_whale_outcomes(live_prices, now_ts)
                if n_marked:
                    await save_bot_state()
            except Exception as e:
                logging.warning(f"whale mark: {e}")

        # Чистим разросшиеся словари (утечка памяти на длинной дистанции)
        _prune_runtime_dicts(now_ts)

        # Раз в CVD_FLUSH_EVERY_SEC сбрасываем накопленную ленту на диск
        if CVD_STORE_ENABLED and (now_ts - CVD_STORE.last_flush_ts) > CVD_FLUSH_EVERY_SEC:
            written = await asyncio.to_thread(CVD_STORE.flush)
            if written:
                logging.debug(f"CVD-хранилище: записано {written} свечей")
            if int(now_ts) % 3600 < 20:
                await asyncio.to_thread(CVD_STORE.prune)


# =====================================================================
# 8. РЕНДЕР ГРАФИКА В ОТДЕЛЬНОМ ПОТОКЕ (БЕЗ ЗАВИСАНИЙ EVENT LOOP)
# =====================================================================
def chart_cov_stats(df) -> tuple[np.ndarray, float]:
    """По свечам графика: маска свечей без реальной ленты и доля их объёма в %.

    tape_cov считается в apply_real_trades_delta_to_df из живой ленты + файла CVD-хранилища
    (hist); если за свечу в файле ничего нет и живое окно её не покрывает, tape_cov = 0 —
    такая свеча «оценочная» (дельта синтетическая, по форме свечи).
    """
    if df is None or df.empty:
        return np.zeros(0, dtype=bool), 100.0
    cov_arr = df["tape_cov"].to_numpy(dtype=float) if "tape_cov" in df.columns else np.zeros(len(df))
    low_cov_mask = cov_arr < (CHART_CVD_CANDLE_COV_PCT / 100.0)
    vol_arr = df["Volume"].to_numpy(dtype=float)
    tot_vol = float(vol_arr.sum())
    low_vol_share = float(vol_arr[low_cov_mask].sum() / tot_vol * 100.0) if tot_vol > 0 else 100.0
    return low_cov_mask, low_vol_share


def _render_chart_sync(
    ticker: str,
    tf_key: str,
    df: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_1d: pd.DataFrame,
    raw_trades: list[dict],
    active_trade: dict | None,
    lot: int = 1,
) -> tuple[bytes, str]:
    """Синхронная функция отрисовки matplotlib, вызываемая через asyncio.to_thread."""
    try:
        # hist — накопленная из файла реальная лента, чтобы CVD на графике был настоящим
        hist = cvd_store_history(ticker, tf_key, df)
        df, _, _ = apply_real_trades_delta_to_df(df, raw_trades, tf_key, hist)

        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
        df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()

        df["bar_delta"] = df["delta"]
        df["cvd_open"] = df["cvd"].shift(1).fillna(0)
        df.loc[df["date_msk"] != df["date_msk"].shift(1), "cvd_open"] = 0.0
        df["cvd_close"] = df["cvd"]
        df["cvd_high"] = df[["cvd_open", "cvd_close"]].max(axis=1)
        df["cvd_low"] = df[["cvd_open", "cvd_close"]].min(axis=1)

        cur_price = float(df["Close"].iloc[-1])
        last_open = float(df["Open"].iloc[-1])

        # Тот же накопленный hist, что и на графике, иначе подпись CVD расходится с картинкой
        cvd_stats = calc_cvd_and_cum_delta(df, raw_trades, tf_key, hist=hist)
        # Низкое покрытие лентой -> CVD в основном синтетический: будем рисовать его приглушённо
        cvd_estimated = float(cvd_stats.get("tape_cov_pct", 0.0) or 0.0) < CHART_CVD_LOW_COV_PCT
        low_cov_mask, low_vol_share = chart_cov_stats(df)

        mtf_tmp = {}
        for k, d_f in ((tf_key, df), ("1h", df_1h), ("1d", df_1d)):
            e_r = compute_tf_emas(d_f)
            if e_r:
                mtf_tmp[k] = e_r
        sr_info = compute_sr_levels(cur_price, df, df_1h, df_1d, mtf_tmp)

        num_bins = 35
        price_min = float(df["Low"].min())
        price_max = float(df["High"].max())
        vp_levels = []
        vp_colors = []
        vp_widths = []
        poc_price = None

        if price_max > price_min:
            bin_edges = [price_min + i * (price_max - price_min) / num_bins for i in range(num_bins + 1)]
            vp_buy = [0.0] * num_bins
            vp_sell = [0.0] * num_bins
            vp_total = [0.0] * num_bins

            for _, row in df.iterrows():
                o, h, l, c, v = row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
                if v <= 0:
                    continue
                buy_p = 0.5 + (0.5 * (c - o) / (h - l)) if h > l else 0.5
                buy_p = max(0.0, min(1.0, buy_p))
                v_buy = v * buy_p
                v_sell = v * (1.0 - buy_p)

                if h == l:
                    b_idx = min(int((h - price_min) / (price_max - price_min) * num_bins), num_bins - 1)
                    vp_buy[b_idx] += v_buy
                    vp_sell[b_idx] += v_sell
                    vp_total[b_idx] += v
                else:
                    for b in range(num_bins):
                        b_low = bin_edges[b]
                        b_high = bin_edges[b + 1]
                        overlap = max(0.0, min(h, b_high) - max(l, b_low))
                        if overlap > 0:
                            ratio = overlap / (h - l)
                            vp_buy[b] += v_buy * ratio
                            vp_sell[b] += v_sell * ratio
                            vp_total[b] += v * ratio

            max_tot_idx = max(range(num_bins), key=lambda i: vp_total[i])
            poc_price = (bin_edges[max_tot_idx] + bin_edges[max_tot_idx + 1]) / 2

            max_tot_vol = max(vp_total + [1.0])
            max_bar_len = len(df) * 0.28

            for b in range(num_bins):
                b_center = (bin_edges[b] + bin_edges[b + 1]) / 2
                tot_v = vp_total[b]
                net_d = vp_buy[b] - vp_sell[b]
                bar_width = (tot_v / max_tot_vol) * max_bar_len
                if bar_width > 0:
                    vp_levels.append(b_center)
                    vp_widths.append(bar_width)
                    if b == max_tot_idx:
                        vp_colors.append("#ffeb3b")
                    else:
                        vp_colors.append("#26a69a" if net_d >= 0 else "#ef5350")

        # ВАЖНО: без pyplot. pyplot держит глобальное состояние и ломается при
        # параллельном рендере двух графиков из разных потоков.
        fig = Figure(figsize=(11, 8.5))
        FigureCanvasAgg(fig)
        ax1, ax2 = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1.2]})
        fig.patch.set_facecolor("#121212")
        ax1.set_facecolor("#121212")
        ax2.set_facecolor("#121212")

        width = 0.6

        if tf_key in ("1m", "5m", "15m", "30m", "1h", "4h"):
            _dates = df["date_msk"].to_numpy()
            _dts = df["dt_msk"].to_numpy()
            for i in (np.nonzero(_dates[1:] != _dates[:-1])[0] + 1):
                ax1.axvline(i - 0.5, color="#64b5f6", linewidth=1.0, linestyle="--", alpha=0.55, zorder=2)
                ax2.axvline(i - 0.5, color="#64b5f6", linewidth=1.0, linestyle="--", alpha=0.55, zorder=2)
                day_str = pd.Timestamp(_dts[i]).strftime("%d.%m")
                ax1.text(
                    i,
                    price_max,
                    f" {day_str} ",
                    color="#64b5f6",
                    fontsize=7.5,
                    fontweight="bold",
                    va="top",
                    ha="left",
                    bbox=dict(boxstyle="round,pad=0.15", facecolor="#1e1e1e", edgecolor="#64b5f6", linewidth=0.7, alpha=0.88),
                    zorder=6,
                )

        for lvl, w, col in zip(vp_levels, vp_widths, vp_colors):
            alpha_val = 0.65 if col == "#ffeb3b" else 0.38
            ax1.barh(lvl, w, left=0, height=(price_max - price_min) / num_bins * 0.85, color=col, alpha=alpha_val, zorder=2)

        if poc_price is not None:
            ax1.axhline(poc_price, color="#ffeb3b", linewidth=1.4, linestyle="--", alpha=0.9, zorder=4)
            ax1.text(
                len(df) * 0.02,
                poc_price,
                f" POC: {poc_price:.2f} ",
                color="#121212",
                fontsize=8,
                fontweight="bold",
                va="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffeb3b", edgecolor="none", alpha=0.9),
                zorder=5,
            )

        res1_p = sr_info.get("res1_price")
        sup1_p = sr_info.get("sup1_price")
        if res1_p and price_min * 0.98 <= res1_p <= price_max * 1.02:
            ax1.axhline(res1_p, color="#ff5252", linewidth=1.1, linestyle="-.", alpha=0.85, zorder=4)
            ax1.text(len(df) * 0.68, res1_p, f" Сопр: {res1_p:.2f} ", color="white", fontsize=7.5, va="bottom", bbox=dict(boxstyle="round,pad=0.15", facecolor="#c62828", edgecolor="none", alpha=0.8), zorder=5)
        if sup1_p and price_min * 0.98 <= sup1_p <= price_max * 1.02:
            ax1.axhline(sup1_p, color="#00e676", linewidth=1.1, linestyle="-.", alpha=0.85, zorder=4)
            ax1.text(len(df) * 0.68, sup1_p, f" Подд: {sup1_p:.2f} ", color="#121212", fontsize=7.5, va="top", bbox=dict(boxstyle="round,pad=0.15", facecolor="#00e676", edgecolor="none", alpha=0.8), zorder=5)

        ax1.plot(range(len(df)), df["EMA20"], color="#29b6f6", linewidth=1.1, alpha=0.85, label="EMA 20", zorder=4)
        ax1.plot(range(len(df)), df["EMA50"], color="#ffa726", linewidth=1.1, alpha=0.85, label="EMA 50", zorder=4)
        ax1.plot(range(len(df)), df["EMA200"], color="#e0e0e0", linewidth=1.2, linestyle=":", alpha=0.75, label="EMA 200", zorder=4)

        trade_caption_block = ""
        if active_trade:
            t_entry = float(active_trade["entry"])
            t_tp = float(active_trade["tp"])
            t_sl = float(active_trade["sl"])
            t_side = active_trade["side"]

            tp_pct = abs(t_tp - t_entry) / t_entry * 100 if t_entry > 0 else 0.0
            sl_pct = abs(t_entry - t_sl) / t_entry * 100 if t_entry > 0 else 0.0
            cur_pnl_pct = (
                ((cur_price - t_entry) / t_entry * 100)
                if t_side == "LONG"
                else ((t_entry - cur_price) / t_entry * 100)
            ) if t_entry > 0 else 0.0

            ax1.axhspan(min(t_entry, t_tp), max(t_entry, t_tp), color="#00e676", alpha=0.09, zorder=1)
            ax1.axhspan(min(t_entry, t_sl), max(t_entry, t_sl), color="#ff1744", alpha=0.09, zorder=1)

            ax1.axhline(t_entry, color="#00e5ff", linewidth=1.6, linestyle="-", alpha=0.95, zorder=6)
            ax1.text(
                len(df) * 0.34,
                t_entry,
                f" Средняя ({t_side}): {t_entry:.2f} ₽ ({cur_pnl_pct:+.2f}%) ",
                color="#121212",
                fontsize=8,
                fontweight="bold",
                va="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#00e5ff", edgecolor="none", alpha=0.95),
                zorder=7,
            )

            ax1.axhline(t_tp, color="#00e676", linewidth=1.5, linestyle="--", alpha=0.95, zorder=6)
            ax1.text(
                len(df) * 0.34,
                t_tp,
                f" TP: {t_tp:.2f} ₽ (+{tp_pct:.2f}%) ",
                color="#121212",
                fontsize=8,
                fontweight="bold",
                va="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#00e676", edgecolor="none", alpha=0.95),
                zorder=7,
            )

            ax1.axhline(t_sl, color="#ff1744", linewidth=1.5, linestyle="--", alpha=0.95, zorder=6)
            ax1.text(
                len(df) * 0.34,
                t_sl,
                f" SL: {t_sl:.2f} ₽ (-{sl_pct:.2f}%) ",
                color="white",
                fontsize=8,
                fontweight="bold",
                va="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#d50000", edgecolor="none", alpha=0.95),
                zorder=7,
            )

            trade_caption_block = (
                f"\n🎯 <b>Активная сделка ({t_side}) на графике:</b>\n"
                f"   • Средняя (Вход): <b>{t_entry} ₽</b> (тек: <b>{cur_pnl_pct:+.2f}%</b>)\n"
                f"   • ✅ Тейк (TP): <b>{t_tp} ₽</b> (+{tp_pct:.2f}%)\n"
                f"   • 🛡 Стоп (SL): <b>{t_sl} ₽</b> (-{sl_pct:.2f}%)"
            )

        ax1.legend(loc="upper left", facecolor="#1e1e1e", edgecolor="none", labelcolor="white", fontsize=8)

        # Свечи рисуем массивами: в 5-10 раз быстрее, чем plot/bar в цикле по свечам
        x_idx = np.arange(len(df))
        o_a = df["Open"].to_numpy(dtype=float)
        h_a = df["High"].to_numpy(dtype=float)
        l_a = df["Low"].to_numpy(dtype=float)
        c_a = df["Close"].to_numpy(dtype=float)
        body_colors = np.where(c_a >= o_a, "#26a69a", "#ef5350")
        ax1.vlines(x_idx, l_a, h_a, colors=body_colors, linewidth=1, zorder=3)
        ax1.bar(x_idx, np.abs(c_a - o_a), bottom=np.minimum(o_a, c_a),
                width=width, color=body_colors, zorder=3)

        cur_color = "#00e676" if cur_price >= last_open else "#ff5252"
        text_fg = "#121212" if cur_price >= last_open else "white"
        ax1.axhline(cur_price, color=cur_color, linewidth=1.1, linestyle=":", alpha=0.85, zorder=5)
        ax1.text(
            -0.008,
            cur_price,
            f" {cur_price:.2f} ",
            transform=ax1.get_yaxis_transform(),
            color=text_fg,
            fontsize=8.5,
            fontweight="bold",
            va="center",
            ha="right",
            bbox=dict(boxstyle="round,pad=0.2", facecolor=cur_color, edgecolor="white", linewidth=0.7, alpha=0.98),
            clip_on=False,
            zorder=10,
        )

        # --- маркеры событий крупняка прямо на графике (🐋 принты, 🧊 iceberg, 🧱 стены, 🐋🐋 конфлюэнс) ---
        try:
            _now = time.time()
            _lot = max(int(lot or 1), 1)
            _tape = prepare_tape(raw_trades)
            if _tape and _tape.get("count"):
                _ts = np.asarray(_tape["ts_precise"], dtype=float)
                _qy = np.asarray(_tape["qty"], dtype=float)
                _sd = np.asarray(_tape["side"], dtype=float)
                _pr = np.asarray(_tape["price"], dtype=float)
                _big = (_pr * _qy * _lot) >= BIG_TRADE_MIN_RUB
                if _big.any():
                    _starts = (pd.DatetimeIndex(df["dt_msk"]).tz_convert("UTC").tz_localize(None)
                               .to_numpy().astype("datetime64[s]").astype("int64"))
                    _tf_sec = TIMEFRAMES[tf_key]["sec"]
                    _idx = np.clip(np.searchsorted(_starts, _ts, side="right") - 1, 0, len(df) - 1)
                    _sel = _big & (_ts >= _starts[0]) & (_ts < _starts[-1] + _tf_sec)
                    if _sel.any():
                        ax1.scatter(_idx[_sel][_sd[_sel] > 0], _pr[_sel][_sd[_sel] > 0], marker="^", s=46,
                                    color="#ffd54f", edgecolors="black", linewidths=0.4, zorder=8,
                                    label="Крупный принт (покупка)")
                        ax1.scatter(_idx[_sel][_sd[_sel] < 0], _pr[_sel][_sd[_sel] < 0], marker="v", s=46,
                                    color="#ff8a80", edgecolors="black", linewidths=0.4, zorder=8,
                                    label="Крупный принт (продажа)")
            for _e in (ICEBERG_STATE.get(ticker) or {}).get("events", [])[:3]:
                if _now - float(_e.get("ts", 0) or 0.0) <= 300:
                    _p = float(_e.get("price", 0) or 0.0)
                    if _p > 0:
                        ax1.axhline(_p, color="#4fc3f7", linewidth=1.0, linestyle=":", alpha=0.85, zorder=4)
                        ax1.text(len(df) * 0.985, _p, f" ICE {_e.get('side')} ", color="#081018", fontsize=7.5,
                                 ha="right", va="bottom",
                                 bbox=dict(boxstyle="round,pad=0.15", facecolor="#4fc3f7", edgecolor="none", alpha=0.85), zorder=9)
            _bk = BOOK_STATE.get(ticker) or {}
            if _now - float(_bk.get("ts", 0) or 0.0) <= BOOK_STALE_SEC:
                for _w in (_bk.get("big_walls") or [])[:3]:
                    _p = float(_w.get("price", 0) or 0.0)
                    if _p > 0:
                        ax1.axhline(_p, color="#b39ddb", linewidth=1.0, linestyle="--", alpha=0.8, zorder=4)
                        ax1.text(len(df) * 0.985, _p, f" WALL {_w.get('side')} ", color="#1a1030", fontsize=7.5,
                                 ha="right", va="top",
                                 bbox=dict(boxstyle="round,pad=0.15", facecolor="#b39ddb", edgecolor="none", alpha=0.8), zorder=9)
            _tm = detect_tape_size_metrics(_tape, cur_price, _lot, now_ts=_now)
            _sig_m = {
                "ticker": ticker,
                "big_prints": detect_big_prints(_tape, cur_price, _lot, now_ts=_now),
                "minute_pressure": detect_minute_pressure(_tape, cur_price, _lot, now_ts=_now),
                "big_twap": detect_big_twap(_tape, cur_price, _lot, now_ts=_now),
                "robot_activity": detect_repeated_trade_pattern(_tape, now_ts=_now),
                "tape_metrics": _tm,
            }
            _kinds = whale_confluence_kinds(_sig_m, _now)
            if len(_kinds) >= WHALE_CONFLUENCE_MIN:
                ax1.text(0.012, 0.985, f"WHALE x{len(_kinds)} (крупняк)", transform=ax1.transAxes, color="white",
                         fontsize=11, fontweight="bold", va="top",
                         bbox=dict(boxstyle="round,pad=0.3", facecolor="#6a1b9a", edgecolor="#ffd54f", alpha=0.95), zorder=11)
        except Exception as _e:
            logging.warning(f"Маркеры крупняка на графике {ticker}: {_e}")

        ax1.set_xlim(-1, len(df) + 1)
        ax1.set_title(
            f"Цена ({cur_price:.2f} ₽) + POC + Уровни + EMA + Дельта — {ticker} ({TIMEFRAMES[tf_key]['label']})",
            color="white",
            fontsize=10.5,
            fontweight="bold",
        )
        ax1.tick_params(colors="white", labelsize=9)
        ax1.grid(True, color="#2a2a2a", linestyle="--", alpha=0.5)

        ax1_right = ax1.twinx()
        ax1_right.set_facecolor("none")
        est_tag = " (оценочно)" if (cvd_estimated or low_vol_share >= 50.0) else ""
        ax1_right.plot(range(len(df)), df["cum_delta"], color="#ab47bc", linewidth=1.5,
                       alpha=0.35 if (cvd_estimated or low_vol_share >= 50.0) else 0.9, label=f"Кум. Дельта (свеча+лента){est_tag}", zorder=4)
        ax1_right.plot(range(len(df)), df["tape_cum_delta"], color="#ffd54f", linewidth=1.0, linestyle="--",
                       alpha=0.35 if cvd_estimated else 0.8, label="Дельта только по ленте", zorder=4)
        ax1_right.legend(loc="upper left", facecolor="#1e1e1e", edgecolor="none", labelcolor="white", fontsize=7.5)
        ax1_right.fill_between(range(len(df)), df["cum_delta"], 0, where=(df["cum_delta"] >= 0), color="#26a69a", alpha=0.16, zorder=1)
        ax1_right.fill_between(range(len(df)), df["cum_delta"], 0, where=(df["cum_delta"] < 0), color="#ef5350", alpha=0.16, zorder=1)
        ax1_right.tick_params(colors="#ab47bc", labelsize=8)
        ax1_right.grid(False)

        co = df["cvd_open"].to_numpy(dtype=float)
        ch = df["cvd_high"].to_numpy(dtype=float)
        cl_ = df["cvd_low"].to_numpy(dtype=float)
        cc = df["cvd_close"].to_numpy(dtype=float)
        # CVD раскрашиваем ПО СВЕЧАМ: свечи без реальной ленты (нет в файле/живом окне) — серые,
        # остальные — обычным цветом. Раньше весь график красился по флагу последних 6 свечей.
        up_col = np.where(low_cov_mask, "#78909c", "#26a69a")
        down_col = np.where(low_cov_mask, "#546e7a", "#ef5350")
        cvd_colors = np.where(cc >= co, up_col, down_col)
        if low_cov_mask.any():
            ax2.vlines(x_idx[low_cov_mask], cl_[low_cov_mask], ch[low_cov_mask],
                       colors=cvd_colors[low_cov_mask], linewidth=1, alpha=0.55)
            ax2.bar(x_idx[low_cov_mask], np.abs(cc[low_cov_mask] - co[low_cov_mask]),
                    bottom=np.minimum(co[low_cov_mask], cc[low_cov_mask]),
                    width=width, color=cvd_colors[low_cov_mask], alpha=0.55)
        ok_mask = ~low_cov_mask
        if ok_mask.any():
            ax2.vlines(x_idx[ok_mask], cl_[ok_mask], ch[ok_mask],
                       colors=cvd_colors[ok_mask], linewidth=1, alpha=1.0)
            ax2.bar(x_idx[ok_mask], np.abs(cc[ok_mask] - co[ok_mask]),
                    bottom=np.minimum(co[ok_mask], cc[ok_mask]),
                    width=width, color=cvd_colors[ok_mask], alpha=1.0)

        ax2.axhline(0, color="gray", linewidth=0.8, linestyle=":")
        ax2.set_ylabel("CVD (Лоты)", color="white", fontsize=9)
        ax2.tick_params(colors="white", labelsize=8.5)
        ax2.grid(True, color="#2a2a2a", linestyle="--", alpha=0.5)

        num_ticks = min(9, len(df))
        if num_ticks > 0:
            step = max(1, (len(df) - 1) // (num_ticks - 1)) if num_ticks > 1 else 1
            tick_indices = list(range(0, len(df), step))
            if (len(df) - 1) not in tick_indices:
                if len(tick_indices) > 1 and (len(df) - 1 - tick_indices[-1]) < step * 0.45:
                    tick_indices[-1] = len(df) - 1
                else:
                    tick_indices.append(len(df) - 1)

            tick_labels = []
            for idx in tick_indices:
                dt_obj = df.loc[idx, "dt_msk"]
                if tf_key == "1d":
                    tick_labels.append(dt_obj.strftime("%d.%m.%y"))
                elif tf_key in ("4h", "1h", "30m", "15m"):
                    tick_labels.append(dt_obj.strftime("%d.%m\n%H:%M"))
                else:
                    tick_labels.append(dt_obj.strftime("%H:%M\n(%d.%m)"))

            ax2.set_xticks(tick_indices)
            ax2.set_xticklabels(tick_labels, color="white", fontsize=8)
            ax2.set_xlabel("Время и дата (МСК) | вертикальная линия — начало нового торгового дня", color="#b0b0b0", fontsize=8.5)

        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
        buf.seek(0)
        png_bytes = buf.read()

        poc_str = f"{poc_price:.2f}" if poc_price else "—"
        est_cond = cvd_estimated or low_vol_share >= 50.0
        est_line = (
            f"\n⚠️ <b>CVD на графике частично ОЦЕНОЧНЫЙ:</b> свежее покрытие лентой {cvd_stats['tape_cov_pct']:.0f}% (порог {CHART_CVD_LOW_COV_PCT:.0f}%), "
            f"{low_vol_share:.0f}% объёма графика — свечи без реальных данных ленты (на графике серые, в файле их нет): их дельта синтетическая (по форме свечи). Жёлтая линия — только реальная лента"
            if est_cond else ""
        )
        last_dt_full = df["dt_msk"].iloc[-1].strftime("%d.%m.%Y %H:%M МСК")
        abs_line = f"\n📡 {cvd_stats['absorption_desc']}" if cvd_stats.get("absorption_desc") else ""

        caption = (
            f"📈 <b>График {ticker} ({TIMEFRAMES[tf_key]['label']})</b>\n"
            f"💰 <b>Текущая цена: {cur_price:.2f} ₽</b> (свеча: <b>{last_dt_full}</b>)\n"
            f"📊 <b>CVD дня: {format_lots_delta(cvd_stats['cvd_today'])}</b> | "
            f"За 6 св.: <b>{format_lots_delta(cvd_stats['cum_delta_change_6'])} ({cvd_stats['delta_efficiency_6']:+.1f}% от объёма)</b> | "
            f"покрытие лентой {cvd_stats['tape_cov_pct']:.0f}%\n"
            f"🟡 <b>POC (макс. объём): {poc_str}</b>\n"
            f"🔴 <b>Сопротивление: {sr_info['res1_price']}</b> | 🟢 <b>Поддержка: {sr_info['sup1_price']}</b>\n"
            f"📉 <b>Линии EMA:</b> 🔵 EMA20 | 🟠 EMA50 | ⚪ EMA200\n"
            f"🟣 <b>На графике:</b> Кум. Дельта | 🕯 <b>В подвале:</b> Свечной CVD"
            f"{abs_line}"
            f"{est_line}"
            f"{trade_caption_block}"
        )
        return png_bytes, caption
    finally:
        # pyplot больше не используется: фигура освобождается сборщиком мусора
        # вместе с локальными ссылками. plt.close("all") закрывал бы фигуры
        # других пользователей, которые рисуются параллельно.
        pass


def _render_locked(*args):
    with CHART_LOCK:
        return _render_chart_sync(*args)


async def render_chart_async(*args) -> tuple[bytes, str]:
    """Рендер в ОДНОМ выделенном потоке: matplotlib не потокобезопасен."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(CHART_EXECUTOR, _render_locked, *args)


# =====================================================================
# 9. ХЕНДЛЕРЫ TELEGRAM
# =====================================================================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in AUTO_SIGNAL_SUBSCRIBERS:
        AUTO_SIGNAL_SUBSCRIBERS[user_id] = 0.8
        await save_bot_state()

    market_open = is_moex_trading_hours()
    if not MOEX_INDEX_CACHE.get("data") or (now_ts - MOEX_INDEX_CACHE.get("ts", 0)) > 120:
        try:
            sess = await get_session()
            await get_moex_index_context(sess)
        except Exception:
            pass
    market_status = "🟢 Открыта (торги идут)" if market_open else "🌙 Закрыта (по календарю/времени сессии)"
    threshold_text = " · ".join(
        f"{TIMEFRAMES[tf]['btn']} >{cvd_absorption_threshold(tf):.0f}%"
        for tf in INFORMANT_TIMEFRAMES
    )

    await message.answer(
        f"👋 <b>Информатор CVD (5м / 15м / 30м / 1ч / 4ч) и Алго-Снайпер запущен!</b>\n"
        f"🕒 Статус Мосбиржи: <b>{market_status}</b>\n"
        f"📡 Пороги перевеса CVD: <b>{threshold_text}</b>. Сигналы считаются активными только при свежих данных по инструменту.\n\n"
        f"👇 Выберите действие:",
        reply_markup=get_main_keyboard(user_id=user_id),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("chart_"))
async def handle_show_chart(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 3:
        await callback.answer("Ошибка данных графика.", show_alert=True)
        return
    ticker = parts[1].upper()
    tf_key = parts[2] if parts[2] in TIMEFRAMES else "15m"
    user_id = callback.from_user.id

    if ticker in ILLIQUID_BLACKLIST:
        await callback.answer("Бумага в чёрном списке по ликвидности.", show_alert=True)
        return

    await callback.answer("Генерирую график в фоновом потоке...")

    session = await get_session()
    inst = await ensure_instrument_loaded(session, ticker)
    if not inst:
        await callback.message.answer("Инструмент не найден.")
        return

    uid = inst["uid"]
    now_utc = datetime.now(timezone.utc)
    tf_1h = TIMEFRAMES["1h"]
    tf_1d = TIMEFRAMES["1d"]

    df_main, d_1h, d_1d, d_trades = await asyncio.gather(
        fetch_candles_for_tf(session, uid, tf_key),
        api_post("MarketDataService/GetCandles", {
            "instrumentId": uid,
            "from": (now_utc - tf_1h["delta"]).isoformat(),
            "to": now_utc.isoformat(),
            "interval": tf_1h["interval"],
        }),
        api_post("MarketDataService/GetCandles", {
            "instrumentId": uid,
            "from": (now_utc - tf_1d["delta"]).isoformat(),
            "to": now_utc.isoformat(),
            "interval": tf_1d["interval"],
        }),
        api_post("MarketDataService/GetLastTrades", {
            "instrumentId": uid,
            "from": (now_utc - timedelta(minutes=TAPE_WINDOW_MINUTES)).isoformat(),
            "to": now_utc.isoformat(),
        }),
        return_exceptions=True,
    )

    if isinstance(df_main, BaseException):
        logging.error(f"Ошибка запроса свечей для графика {ticker}: {df_main}")
        await callback.message.answer("Ошибка связи с биржей, попробуйте ещё раз.")
        return

    c_1h = d_1h.get("candles", []) if isinstance(d_1h, dict) else []
    c_1d = d_1d.get("candles", []) if isinstance(d_1d, dict) else []
    raw_trades = d_trades.get("trades", []) if isinstance(d_trades, dict) else []

    if df_main.empty:
        await callback.message.answer("Недостаточно данных для построения графика.")
        return

    try:
        df_1h = candles_to_df(c_1h, 0.0)
        df_1d = candles_to_df(c_1d, 0.0)
        active_trade = TRACKED_SIGNALS.get(user_id, {}).get(ticker)

        # Рендер в отдельном потоке: event loop не блокируется, кнопки отвечают сразу
        png_bytes, caption = await render_chart_async(
            ticker, tf_key, df_main, df_1h, df_1d, raw_trades, active_trade, inst.get("lot", 1),
        )

        photo = BufferedInputFile(png_bytes, filename=f"{ticker}_{tf_key}_chart.png")
        chart_kb = get_main_keyboard(active_ticker=ticker, active_tf=tf_key, user_id=user_id)
        await callback.message.answer_photo(photo, caption=caption, reply_markup=chart_kb, parse_mode="HTML")
    except Exception as e:
        logging.exception(f"Ошибка рендеринга графика для {ticker}: {e}")
        await callback.message.answer(
            f"Произошла ошибка при построении графика: <code>{type(e).__name__}: {str(e)[:150].replace('<', '&lt;')}</code>\n"
            f"Traceback — в логах бота (строка «Ошибка рендеринга графика для {ticker}»).",
            parse_mode="HTML",
        )


@dp.callback_query(F.data.startswith("manual_track_"))
async def handle_manual_track(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer("Ошибка параметров сделки.", show_alert=True)
        return

    ticker = parts[2].upper()
    tf_key = parts[3] if parts[3] in TIMEFRAMES else "15m"
    forced_side = parts[4] if len(parts) >= 5 and parts[4] in ("LONG", "SHORT") else None
    user_id = callback.from_user.id

    if ticker == "IMOEX":
        await callback.answer("Индекс IMOEX нельзя добавить в сделки.", show_alert=True)
        return

    if ticker in TRACKED_SIGNALS.get(user_id, {}):
        await callback.answer(f"{ticker} уже в сделке — смотри раздел «👁 В сделке».", show_alert=True)
        return

    sig = await get_signal_cached(ticker, tf_key)

    if not sig or sig.get("is_illiquid"):
        await callback.answer("Не удалось получить данные по бумаге.", show_alert=True)
        return

    chosen_side = forced_side or (sig["verdict"] if sig["verdict"] in ("LONG", "SHORT") else sig["calc_side"])
    t_info = sig.get("targets_by_side", {}).get(chosen_side, sig)

    _amt = position_amount_rub()
    _inst = INSTRUMENTS_CACHE.get(ticker) or {}
    _lot = max(int(_inst.get("lot", 1) or 1), 1)
    _entry_p = float(t_info["entry"]) if float(t_info["entry"]) > 0 else 1.0
    _lots = max(1, int(_amt / max(_entry_p * _lot, 1e-9)))
    _real_amt = round(_lots * _lot * _entry_p, 0)
    TRACKED_SIGNALS.setdefault(user_id, {})[ticker] = {
        "ticker": ticker,
        "name": sig["name"],
        "side": chosen_side,
        "entry": t_info["entry"],
        "tp": t_info["tp"],
        "sl": t_info["sl"],
        "opened_at": datetime.now(MSK_TZ).strftime("%H:%M"),
        "partial_taken": False,
        "amount_rub": round(_amt, 0),
        "lots": _lots,
        "lot": _lot,
        "real_amount_rub": _real_amt,
    }
    LAST_SIGNAL_TIME[(user_id, ticker)] = time.time()
    await save_bot_state(force=True)

    await callback.answer(
        f"✅ {ticker} ({chosen_side}) взята в сделку! Вход: {t_info['entry']} ₽ | TP: {t_info['tp']} ₽ | SL: {t_info['sl']} ₽\n"
        f"💼 Позиция: {_lots} лот × {_lot} ≈ {_real_amt:,.0f} ₽ (1/{max(1, TRADING_MAX_POSITIONS)} депозита {TRADING_DEPOSIT_RUB:,.0f} ₽)",
        show_alert=True,
    )


@dp.callback_query(F.data == "show_sniper_entries")
async def show_sniper_entries_handler(callback: CallbackQuery):
    await callback.answer("Сканирую 5 ТФ (5м/15м/30м/1ч/4ч) и Индекс Мосбиржи...")
    all_scanned = await scan_market_sniper()
    confirmed = [
        s for s in all_scanned
        if s["verdict"] in ("LONG", "SHORT") and signal_data_is_live(s, require_candle=True)
    ]

    # Бумаги, где обнаружен скрытый набор/раздача по CVD во флэте на любом из 5 ТФ
    informant_hits = []
    for s in all_scanned:
        if not signal_data_is_live(s):
            continue
        for tf_k in INFORMANT_TIMEFRAMES:
            c_i = s.get("mtf_cvd", {}).get(tf_k, {})
            if c_i.get("absorption_side") or c_i.get("pressure_side"):
                informant_hits.append((s, tf_k, c_i))

    moex_info = MOEX_INDEX_CACHE.get("data")
    moex_header = ""
    if moex_info:
        moex_header = (
            f"🏛 <b>Индекс Мосбиржи (IMOEX): {moex_info['price']:.2f} п.</b> ({moex_info['change_pct']:+.2f}%) — {moex_info['summary_badge']}\n"
            f"   • Сопр: <b>{moex_info['sr']['res1_price']}</b> | Подд: <b>{moex_info['sr']['sup1_price']}</b>\n\n"
        )

    lines = ["📡 <b>ИНФОРМАТОР CVD (5м / 15м / 30м / 1ч / 4ч) И СНАЙПЕР:</b>\n", moex_header]
    kb_buttons = []

    if informant_hits:
        lines.append("🔥 <b>Скрытый набор / раздача при стоящем графике:</b>")
        for s, tf_k, c_i in informant_hits[:5]:
            tf_btn = TIMEFRAMES[tf_k]["btn"]
            _side = c_i.get("absorption_side") or c_i.get("pressure_side")
            side_icon = "🟢 Набор LONG" if _side == "LONG" else "🔴 Раздача SHORT"
            lines.append(
                f"• <b>{s['name']} ({s['ticker']}) [{tf_btn}]</b> — {side_icon}\n"
                f"   Цена (6 св.): <b>{c_i['price_change_6_pct']:+.2f}%</b> | CVD (6 св.): <b>{format_lots_delta(c_i['cum_delta_change_6'])}</b> (перевес <b>{c_i['delta_efficiency_6']:+.1f}%</b>, порог >{c_i.get('threshold_pct', cvd_absorption_threshold(tf_k)):.0f}%)"
            )
            kb_buttons.append([
                InlineKeyboardButton(
                    text=f"📈 График {s['ticker']} ({tf_btn})",
                    callback_data=f"chart_{s['ticker']}_{tf_k}",
                ),
                InlineKeyboardButton(
                    text=f"🎯 В сделку ({_side})",
                    callback_data=f"manual_track_{s['ticker']}_{tf_k}_{_side}",
                ),
            ])
        lines.append("")

    if confirmed:
        lines.append("🎯 <b>Подтверждённые сигналы Снайпера:</b>")
        for item in confirmed[:5]:
            badge = "🟢 LONG" if item["verdict"] == "LONG" else "🔴 SHORT"
            cvd_t = item.get("cvd_data", {}).get("cvd_today", 0.0)
            eff_6 = item.get("cvd_data", {}).get("delta_efficiency_6", 0.0)
            lines.append(
                f"🏢 <b>{item['name']} ({item['ticker']})</b> — {badge} ({abs(item['score'])}/10 балл.)\n"
                f"   • Вход: <b>{item['entry']} ₽</b> | 🎯 TP: <b>{item['tp']} ₽</b> | 🛡 SL: <b>{item['sl']} ₽</b>\n"
                f"   • 📊 CVD дня: <b>{format_lots_delta(cvd_t)}</b> (перевес 6 св.: <b>{eff_6:+.1f}%</b>)\n"
            )
            kb_buttons.append([
                InlineKeyboardButton(
                    text=f"🔎 Разбор {item['ticker']} ({item['verdict']})",
                    callback_data=f"ticker_{item['ticker']}",
                )
            ])
    elif not informant_hits:
        watching = all_scanned[:4]
        lines.append("⏸ <b>Прямо сейчас подтверждённых точек входа и флэт-аномалий CVD нет.</b>\n")
        lines.append("🔎 <b>Ближайшие бумаги под наблюдением:</b>")
        for s in watching:
            cvd_t = s.get("cvd_data", {}).get("cvd_today", 0.0)
            eff_6 = s.get("cvd_data", {}).get("delta_efficiency_6", 0.0)
            lines.append(
                f"• <b>{s['name']} ({s['ticker']})</b> — {abs(s['score'])}/{MIN_SCORE_FOR_ENTRY} балл. | CVD: {format_lots_delta(cvd_t)} ({eff_6:+.1f}%)"
            )
            kb_buttons.append([InlineKeyboardButton(text=f"🔎 Разбор {s['ticker']}", callback_data=f"ticker_{s['ticker']}")])

    kb_buttons.append([
        InlineKeyboardButton(text="🔄 Пересканировать", callback_data="show_sniper_entries"),
        InlineKeyboardButton(text="« Главное меню", callback_data="back_home"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    text = "\n".join(lines)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.in_({"show_active_robots", "rescan_robots"}))
async def show_active_robots_handler(callback: CallbackQuery):
    """Показывает список активных роботов/сигналов (информатор + снайпер)."""
    await callback.answer("Сканирую роботов и сигналы...")
    all_scanned = await scan_market_sniper()
    confirmed = [
        s for s in all_scanned
        if s["verdict"] in ("LONG", "SHORT") and signal_data_is_live(s, require_candle=True)
    ]

    informant_hits = []
    for s in all_scanned:
        if not signal_data_is_live(s):
            continue
        for tf_k in INFORMANT_TIMEFRAMES:
            c_i = s.get("mtf_cvd", {}).get(tf_k, {})
            if c_i.get("absorption_side") or c_i.get("pressure_side"):
                informant_hits.append((s, tf_k, c_i))

    moex_info = MOEX_INDEX_CACHE.get("data")
    moex_header = ""
    if moex_info:
        moex_header = (
            f"🏛 <b>Индекс Мосбиржи (IMOEX): {moex_info['price']:.2f} п.</b> ({moex_info['change_pct']:+.2f}%) — {moex_info['summary_badge']}\n"
            f"   • Сопр: <b>{moex_info['sr']['res1_price']}</b> | Подд: <b>{moex_info['sr']['sup1_price']}</b>\n\n"
        )

    ri_header = ""
    if RI_STATE.get("ts") and time.time() - float(RI_STATE["ts"]) < 600:
        if RI_STATE.get("detected"):
            ri_header = (f"📉 <b>RI ({RI_STATE.get('ticker')})</b>: крупные принты {RI_STATE.get('side')} на нетто "
                         f"{format_rub_volume(abs(float(RI_STATE.get('net_rub') or 0.0)))} ({RI_STATE.get('big_count')} шт. за 5 мин) — возможен крупный вход на рынке\n\n")
        else:
            ri_header = (f"📉 <b>RI ({RI_STATE.get('ticker')})</b>: без крупных принтов за окно "
                         f"(нетто {format_rub_volume(float(RI_STATE.get('net_rub') or 0.0))})\n\n")
    lines = ["📡 <b>АКТИВНЫЕ РОБОТЫ, ИНФОРМАТОР И СНАЙПЕР:</b>\n", moex_header, ri_header]
    kb_buttons = []

    # 1. Информатор (скрытый набор/раздача)
    if informant_hits:
        lines.append("🔥 <b>Роботы-Информаторы (скрытый набор / раздача при стоящем графике):</b>")
        for s, tf_k, c_i in informant_hits[:5]:
            tf_btn = TIMEFRAMES[tf_k]["btn"]
            _side = c_i.get("absorption_side") or c_i.get("pressure_side")
            side_icon = "🟢 Набор LONG" if _side == "LONG" else "🔴 Раздача SHORT"
            lines.append(
                f"• <b>{s['name']} ({s['ticker']}) [{tf_btn}]</b> — {side_icon}\n"
                f"   Цена (6 св.): <b>{c_i['price_change_6_pct']:+.2f}%</b> | CVD (6 св.): <b>{format_lots_delta(c_i['cum_delta_change_6'])}</b> (перевес <b>{c_i['delta_efficiency_6']:.1f}%</b>, порог >{c_i.get('threshold_pct', cvd_absorption_threshold(tf_k)):.0f}%)\n"
            )
            kb_buttons.append([
                InlineKeyboardButton(
                    text=f"📈 График {s['ticker']} ({tf_btn})",
                    callback_data=f"chart_{s['ticker']}_{tf_k}",
                ),
                InlineKeyboardButton(
                    text=f"🎯 В сделку ({_side})",
                    callback_data=f"manual_track_{s['ticker']}_{tf_k}_{_side}",
                ),
            ])
        lines.append("")

    # 2. Снайпер (подтвержденные сигналы)
    if confirmed:
        lines.append("🎯 <b>Активные роботы-Снайперы (подтверждённые сигналы):</b>")
        for item in confirmed[:5]:
            badge = "🟢 LONG" if item["verdict"] == "LONG" else "🔴 SHORT"
            cvd_t = item.get("cvd_data", {}).get("cvd_today", 0.0)
            eff_6 = item.get("cvd_data", {}).get("delta_efficiency_6", 0.0)
            lines.append(
                f"🏢 <b>{item['name']} ({item['ticker']})</b> — {badge} ({abs(item['score'])}/10 балл.)\n"
                f"   • Вход: <b>{item['entry']} ₽</b> | 🎯 TP: <b>{item['tp']} ₽</b> | 🛡 SL: <b>{item['sl']} ₽</b>\n"
                f"   • 📊 CVD дня: <b>{format_lots_delta(cvd_t)}</b> (перевес 6 св.: <b>{eff_6:.1f}%</b>)\n"
            )
            kb_buttons.append([
                InlineKeyboardButton(
                    text=f"🔎 Разбор {item['ticker']} ({item['verdict']})",
                    callback_data=f"ticker_{item['ticker']}",
                )
            ])
    elif not informant_hits:
        watching = all_scanned[:4]
        lines.append("⏸ <b>Прямо сейчас активных роботов и флэт-аномалий CVD нет.</b>\n")
        lines.append("🔎 <b>Ближайшие бумаги под наблюдением роботов:</b>")
        for s in watching:
            cvd_t = s.get("cvd_data", {}).get("cvd_today", 0.0)
            eff_6 = s.get("cvd_data", {}).get("delta_efficiency_6", 0.0)
            lines.append(
                f"• <b>{s['name']} ({s['ticker']})</b> — {abs(s['score'])}/{MIN_SCORE_FOR_ENTRY} балл. | CVD: {format_lots_delta(cvd_t)} ({eff_6:.1f}%)\n"
            )
            kb_buttons.append([InlineKeyboardButton(text=f"🔎 Разбор {s['ticker']}", callback_data=f"ticker_{s['ticker']}")])

    kb_buttons.append([
        InlineKeyboardButton(text="🔄 Пересканировать", callback_data="rescan_robots"),
        InlineKeyboardButton(text="« Главное меню", callback_data="back_home"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    text = "\n".join(lines)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

def collect_whale_events(scanned: list[dict], now_ts: float | None = None) -> list[dict]:
    """Агрегация свежих эвристических событий крупняка по результатам скана watchlist.

    Источники: анонимная лента GetLastTrades (крупные принты / минутное давление / TWAP /
    повторяющийся паттерн) и снапшоты стакана GetOrderBook (iceberg-стены, <=300 c).
    Справочно: эвристика по анонимным данным, не доказательство участника.
    """
    now_ts = float(now_ts if now_ts is not None else time.time())
    rows: list[dict] = []
    for s in scanned or []:
        t = s.get("ticker")
        if not t or not signal_data_is_live(s, now_ts=now_ts):
            continue
        bp = s.get("big_prints") or {}
        mp = s.get("minute_pressure") or {}
        tw = s.get("big_twap") or {}
        ra = s.get("robot_activity") or {}
        ice = [
            e for e in (ICEBERG_STATE.get(t) or {}).get("events", [])
            if now_ts - float(e.get("ts", 0) or 0.0) <= 300
        ]
        events: list[tuple[float, str]] = []
        if bp.get("detected"):
            events.append((float(bp.get("total_rub") or 0.0),
                f"🐋 {bp.get('big_count')} крупных принтов ({bp.get('side')}) на {format_rub_volume(float(bp.get('total_rub') or 0.0))} за {BIG_TRADE_WINDOW_SECONDS} c — нетто {format_rub_volume(abs(float(bp.get('net_rub') or 0.0)))}, последняя {bp.get('last_big_age_sec')} c назад"))
        if mp.get("detected"):
            events.append((abs(float(mp.get("net_rub") or 0.0)),
                f"⏱ минутное давление {mp.get('side')}: нетто {format_rub_volume(abs(float(mp.get('net_rub') or 0.0)))} за минуту при движении цены {float(mp.get('move_pct') or 0.0):+.3f}% (impact {float(mp.get('impact') or 0.0):.0f})"))
        if tw.get("detected"):
            events.append((float(tw.get("total_rub") or 0.0),
                f"⏲ TWAP-паттерн: {tw.get('count')} сделок по {tw.get('qty')} лот. ({tw.get('side')}), сумма {format_rub_volume(float(tw.get('total_rub') or 0.0))}, CV интервалов {tw.get('interval_cv')}"))
        if ra.get("pattern_detected"):
            events.append((0.0,
                f"🔁 повторяющийся паттерн: {ra.get('trade_count')} сделок по {ra.get('quantity_lots')} лот. ({ra.get('side')}) за {float(ra.get('span_seconds') or 0.0):.0f} c, медианный интервал {float(ra.get('median_interval_seconds') or 0.0):.2f} c (CV {float(ra.get('interval_cv') or 0.0):.2f})"))
        for e in ice[:2]:
            events.append((float(e.get("qty") or 0.0) * float(e.get("price") or 0.0),
                f"🧊 возможный iceberg ({e.get('side')}): уровень {float(e.get('price') or 0.0):.4f} ₽ — {float(e.get('qty') or 0.0):.0f} → {float(e.get('recovered_qty') or 0.0):.0f} лот. восстановилось, {int(now_ts - float(e.get('ts') or 0.0))} c назад"))
        bk = BOOK_STATE.get(t) or {}
        if now_ts - float(bk.get("ts", 0) or 0.0) <= BOOK_STALE_SEC:
            if bk.get("detected_imbalance"):
                events.append((float(bk.get("bid_rub") or 0.0) + float(bk.get("ask_rub") or 0.0),
                    f"⚖️ дисбаланс стакана {float(bk.get('imbalance_pct') or 0.0):+.0f}% ({bk.get('imbalance_side')}), плотность топ-5 {float(bk.get('depth_conc_pct') or 0.0):.0f}%"))
            for w in (bk.get("big_walls") or [])[:2]:
                events.append((float(w.get("rub") or 0.0),
                    f"🧱 big wall {w.get('side')} {float(w.get('price') or 0.0):.4f} ₽ — {format_rub_volume(float(w.get('rub') or 0.0))}"))
        tm = s.get("tape_metrics") or {}
        if tm.get("detected_size"):
            events.append((float(tm.get("avg_trade_rub") or 0.0),
                f"📏 средний чек вырос до {format_rub_volume(float(tm.get('avg_trade_rub') or 0.0))} ({float(tm.get('avg_trend_pct') or 0.0):+.0f}%)"))
        if tm.get("detected_accel"):
            events.append((0.0,
                f"🚀 ускорение принтов x{float(tm.get('rate_accel') or 0.0):.1f} ({float(tm.get('big_rate_per_min') or 0.0):.1f}/мин)"))
        kinds = s.get("whale_kinds") or []
        if len(kinds) >= WHALE_CONFLUENCE_MIN:
            events.append((1e12, f"🐋🐋 КОНФЛЮЭНС ({len(kinds)} признаков): " + ", ".join(kinds[:4])))
        if not events:
            continue
        events.sort(key=lambda x: x[0], reverse=True)
        rows.append({
            "ticker": t,
            "name": s.get("name") or t,
            "price": float(s.get("price") or 0.0),
            "change": float(s.get("change") or 0.0),
            "sort_rub": events[0][0],
            "events": [txt for _, txt in events],
        })
    rows.sort(key=lambda r: r["sort_rub"], reverse=True)
    return rows


def format_whales_text(rows: list[dict]) -> str:
    """Текст сообщения «🐋 Крупняк» (HTML-разметка, без «голых» < вне тегов)."""
    ri_line = ""
    if RI_STATE.get("ts") and time.time() - float(RI_STATE["ts"]) < 600 and RI_STATE.get("detected"):
        ri_line = (f"📉 <b>RI ({RI_STATE.get('ticker')})</b>: крупные принты {RI_STATE.get('side')} на нетто "
                   f"{format_rub_volume(abs(float(RI_STATE.get('net_rub') or 0.0)))} — возможен крупный вход на рынке\n")
    lines = [
        "🐋 <b>КРУПНЯК — свежие события по ленте и стаканам (скан watchlist)</b>",
        "⚠️ <i>Эвристика по анонимным данным: не доказательство участника и не сигнал входа.</i>\n",
        ri_line,
    ]
    if rows:
        for r in rows[:8]:
            lines.append(f"• <b>{r['name']} ({r['ticker']})</b> — {r['price']:.2f} ₽ ({r['change']:+.2f}%)")
            for ev in r["events"][:3]:
                lines.append(f"   {ev}")
    else:
        lines.append("⏸ За последние ~5 минут крупные принты, TWAP, минутное давление, повторяющиеся серии и iceberg-стены не обнаружены.")
        lines.append("🔎 Ближайшие к порогу бумаги — в «📡 Информатор / Снайпер / Роботы».")
    _ws = whale_stats_text()
    if _ws:
        lines.append(_ws.rstrip())
    return "\n".join(lines)


@dp.callback_query(F.data.in_({"show_whales", "rescan_whales"}))
async def show_whales_handler(callback: CallbackQuery):
    """Кнопка «🐋 Крупняк»: скан watchlist + бумаги со свежими событиями детекторов крупняка."""
    await callback.answer("Сканирую ленту и стаканы на крупняк...")
    all_scanned = await scan_market_sniper()
    rows = collect_whale_events(all_scanned)
    kb_buttons = []
    for r in rows[:8]:
        kb_buttons.append([
            InlineKeyboardButton(text=f"📈 График {r['ticker']}", callback_data=f"chart_{r['ticker']}_15m"),
            InlineKeyboardButton(text=f"🔎 Разбор {r['ticker']}", callback_data=f"ticker_{r['ticker']}"),
        ])
    kb_buttons.append([
        InlineKeyboardButton(text="🔄 Пересканировать", callback_data="rescan_whales"),
        InlineKeyboardButton(text="« Главное меню", callback_data="back_home"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    text = format_whales_text(rows)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


BT_CACHE: dict[int, tuple[float, dict]] = {}   # days -> (ts, result), кэш 10 минут
BT_LOCK = asyncio.Lock()


def format_backtest_text(res: dict) -> str:
    """Текст сообщения «🧪 Бэктест» (HTML-разметка, без «голых» < вне тегов)."""
    if not res.get("ok"):
        err_txt = str(res.get("error", "unknown"))[:200].replace("<", "&lt;")
        return f"🧪 <b>Бэктест не удался:</b> <code>{err_txt}</code>"
    days = int(res.get("days", 0))
    sk = res.get("skipped") or []
    skip_txt = (f", пропущено без данных: {len(sk)} ({', '.join(sk[:6])}{'…' if len(sk) > 6 else ''})") if sk else ""
    lines = [
        f"🧪 <b>БЭКТЕСТ портфеля за {days} дн.</b> (дневные свечи; в бэктесте бумаг: {int(res.get('tickers', 0))} из выбранных {int(res.get('watchlist_size', 0))}{skip_txt})",
        f"📊 Сделок: <b>{int(res.get('trades', 0))}</b> | Винрейт: <b>{float(res.get('winrate', 0.0)):.1f}%</b> | "
        f"Средний PnL на бумагу: <b>{float(res.get('avg_pnl_per_ticker_pct', 0.0)):+.2f}%</b>",
        f"💰 При депозите {float(res.get('deposit_rub', TRADING_DEPOSIT_RUB)):,.0f} ₽ (равные доли, сложными): <b>{float(res.get('pnl_rub', 0.0)):+,.0f} ₽</b>",
        "",
        "🏢 <b>По бумагам (сортировка по PnL):</b>",
    ]
    rows = sorted(res.get("per_ticker", []), key=lambda p: float(p.get("pnl_pct", 0.0)), reverse=True)
    for p in rows[:12]:
        lines.append(
            f"• <b>{p['ticker']}</b> — сделок {int(p['trades'])}, WR {float(p['winrate']):.0f}%, "
            f"PnL <b>{float(p['pnl_pct']):+.2f}%</b>, макс. просадка {float(p['max_dd_pct']):.1f}%"
        )
    note = str(res.get("note", "")).replace("<", "&lt;")
    if note:
        lines.append("")
        lines.append(f"ℹ️ <i>{note}</i>")
    return "\n".join(lines)


@dp.callback_query(F.data.startswith("backtest_"))
async def backtest_handler(callback: CallbackQuery):
    """«🧪 Бэктест Nд»: честный портфельный бэктест по дневным свечам watchlist (как /api/backtest на сайте)."""
    try:
        days = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        days = 60
    days = max(20, min(days, 180))
    await callback.answer(f"Считаю бэктест за {days} дн. — может занять до минуты...")
    now_ts = time.time()
    cached = BT_CACHE.get(days)
    if cached and now_ts - cached[0] < 600:
        res = cached[1]
    else:
        try:
            await asyncio.wait_for(BT_LOCK.acquire(), timeout=90)
        except asyncio.TimeoutError:
            await callback.message.answer(
                "Бэктест уже считается по другому запросу — подождите ~30–60 с и нажмите ещё раз (есть кэш 10 мин)."
            )
            return
        try:
            cached = BT_CACHE.get(days)
            if cached and time.time() - cached[0] < 600:
                res = cached[1]
            else:
                res = await run_honest_portfolio_backtest(days=days)
                BT_CACHE[days] = (time.time(), res)
        finally:
            BT_LOCK.release()
    text = format_backtest_text(res)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧪 30д", callback_data="backtest_30"),
            InlineKeyboardButton(text="🧪 60д", callback_data="backtest_60"),
            InlineKeyboardButton(text="🧪 90д", callback_data="backtest_90"),
        ],
        [InlineKeyboardButton(text="« Главное меню", callback_data="back_home")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


def _stocks_menu_text() -> str:
    emoji = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣"}
    parts = []
    for tier in (1, 2, 3):
        on = sum(1 for _, t in TIER_WATCHLISTS[tier] if t in ACTIVE_TICKERS)
        parts.append(f"{emoji[tier]} {tier}-й: {on}/{len(TIER_WATCHLISTS[tier])}")
    return (
        "🎛 <b>ВЫБОР БУМАГ ДЛЯ МОНИТОРИНГА</b>\n"
        f"Активно: <b>{len(ACTIVE_TICKERS)}</b> из {len(ALL_TIER_ENTRIES)} | " + " | ".join(parts) + "\n\n"
        "Откройте эшелон кнопкой ниже и отметьте бумаги ✅/⬜ — выбранные попадают в скан "
        "Снайпера/Информатора/🐋, в быстрые кнопки меню и в бэктест. Затем «✅ Применить»."
    )


def _stocks_menu_kb() -> InlineKeyboardMarkup:
    emoji = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣"}
    rows = []
    for tier in (1, 2, 3):
        on = sum(1 for _, t in TIER_WATCHLISTS[tier] if t in ACTIVE_TICKERS)
        rows.append([InlineKeyboardButton(
            text=f"{emoji[tier]} {tier}-й эшелон ({on}/{len(TIER_WATCHLISTS[tier])})",
            callback_data=f"stier_{tier}",
        )])
    rows.append([InlineKeyboardButton(text="✅ Применить", callback_data="sapply")])
    rows.append([InlineKeyboardButton(text="« Главное меню", callback_data="back_home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tier_text(n: int) -> str:
    on = sum(1 for _, t in TIER_WATCHLISTS.get(n, []) if t in ACTIVE_TICKERS)
    return (
        f"🎛 <b>{n}-й эшелон</b> — отметьте бумаги (✅ включить / ⬜ выключить):\n"
        f"Активно: <b>{on}/{len(TIER_WATCHLISTS.get(n, []))}</b>"
    )


def _tier_kb(n: int) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for name, ticker in TIER_WATCHLISTS.get(n, []):
        mark = "✅" if ticker in ACTIVE_TICKERS else "⬜"
        row.append(InlineKeyboardButton(text=f"{mark} {ticker}", callback_data=f"stg_{n}_{ticker}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    tickers = [t for _, t in TIER_WATCHLISTS.get(n, [])]
    all_on = bool(tickers) and all(t in ACTIVE_TICKERS for t in tickers)
    rows.append([InlineKeyboardButton(
        text="❌ Выключить весь эшелон" if all_on else "☑️ Включить весь эшелон",
        callback_data=f"stall_{n}",
    )])
    rows.append([
        InlineKeyboardButton(text="« К эшелонам", callback_data="stocks_menu"),
        InlineKeyboardButton(text="✅ Применить", callback_data="sapply"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "stocks_menu")
async def stocks_menu_handler(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text(_stocks_menu_text(), reply_markup=_stocks_menu_kb(), parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(_stocks_menu_text(), reply_markup=_stocks_menu_kb(), parse_mode="HTML")


@dp.callback_query(F.data.startswith("stier_"))
async def stocks_tier_handler(callback: CallbackQuery):
    try:
        n = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        n = 1
    if n not in TIER_WATCHLISTS:
        await callback.answer("Нет такого эшелона", show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.edit_text(_tier_text(n), reply_markup=_tier_kb(n), parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(_tier_text(n), reply_markup=_tier_kb(n), parse_mode="HTML")


@dp.callback_query(F.data.startswith("stg_"))
async def stocks_toggle_handler(callback: CallbackQuery):
    parts = callback.data.split("_")
    try:
        n = int(parts[1])
        ticker = parts[2].upper()
    except (IndexError, ValueError):
        await callback.answer("Некорректные данные кнопки", show_alert=True)
        return
    if ticker in ACTIVE_TICKERS:
        ACTIVE_TICKERS.discard(ticker)
        msg = f"Выключена: {ticker}"
    else:
        ACTIVE_TICKERS.add(ticker)
        msg = f"Включена: {ticker}"
    rebuild_active_watchlist()          # б ectест/скан/🐋 сразу работают по новому набору (в т.ч. 3-й эшелон)
    BT_CACHE.clear()                    # старый кэш б ectеста под новый набор не отдаём
    await callback.answer(msg)
    if n in TIER_WATCHLISTS:
        try:
            await callback.message.edit_text(_tier_text(n), reply_markup=_tier_kb(n), parse_mode="HTML")
        except TelegramBadRequest:
            pass


@dp.callback_query(F.data.startswith("stall_"))
async def stocks_tier_all_handler(callback: CallbackQuery):
    try:
        n = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        n = 1
    tickers = [t for _, t in TIER_WATCHLISTS.get(n, [])]
    if tickers and all(t in ACTIVE_TICKERS for t in tickers):
        for t in tickers:
            ACTIVE_TICKERS.discard(t)
        await callback.answer(f"Весь {n}-й эшелон выключен")
    else:
        ACTIVE_TICKERS.update(tickers)
        await callback.answer(f"Весь {n}-й эшелон включён")
    rebuild_active_watchlist()
    BT_CACHE.clear()
    if n in TIER_WATCHLISTS:
        try:
            await callback.message.edit_text(_tier_text(n), reply_markup=_tier_kb(n), parse_mode="HTML")
        except TelegramBadRequest:
            pass


@dp.callback_query(F.data == "sapply")
async def stocks_apply_handler(callback: CallbackQuery):
    rebuild_active_watchlist()
    BT_CACHE.clear()
    await save_bot_state(force=True)
    await callback.answer(f"Применено: мониторинг по {len(LIQUID_WATCHLIST)} бумагам", show_alert=True)
    text = (_stocks_menu_text()
            + "\n\n✅ <b>Применено и сохранено.</b> Скан, быстрые кнопки, 🐋, радар и бэктест работают по выбранным бумагам.")
    try:
        await callback.message.edit_text(text, reply_markup=_stocks_menu_kb(), parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=_stocks_menu_kb(), parse_mode="HTML")


@dp.callback_query(F.data == "show_strats")
async def show_strats_handler(callback: CallbackQuery):
    """💼 Счета стратегий: 3 виртуальных портфеля, их статистика и открытые позиции (patch30b)."""
    share = TRADING_DEPOSIT_RUB / max(1, len(STRATS))
    lines = [
        "💼 <b>СЧЕТА СТРАТЕГИЙ</b> — виртуальные портфели (бот не выставляет реальные ордера)\n",
        f"Депозит {TRADING_DEPOSIT_RUB:,.0f} ₽ делится на {len(STRATS)} долей по <b>{share:,.0f} ₽</b>. "
        "Автовход — по условию стратегии в цикле мониторинга; сопровождение общее (50% → 25% по TP → трейлинг остатка).\n",
    ]
    for key, st in STRATS.items():
        uid = st["uid"]
        stats = get_user_stats(uid)
        total = stats["wins"] + stats["losses"]
        wr = (stats["wins"] / total * 100) if total else 0.0
        mult = float(stats.get("compound_mult", 1.0))
        val, pnl = share * mult, share * (mult - 1.0)
        open_tr = TRACKED_SIGNALS.get(uid, {})
        lines.append(f"<b>{st['name']}</b> — {st['desc']}")
        lines.append(f"  💰 {val:,.0f} ₽ (PnL {pnl:+,.0f} ₽ / {(mult - 1.0) * 100:+.2f}%, сложными) | винрейт {wr:.0f}% ({stats['wins']}В/{stats['losses']}С/{stats.get('be', 0)}Б) | открыто {len(open_tr)}/{STRAT_MAX_POSITIONS}")
        for tick, si in list(open_tr.items())[:4]:
            tr = " | 🎯 трейлинг" if si.get("tp_trailed") else ""
            lines.append(f"    • {si['name']} ({tick}) {si['side']} вход {si['entry']:.2f} | TP {si['tp']:.2f} | SL {si['sl']:.2f}{tr}")
        lines.append("")
    if not STRATS_ENABLED:
        lines.append("(сейчас автовходы выключены: STRATS_ENABLED=0)")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="show_strats")],
        [InlineKeyboardButton(text="« Главное меню", callback_data="back_home")],
    ])
    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "show_stats")
async def show_stats_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    primary = _get_primary_user_id()
    st = get_user_stats(primary if (user_id not in USER_STATS or not USER_STATS[user_id].get("history")) else user_id)
    total = st["wins"] + st["losses"]
    wr = (st["wins"] / total * 100) if total > 0 else 0.0
    net_pct_val = (st["compound_mult"] - 1.0) * 100.0

    history_items = []
    seen = set()
    for uid_cand in (user_id, primary, 1, 1714890961):
        if uid_cand in USER_STATS:
            for item in USER_STATS[uid_cand].get("history", []):
                item_text = item["text"] if isinstance(item, dict) else str(item)
                if item_text and item_text not in seen:
                    seen.add(item_text)
                    history_items.append(item_text)

    if not history_items:
        for u_id, u_st in USER_STATS.items():
            for item in u_st.get("history", []):
                item_text = item["text"] if isinstance(item, dict) else str(item)
                if item_text and item_text not in seen:
                    seen.add(item_text)
                    history_items.append(item_text)

    header_text = (
        f"📊 <b>СТАТИСТИКА И ВИНРЕЙТ</b>\n\n"
        f"🎯 <b>Винрейт: {wr:.1f}%</b> (без учёта безубытков)\n"
        f"✅ TP: <b>{st['wins']}</b> | 🛡 SL: <b>{st['losses']}</b> | 🤝 Безубыток: <b>{st.get('be', 0)}</b>\n"
        f"💰 Суммарный результат (сложный %): <b>{net_pct_val:+.2f}%</b>\n"
        + portfolio_line(user_id) + "\n\n"
        f"📜 <b>Все закрытые сделки ({len(history_items)} шт.):</b>\n"
        + whale_stats_text()
    )

    if not history_items:
        full_text = header_text + "<i>Пока нет завершённых сделок.</i>"
        chunks = [full_text]
    else:
        chunks = []
        cur_chunk = header_text
        for idx, item_str in enumerate(history_items, 1):
            line = f"{idx}. {item_str}\n"
            if len(cur_chunk) + len(line) > 3900:
                chunks.append(cur_chunk.rstrip())
                cur_chunk = f"📜 <b>Продолжение списка сделок:</b>\n{line}"
            else:
                cur_chunk += line
        if cur_chunk:
            chunks.append(cur_chunk.rstrip())

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Сбросить статистику", callback_data="reset_stats")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="back_home")]
        ]
    )

    try:
        if len(chunks) == 1:
            await callback.message.edit_text(chunks[0], reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(chunks[0], parse_mode="HTML")
            for mid_chunk in chunks[1:-1]:
                await callback.message.answer(mid_chunk, parse_mode="HTML")
            await callback.message.answer(chunks[-1], reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        for ch_idx, chunk in enumerate(chunks):
            reply_kb = kb if ch_idx == len(chunks) - 1 else None
            await callback.message.answer(chunk, reply_markup=reply_kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "reset_stats")
async def reset_stats_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    USER_STATS[user_id] = {
        "wins": 0,
        "losses": 0,
        "be": 0,
        "compound_mult": 1.0,
        "history": deque(),
    }
    await save_bot_state(force=True)
    await callback.answer("Статистика успешно обнулена!", show_alert=True)
    await show_stats_handler(callback)


async def close_tracked_position_by_market(ticker: str, user_id: int | None = None, strat_key: str | None = None) -> tuple[bool, str]:
    """Закрывает открытую позицию по текущей рыночной цене, фиксирует PnL в статистику и историю."""
    ticker = ticker.upper().strip()
    target_uid = None
    s_info = None

    if strat_key and strat_key in STRATS:
        st_uid = STRATS[strat_key]["uid"]
        if ticker in TRACKED_SIGNALS.get(st_uid, {}):
            target_uid = st_uid
            s_info = TRACKED_SIGNALS[st_uid].pop(ticker)
    else:
        strat_uids = {st["uid"] for st in STRATS.values()}
        # Ищем сделку у указанного пользователя или в любом ручном слоте TRACKED_SIGNALS
        search_uids = []
        if user_id:
            search_uids.append(user_id)
        search_uids.append(_get_primary_user_id())
        for u in list(TRACKED_SIGNALS.keys()):
            if u not in strat_uids and u not in search_uids:
                search_uids.append(u)

        for u in search_uids:
            if ticker in TRACKED_SIGNALS.get(u, {}):
                target_uid = u
                s_info = TRACKED_SIGNALS[u].pop(ticker)
                break

    if not s_info or target_uid is None:
        return False, f"Сделка по {ticker} не найдена."

    # Получаем актуальную цену для расчёта результата
    cur_price = float((WEB_SCAN_CACHE.get(ticker) or {}).get("price") or 0.0)
    inst = INSTRUMENTS_CACHE.get(ticker)
    if cur_price <= 0 and inst:
        data = await api_post(
            "MarketDataService/GetLastPrices",
            {"instrumentId": [inst["uid"]], "lastPriceType": "LAST_PRICE_EXCHANGE"},
            timeout=6,
        )
        lps = data.get("lastPrices", [])
        if lps:
            cur_price = float(quotation_to_float(lps[0].get("price")) or 0.0)

    entry = float(s_info.get("entry") or 0.0)
    if cur_price <= 0:
        cur_price = entry

    side = s_info.get("side", "LONG")
    rem_frac = float(s_info.get("remaining_frac", 0.5 if s_info.get("partial_taken") else 1.0))
    raw_pct = ((cur_price - entry) / entry * 100.0) if (entry > 0 and side == "LONG") else (
        ((entry - cur_price) / entry * 100.0) if entry > 0 else 0.0
    )
    eff_pct = raw_pct * rem_frac

    has_leverage = bool(s_info.get("use_leverage")) and float(s_info.get("leverage") or 1.0) > 1.05
    leverage = float(s_info.get("leverage") or 1.0) if has_leverage else 1.0
    real_amt = float(s_info.get("real_amount_rub") or s_info.get("amount_rub") or 0.0)
    pnl_rub = (real_amt * rem_frac * (raw_pct / 100.0)) if real_amt > 0 else (position_amount_rub() * rem_frac * (raw_pct / 100.0))
    pnl_margin_pct = raw_pct * leverage if has_leverage else raw_pct

    stats_uid = _get_primary_user_id() if target_uid > 0 else target_uid
    stats = get_user_stats(stats_uid)
    dep = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 1.0

    rub_lbl = f" ({pnl_rub:+,.0f} ₽)" if real_amt > 0 else ""
    lev_lbl = f" [плечо {leverage:.1f}x: {pnl_margin_pct:+.2f}%]" if has_leverage else " [без плеча]"

    if abs(raw_pct) < 0.05:
        stats["be"] = int(stats.get("be", 0)) + 1
        add_history_entry(stats_uid, f"🤝 {ticker} ({side}) закрыта в Б/У 0.00%{rub_lbl} (по {cur_price} ₽)")
        res_label = f"в безубыток (0.00%) по {cur_price} ₽{rub_lbl}"
    elif raw_pct > 0:
        stats["wins"] += 1
        stats["compound_mult"] *= (1.0 + pnl_rub / dep)
        add_history_entry(stats_uid, f"✅ {ticker} ({side}) закрыта +{raw_pct:.2f}%{lev_lbl}{rub_lbl} (по {cur_price} ₽)")
        res_label = f"в плюс +{raw_pct:.2f}%{lev_lbl} по цене {cur_price} ₽{rub_lbl}"
    else:
        stats["losses"] += 1
        stats["compound_mult"] = max(0.0, stats["compound_mult"] * (1.0 + pnl_rub / dep))
        add_history_entry(stats_uid, f"🛡 {ticker} ({side}) закрыта {raw_pct:.2f}%{lev_lbl}{rub_lbl} (по {cur_price} ₽)")
        res_label = f"в минус {raw_pct:.2f}%{lev_lbl} по цене {cur_price} ₽{rub_lbl}"

    LAST_SIGNAL_TIME[(stats_uid, ticker)] = time.time()
    await save_bot_state(force=True)
    return True, f"Позиция {ticker} ({side}) закрыта {res_label}."


async def reduce_tracked_position(ticker: str, reduce_pct: float = 50.0, user_id: int | None = None, strat_key: str | None = None) -> tuple[bool, str]:
    """Сокращает открытую позицию на заданный процент по рыночной цене."""
    ticker = ticker.upper().strip()
    reduce_pct = max(1.0, min(100.0, float(reduce_pct)))

    target_uid = None
    s_info = None

    if strat_key and strat_key in STRATS:
        st_uid = STRATS[strat_key]["uid"]
        if ticker in TRACKED_SIGNALS.get(st_uid, {}):
            target_uid = st_uid
            s_info = TRACKED_SIGNALS[st_uid][ticker]
    else:
        strat_uids = {st["uid"] for st in STRATS.values()}
        search_uids = []
        if user_id:
            search_uids.append(user_id)
        search_uids.append(_get_primary_user_id())
        for u in list(TRACKED_SIGNALS.keys()):
            if u not in strat_uids and u not in search_uids:
                search_uids.append(u)

        for u in search_uids:
            if ticker in TRACKED_SIGNALS.get(u, {}):
                target_uid = u
                s_info = TRACKED_SIGNALS[u][ticker]
                break

    if not s_info or target_uid is None:
        return False, f"Сделка по {ticker} не найдена."

    if reduce_pct >= 99.5:
        return await close_tracked_position_by_market(ticker, user_id=user_id)

    cur_price = float((WEB_SCAN_CACHE.get(ticker) or {}).get("price") or 0.0)
    inst = INSTRUMENTS_CACHE.get(ticker)
    if cur_price <= 0 and inst:
        data = await api_post(
            "MarketDataService/GetLastPrices",
            {"instrumentId": [inst["uid"]], "lastPriceType": "LAST_PRICE_EXCHANGE"},
            timeout=6,
        )
        lps = data.get("lastPrices", [])
        if lps:
            cur_price = float(quotation_to_float(lps[0].get("price")) or 0.0)

    entry = float(s_info.get("entry") or 0.0)
    if cur_price <= 0:
        cur_price = entry

    side = s_info.get("side", "LONG")
    old_rem_frac = float(s_info.get("remaining_frac", 1.0))
    reduce_fraction = (reduce_pct / 100.0) * old_rem_frac

    raw_pct = ((cur_price - entry) / entry * 100.0) if (entry > 0 and side == "LONG") else (
        ((entry - cur_price) / entry * 100.0) if entry > 0 else 0.0
    )

    leverage = float(s_info.get("leverage") or 1.0)
    real_amt = float(s_info.get("real_amount_rub") or s_info.get("amount_rub") or 0.0)
    pnl_rub = real_amt * (reduce_pct / 100.0) * (raw_pct / 100.0)
    pnl_margin_pct = raw_pct * leverage

    stats_uid = _get_primary_user_id() if target_uid > 0 else target_uid
    stats = get_user_stats(stats_uid)
    dep = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 1.0

    if raw_pct > 0:
        stats["wins"] += 1
        stats["compound_mult"] *= (1.0 + pnl_rub / dep)
    elif raw_pct < 0:
        stats["losses"] += 1
        stats["compound_mult"] = max(0.0, stats["compound_mult"] * (1.0 + pnl_rub / dep))

    old_lots = int(s_info.get("lots") or 1)
    lots_to_reduce = max(1, int(round(old_lots * (reduce_pct / 100.0))))
    new_lots = max(0, old_lots - lots_to_reduce)
    lot_size = int(s_info.get("lot") or 1)

    s_info["remaining_frac"] = max(0.0, old_rem_frac - reduce_fraction)
    s_info["lots"] = new_lots
    s_info["real_amount_rub"] = round(new_lots * lot_size * entry, 0)
    s_info["margin_rub"] = round(s_info["real_amount_rub"] / leverage, 0)
    s_info["amount_rub"] = s_info["margin_rub"]
    s_info["partial_taken"] = True

    lev_lbl = f" [плечо {leverage:.1f}x: {pnl_margin_pct:+.2f}%]" if leverage > 1.05 else ""
    rub_lbl = f" ({pnl_rub:+,.0f} ₽)" if real_amt > 0 else ""
    add_history_entry(stats_uid, f"✂ {ticker} ({side}) сокращена на {reduce_pct:.0f}%: {raw_pct:+.2f}%{lev_lbl}{rub_lbl} (остаток {new_lots} лот)")

    if new_lots == 0 or s_info["remaining_frac"] <= 0.05:
        TRACKED_SIGNALS[target_uid].pop(ticker, None)

    await save_bot_state(force=True)
    return True, f"Позиция {ticker} сокращена на {reduce_pct:.0f}% ({raw_pct:+.2f}%, {pnl_rub:+,.0f} ₽). Осталось {new_lots} лот."


async def update_tracked_position_levels(ticker: str, tp: float | None = None, sl: float | None = None,
                                        to_be: bool = False, partial_take_pct: float | None = None,
                                        partial_trigger_pct: float | None = None,
                                        auto_partial_enabled: bool | None = None,
                                        user_id: int | None = None,
                                        take_profits: list | None = None) -> tuple[bool, str]:
    """Изменяет уровни TP / SL / БУ и параметры частичной фиксации открытой позиции."""
    ticker = ticker.upper().strip()
    target_uid = None
    s_info = None

    strat_uids = {st["uid"] for st in STRATS.values()}
    search_uids = []
    if user_id:
        search_uids.append(user_id)
    search_uids.append(_get_primary_user_id())
    for u in list(TRACKED_SIGNALS.keys()):
        if u not in strat_uids and u not in search_uids:
            search_uids.append(u)

    for u in search_uids:
        if ticker in TRACKED_SIGNALS.get(u, {}):
            target_uid = u
            s_info = TRACKED_SIGNALS[u][ticker]
            break

    if not s_info or target_uid is None:
        return False, f"Сделка по {ticker} не найдена."

    entry = float(s_info.get("entry") or 0.0)
    side = s_info.get("side", "LONG")
    changes = []

    if to_be:
        s_info["sl"] = entry
        changes.append(f"SL перенесён в безубыток ({entry} ₽)")
    elif sl is not None:
        val_sl = float(sl)
        if val_sl > 0:
            s_info["sl"] = round(val_sl, 4)
            changes.append(f"новый SL: {s_info['sl']} ₽")
        else:
            s_info["sl"] = 0.0
            changes.append("SL отключён (0 ₽)")

    if tp is not None:
        val_tp = float(tp)
        if val_tp > 0:
            s_info["tp"] = round(val_tp, 4)
            changes.append(f"новый TP: {s_info['tp']} ₽")
        else:
            s_info["tp"] = 0.0
            changes.append("TP отключён (0 ₽)")

    if take_profits is not None:
        if isinstance(take_profits, list):
            valid_tps = []
            for item in take_profits:
                try:
                    p_val = float(item.get("price", 0.0))
                    pct_val = float(item.get("pct", 50.0))
                    if p_val > 0 and pct_val > 0:
                        valid_tps.append({"price": round(p_val, 4), "pct": pct_val, "hit": bool(item.get("hit", False))})
                except Exception:
                    pass
            s_info["take_profits"] = valid_tps
            changes.append(f"каскад TP ({len(valid_tps)} уровней)")

    if auto_partial_enabled is not None:
        s_info["auto_partial_enabled"] = bool(auto_partial_enabled)
        changes.append("автофикс ВКЛ" if s_info["auto_partial_enabled"] else "автофикс ВЫКЛ")

    if partial_take_pct is not None:
        val = float(partial_take_pct)
        if val <= 0:
            s_info["auto_partial_enabled"] = False
            s_info["partial_take_pct"] = 0.0
            changes.append("автофиксация отключена")
        elif 1 <= val <= 90:
            s_info["partial_take_pct"] = val
            s_info["auto_partial_enabled"] = True
            changes.append(f"автофикс {val:.0f}%")

    if partial_trigger_pct is not None and 10 <= float(partial_trigger_pct) <= 90:
        s_info["partial_trigger_pct"] = float(partial_trigger_pct)
        changes.append(f"рубеж {s_info['partial_trigger_pct']:.0f}% пути")

    stats_uid = _get_primary_user_id() if target_uid > 0 else target_uid
    msg = f"⚙ {ticker} ({side}): " + ", ".join(changes)
    add_history_entry(stats_uid, msg)
    await save_bot_state(force=True)
    return True, msg


@dp.callback_query(F.data.startswith("close_trade_"))
async def close_single_trade_handler(callback: CallbackQuery):
    ticker = callback.data.replace("close_trade_", "").strip().upper()
    ok, msg = await close_tracked_position_by_market(ticker, user_id=callback.from_user.id)
    await callback.answer(msg, show_alert=True)
    await show_tracked_handler(callback)


@dp.callback_query(F.data == "show_tracked")
async def show_tracked_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    owner_uid = _get_primary_user_id()
    strat_uids = {st["uid"] for st in STRATS.values()}
    tracked = {}
    for u_id, u_sigs in TRACKED_SIGNALS.items():
        if u_id not in strat_uids and isinstance(u_sigs, dict):
            tracked.update(u_sigs)

    if not tracked:
        try:
            await callback.message.edit_text(
                "👁 Сейчас нет открытых ручных сделок на сопровождении.",
                reply_markup=get_main_keyboard(user_id=user_id),
            )
        except TelegramBadRequest:
            pass
        await callback.answer("Сейчас нет открытых сделок на сопровождении.")
        return

    live_prices = {}
    uids_to_fetch = []
    for ticker in tracked.keys():
        inst = INSTRUMENTS_CACHE.get(ticker)
        if inst:
            uids_to_fetch.append(inst["uid"])

    if uids_to_fetch:
        data = await api_post(
            "MarketDataService/GetLastPrices",
            {"instrumentId": uids_to_fetch, "lastPriceType": "LAST_PRICE_EXCHANGE"},
            timeout=8,
        )
        for lp in data.get("lastPrices", []):
            t_ticker = UID_TO_TICKER.get(lp.get("instrumentUid"))
            price = quotation_to_float(lp.get("price"))
            if t_ticker and price:
                live_prices[t_ticker] = price

    lines = ["👁 <b>АКТИВНЫЕ СДЕЛКИ НА КОНТРОЛЕ:</b>\n", portfolio_line(user_id if user_id in USER_STATS else owner_uid) + "\n"]
    kb_rows = []
    for i, (ticker, info) in enumerate(tracked.items(), 1):
        emoji = "🟢 LONG" if info["side"] == "LONG" else "🔴 SHORT"
        entry = info["entry"]
        cur_price = live_prices.get(ticker)

        diff_str = "⌛ <i>цена обновляется...</i>"
        if cur_price and entry > 0:
            side = info["side"]
            if side == "LONG":
                diff_pct = ((cur_price - entry) / entry) * 100
                diff_rub = cur_price - entry
            else:
                diff_pct = ((entry - cur_price) / entry) * 100
                diff_rub = entry - cur_price

            p_emoji = "🟢" if diff_pct >= 0 else "🔴"
            _pos_rub = float(info.get("real_amount_rub") or info.get("amount_rub") or 0.0)
            diff_str = (f"{p_emoji} Тек: <b>{cur_price} ₽</b> (отход: <b>{diff_rub:+.2f} ₽ / {diff_pct:+.2f}%</b>"
                        + (f" | позиция <b>{_pos_rub * diff_pct / 100.0:+,.0f} ₽</b>" if _pos_rub > 0 else "") + ")")

        be_tag = " [безубыток]" if info.get("sl") == entry else ""
        _amt2 = float(info.get("real_amount_rub") or info.get("amount_rub") or 0.0)
        _lots2 = int(info.get("lots") or 0)
        _lev = float(info.get("leverage") or 1.0)
        _lev_tag = f" | Плечо: <b>{_lev:.1f}x</b>" if _lev > 1.05 else ""
        _dep_tag = f" | Доля депо: <b>{info.get('dep_pct')}%</b>" if info.get('dep_pct') else f" (1/{max(1, TRADING_MAX_POSITIONS)} депо)"
        pos_line = (f"   • Позиция: <b>{_lots2} лот</b> ≈ <b>{_amt2:,.0f} ₽</b>{_lev_tag}{_dep_tag}\n") if _amt2 > 0 else ""
        _tmax = float(info.get("trail_max") or info.get("trail_min") or 0.0)
        _rem = float(info.get("remaining_frac", 1.0)) * 100
        trail_line = (f"   • 🎯 Трейлинг остатка {_rem:.0f}%: экстр. <b>{_tmax:.2f} ₽</b>, стоп <b>{float(info.get('trail_stop') or 0.0):.2f} ₽</b>\n") \
            if (info.get("tp_trailed") and _tmax > 0) else ""
        lines.append(
            f"{i}. <b>{info['name']} ({ticker})</b>{be_tag} — {emoji} (от {info.get('opened_at', 'ранее')})\n"
            f"   • Вход: <b>{entry} ₽</b> | TP: <b>{info['tp']} ₽</b> | SL: <b>{info['sl']} ₽</b>\n"
            f"{pos_line}"
            f"{trail_line}"
            f"   • {diff_str}\n"
        )
        kb_rows.append([
            InlineKeyboardButton(text=f"📈 График {ticker}", callback_data=f"chart_{ticker}_15m"),
            InlineKeyboardButton(text=f"✖ Закрыть {ticker} по рынку", callback_data=f"close_trade_{ticker}"),
        ])

    kb_rows.extend([
        [InlineKeyboardButton(text="🔄 Обновить цены", callback_data="show_tracked")],
        [InlineKeyboardButton(text="🗑 Очистить все без учёта", callback_data="clear_tracked")],
        [InlineKeyboardButton(text="« Главное меню", callback_data="back_home")],
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await callback.answer()


async def _send_cvd_journal(target: Message | CallbackQuery):
    """Отправляет CSV-журнал сигналов информатора документом в чат."""
    message = target.message if isinstance(target, CallbackQuery) else target
    if not CVD_STORE_ENABLED:
        await message.answer("CVD-хранилище выключено (CVD_STORE_ENABLED=0).")
        return

    await asyncio.to_thread(CVD_STORE.flush)
    if not os.path.exists(CVD_ALERTS_CSV) or os.path.getsize(CVD_ALERTS_CSV) == 0:
        await message.answer(
            "📥 Журнал пока пуст — сигналов ещё не было.\n"
            f"Накоплено минут ленты: <b>{CVD_STORE.stats()['minutes_in_memory']}</b> "
            f"в файле <code>{CVD_DB_PATH}</code>.",
            parse_mode="HTML",
        )
        return

    size_kb = os.path.getsize(CVD_ALERTS_CSV) / 1024
    await message.answer_document(
        FSInputFile(CVD_ALERTS_CSV, filename="cvd_alerts.csv"),
        caption=(
            f"📥 <b>Журнал сигналов информатора CVD</b>\n"
            f"• Файл: <code>{CVD_ALERTS_CSV}</code> ({size_kb:.1f} КБ)\n"
            f"• Всего сигналов: <b>{CVD_STORE.alerts_total}</b>\n"
            f"• Накоплено минут реальной ленты: <b>{CVD_STORE.stats()['minutes_in_memory']}</b>\n"
            f"• Разделитель «;» — открывается в Excel/Google Sheets"
        ),
        parse_mode="HTML",
    )


@dp.message(Command("panic"))
async def cmd_panic(message: Message):
    strat_uids = {st["uid"]: key for key, st in STRATS.items()}
    all_to_close = []
    for uid, ticks in list(TRACKED_SIGNALS.items()):
        is_strat = strat_uids.get(uid)
        for tick in list(ticks.keys()):
            all_to_close.append((tick, is_strat))

    if not all_to_close:
        await message.answer("ℹ️ Нет активных открытых позиций для закрытия.")
        return

    closed_names = []
    for tick, strat_k in all_to_close:
        try:
            ok, msg = await close_tracked_position_by_market(tick, strat_key=strat_k)
            if ok:
                closed_names.append(tick)
        except Exception:
            pass

    await save_bot_state(force=True)
    await message.answer(
        f"🚨 <b>EMERGENCY FLATTEN:</b>\n"
        f"Экстренно закрыто позиций: {len(closed_names)}\n"
        f"Тикеры: {', '.join(closed_names) if closed_names else 'ошибок нет'}"
    )


@dp.message(Command("export"))
async def cmd_export_cvd(message: Message):
    await _send_cvd_journal(message)


@dp.callback_query(F.data == "export_cvd")
async def handle_export_cvd(callback: CallbackQuery):
    await callback.answer("Собираю журнал...")
    await _send_cvd_journal(callback)


@dp.callback_query(F.data == "back_home")
async def back_home_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏠 Главное меню алгоритмического бота Мосбиржи:",
        reply_markup=get_main_keyboard(user_id=callback.from_user.id),
    )
    await callback.answer()


@dp.callback_query(F.data == "clear_tracked")
async def clear_tracked_handler(callback: CallbackQuery):
    TRACKED_SIGNALS[callback.from_user.id] = {}
    await save_bot_state(force=True)
    await callback.message.edit_text(
        "🗑 Активные сделки очищены.",
        reply_markup=get_main_keyboard(user_id=callback.from_user.id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("ticker_"))
async def handle_ticker_button(callback: CallbackQuery):
    ticker = callback.data.split("_")[1]
    await callback.answer("Сканирую тикеры и обновляю данные CVD, IMOEX и уровней...")
    await send_signal_response(callback.message, ticker, user_id=callback.from_user.id)


@dp.callback_query(F.data.startswith("tf_"))
async def handle_timeframe_change(callback: CallbackQuery):
    _, ticker, tf_key = callback.data.split("_")
    user_id = callback.from_user.id
    sig = await get_signal_cached(ticker, tf_key, force=True)  # пользователь ждёт свежие данные
    if not sig or sig.get("is_illiquid"):
        err = _LAST_ANALYZE_ERR.get((ticker.upper().strip(), tf_key))
        why = f" Причина: {err[1][:120]}" if (not sig and err and (time.time() - err[0]) < 600) else ""
        await callback.answer(f"Нет данных по {ticker}.{why}"[:200], show_alert=True)
        return

    caption = format_signal_caption(sig)
    kb = get_main_keyboard(active_ticker=sig["ticker"], active_tf=sig["tf_key"], user_id=user_id)
    try:
        await callback.message.edit_text(caption, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    await callback.answer(f"Таймфрейм: {TIMEFRAMES[sig['tf_key']]['label']}")


TICKER_RE = re.compile(r"^[A-Za-z]{3,6}$")


@dp.message(F.text)
async def handle_ticker_text(message: Message):
    raw = (message.text or "").strip()
    if not TICKER_RE.match(raw):
        await message.answer(
            "Введите тикер одним словом, латиницей (например: <code>SBER</code>, <code>LKOH</code>, "
            "<code>IMOEX</code>).\nКоманды: /start — меню.",
            parse_mode="HTML",
            reply_markup=get_main_keyboard(user_id=message.from_user.id),
        )
        return
    await send_signal_response(message, raw.upper(), user_id=message.from_user.id)


# =====================================================================
# 10. ВЕБ-СЕРВЕР И REST API (РАБОТАЕТ ОТ ЕДИНОГО КЭША WEB_SCAN_CACHE)
# =====================================================================
def _get_primary_user_id() -> int:
    """patch35: uid владельца для веб-панели. WEB_USER_ID в приоритете; иначе первый
    ПОЛОЖИТЕЛЬНЫЙ uid не из счетов стратегий (раньше первым мог быть -9001 — тогда веб-сделки
    уходили «в стратегию» и не отображались в «В сделке» TG-пользователя)."""
    if WEB_USER_ID > 0:
        return WEB_USER_ID
    if _TG_OWNER_UID > 0:  # patch36: владелец, выученный из Telegram
        return _TG_OWNER_UID
    strat_uids = {st["uid"] for st in STRATS.values()}
    # Prefer real telegram IDs (> 1000)
    for src in (USER_STATS, TRACKED_SIGNALS, AUTO_SIGNAL_SUBSCRIBERS):
        for uid in src:
            if isinstance(uid, int) and uid > 1000 and uid not in strat_uids:
                return uid
    for src in (USER_STATS, TRACKED_SIGNALS, AUTO_SIGNAL_SUBSCRIBERS):
        for uid in src:
            if isinstance(uid, int) and uid > 0 and uid not in strat_uids:
                return uid
    return 1


def _migrate_orphan_trades() -> int:
    """patch35: ручные веб-сделки (без поля strategy), записанные на uid<=0 или на счёт
    стратегии, переносим владельцу — чтобы они были видны в «👁 В сделке» в Telegram."""
    primary = _get_primary_user_id()
    if primary <= 0:
        return 0
    strat_uids = {st["uid"] for st in STRATS.values()}
    moved = 0
    for uid in list(TRACKED_SIGNALS.keys()):
        if uid == primary or (isinstance(uid, int) and uid > 0 and uid not in strat_uids):
            continue
        for tk, info in list((TRACKED_SIGNALS.get(uid) or {}).items()):
            if not (info or {}).get("strategy"):
                TRACKED_SIGNALS.setdefault(primary, {})[tk] = info
                del TRACKED_SIGNALS[uid][tk]
                moved += 1
        if not TRACKED_SIGNALS.get(uid):
            TRACKED_SIGNALS.pop(uid, None)
    return moved


async def _fetch_chart_series_for_web(ticker: str, tf_key: str = "15m") -> list[dict]:
    session = await get_session()
    inst = await ensure_instrument_loaded(session, ticker)
    if not inst:
        return []

    uid = inst["uid"]
    now_utc = datetime.now(timezone.utc)
    df, d_trades = await asyncio.gather(
        fetch_candles_for_tf(session, uid, tf_key),
        api_post("MarketDataService/GetLastTrades", {
            "instrumentId": uid,
            "from": (now_utc - timedelta(minutes=TAPE_WINDOW_MINUTES)).isoformat(),
            "to": now_utc.isoformat(),
        }),
    )
    raw_trades = d_trades.get("trades", [])

    if df.empty:
        return []

    df, _, _ = apply_real_trades_delta_to_df(
        df, raw_trades, tf_key, hist=cvd_store_history(ticker, tf_key, df)
    )

    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()

    df["cvd_open"] = df["cvd"].shift(1).fillna(0)
    df.loc[df["date_msk"] != df["date_msk"].shift(1), "cvd_open"] = 0.0
    df["cvd_close"] = df["cvd"]
    df["cvd_high"] = df[["cvd_open", "cvd_close"]].max(axis=1)
    df["cvd_low"] = df[["cvd_open", "cvd_close"]].min(axis=1)

    out = []
    for _, r in df.iterrows():
        out.append({
            "time": r["dt_msk"].strftime("%d.%m %H:%M"),
            "open": round(float(r["Open"]), 4),
            "high": round(float(r["High"]), 4),
            "low": round(float(r["Low"]), 4),
            "close": round(float(r["Close"]), 4),
            "vol": int(r["Volume"]),
            "delta": round(float(r["delta"]), 1),
            "cvd_open": round(float(r["cvd_open"]), 1),
            "cvd_high": round(float(r["cvd_high"]), 1),
            "cvd_low": round(float(r["cvd_low"]), 1),
            "cvd_close": round(float(r["cvd_close"]), 1),
            "cum_delta": round(float(r["cum_delta"]), 1),
            "tape_cov": round(float(r["tape_cov"]), 3),
            "tape_delta": round(float(r["tape_delta"]), 1),
            "tape_cum_delta": round(float(r["tape_cum_delta"]), 1),
            "ema20": round(float(r["EMA20"]), 4),
            "ema50": round(float(r["EMA50"]), 4),
            "ema200": round(float(r["EMA200"]), 4),
        })
    return out


def _web_authorized(request, body: dict | None = None) -> bool:
    """Простая авторизация веб-терминала и REST API по WEB_SECRET."""
    if not WEB_SECRET:
        return False
    given = (
        request.query.get("token")
        or request.headers.get("X-Web-Secret", "")
        or (body or {}).get("token", "")
    )
    return hmac.compare_digest(str(given or ""), WEB_SECRET)


def _unauthorized() -> web.Response:
    return web.json_response({"ok": False, "error": "unauthorized"}, status=401)


async def handle_web_dashboard(request):
    if os.path.exists("index.html"):
        return web.FileResponse("index.html")
    return web.Response(text="MOEX CVD Informant (5m/15m/30m/1h/4h) & Sniper Web Terminal is running!")


LIVE_PRICES_CACHE: dict[str, float] = {}


def _resolve_position_price(ticker: str, info: dict | None = None) -> float:
    """Возвращает актуальную рыночную цену инструмента для расчёта PnL."""
    tk = str(ticker).upper().strip()
    p = float(LIVE_PRICES_CACHE.get(tk, 0.0) or 0.0)
    if p > 0:
        return p
    p_web = float((WEB_SCAN_CACHE.get(tk) or {}).get("price") or 0.0)
    if p_web > 0:
        return p_web
    return float((info or {}).get("entry") or 0.0)


async def _refresh_tracked_live_prices():
    """Обновляет LIVE_PRICES_CACHE актуальными ценами с Мосбиржи для всех открытых позиций."""
    try:
        all_tickers = set(t for _, t in LIQUID_WATCHLIST)
        for u_sigs in TRACKED_SIGNALS.values():
            if isinstance(u_sigs, dict):
                all_tickers.update(u_sigs.keys())

        uids_to_fetch = []
        for ticker in all_tickers:
            inst = INSTRUMENTS_CACHE.get(ticker)
            if inst and inst.get("uid"):
                uids_to_fetch.append(inst["uid"])

        if not uids_to_fetch:
            return

        data = await api_post(
            "MarketDataService/GetLastPrices",
            {"instrumentId": uids_to_fetch, "lastPriceType": "LAST_PRICE_EXCHANGE"},
            timeout=8,
        )
        for lp in (data or {}).get("lastPrices", []):
            t_ticker = UID_TO_TICKER.get(lp.get("instrumentUid"))
            price = quotation_to_float(lp.get("price"))
            if t_ticker and price and price > 0:
                LIVE_PRICES_CACHE[t_ticker] = price
                if t_ticker in WEB_SCAN_CACHE:
                    WEB_SCAN_CACHE[t_ticker]["price"] = price

        # Если биржа закрыта или по части бумаг нет last_price, подтягиваем GetClosePrices
        missing_tickers = [t for t in all_tickers if LIVE_PRICES_CACHE.get(t, 0.0) <= 0]
        if missing_tickers:
            close_uids = [INSTRUMENTS_CACHE[t]["uid"] for t in missing_tickers if t in INSTRUMENTS_CACHE and INSTRUMENTS_CACHE[t].get("uid")]
            if close_uids:
                cdata = await api_post(
                    "MarketDataService/GetClosePrices",
                    {"instruments": [{"instrumentId": uid} for uid in close_uids[:40]]},
                    timeout=8,
                )
                for cp in (cdata or {}).get("closePrices", []):
                    t_ticker = UID_TO_TICKER.get(cp.get("instrumentUid"))
                    price = quotation_to_float(cp.get("price"))
                    if t_ticker and price and price > 0:
                        LIVE_PRICES_CACHE[t_ticker] = price
                        if t_ticker in WEB_SCAN_CACHE:
                            WEB_SCAN_CACHE[t_ticker]["price"] = price
    except Exception as e:
        logger.debug(f"_refresh_tracked_live_prices error: {e}")


def _strats_dashboard() -> list[dict]:
    """Сводка по виртуальным счетам стратегий с живым расчётом PnL открытых сделок."""
    share = STRAT_DEPOSIT_RUB
    out = []
    for key, st in STRATS.items():
        uid = st["uid"]
        stats = get_user_stats(uid)
        total = stats["wins"] + stats["losses"]
        mult = float(stats.get("compound_mult", 1.0))
        open_pos = []
        open_unrealized_rub = 0.0

        for tk, info in (TRACKED_SIGNALS.get(uid) or {}).items():
            cur_p = _resolve_position_price(tk, info)
            entry_p = float(info.get("entry") or 0.0)
            side = info.get("side")
            if entry_p > 0 and cur_p > 0:
                pnl_pct = ((cur_p - entry_p) / entry_p * 100) if side == "LONG" else ((entry_p - cur_p) / entry_p * 100)
            else:
                pnl_pct = 0.0

            pos_rub = float(info.get("real_amount_rub") or info.get("amount_rub") or (share / max(1, STRAT_MAX_POSITIONS)))
            rem_frac = float(info.get("remaining_frac", 0.5 if info.get("partial_taken") else 1.0))
            open_unrealized_rub += pos_rub * rem_frac * (pnl_pct / 100.0)

            open_pos.append({
                "ticker": tk, "name": info.get("name"), "side": side,
                "entry": info.get("entry"), "tp": info.get("tp"), "sl": info.get("sl"),
                "opened_at": info.get("opened_at"), "partial_taken": info.get("partial_taken", False),
                "tp_trailed": info.get("tp_trailed", False),
                "trail_max": info.get("trail_max"), "trail_min": info.get("trail_min"),
                "trail_stop": info.get("trail_stop"), "remaining_frac": info.get("remaining_frac"),
                "amount_rub": info.get("amount_rub"), "real_amount_rub": info.get("real_amount_rub"),
                "strategy": key, "current_price": round(cur_p, 4), "pnl_pct": round(pnl_pct, 2),
            })

        realized_pnl_rub = share * (mult - 1.0)
        total_pnl_rub = realized_pnl_rub + open_unrealized_rub
        total_mult = 1.0 + (total_pnl_rub / share) if share > 0 else mult

        out.append({
            "key": key, "name": st["name"], "desc": st["desc"], "enabled": bool(STRATS_ENABLED),
            "share_rub": round(share, 0), "max_positions": STRAT_MAX_POSITIONS,
            "wins": stats["wins"], "losses": stats["losses"], "be": stats.get("be", 0),
            "winrate": round(stats["wins"] / total * 100, 1) if total else 0.0,
            "compound_mult": round(total_mult, 6),
            "portfolio_rub": round(share + total_pnl_rub, 0),
            "pnl_rub": round(total_pnl_rub, 0),
            "open": open_pos,
        })
    return out


MARKET_NEWS_CACHE = {"ts": 0.0, "items": []}

async def _fetch_market_news(limit: int = 25) -> list[dict]:
    now = time.time()
    if now - MARKET_NEWS_CACHE["ts"] < 60 and MARKET_NEWS_CACHE["items"]:
        return MARKET_NEWS_CACHE["items"][:limit]

    items = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    timeout = aiohttp.ClientTimeout(total=4)
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            # 1. MOEX sitenews (официальные биржевые события, аукционы, границы цен)
            try:
                async with session.get("https://iss.moex.com/iss/sitenews.json?limit=15") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        cols = data.get("sitenews", {}).get("columns", [])
                        for r in data.get("sitenews", {}).get("data", [])[:12]:
                            row = dict(zip(cols, r))
                            title = str(row.get("title", "")).replace("&quot;", '"').strip()
                            pub = str(row.get("published_at", ""))
                            time_str = pub[11:16] if len(pub) >= 16 else ""
                            date_str = pub[:10] if len(pub) >= 10 else ""
                            is_crit = any(k in title.lower() for k in ["дискретн", "аукцион", "приостановк", "коридор", "рисков", "ограничен"])
                            items.append({
                                "source": "MOEX",
                                "time": time_str,
                                "date": date_str,
                                "title": title,
                                "url": f"https://www.moex.com/n{row.get('id', '')}",
                                "important": is_crit,
                                "raw_time": pub,
                            })
            except Exception:
                pass

            # 2. РБК Экономика / Финансы (главные новости рынка РФ)
            try:
                async with session.get("https://rssexport.rbc.ru/rbcnews/news/30/full.rss") as resp:
                    if resp.status == 200:
                        import xml.etree.ElementTree as ET
                        text_rss = await resp.text()
                        root = ET.fromstring(text_rss)
                        for item in root.findall("./channel/item")[:10]:
                            title = (item.findtext("title") or "").strip()
                            pub_date = (item.findtext("pubDate") or "").strip()
                            link = (item.findtext("link") or "").strip()
                            time_str = pub_date[17:22] if len(pub_date) > 22 else ""
                            date_str = pub_date[5:16] if len(pub_date) > 16 else ""
                            items.append({
                                "source": "РБК",
                                "time": time_str,
                                "date": date_str,
                                "title": title,
                                "url": link,
                                "important": False,
                                "raw_time": pub_date,
                            })
            except Exception:
                pass
    except Exception:
        pass

    if items:
        MARKET_NEWS_CACHE["ts"] = now
        MARKET_NEWS_CACHE["items"] = items

    return items[:limit]


async def handle_api_dashboard(request):
    if not _web_authorized(request):
        return _unauthorized()

    _migrate_orphan_trades()
    await _refresh_tracked_live_prices()

    uid = _get_primary_user_id()
    st = get_user_stats(uid)
    total = st["wins"] + st["losses"]
    wr = round((st["wins"] / total * 100), 1) if total > 0 else 0.0
    net_pct = round((st["compound_mult"] - 1.0) * 100.0, 2)
    history_list = [(x["text"] if isinstance(x, dict) else str(x)) for x in st["history"]]

    tracked_list = []
    for u_uid, u_sigs in TRACKED_SIGNALS.items():
        for tk, info in u_sigs.items():
            cur_p = _resolve_position_price(tk, info)
            entry_p = float(info["entry"])
            pnl_pct = ((cur_p - entry_p) / entry_p * 100) if info["side"] == "LONG" else ((entry_p - cur_p) / entry_p * 100)
            tracked_list.append({
                **info,
                "owner_uid": u_uid,
                "current_price": round(cur_p, 4),
                "pnl_pct": round(pnl_pct, 2),
                "is_be": abs(float(info["sl"]) - entry_p) / max(entry_p, 1e-9) < 0.002,
                "leverage": info.get("leverage", 1.0),
                "margin_rub": info.get("margin_rub", info.get("amount_rub")),
                "dep_pct": info.get("dep_pct"),
                "auto_partial_enabled": info.get("auto_partial_enabled", True),
                "partial_take_pct": info.get("partial_take_pct", 50),
                "partial_trigger_pct": info.get("partial_trigger_pct", 55),
            })

    now_ts = time.time()
    market_open = is_moex_trading_hours()
    if not MOEX_INDEX_CACHE.get("data") or (now_ts - MOEX_INDEX_CACHE.get("ts", 0)) > 120:
        try:
            sess = await get_session()
            await get_moex_index_context(sess)
        except Exception:
            pass
    robots_active = [
        v for v in ACTIVE_ROBOTS_REGISTRY.values()
        if (now_ts - v.get("updated_ts", 0)) < 1200
    ]

    stocks_list = []
    for name, ticker in LIQUID_WATCHLIST:
        s = WEB_SCAN_CACHE.get(ticker)
        inst = INSTRUMENTS_CACHE.get(ticker) or {}
        dlong = float(inst.get("dlong") or 0.0)
        dshort = float(inst.get("dshort") or 0.0)
        lev_l = float(inst.get("leverage_long") or (round(1.0 / dlong, 2) if dlong > 0 else 1.0))
        lev_s = float(inst.get("leverage_short") or (round(1.0 / dshort, 2) if dshort > 0 else 1.0))
        if s:
            s = dict(s)
            s["leverage_long"] = lev_l
            s["leverage_short"] = lev_s
            s["dlong"] = dlong
            s["dshort"] = dshort
            if ticker in LIVE_PRICES_CACHE and LIVE_PRICES_CACHE[ticker] > 0:
                s["price"] = LIVE_PRICES_CACHE[ticker]
            checked_ts = float(s.get("data_checked_ts", 0.0) or 0.0)
            elapsed_min = max(0.0, (now_ts - checked_ts) / 60.0) if checked_ts > 0 else 99999.0
            raw_activity_age = s.get("last_activity_age_min")
            raw_candle_age = s.get("last_candle_age_min")
            activity_age_now = (float(raw_activity_age) if raw_activity_age is not None else 99999.0) + elapsed_min
            s["last_candle_age_min_now"] = round((float(raw_candle_age) if raw_candle_age is not None else 99999.0) + elapsed_min, 1)
            s["iceberg_events"] = [e for e in (ICEBERG_STATE.get(ticker) or {}).get("events", []) if now_ts - e.get("ts", 0) < 300]
            s["ticker_live"] = signal_data_is_live(s, now_ts=now_ts, market_open=market_open)
            s["is_live_market"] = signal_data_is_live(
                s, now_ts=now_ts, require_candle=True, market_open=market_open
            )
            s["last_activity_age_min_now"] = round(activity_age_now, 1)
            if not s["is_live_market"]:
                s["verdict"] = "WAIT"
            if not s["ticker_live"]:
                s["score"] = 0
                s["verdict"] = "WAIT"
                s["factors"] = [
                    factor for factor in s.get("factors", [])
                    if "Скрытый набор" not in str(factor) and "Скрытая раздача" not in str(factor) and "Давление объёмом" not in str(factor)
                ]
            stocks_list.append(s)
        else:
            stocks_list.append({
                "ticker": ticker,
                "name": name,
                "price": LIVE_PRICES_CACHE.get(ticker, 0.0),
                "leverage_long": lev_l,
                "leverage_short": lev_s,
                "dlong": dlong,
                "dshort": dshort,
                "change": 0.0,
                "tf_key": "15m",
                "score": 0,
                "verdict": "WAIT",
                "calc_side": "LONG",
                "factors": ["📊 Базовая цена получена, расчёт снайперских уровней..."],
                "block_reasons": ["Синхронизация стакана и индикаторов..."],
                "robots": [],
                "cvd_data": {"bar_delta": 0, "cvd_today": 0, "cum_delta_change_6": 0, "delta_efficiency_6": 0},
                "mtf_cvd": {},
                "mtf_emas": {},
                "sr_levels": {"poc": 0, "res1_price": 0, "res1_dist_pct": 0, "sup1_price": 0, "sup1_dist_pct": 0},
                "entry": 0, "tp": 0, "sl": 0, "profit_pct": 0, "risk_pct": 0, "rr_ratio": 1.9,
                "rvol": 1.0,
            })

    stocks_list.sort(
        key=lambda x: (
            bool(x.get("ticker_live")) and any(v.get("absorption_side") or v.get("pressure_side") for v in x.get("mtf_cvd", {}).values()),
            x.get("verdict") in ("LONG", "SHORT"),
            abs(x.get("score", 0)),
        ),
        reverse=True,
    )

    all_history_items = []
    seen_texts = set()
    for item in st.get("history", []):
        item_text = item["text"] if isinstance(item, dict) else str(item)
        if item_text and item_text not in seen_texts:
            seen_texts.add(item_text)
            all_history_items.append(item_text)

    for u_id, u_st in USER_STATS.items():
        if u_id > 0 and u_id != uid:
            for item in u_st.get("history", []):
                item_text = item["text"] if isinstance(item, dict) else str(item)
                if item_text and item_text not in seen_texts:
                    seen_texts.add(item_text)
                    all_history_items.append(item_text)

    for u_id, u_st in USER_STATS.items():
        if u_id <= 0:
            for item in u_st.get("history", []):
                item_text = item["text"] if isinstance(item, dict) else str(item)
                if item_text and item_text not in seen_texts:
                    seen_texts.add(item_text)
                    all_history_items.append(item_text)

    history_list = list(all_history_items)

    return web.json_response({
        "server_time": datetime.now(MSK_TZ).strftime("%H:%M:%S МСК"),
        "market_open": market_open,
        "min_score": MIN_SCORE_FOR_ENTRY,
        "imoex": MOEX_INDEX_CACHE.get("data"),
        "stats": {
            "wins": st["wins"],
            "losses": st["losses"],
            "winrate": wr,
            "net_pct": net_pct,
            "history": history_list,
            "all_history": all_history_items,
        },
        "tracked": tracked_list,
        "pending_orders": list(PENDING_OPEN_ORDERS.values()),
        "robots": robots_active,
        "stocks": stocks_list,
        "tiers": {
            str(tier): [{"name": n, "ticker": t, "active": t in ACTIVE_TICKERS} for n, t in lst]
            for tier, lst in TIER_WATCHLISTS.items()
        },
        "active_count": len(ACTIVE_TICKERS),
        "deposit_rub": float(TRADING_DEPOSIT_RUB),
        "margin_summary": get_account_margin_summary(uid),
        "strats": _strats_dashboard(),
        "whales": collect_whale_events(stocks_list, now_ts)[:40],
        "news": await _fetch_market_news(),
        "dividend_calendar": get_moex_dividend_calendar_summary(),
    })


async def handle_api_analyze(request):
    ticker = request.query.get("ticker", "SBER").upper().strip()
    tf_key = request.query.get("tf", "15m").strip()
    if tf_key not in TIMEFRAMES:
        tf_key = "15m"

    if not _web_authorized(request):
        return _unauthorized()

    sig = await get_signal_cached(ticker, tf_key)
    candles = await _fetch_chart_series_for_web(ticker, tf_key)
    cvd_cov = float(((sig or {}).get("cvd_data") or {}).get("tape_cov_pct", 0.0) or 0.0)
    inst = INSTRUMENTS_CACHE.get(ticker) or {}
    dlong = float(inst.get("dlong") or 0.0)
    dshort = float(inst.get("dshort") or 0.0)
    lev_long = float(inst.get("leverage_long") or (round(1.0 / dlong, 2) if dlong > 0 else 1.0))
    lev_short = float(inst.get("leverage_short") or (round(1.0 / dshort, 2) if dshort > 0 else 1.0))

    # Снапшот биржевого стакана заявок L2 (Order Book)
    orderbook = {"bids": [], "asks": []}
    try:
        session = await get_session()
        inst_full = await ensure_instrument_loaded(session, ticker)
        uid = (inst_full or {}).get("uid") or inst.get("uid")
        if uid:
            ob_raw = await api_post("MarketDataService/GetOrderBook", {"instrumentId": uid, "depth": 10}, timeout=3)
            bids = []
            asks = []
            for b in ob_raw.get("bids", []):
                p = quotation_to_float(b.get("price")) if isinstance(b.get("price"), dict) else float(b.get("price", 0))
                q = int(b.get("quantity", 0))
                if p and p > 0 and q > 0:
                    bids.append({"price": round(float(p), 2), "quantity": q})
            for a in ob_raw.get("asks", []):
                p = quotation_to_float(a.get("price")) if isinstance(a.get("price"), dict) else float(a.get("price", 0))
                q = int(a.get("quantity", 0))
                if p and p > 0 and q > 0:
                    asks.append({"price": round(float(p), 2), "quantity": q})
            orderbook = {"bids": bids, "asks": asks}
    except Exception:
        pass

    return web.json_response({
        "signal": sig,
        "candles": candles,
        "orderbook": orderbook,
        "cvd_estimated": cvd_cov < CHART_CVD_LOW_COV_PCT,
        "tape_cov_pct": round(cvd_cov, 1),
        "candle_cov_pct": CHART_CVD_CANDLE_COV_PCT,
        "low_cov_pct": CHART_CVD_LOW_COV_PCT,
        "margin": {
            "dlong": dlong,
            "dshort": dshort,
            "leverage_long": lev_long,
            "leverage_short": lev_short,
            "short_enabled": bool(inst.get("short_enabled", True)),
        }
    })


async def handle_api_action(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    # Любое изменение состояния (сброс статистики, ручной вход) — только с паролем
    if not _web_authorized(request, body):
        return _unauthorized()

    action = body.get("action")
    uid = _get_primary_user_id()

    if action == "reset_stats":
        USER_STATS[uid] = {"wins": 0, "losses": 0, "compound_mult": 1.0, "history": deque()}
        await save_bot_state()
        return web.json_response({"ok": True})

    if action == "clear_tracked":
        for k in list(TRACKED_SIGNALS.keys()):
            TRACKED_SIGNALS[k] = {}
        await save_bot_state()
        return web.json_response({"ok": True})

    if action == "queue_open_order":
        ticker = str(body.get("ticker", "SBER")).upper().strip()
        side = str(body.get("side", "LONG")).upper().strip()
        dep_pct = float(body.get("dep_pct") or 20.0)
        use_lev = bool(body.get("use_leverage", True))
        auto_p = bool(body.get("auto_partial", True))
        c_tp = float(body.get("custom_tp") or 0.0)
        c_sl = float(body.get("custom_sl") or 0.0)
        max_gap = float(body.get("max_gap_pct") or 1.0)
        ref_p = float(body.get("ref_price") or LIVE_PRICES_CACHE.get(ticker) or 0.0)

        PENDING_OPEN_ORDERS[ticker] = {
            "ticker": ticker,
            "side": side,
            "dep_pct": dep_pct,
            "use_leverage": use_lev,
            "auto_partial": auto_p,
            "custom_tp": c_tp,
            "custom_sl": c_sl,
            "max_gap_pct": max_gap,
            "ref_price": ref_p,
            "created_at": datetime.now(MSK_TZ).strftime("%d.%m %H:%M"),
            "user_id": uid,
        }
        await save_bot_state(force=True)
        return web.json_response({"ok": True, "message": f"Ордер на открытие для {ticker} ({side}) добавлен. Макс. гэп: {max_gap:.1f}%."})

    if action == "cancel_open_order":
        ticker = str(body.get("ticker", "")).upper().strip()
        if ticker in PENDING_OPEN_ORDERS:
            del PENDING_OPEN_ORDERS[ticker]
            await save_bot_state(force=True)
            return web.json_response({"ok": True, "message": f"Ордер на открытие для {ticker} отменён."})
        return web.json_response({"ok": False, "error": "Ордер не найден."})

    if action == "track_manual":
        ticker = str(body.get("ticker", "SBER")).upper().strip()
        side_req = str(body.get("side") or "").upper().strip()
        dep_pct = float(body.get("dep_pct") or body.get("percent") or 0.0)
        use_leverage = bool(body.get("use_leverage", True))

        sig = await get_signal_cached(ticker, "15m")
        if sig and not sig.get("is_illiquid"):
            side = side_req if side_req in ("LONG", "SHORT") else sig["calc_side"]
            tgt = (sig.get("targets_by_side") or {}).get(side) or {}
            entry_v = float(tgt.get("entry") or sig["entry"])
            tp_v = float(tgt.get("tp") or sig["tp"])
            sl_v = float(tgt.get("sl") or sig["sl"])

            tps_raw = body.get("take_profits")
            take_profits_list = None
            if isinstance(tps_raw, list) and len(tps_raw) > 0:
                take_profits_list = []
                for item in tps_raw:
                    try:
                        p_val = float(item.get("price", 0.0))
                        pct_val = float(item.get("pct", 50.0))
                        if p_val > 0 and pct_val > 0:
                            take_profits_list.append({"price": round(p_val, 4), "pct": pct_val, "hit": False})
                    except Exception:
                        pass

            if "custom_tp" in body:
                c_tp = float(body.get("custom_tp") or 0.0)
                tp_v = round(c_tp, 4) if c_tp > 0 else 0.0
            if "custom_sl" in body:
                c_sl = float(body.get("custom_sl") or 0.0)
                sl_v = round(c_sl, 4) if c_sl > 0 else 0.0

            _inst = INSTRUMENTS_CACHE.get(ticker) or {}
            dlong = float(_inst.get("dlong") or 0.0)
            dshort = float(_inst.get("dshort") or 0.0)
            lev_long = float(_inst.get("leverage_long") or (round(1.0 / dlong, 2) if dlong > 0 else 1.0))
            lev_short = float(_inst.get("leverage_short") or (round(1.0 / dshort, 2) if dshort > 0 else 1.0))
            leverage = (lev_long if side == "LONG" else lev_short) if use_leverage else 1.0
            if leverage <= 0:
                leverage = 1.0

            dep_total = float(TRADING_DEPOSIT_RUB) if TRADING_DEPOSIT_RUB > 0 else 10_000_000.0
            margin_summary = get_account_margin_summary(uid)
            free_margin = margin_summary["free_margin_rub"]

            if dep_pct > 0:
                margin_rub = dep_total * (dep_pct / 100.0)
            else:
                margin_rub = position_amount_rub()
                dep_pct = round((margin_rub / dep_total) * 100.0, 1)

            # Проверка лимита свободной маржи
            if margin_rub > free_margin:
                if free_margin <= 500:
                    return web.json_response({
                        "ok": False,
                        "error": f"Недостаточно свободной маржи! Занято {margin_summary['used_margin_rub']:,.0f} ₽ из {dep_total:,.0f} ₽. Закройте или сократите другие позиции."
                    })
                # Если маржи частично хватает, открываем на доступный остаток
                margin_rub = free_margin
                dep_pct = round((margin_rub / dep_total) * 100.0, 1)

            buying_power = margin_rub * leverage
            _lot = max(int(_inst.get("lot", 1) or 1), 1)
            _entry_p = entry_v if entry_v > 0 else 1.0
            one_lot_rub = _entry_p * _lot
            _lots = max(1, int(buying_power / max(one_lot_rub, 1e-9)))
            real_amount = round(_lots * one_lot_rub, 0)
            actual_margin = round(real_amount / leverage, 0)

            auto_p_en = bool(body.get("auto_partial", True)) if body.get("auto_partial") is not None else True
            p_take = float(body.get("partial_take_pct", AUTO_PARTIAL_TAKE_PCT))
            p_trig = float(body.get("partial_trigger_pct", AUTO_PARTIAL_TRIGGER_PCT))

            TRACKED_SIGNALS.setdefault(uid, {})[ticker] = {
                "ticker": ticker,
                "name": sig["name"],
                "side": side,
                "entry": entry_v,
                "tp": tp_v,
                "sl": sl_v,
                "opened_at": datetime.now(MSK_TZ).strftime("%H:%M"),
                "partial_taken": False,
                "auto_partial_enabled": auto_p_en and (p_take > 0),
                "partial_take_pct": p_take,
                "partial_trigger_pct": p_trig,
                "dep_pct": dep_pct,
                "leverage": round(leverage, 2),
                "margin_rub": actual_margin,
                "amount_rub": actual_margin,
                "lots": _lots,
                "lot": _lot,
                "real_amount_rub": real_amount,
            }
            await save_bot_state()
        return web.json_response({
            "ok": True,
            "message": f"Сделка {side} {ticker} открыта на {real_amount:,.0f} ₽ ({_lots} лот.)",
            "ticker": ticker,
            "side": side,
            "entry": entry_v,
            "lots": _lots,
            "tp": tp_v,
            "sl": sl_v,
        })

    if action == "toggle_ticker":  # patch33: вкл/выкл бумаги из веб-панели (как в меню 🎛)
        ticker = str(body.get("ticker", "")).upper()
        if ticker in TICKER_TO_TIER:
            if ticker in ACTIVE_TICKERS:
                ACTIVE_TICKERS.discard(ticker)
            else:
                ACTIVE_TICKERS.add(ticker)
            rebuild_active_watchlist()
            BT_CACHE.clear()
            await save_bot_state(force=True)
            return web.json_response({"ok": True, "ticker": ticker, "active": ticker in ACTIVE_TICKERS, "count": len(LIQUID_WATCHLIST)})
        return web.json_response({"ok": False})

    if action == "tier_set":  # patch33: весь эшелон вкл/выкл
        try:
            tier = int(body.get("tier", 1))
        except (TypeError, ValueError):
            return web.json_response({"ok": False})
        on = bool(body.get("on", True))
        if tier in TIER_WATCHLISTS:
            for _, t in TIER_WATCHLISTS[tier]:
                if on:
                    ACTIVE_TICKERS.add(t)
                else:
                    ACTIVE_TICKERS.discard(t)
            rebuild_active_watchlist()
            BT_CACHE.clear()
            await save_bot_state(force=True)
            return web.json_response({"ok": True, "count": len(LIQUID_WATCHLIST)})
        return web.json_response({"ok": False})

    if action in ("panic_close_all", "emergency_flatten"):
        closed_results = []
        strat_uids = {st["uid"]: key for key, st in STRATS.items()}
        all_to_close = []
        for uid, ticks in list(TRACKED_SIGNALS.items()):
            is_strat = strat_uids.get(uid)
            for tick in list(ticks.keys()):
                all_to_close.append((tick, is_strat))

        for tick, strat_k in all_to_close:
            try:
                ok, msg = await close_tracked_position_by_market(tick, strat_key=strat_k)
                closed_results.append({"ticker": tick, "ok": ok, "message": msg})
            except Exception as e:
                closed_results.append({"ticker": tick, "ok": False, "message": str(e)})

        await save_bot_state(force=True)
        return web.json_response({
            "ok": True,
            "closed_count": len(closed_results),
            "details": closed_results,
            "message": f"🚨 Экстренно закрыто сделок: {len(closed_results)}"
        })

    if action == "untrack":  # Закрытие ручной сделки с сайта по текущей цене с записью в статистику
        ticker = str(body.get("ticker", "")).upper()
        ok, msg = await close_tracked_position_by_market(ticker)
        return web.json_response({"ok": True, "removed": ok, "message": msg})

    if action == "untrack_strat":  # Закрытие сделки стратегии с сайта по текущей цене
        key = str(body.get("strategy", ""))
        ticker = str(body.get("ticker", "")).upper()
        ok, msg = await close_tracked_position_by_market(ticker, strat_key=key)
        return web.json_response({"ok": True, "removed": ok, "message": msg})

    if action == "reduce_position":  # Сокращение позиции на X%
        ticker = str(body.get("ticker", "")).upper().strip()
        pct = float(body.get("reduce_pct", 50.0))
        ok, msg = await reduce_tracked_position(ticker, reduce_pct=pct)
        return web.json_response({"ok": ok, "message": msg})

    if action == "update_position_levels":  # Перемещение TP / SL / БУ и % фиксации
        ticker = str(body.get("ticker", "")).upper().strip()
        tp_v = float(body.get("tp")) if body.get("tp") is not None else None
        sl_v = float(body.get("sl")) if body.get("sl") is not None else None
        to_be_v = bool(body.get("to_be", False))
        part_take_v = float(body.get("partial_take_pct")) if body.get("partial_take_pct") is not None else None
        part_trig_v = float(body.get("partial_trigger_pct")) if body.get("partial_trigger_pct") is not None else None
        auto_p = bool(body.get("auto_partial_enabled")) if body.get("auto_partial_enabled") is not None else (bool(body.get("auto_partial")) if body.get("auto_partial") is not None else None)
        ok, msg = await update_tracked_position_levels(
            ticker, tp=tp_v, sl=sl_v, to_be=to_be_v,
            partial_take_pct=part_take_v, partial_trigger_pct=part_trig_v,
            auto_partial_enabled=auto_p
        )
        return web.json_response({"ok": ok, "message": msg})

    return web.json_response({"ok": False})


async def handle_api_cvd_csv(request):
    if not _web_authorized(request):
        return _unauthorized()
    if not CVD_STORE_ENABLED or not os.path.exists(CVD_ALERTS_CSV):
        return web.Response(text="no data yet", status=404)
    return web.FileResponse(
        CVD_ALERTS_CSV,
        headers={"Content-Disposition": 'attachment; filename="cvd_alerts.csv"'},
    )


async def handle_healthz(request):
    """Лёгкий health-check для Render/докера: не трогает T-Invest API."""
    return web.json_response({
        "ok": True,
        "market_open": is_moex_trading_hours(),
        "server_time": datetime.now(MSK_TZ).strftime("%H:%M:%S МСК"),
        "instruments": len(INSTRUMENTS_CACHE),
        "scan_cache": len(SCAN_CACHE),
        "cvd_store": CVD_STORE.stats() if CVD_STORE_ENABLED else {"enabled": False},
    })


async def run_honest_portfolio_backtest(days: int = 60) -> dict:
    """Честный портфельный бэктест по дневным свечам АКТИВНОГО watchlist (все ликвидные бумаги).

    На каждом дне считаем дневную модель: тренд EMA20/50 (±2) + синтетическая CVD-дельта
    за 6 дней (±2 при |перевес| >= BACKTEST_CVD_THRESHOLD_PCT). Вход LONG на закрытии дня
    при score >= 4; выход по TP +3% / SL -1.5% / удержание 5 дней.
    Реалистичный учет комиссий (двусторонняя 0.05% со всего оборота: 0.10% round-trip),
    учет утренних гэпов открытия и консервативное разрешение коллизий TP/SL.
    """
    session = await get_session()
    days = max(20, min(int(days), 180))
    thr = float(os.getenv("BACKTEST_CVD_THRESHOLD_PCT", "8"))
    tp_pct, sl_pct, hold_max, commission = 0.03, 0.015, 5, 0.0005
    per_ticker = []
    pnl_parts = []
    bt_cap = max(1, int(os.getenv("BACKTEST_MAX_TICKERS", "70")))
    bt_tickers = LIQUID_WATCHLIST[:bt_cap]
    skipped: list[str] = []

    for name, ticker in bt_tickers:
        inst = INSTRUMENTS_CACHE.get(ticker) or await ensure_instrument_loaded(session, ticker)
        if not inst:
            skipped.append(ticker)
            continue
        now_utc = datetime.now(timezone.utc)
        fetch_days = int((days + 60) * 1.7) + 10
        c = await api_post("MarketDataService/GetCandles", {
            "instrumentId": inst["uid"],
            "from": (now_utc - timedelta(days=fetch_days)).isoformat(),
            "to": now_utc.isoformat(),
            "interval": "CANDLE_INTERVAL_DAY",
        }, timeout=15)
        df = candles_to_df(c.get("candles", []), 0.0)
        if len(df) < 55:
            skipped.append(ticker)
            continue

        if len(df) > days + 55:
            df = df.iloc[-(days + 55):].reset_index(drop=True)

        close = df["Close"].to_numpy(dtype=float)
        opn = df["Open"].to_numpy(dtype=float)
        high = df["High"].to_numpy(dtype=float)
        low = df["Low"].to_numpy(dtype=float)
        vol = df["Volume"].to_numpy(dtype=float) if "Volume" in df.columns else np.zeros(len(df))
        ema20 = pd.Series(close).ewm(span=20, adjust=False).mean().to_numpy()
        ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().to_numpy()
        rng = np.maximum(high - low, 1e-9)
        ddelta = ((close - opn) / rng) * vol

        trades: list[float] = []
        equity = 100.0
        eq_curve = [equity]
        pos = None                                    # (entry, day, tp, sl)
        i = 50

        while i < len(df) - 1:
            if pos is not None:
                ep, ed, etp, esl = pos
                exit_p = None

                # 1. Проверка утреннего гэпа на открытии дня
                if opn[i] <= esl:
                    exit_p = float(opn[i])   # Стоп пробит утренним гэпом вниз
                elif opn[i] >= etp:
                    exit_p = float(opn[i])   # Тейк исполнен утренним гэпом вверх
                # 2. Коллизия: свеча дня коснулась и TP, и SL
                elif high[i] >= etp and low[i] <= esl:
                    # Консервативно: если цена открытия ниже входа или ближе к SL, считаем стоп
                    if opn[i] <= ep or (opn[i] - esl) <= (etp - opn[i]):
                        exit_p = float(esl)
                    else:
                        exit_p = float(etp)
                # 3. Обычное исполнение по дневному диапазону
                elif low[i] <= esl:
                    exit_p = float(esl)
                elif high[i] >= etp:
                    exit_p = float(etp)
                # 4. Выход по истечению максимального времени удержания
                elif i - ed >= hold_max:
                    exit_p = float(close[i])

                if exit_p is not None:
                    # Честный расчет PnL с двусторонней комиссией со всего оборота:
                    pnl = (exit_p * (1.0 - commission)) / (ep * (1.0 + commission)) - 1.0
                    trades.append(pnl)
                    equity *= (1.0 + pnl)
                    pos = None
                else:
                    i += 1
                    eq_curve.append(equity)
                    continue

            # Расчет сигнала входа
            c6 = float(ddelta[max(0, i - 5):i + 1].sum())
            v6 = float(vol[max(0, i - 5):i + 1].sum())
            eff = c6 / v6 * 100.0 if v6 > 0 else 0.0
            sc = 0
            if close[i] > ema20[i] >= ema50[i]:
                sc += 2
            elif close[i] < ema20[i] <= ema50[i]:
                sc -= 2
            if eff >= thr:
                sc += 2
            elif eff <= -thr:
                sc -= 2

            if sc >= 4 and pos is None:
                pos = (float(close[i]), i, float(close[i]) * (1.0 + tp_pct), float(close[i]) * (1.0 - sl_pct))

            i += 1
            eq_curve.append(equity)

        # Если на последней свече осталась открытая позиция
        if pos is not None:
            exit_p = float(close[-1])
            pnl = (exit_p * (1.0 - commission)) / (pos[0] * (1.0 + commission)) - 1.0
            trades.append(pnl)
            equity *= (1.0 + pnl)
            eq_curve.append(equity)

        wins = sum(1 for t in trades if t > 0)
        max_dd = 0.0
        peak = eq_curve[0]
        for v in eq_curve:
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak * 100.0)

        per_ticker.append({
            "ticker": ticker, "name": name, "trades": int(len(trades)), "wins": int(wins),
            "winrate": float(round(wins / len(trades) * 100.0, 1)) if trades else 0.0,
            "pnl_pct": float(round(float(equity) - 100.0, 2)), "max_dd_pct": float(round(max_dd, 2)),
        })
        pnl_parts.append(float(equity) - 100.0)

    all_trades = sum(p["trades"] for p in per_ticker)
    all_wins = sum(p["wins"] for p in per_ticker)
    return {
        "ok": True, "days": int(days), "tickers": len(per_ticker), "watchlist_size": len(LIQUID_WATCHLIST),
        "bt_cap": int(bt_cap), "skipped": skipped, "trades": int(all_trades),
        "winrate": float(round(all_wins / all_trades * 100.0, 1)) if all_trades else 0.0,
        "avg_pnl_per_ticker_pct": float(round(sum(pnl_parts) / len(pnl_parts), 2)) if pnl_parts else 0.0,
        "deposit_rub": float(TRADING_DEPOSIT_RUB),
        "pnl_rub": float(round((sum(pnl_parts) / len(pnl_parts) if pnl_parts else 0.0) / 100.0 * TRADING_DEPOSIT_RUB, 0)),
        "per_ticker": per_ticker,
        "note": "Честная дневная модель: двусторонняя комиссия 0.05%×2 со всего оборота, учет утренних гэпов открытия, консервативное разрешение коллизий TP/SL, EMA20/50 + CVD-дельта за 6 дней, вход LONG на закрытии при score≥4, TP +3% / SL −1.5% / холд 5 дней. Только исторические свечи, без данных из будущего.",
    }


async def handle_api_backtest(request: web.Request):
    if not _web_authorized(request):
        return _unauthorized()
    try:
        days = int(request.query.get("days", "60"))
    except (TypeError, ValueError):
        days = 60
    try:
        res = await run_honest_portfolio_backtest(days=days)
        return web.json_response(res)
    except Exception as e:
        logging.exception(f"/api/backtest: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)



async def handle_manifest(request):
    if os.path.exists("manifest.json"):
        return web.FileResponse("manifest.json", headers={"Content-Type": "application/manifest+json"})
    return web.json_response({
        "name": "MOEX // TradingGuru PRO",
        "short_name": "TradingGuru",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b0f17",
        "theme_color": "#0b0f17"
    })


async def handle_pwa_icon(request):
    name = request.match_info.get("filename", "apple-touch-icon.png")
    if os.path.exists(name):
        return web.FileResponse(name, headers={"Content-Type": "image/png"})
    return web.Response(status=404)

async def start_healthcheck_server():
    app = web.Application()
    app.router.add_get("/", handle_web_dashboard)
    app.router.add_get("/manifest.json", handle_manifest)
    app.router.add_get("/apple-touch-icon.png", handle_pwa_icon)
    app.router.add_get("/icon-192.png", handle_pwa_icon)
    app.router.add_get("/icon-512.png", handle_pwa_icon)
    app.router.add_get("/healthz", handle_healthz)
    app.router.add_get("/api/cvd.csv", handle_api_cvd_csv)
    app.router.add_get("/api/dashboard", handle_api_dashboard)
    app.router.add_get("/api/analyze", handle_api_analyze)
    app.router.add_post("/api/action", handle_api_action)
    app.router.add_get("/api/backtest", handle_api_backtest)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Веб-терминал и REST API запущены на порту {PORT}")
    if not WEB_SECRET:
        logging.warning("WEB_SECRET не задан: /api/* закрыты. Задайте WEB_SECRET в переменных окружения.")


# =====================================================================
# 11. ТОЧКА ВХОДА (ЕДИНЫЙ ФОНОВЫЙ МОНИТОР БЕЗ ДУБЛИРОВАНИЯ ЗАПРОСОВ)
# =====================================================================
async def main():
    logging.info("CVD использует обезличенную ленту; повторяющиеся торговые паттерны показываются только справочно и не влияют на сделки.")
    if not CLOUD_BACKUP_ENABLED:
        logging.warning("CLOUD_BACKUP_ENABLED=0: облачный бэкап ВЫКЛЮЧЕН — на Render (эфемерный диск) "
                        "винрейт и активные сделки НЕ переживут рестарт; задайте CLOUD_BACKUP_ENABLED=1")
    loop = asyncio.get_running_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_name, STOP_EVENT.set)
        except (NotImplementedError, RuntimeError):
            pass

    async def _stop_watcher():
        # patch32: на SIGTERM/SIGINT (напр. stop на Render) сразу force-сохраняем стейт и бэкапим cvd_data.db
        await STOP_EVENT.wait()
        logging.info("Сигнал остановки: force-сохранение стейта и бэкап CVD-файла...")
        try:
            await save_bot_state(force=True)
            await _backup_cvd_file_now(force=True)
        except Exception as e:
            logging.error(f"сохранение при остановке: {e}")

    asyncio.create_task(_stop_watcher())

    await start_healthcheck_server()
    await load_all_moex_shares()
    if not INSTRUMENTS_CACHE:
        if _LAST_AUTH_ERR_TS and (time.time() - _LAST_AUTH_ERR_TS) < 60:
            logging.error("Каталог MOEX пуст: T-Invest API отвечает 401/403 — проверьте T_INVEST_TOKEN")
        elif _LAST_TLS_ERR_TS and (time.time() - _LAST_TLS_ERR_TS) < 60:
            logging.error("Каталог MOEX пуст: TLS-сертификат invest-public-api.tbank.ru не доверен на этом хосте "
                          "(перехват трафика DPI/прокси) — задайте T_INVEST_CA_BUNDLE (корневой CA, напр. Минцифры) или T_INVEST_PROXY; см. подсказку выше")
        else:
            logging.error("Каталог MOEX пуст: сетевая ошибка до invest-public-api.tbank.ru (DNS/блокировка/прокси)")
    await load_bot_state()
    if CVD_STORE_ENABLED:
        await _restore_cvd_file_from_cloud()
        await asyncio.to_thread(CVD_STORE.load)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"delete_webhook: {e}")

    monitor_task = asyncio.create_task(realtime_market_monitor(), name="market_monitor")
    # patch34: на SIGTERM/SIGINT (STOP_EVENT, напр. stop/restart на Render) выходим из polling,
    # чтобы finally ниже ВСЕГДА выполнил force-сохранение стейта и CVD-файла
    poll_task = asyncio.create_task(dp.start_polling(bot), name="tg_polling")
    try:
        await asyncio.wait(
            [poll_task, asyncio.create_task(STOP_EVENT.wait(), name="stop_wait")],
            return_when=asyncio.FIRST_COMPLETED,
        )
        poll_task.cancel()
        try:
            await poll_task
        except (asyncio.CancelledError, Exception):
            pass
    finally:
        logging.info("Останавливаюсь: сохраняю состояние и закрываю соединения...")
        STOP_EVENT.set()
        monitor_task.cancel()
        try:
            await monitor_task
        except (asyncio.CancelledError, Exception):
            pass
        await save_bot_state(force=True)
        await _backup_cvd_file_now(force=True)
        if CVD_STORE_ENABLED:
            try:
                await asyncio.to_thread(CVD_STORE.close)
                logging.info("CVD-хранилище: данные сохранены")
            except Exception as e:
                logging.error(f"CVD-хранилище: ошибка при закрытии ({e})")
        if SESSION is not None and not SESSION.closed:
            await SESSION.close()
        CHART_EXECUTOR.shutdown(wait=False)
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен вручную")
