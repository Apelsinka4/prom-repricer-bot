"""
Клієнт Prom.ua REST API.
Документація: https://my.prom.ua/api/v1/docs
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_BASE = "https://my.prom.ua/api/v1"
_TIMEOUT = aiohttp.ClientTimeout(total=10)


@dataclass
class PromApiResult:
    ok: bool
    status: int
    data: dict[str, Any] | None = None
    error: str | None = None


def get_headers(api_key: str) -> dict:
    """Генерує правильні заголовки для обходу WAF/Cloudflare."""
    return {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }


async def validate_api_key(api_key: str) -> PromApiResult:
    """Робить тестовий GET /products/list?limit=1."""
    url = f"{_BASE}/products/list"
    params = {"limit": 1}

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url, headers=get_headers(api_key), params=params) as resp:
                status = resp.status
                if status == 200:
                    data = await resp.json()
                    logger.info("Prom API key valid. Products found: %s", len(data.get("products", [])))
                    return PromApiResult(ok=True, status=status, data=data)
                elif status in (401, 403):
                    text = await resp.text()
                    logger.error("API Auth Error (Status %s): %s", status, text)
                    return PromApiResult(ok=False, status=status,
                                         error=f"Помилка {status}. Prom.ua відхилив запит (можливо токен недійсний). Відповідь: {text[:100]}")
                else:
                    text = await resp.text()
                    logger.warning("Prom API unexpected status %s: %s", status, text[:200])
                    return PromApiResult(ok=False, status=status, error=f"Несподіваний статус від Prom: {status}")

    except Exception as exc:
        logger.exception("Prom API unexpected error")
        return PromApiResult(ok=False, status=0, error=f"Помилка підключення: {exc}")


async def get_product_info(api_key: str, sku: str) -> dict[str, Any] | None:
    """Шукає товар на Prom.ua за артикулом (SKU) або ID."""
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            # 1. Припускаємо, що sku — це числовий ID товару
            if sku.isdigit():
                url = f"{_BASE}/products/{sku}"
                async with session.get(url, headers=get_headers(api_key)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "product" in data and "id" in data["product"]:
                            p = data["product"]
                            return {"id": p["id"], "price": float(p.get("price", 0))}

            # 2. Якщо не ID, шукаємо через список товарів (пошук по sku / external_id)
            url = f"{_BASE}/products/list"
            params = {"search_term": sku, "limit": 100}

            async with session.get(url, headers=get_headers(api_key), params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for p in data.get("products", []):
                        p_sku = str(p.get("sku") or "")
                        p_ext_id = str(p.get("external_id") or "")
                        p_id = str(p.get("id") or "")

                        if sku in (p_sku, p_ext_id, p_id):
                            return {"id": p["id"], "price": float(p.get("price", 0))}
    except Exception as exc:
        logger.exception("Помилка при отриманні інформації про товар %s: %s", sku, exc)

    return None


async def update_prom_price(api_key: str, sku: str, new_price: float, product_id: int | None = None) -> bool:
    """Оновлює ціну товару на Prom.ua."""
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            if not product_id:
                info = await get_product_info(api_key, sku)
                if not info:
                    logger.error("Товар з SKU/ID '%s' не знайдено на Prom.ua.", sku)
                    return False
                product_id = info["id"]

            url = f"{_BASE}/products/edit"
            payload = [{"id": product_id, "price": str(new_price)}]

            async with session.post(url, headers=get_headers(api_key), json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "processed_items" in data:
                        logger.info("Ціну для %s оновлено на Prom: %s грн", sku, new_price)
                        return True
                    else:
                        logger.error("Помилка від Prom.ua при оновленні: %s", data)
                        return False
                else:
                    text = await resp.text()
                    logger.error("HTTP %s при оновленні ціни для %s: %s", resp.status, sku, text)
                    return False

    except Exception as exc:
        logger.exception("Виняток при оновленні ціни для %s: %s", sku, exc)
        return False