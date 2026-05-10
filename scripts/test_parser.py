"""
Тести модуля parser.py.

Частина 1 — unit-тести (без мережі):
  • _to_float()         — різні формати рядків ціни
  • _is_captcha()       — виявлення сторінок-блокувань
  • _extract_price()    — витягування ціни з мок-HTML

Частина 2 — live-тест (потребує інтернету, пропускається при --no-live):
  • parse_competitor_price() — реальний запит на задану URL

Запуск:
    python -m scripts.test_parser             # лише unit
    python -m scripts.test_parser --live <url>  # unit + live
"""

import asyncio
import io
import sys
from pathlib import Path
from textwrap import dedent

# UTF-8 консоль (Windows)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.parser import (
    _to_float,
    _is_captcha,
    _extract_price,
    parse_competitor_price,
)

PASS = "[PASS]"
FAIL = "[FAIL]"
errors: list[str] = []


def check(name: str, got, expected) -> None:
    if got == expected:
        print(f"  {PASS}  {name}")
    else:
        msg = f"  {FAIL}  {name}  →  got={got!r}  expected={expected!r}"
        print(msg)
        errors.append(msg)


# ──────────────────────────────────────────────
# 1. _to_float
# ──────────────────────────────────────────────

def test_to_float() -> None:
    print("\n── _to_float() ─────────────────────────────")
    cases = [
        ("integer",             "1299",          1299.0),
        ("float dot",           "1299.50",       1299.50),
        ("float comma",         "1299,50",       1299.50),
        ("space thousands",     "1 299",         1299.0),
        ("nbsp thousands",      "1\u00a0299",    1299.0),
        ("narrow nbsp",         "1\u202f299",    1299.0),
        ("space + comma dec",   "1 299,99",      1299.99),
        ("space + dot dec",     "1 299.99",      1299.99),
        ("currency suffix",     "1 299 грн",     1299.0),
        ("currency prefix",     "₴1299",         1299.0),
        ("raw int",             1299,            1299.0),
        ("raw float",           99.9,            99.9),
        ("zero",                "0",             None),
        ("negative",            "-100",          None),
        ("empty string",        "",              None),
        ("pure text",           "немає ціни",    None),
        ("None input",          None,            None),
    ]
    for name, raw, expected in cases:
        check(name, _to_float(raw), expected)


# ──────────────────────────────────────────────
# 2. _is_captcha
# ──────────────────────────────────────────────

def test_is_captcha() -> None:
    print("\n── _is_captcha() ────────────────────────────")
    cases = [
        ("cloudflare challenge",  "<html>CloudFlare Challenge</html>",     True),
        ("captcha keyword",       "<html>Please solve the captcha</html>", True),
        ("access denied",         "<html>Access Denied</html>",            True),
        ("robot check",           "<html>Are you a robot?</html>",         True),
        ("normal page",           "<html><body>Купити товар</body></html>", False),
        ("price page",            "<html>Ціна: 999 грн</html>",            False),
    ]
    for name, html, expected in cases:
        check(name, _is_captcha(html), expected)


# ──────────────────────────────────────────────
# 3. _extract_price — мок-HTML
# ──────────────────────────────────────────────

def test_extract_price() -> None:
    print("\n── _extract_price() ─────────────────────────")

    # ── Стратегія 1: JSON-LD Product ──────────
    html_jsonld_product = dedent("""
        <html><head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Тестовий товар",
          "offers": {
            "@type": "Offer",
            "price": "1299.00",
            "priceCurrency": "UAH"
          }
        }
        </script>
        </head><body></body></html>
    """)
    check("JSON-LD Product.offers.price", _extract_price(html_jsonld_product), 1299.0)

    # ── Стратегія 1: JSON-LD масив ─────────────
    html_jsonld_array = dedent("""
        <html><head>
        <script type="application/ld+json">
        [
          {"@type": "WebSite", "name": "Prom"},
          {
            "@type": "Product",
            "offers": {"@type": "AggregateOffer", "lowPrice": 899, "priceCurrency": "UAH"}
          }
        ]
        </script>
        </head><body></body></html>
    """)
    check("JSON-LD array + lowPrice", _extract_price(html_jsonld_array), 899.0)

    # ── Стратегія 2: meta itemprop ─────────────
    html_meta = dedent("""
        <html><head>
          <meta itemprop="price" content="749.90">
        </head><body></body></html>
    """)
    check("meta itemprop=price", _extract_price(html_meta), 749.90)

    # ── Стратегія 2: og:price:amount ──────────
    html_og = dedent("""
        <html><head>
          <meta property="og:price:amount" content="2 500">
        </head><body></body></html>
    """)
    check("meta og:price:amount (space thousands)", _extract_price(html_og), 2500.0)

    # ── Стратегія 3: data-qaid ─────────────────
    html_qaid = dedent("""
        <html><body>
          <span data-qaid="product_price">1\u00a0599\u00a0грн</span>
        </body></html>
    """)
    check("data-qaid=product_price", _extract_price(html_qaid), 1599.0)

    # ── Стратегія 3: data-price attr ──────────
    html_data_price = dedent("""
        <html><body>
          <div data-price="450.00">450 грн</div>
        </body></html>
    """)
    check("data-price attribute", _extract_price(html_data_price), 450.0)

    # ── Стратегія 4: CSS .js-price-value ──────
    html_css = dedent("""
        <html><body>
          <span class="js-price-value">3 200</span>
        </body></html>
    """)
    check("CSS .js-price-value", _extract_price(html_css), 3200.0)

    # ── Стратегія 4: itemprop=price tag ───────
    html_itemprop_span = dedent("""
        <html><body>
          <span itemprop="price" content="670">670</span>
        </body></html>
    """)
    check("itemprop=price span content attr", _extract_price(html_itemprop_span), 670.0)

    # ── Немає ціни на сторінці ─────────────────
    html_no_price = "<html><body><p>Товар відсутній</p></body></html>"
    check("no price at all → None", _extract_price(html_no_price), None)

    # ── Декілька кандидатів — береться перший ─
    html_multi = dedent("""
        <html><head>
        <script type="application/ld+json">
        {"@type":"Product","offers":{"price":555}}
        </script>
        <meta itemprop="price" content="666">
        </head><body></body></html>
    """)
    check("JSON-LD wins over meta", _extract_price(html_multi), 555.0)


# ──────────────────────────────────────────────
# 4. Live-тест (необов'язковий)
# ──────────────────────────────────────────────

async def test_live(url: str) -> None:
    print(f"\n── live: parse_competitor_price() ──────────")
    print(f"  URL: {url}")
    price = await parse_competitor_price(url)
    if price is not None:
        print(f"  {PASS}  Ціна: {price:.2f} грн")
    else:
        print(f"  [WARN]  Ціну не вдалося отримати (None)")


# ──────────────────────────────────────────────
# Точка входу
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 52)
    print("  Тест модуля parser.py — Prom Repricer Bot")
    print("=" * 52)

    test_to_float()
    test_is_captcha()
    test_extract_price()

    # Live-тест якщо передано --live <url>
    live_url: str | None = None
    if "--live" in sys.argv:
        idx = sys.argv.index("--live")
        if idx + 1 < len(sys.argv):
            live_url = sys.argv[idx + 1]

    if live_url:
        asyncio.run(test_live(live_url))

    # Підсумок
    print("\n" + "=" * 52)
    if errors:
        print(f"  FAILED: {len(errors)} помилок")
        for e in errors:
            print(f"    {e}")
        sys.exit(1)
    else:
        print(f"  Всі unit-тести пройдено успішно!")
