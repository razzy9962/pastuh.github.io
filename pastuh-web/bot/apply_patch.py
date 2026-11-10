# -*- coding: utf-8 -*-
"""
АВТОПАТЧЕР investrobot.py  →  15 стратегий + вшитый сайт
=========================================================

Запуск (из папки, где лежит бот):
    python3 apply_patch.py "investrobot (18).py"

Что делает (каждый шаг идемпотентен — повторный запуск ничего не сломает):
  1. импортирует strategies.py и web_ui.py;
  2. заменяет каталог STRATS на 15 стратегий;
  3. переключает strategy_side() на новый движок;
  4. добавляет в cvd_data честные тейп-поля (настоящий CVD по ленте);
  5. учит автовход уважать лимит позиций и кулдаун КАЖДОЙ стратегии;
  6. отдаёт сайт из памяти (gzip), без index.html на диске.

Перед изменениями создаётся резервная копия <файл>.bak
"""

import os
import re
import shutil
import sys

MARK = "# >>> MULTISTRAT PATCH"


# ---------------------------------------------------------------- helpers
def _say(ok: bool, text: str) -> None:
    print(("  [+] " if ok else "  [=] ") + text)


# ---------------------------------------------------------------- шаг 1
def step_imports(src: str) -> tuple[str, bool]:
    if "from strategies import" in src:
        return src, False
    anchor = "from aiogram import Bot, Dispatcher, F"
    inject = (
        f"{MARK}: движок стратегий и вшитый веб-терминал\n"
        "from strategies import (\n"
        "    STRATS_EXT,\n"
        "    strategy_side_ext,\n"
        "    strategy_risk,\n"
        "    strategy_targets,\n"
        "    real_cvd,\n"
        ")\n"
        "try:\n"
        "    from web_ui import index_bytes as _embedded_index_bytes\n"
        "except Exception:\n"
        "    _embedded_index_bytes = None\n"
        f"# <<< MULTISTRAT PATCH\n\n"
    )
    if anchor not in src:
        return src, False
    return src.replace(anchor, inject + anchor, 1), True


# ---------------------------------------------------------------- шаг 2
def step_strats_dict(src: str) -> tuple[str, bool]:
    if "STRATS = STRATS_EXT" in src:
        return src, False
    pat = re.compile(r"^STRATS\s*=\s*\{.*?^\}\s*$", re.S | re.M)
    if not pat.search(src):
        return src, False
    repl = (
        f"{MARK}: каталог из 15 стратегий живёт в strategies.py\n"
        "STRATS = STRATS_EXT\n"
        "# <<< MULTISTRAT PATCH\n"
    )
    return pat.sub(repl, src, count=1), True


# ---------------------------------------------------------------- шаг 3
def step_strategy_side(src: str) -> tuple[str, bool]:
    if "strategy_side_ext(" in src and "def strategy_side(" in src and "MULTISTRAT" in src.split("def strategy_side(")[1][:400]:
        return src, False
    start = src.find("def strategy_side(")
    if start == -1:
        return src, False
    nxt = src.find("\ndef maybe_auto_enter_strats", start)
    if nxt == -1:
        return src, False
    new_fn = (
        "def strategy_side(key: str, sig: dict) -> str | None:\n"
        f"    {MARK}\n"
        '    """Сторона автовхода стратегии. Логика вынесена в strategies.py (15 стратегий)."""\n'
        "    return strategy_side_ext(\n"
        "        key,\n"
        "        sig,\n"
        "        ctx={\n"
        '            "news": MARKET_NEWS_CACHE.get("items") or [],\n'
        '            "iceberg_state": ICEBERG_STATE,\n'
        '            "book_state": BOOK_STATE,\n'
        "        },\n"
        "    )\n"
    )
    return src[:start] + new_fn + src[nxt:], True


# ---------------------------------------------------------------- шаг 4
def step_tape_fields(src: str) -> tuple[str, bool]:
    if '"tape_net_lots"' in src:
        return src, False
    anchor = '        "pressure_desc": pressure_desc,\n'
    if anchor not in src:
        return src, False
    inject = anchor + (
        f"        {MARK}: НАСТОЯЩИЙ CVD — только по ленте реальных сделок\n"
        '        "tape_buy_vol": float(tape_buy_vol),\n'
        '        "tape_sell_vol": float(tape_sell_vol),\n'
        '        "tape_net_lots": float(tape_buy_vol - tape_sell_vol),\n'
        '        "tape_cum_delta": float(last["tape_cum_delta"]) if "tape_cum_delta" in df.columns else 0.0,\n'
        '        "tape_delta_bar": float(last["tape_delta"]) if "tape_delta" in df.columns else 0.0,\n'
        "        # <<< MULTISTRAT PATCH\n"
    )
    return src.replace(anchor, inject, 1), True


