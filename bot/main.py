"""
Точка входу — запускає бота та ініціалізує БД.

Запуск:
    python -m bot.main
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot import config
from bot.database import init_db, close_db
from bot.handlers import common, settings, tasks
from bot.middlewares import RateLimitMiddleware
from bot.worker import start_worker

# ──────────────────────────────────────────────
# Логування
# ──────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    # Валідуємо токен одразу — до будь-яких звернень до aiogram
    config.validate()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # MemoryStorage — для MVP достатньо; замінити на RedisStorage у продакшені
    dp = Dispatcher(storage=MemoryStorage())
    rate_limiter = RateLimitMiddleware()
    dp.message.middleware(rate_limiter)
    dp.callback_query.middleware(rate_limiter)

    # ── Реєстрація роутерів ────────────────────
    # Порядок важливий: settings має свій fsm:cancel,
    # тому підключаємо його до того як tasks
    dp.include_router(common.router)
    dp.include_router(settings.router)
    dp.include_router(tasks.router)

    # ── Lifecycle-хуки ─────────────────────────
    @dp.startup()
    async def on_startup() -> None:
        await init_db()
        me = await bot.me()
        logger.info("Бот запущено: @%s (id=%s)", me.username, me.id)
        
        # Запускаємо фоновий воркер
        bot.worker_task = start_worker(bot)

    @dp.shutdown()
    async def on_shutdown() -> None:
        # Зупиняємо воркер
        if hasattr(bot, "worker_task"):
            bot.worker_task.cancel()
            
        await close_db()
        await bot.session.close()
        logger.info("Бот зупинено.")

    # ── Запуск ─────────────────────────────────
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
