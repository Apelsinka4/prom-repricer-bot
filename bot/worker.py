"""
Фоновий процес (воркер) для перевірки цін.
Періодично перевіряє ціни конкурентів, та якщо потрібно — знижує ціни на Prom.ua.
"""

import asyncio
import logging

from aiogram import Bot

from bot import config
from bot.database import get_all_active_tasks, record_repricing_event
from bot.parser import parse_competitor_price
from bot.prom_api import get_product_info, update_prom_price

logger = logging.getLogger(__name__)

# Час між повними проходами та пауза між задачами керуються через env.
WORKER_INTERVAL = config.WORKER_INTERVAL_SECONDS
TASK_DELAY = config.WORKER_TASK_DELAY_SECONDS

STRATEGY_LABELS = {
    "beat_by_step": "дешевше на крок",
    "match_lowest": "дорівнювати мінімальній",
    "notify_only": "тільки сповіщати",
}


def _price_floor(min_price: float, cost_price: float | None, min_margin_percent: float | None) -> float:
    """Рахує нижню межу ціни з урахуванням мінімальної ціни та маржі."""
    floor = float(min_price)
    if cost_price is not None:
        margin = min_margin_percent or 0
        floor = max(floor, float(cost_price) * (1 + float(margin) / 100))
    return floor


def _calculate_target_price(strategy: str, competitor_price: float, step: float) -> float | None:
    if strategy == "notify_only":
        return None
    if strategy == "match_lowest":
        return competitor_price
    return competitor_price - step


async def _notify_error(bot: Bot, user_id: int, sku: str, text: str) -> None:
    try:
        await bot.send_message(
            user_id,
            f"⚠️ <b>Проблема з моніторингом</b>\n\n"
            f"🏷 Артикул: <code>{sku}</code>\n"
            f"{text}",
        )
    except Exception as exc:
        logger.error("Не вдалося відправити повідомлення користувачу %s: %s", user_id, exc)