# ---------------------------------------------------------------- шаг 5
def step_per_strategy_limits(src: str) -> tuple[str, bool]:
    changed = False
    old_limit = "        if ticker in user_sigs or len(user_sigs) >= STRAT_MAX_POSITIONS:\n            continue"
    new_limit = (
        f"        {MARK}: лимит позиций и кулдаун — у каждой стратегии свои\n"
        "        _risk = strategy_risk(key)\n"
        "        if ticker in user_sigs or len(user_sigs) >= int(_risk.get(\"max_pos\", STRAT_MAX_POSITIONS)):\n"
        "            continue"
    )
    if old_limit in src:
        src = src.replace(old_limit, new_limit, 1)
        changed = True

    old_cd = "        if now_ts - LAST_SIGNAL_TIME.get((uid, ticker), 0) <= SIGNAL_COOLDOWN_SECONDS:\n            continue"
    new_cd = (
        "        if now_ts - LAST_SIGNAL_TIME.get((uid, ticker), 0) <= int(_risk.get(\"cooldown\", SIGNAL_COOLDOWN_SECONDS)):\n"
        "            continue"
    )
    if old_cd in src:
        src = src.replace(old_cd, new_cd, 1)
        changed = True

    # цели с учётом риск-профиля стратегии
    old_tp = (
        '        tp = float(t.get("tp") or (entry * 1.03 if side == "LONG" else entry * 0.97))\n'
        '        sl = float(t.get("sl") or (entry * 0.985 if side == "LONG" else entry * 1.015))'
    )
    new_tp = (
        f"        {MARK}: TP/SL по риск-профилю стратегии (множители ATR)\n"
        "        _tg = strategy_targets(key, sig, side) or {}\n"
        '        tp = float(_tg.get("tp") or t.get("tp") or (entry * 1.03 if side == "LONG" else entry * 0.97))\n'
        '        sl = float(_tg.get("sl") or t.get("sl") or (entry * 0.985 if side == "LONG" else entry * 1.015))'
    )
    if old_tp in src:
        src = src.replace(old_tp, new_tp, 1)
        changed = True

    return src, changed


# ---------------------------------------------------------------- шаг 6
def step_embedded_site(src: str) -> tuple[str, bool]:
    if "сайт вшит в код бота" in src:
        return src, False
    old = '    if os.path.exists("index.html"):\n        return web.FileResponse("index.html")'
    if old not in src:
        return src, False
    new = (
        f"    {MARK}: сайт вшит в код бота (web_ui.py), файл на диске не нужен\n"
        "    if _embedded_index_bytes is not None:\n"
        "        _body, _hdrs = _embedded_index_bytes(request.headers.get(\"Accept-Encoding\", \"\"))\n"
        "        _hdrs[\"Cache-Control\"] = \"no-cache\"\n"
        "        return web.Response(body=_body, content_type=\"text/html\", charset=\"utf-8\", headers=_hdrs)\n"
        "    if os.path.exists(\"index.html\"):\n"
        "        return web.FileResponse(\"index.html\")"
    )
    return src.replace(old, new, 1), True


# ---------------------------------------------------------------- шаг 7
def step_fix_fstring(src: str) -> tuple[str, bool]:
    """
    Чинит SyntaxError на Python <= 3.11: бэкслэш (\\n) внутри выражения f-строки.
    Это не правка логики, а условие запуска: иначе файл не компилируется вовсе.
    """
    lines = src.split("\n")
    hit = -1
    for i, ln in enumerate(lines):
        # ищем f-строку, где внутри {...} есть экранированный перевод строки
        if "auto_badge" in ln and "short_proposal" in ln and "\\n'" in ln:
            hit = i
            break
    if hit == -1:
        return src, False

    indent = " " * (len(lines[hit]) - len(lines[hit].lstrip()))
    lines[hit] = (
        f"{indent}{MARK}: вынесли перевод строки из выражения f-строки (Python <=3.11)\n"
        f'{indent}f"{{auto_badge}}{{_div_pump_note if sig.get(\'short_proposal\') else \'\'}}{{side_header}}\\n"'
    )
    src = "\n".join(lines)

    # объявляем константу рядом с остальными настройками
    anchor = "MSK_TZ = timezone(timedelta(hours=3))"
    if anchor in src and "_div_pump_note" not in src.split(anchor)[0]:
        src = src.replace(
            anchor,
            "_div_pump_note = \"⚠️ <b>ДИВЕРГЕНЦИЯ-ПАМП: предлагается ШОРТ (эвристика)</b>\" + \"\\\\n\"\n"
            + anchor,
            1,
        )
    return src, True


STEPS = [
    ("фикс f-string (запуск на Python 3.11)", step_fix_fstring),
    ("импорт движка стратегий + вшитого сайта", step_imports),
    ("каталог STRATS → 15 стратегий", step_strats_dict),
    ("strategy_side() → новый движок", step_strategy_side),
    ("честные тейп-поля CVD в cvd_data", step_tape_fields),
    ("лимиты/кулдаун/цели по каждой стратегии", step_per_strategy_limits),
    ("отдача сайта из памяти (gzip)", step_embedded_site),
]


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "investrobot.py"
    if not os.path.exists(path):
        print(f"[!] не найден файл бота: {path}")
        print('    укажи путь: python3 apply_patch.py "investrobot (18).py"')
        return 1

    here = os.path.dirname(os.path.abspath(__file__))
    for need in ("strategies.py", "web_ui.py"):
        if not os.path.exists(os.path.join(here, need)):
            print(f"[!] рядом с apply_patch.py должен лежать {need}")
            return 1

    src = open(path, encoding="utf-8").read()
    backup = path + ".bak"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print(f"[i] резервная копия: {backup}")

    print("[i] применяю патчи:")
    total = 0
    for title, fn in STEPS:
        src, done = fn(src)
        _say(done, title)
        total += int(done)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)

    print(f"[i] изменений внесено: {total}/{len(STEPS)}")
    print("[i] проверяю синтаксис…")
    import py_compile

    try:
        py_compile.compile(path, doraise=True)
        print("[+] синтаксис в порядке — можно запускать бота")
    except py_compile.PyCompileError as e:
        print(f"[!] синтаксическая ошибка: {e}")
        print(f"    откат: cp '{backup}' '{path}'")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
