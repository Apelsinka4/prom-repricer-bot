from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Optional

from bs4 import BeautifulSoup
import nodriver as uc

from bot import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_BACKOFF = 2.0

_CAPTCHA_HINTS = (
    "access denied",
    "are you a robot",
    "captcha",
    "cf-challenge",
    "challenge-platform",
    "cloudflare challenge",
    "<title>just a moment...</title>",
)


def _extract_via_json_ld(soup: BeautifulSoup) -> Optional[float]:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            raw = tag.string or ""
            data = json.loads(raw)
            candidates = data if isinstance(data, list) else [data]

            for item in candidates:
                if item.get("@type") in ("Product", "IndividualProduct"):
                    offers = item.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0]
                    price = offers.get("price") or offers.get("lowPrice")
                    if price is not None:
                        return _to_float(price)

                if item.get("@type") in ("Offer", "AggregateOffer"):
                    price = item.get("price") or item.get("lowPrice")
                    if price is not None:
                        return _to_float(price)
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue
    return None


def _extract_via_meta(soup: BeautifulSoup) -> Optional[float]:
    selectors = [
        {"itemprop": "price"},
        {"property": "og:price:amount"},
        {"name": "price"},
        {"property": "product:price:amount"},
    ]
    for attrs in selectors:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            val = _to_float(tag["content"])
            if val is not None:
                return val
    return None


def _extract_via_data_attrs(soup: BeautifulSoup) -> Optional[float]:
    for qaid in ("product_price", "price", "price_value"):
        tag = soup.find(attrs={"data-qaid": qaid})
        if tag:
            val = _to_float(tag.get_text(strip=True))
            if val is not None:
                return val

    tag = soup.find(attrs={"data-price": True})
    if tag:
        val = _to_float(tag["data-price"])
        if val is not None:
            return val

    tag = soup.find(attrs={"data-initial-price": True})
    if tag:
        val = _to_float(tag["data-initial-price"])
        if val is not None:
            return val
    return None


def _extract_via_css(soup: BeautifulSoup) -> Optional[float]:
    selectors = [
        "[class*='price'][class*='product']",
        "[class*='ProductPrice']",
        "[class*='product-price']",
        ".js-price-value",
        ".price-value",
        "[class*='Price__value']",
        "[class*='price__value']",
        "span[class*='price']",
        "[itemprop='price']",
        ".b-product-cost__price",
        ".js-product-price",
    ]
    for sel in selectors:
        try:
            tags = soup.select(sel)
            for tag in tags:
                for attr in ("content", "data-price", "value"):
                    if tag.get(attr):
                        val = _to_float(tag[attr])
                        if val is not None:
                            return val
                val = _to_float(tag.get_text(strip=True))
                if val is not None:
                    return val
        except Exception:
            continue
    return None


def _extract_price(html: str) -> Optional[float]:
    soup = BeautifulSoup(html, "html.parser")
    strategies = [
        ("JSON-LD", _extract_via_json_ld),
        ("meta-tags", _extract_via_meta),
        ("data-attrs", _extract_via_data_attrs),
        ("css-selectors", _extract_via_css),
    ]

    for name, fn in strategies:
        try:
            price = fn(soup)
            if price is not None and price > 0:
                logger.debug("Ціну знайдено через стратегію «%s»: %s", name, price)
                return price
        except Exception as exc:
            logger.debug("Стратегія «%s» завершилась помилкою: %s", name, exc)
    return None


_PRICE_RE = re.compile(r"[\d\s\u00a0\u202f]+[.,]?\d*")


def _to_float(raw: object) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip()
    if "-" in text:
        return None
    text = re.sub(r"[^\d.,\s]", " ", text)
    m = _PRICE_RE.search(text)
    if not m:
        return None
    clean = m.group().replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    clean = clean.replace(",", ".")
    parts = clean.split(".")
    if len(parts) > 2:
        clean = "".join(parts[:-1]) + "." + parts[-1]
    try:
        result = float(clean)
        return result if result > 0 else None
    except ValueError:
        return None


def _is_captcha(html: str) -> bool:
    lower = html.lower()
    return any(hint in lower for hint in _CAPTCHA_HINTS)


async def parse_competitor_price(url: str) -> Optional[float]:
    last_error: str = ""

    for attempt in range(1, MAX_RETRIES + 1):
        backoff = BASE_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0.5, 1.5)
        browser = None

        try:
            browser = await uc.start(headless=config.SCRAPER_HEADLESS)
            page = await browser.get(url)

            await asyncio.sleep(8)
            html = await page.get_content()

            price = _extract_price(html)
            if price is not None:
                logger.info("[%s] Ціна знайдена: %.2f грн (спроба %d).", url, price, attempt)
                return price

            if _is_captcha(html):
                last_error = "CAPTCHA/блокування виявлено"
                logger.warning("[%s] Спроба %d/%d — %s. Backoff %.1fs…", url, attempt, MAX_RETRIES, last_error, backoff)
                await asyncio.sleep(backoff)
                continue

        except asyncio.TimeoutError:
            last_error = "Timeout"
            logger.warning("[%s] Спроба %d/%d — Timeout. Backoff %.1fs…", url, attempt, MAX_RETRIES, backoff)
            await asyncio.sleep(backoff)

        except Exception as exc:
            last_error = f"Несподівана помилка: {exc}"
            logger.exception("[%s] Спроба %d/%d — %s.", url, attempt, MAX_RETRIES, last_error)
            await asyncio.sleep(backoff)

        finally:
            if browser:
                browser.stop()

    logger.error("[%s] Всі %d спроби вичерпано. Остання помилка: %s", url, MAX_RETRIES, last_error)
    return None


if __name__ == "__main__":
    test_url = "https://prom.ua/ua/p3012797759-fleshka-usb-nael.html"
    price = asyncio.run(parse_competitor_price(test_url))
    print(f"Зібрана ціна: {price}")