async def worker_loop(bot: Bot) -> None:
    """Нескінченний цикл перевірки цін."""
    logger.info("Фоновий воркер запущено. Інтервал: %s сек.", WORKER_INTERVAL)

    while True:
        try:
            tasks = await get_all_active_tasks()
            if tasks:
                logger.info("Починаю перевірку %s завдань...", len(tasks))
            else:
                logger.debug("Немає активних завдань для перевірки.")

            for task in tasks:
                user_id = task["user_id"]
                sku = task["my_sku"]
                competitor_url = task["competitor_url"]
                competitor_urls = task.get("competitor_urls") or [competitor_url]
                min_price = task["min_price"]
                step = task["step"]
                strategy = task.get("strategy") or "beat_by_step"
                cost_price = task.get("cost_price")
                min_margin_percent = task.get("min_margin_percent")
                api_key = task["prom_api_key"]

                logger.debug("Перевірка завдання #%s (Користувач: %s, SKU: %s)", task["task_id"], user_id, sku)

                # 1. Парсимо ціни конкурентів і беремо найнижчу успішну
                parsed_prices: list[tuple[str, float]] = []
                for url in competitor_urls:
                    comp_price = await parse_competitor_price(url)
                    if comp_price is None:
                        await record_repricing_event(
                            task_id=task["task_id"],
                            user_id=user_id,
                            my_sku=sku,
                            status="parse_error",
                            strategy=strategy,
                            competitor_url=url,
                            reason="Не вдалося отримати ціну конкурента",
                            error="parse_competitor_price returned None",
                        )
                        continue
                    parsed_prices.append((url, comp_price))

                if not parsed_prices:
                    await record_repricing_event(
                        task_id=task["task_id"],
                        user_id=user_id,
                        my_sku=sku,
                        status="error",
                        strategy=strategy,
                        reason="Не вдалося отримати ціни жодного конкурента",
                    )
                    await _notify_error(
                        bot,
                        user_id,
                        sku,
                        "Не вдалося отримати ціни конкурентів. Перевірте URL товарів.",
                    )
                    await asyncio.sleep(TASK_DELAY)
                    continue

                competitor_url, comp_price = min(parsed_prices, key=lambda item: item[1])

                # 2. Отримуємо поточну ціну на Prom.ua
                prod_info = await get_product_info(api_key, sku)
                if not prod_info:
                    logger.warning("Не вдалося отримати інфо про товар %s для користувача %s", sku, user_id)
                    await record_repricing_event(
                        task_id=task["task_id"],
                        user_id=user_id,
                        my_sku=sku,
                        status="error",
                        strategy=strategy,
                        competitor_url=competitor_url,
                        competitor_price=comp_price,
                        reason="Товар не знайдено через Prom API",
                        error="get_product_info returned None",
                    )
                    await _notify_error(
                        bot,
                        user_id,
                        sku,
                        "Не вдалося знайти ваш товар у Prom API. Перевірте SKU або ID.",
                    )
                    await asyncio.sleep(TASK_DELAY)
                    continue

                current_price = prod_info["price"]
                product_id = prod_info["id"]

                # 3. Перевіряємо умови для зміни ціни
                if comp_price < current_price:
                    if strategy == "notify_only":
                        await record_repricing_event(
                            task_id=task["task_id"],
                            user_id=user_id,
                            my_sku=sku,
                            status="notified",
                            strategy=strategy,
                            competitor_url=competitor_url,
                            competitor_price=comp_price,
                            current_price=current_price,
                            reason="Конкурент дешевший, стратегія працює в режимі сповіщення",
                        )
                        try:
                            await bot.send_message(
                                user_id,
                                f"🔔 <b>Конкурент дешевший</b>\n\n"
                                f"🏷 Артикул: <code>{sku}</code>\n"
                                f"Ваша ціна: <b>{current_price:.2f} грн</b>\n"
                                f"Конкурент: <b>{comp_price:.2f} грн</b>\n"
                                f"Ціну не змінено, бо стратегія: <b>{STRATEGY_LABELS[strategy]}</b>.",
                            )
                        except Exception as e:
                            logger.error("Не вдалося відправити повідомлення користувачу %s: %s", user_id, e)
                        await asyncio.sleep(TASK_DELAY)
                        continue

                    new_price = _calculate_target_price(strategy, comp_price, step)
                    if new_price is None:
                        await asyncio.sleep(TASK_DELAY)
                        continue

                    # Перевіряємо ліміт рентабельності
                    floor = _price_floor(min_price, cost_price, min_margin_percent)
                    if new_price < floor:
                        new_price = floor

                    # Якщо після застосування ліміту нова ціна все ще нижча за поточну
                    if new_price < current_price:
                        logger.info(
                            "Товар %s: Зміна ціни з %.2f на %.2f (Конкурент: %.2f)",
                            sku, current_price, new_price, comp_price
                        )

                        # 4. Оновлюємо ціну на Prom.ua
                        success = await update_prom_price(api_key, sku, new_price, product_id=product_id)
                        
                        if success:
                            await record_repricing_event(
                                task_id=task["task_id"],
                                user_id=user_id,
                                my_sku=sku,
                                status="updated",
                                strategy=strategy,
                                competitor_url=competitor_url,
                                competitor_price=comp_price,
                                current_price=current_price,
                                new_price=new_price,
                                reason="Ціну оновлено згідно зі стратегією",
                            )
                            msg = (
                                f"✅ <b>Ціну оновлено!</b>\n\n"
                                f"🏷 Артикул: <code>{sku}</code>\n"
                                f"📉 Нова ціна: <b>{new_price:.2f} грн</b>\n"
                                f"🔗 Конкурент: {comp_price:.2f} грн\n"
                                f"📉 Ваша попередня ціна: {current_price:.2f} грн\n"
                                f"🎛 Стратегія: <b>{STRATEGY_LABELS.get(strategy, strategy)}</b>"
                            )
                            try:
                                await bot.send_message(user_id, msg)
                            except Exception as e:
                                logger.error("Не вдалося відправити повідомлення користувачу %s: %s", user_id, e)
                        else:
                            await record_repricing_event(
                                task_id=task["task_id"],
                                user_id=user_id,
                                my_sku=sku,
                                status="update_error",
                                strategy=strategy,
                                competitor_url=competitor_url,
                                competitor_price=comp_price,
                                current_price=current_price,
                                new_price=new_price,
                                reason="Prom API не підтвердив оновлення ціни",
                                error="update_prom_price returned False",
                            )
                            await _notify_error(
                                bot,
                                user_id,
                                sku,
                                f"Prom API не підтвердив оновлення ціни до <b>{new_price:.2f} грн</b>.",
                            )
                    else:
                        await record_repricing_event(
                            task_id=task["task_id"],
                            user_id=user_id,
                            my_sku=sku,
                            status="blocked_by_floor",
                            strategy=strategy,
                            competitor_url=competitor_url,
                            competitor_price=comp_price,
                            current_price=current_price,
                            new_price=new_price,
                            reason=(
                                "Ціну не змінено: мінімальна ціна або захист маржі "
                                "не дозволяє знизити нижче поточної"
                            ),
                        )
                else:
                    await record_repricing_event(
                        task_id=task["task_id"],
                        user_id=user_id,
                        my_sku=sku,
                        status="checked",
                        strategy=strategy,
                        competitor_url=competitor_url,
                        competitor_price=comp_price,
                        current_price=current_price,
                        reason="Ваша ціна не вища за найнижчу ціну конкурента",
                    )

                await asyncio.sleep(TASK_DELAY)

        except asyncio.CancelledError:
            logger.info("Воркер зупинено.")
            break
        except Exception as e:
            logger.exception("Несподівана помилка у фоновому воркері: %s", e)

        # Чекаємо до наступного запуску
        await asyncio.sleep(WORKER_INTERVAL)


def start_worker(bot: Bot) -> asyncio.Task:
    """Запускає воркер у фоновому завданні."""
    return asyncio.create_task(worker_loop(bot))
