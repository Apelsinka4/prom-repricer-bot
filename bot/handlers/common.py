"""
Хендлер /start та навігація по головному меню.
"""

import logging

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.database import upsert_user, get_user
from bot import keyboards as kb

logger = logging.getLogger(__name__)
router = Router()


# ──────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()  # скидаємо будь-який активний FSM
    user = await upsert_user(message.from_user.id)

    has_key = bool(user["prom_api_key"])
    key_status = "✅ API-ключ налаштовано" if has_key else "⚠️ API-ключ не задано"

    await message.answer(
        f"👋 Привіт, <b>{message.from_user.first_name}</b>!\n\n"
        f"🤖 <b>Prom Repricer Bot</b> — автоматичний моніторинг цін конкурентів "
        f"та оновлення цін у вашому магазині на Prom.ua.\n\n"
        f"📊 Тарифний план: <b>до {user['plan_limit']} товарів</b>\n"
        f"{key_status}\n\n"
        f"Оберіть дію:",
        reply_markup=kb.main_menu(),
    )
    logger.info("Користувач %s відкрив /start.", message.from_user.id)


# ──────────────────────────────────────────────
# Повернення до головного меню (callback)
# ──────────────────────────────────────────────

@router.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user = await get_user(callback.from_user.id)
    if not user:
        user = await upsert_user(callback.from_user.id)

    has_key = bool(user["prom_api_key"])
    key_status = "✅ API-ключ налаштовано" if has_key else "⚠️ API-ключ не задано"

    await callback.message.edit_text(
        f"🏠 <b>Головне меню</b>\n\n"
        f"📊 Тарифний план: <b>до {user['plan_limit']} товарів</b>\n"
        f"{key_status}\n\n"
        f"Оберіть дію:",
        reply_markup=kb.main_menu(),
    )
    await callback.answer()
