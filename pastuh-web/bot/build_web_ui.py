# -*- coding: utf-8 -*-
"""
Генератор web_ui.py — вшивает собранный index.html прямо в код бота.

Запуск:
    python3 build_web_ui.py ../dist/index.html

После этого отдельный index.html на диске не нужен: бот отдаёт страницу
из памяти (gzip), что быстрее и не ломается при деплое.
"""

import base64
import gzip
import os
import sys

HEADER = '''# -*- coding: utf-8 -*-
"""
ВЕБ-ТЕРМИНАЛ, ВШИТЫЙ В КОД БОТА  (автогенерация build_web_ui.py — не править руками)
"""

import base64
import gzip

_B64 = (
'''

FOOTER = '''
)

#: Готовый gzip-блоб страницы — можно отдавать напрямую с Content-Encoding: gzip
INDEX_GZIP: bytes = base64.b64decode(_B64)

_CACHE: str | None = None


def render_index() -> str:
    """Распакованный HTML веб-терминала (кэшируется после первого вызова)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = gzip.decompress(INDEX_GZIP).decode("utf-8")
    return _CACHE


def index_bytes(accept_encoding: str = "") -> tuple[bytes, dict]:
    """(тело, заголовки) — сам выбирает gzip или plain по Accept-Encoding."""
    if "gzip" in (accept_encoding or "").lower():
        return INDEX_GZIP, {{"Content-Encoding": "gzip", "Vary": "Accept-Encoding"}}
    return render_index().encode("utf-8"), {{}}


SIZE_RAW = {raw}
SIZE_GZIP = {gz}
'''


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "dist/index.html"
    if not os.path.exists(src):
        print(f"[!] не найден {src}")
        return 1
    raw = open(src, "rb").read()
    comp = gzip.compress(raw, 9)
    b64 = base64.b64encode(comp).decode("ascii")
    body = "\n".join('    "%s"' % b64[i:i + 116] for i in range(0, len(b64), 116))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_ui.py")
    with open(out, "w", encoding="utf-8") as f:
        f.write(HEADER + body + FOOTER.format(raw=len(raw), gz=len(comp)))
    print(f"[+] {out}: {len(raw)//1024} КБ -> gzip {len(comp)//1024} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
