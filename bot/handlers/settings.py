"""
Хендлер SetAPI — збереження та валідація Prom API-ключа.
Викликається через:
  - callback menu:setapi (кнопка в головному меню)
  - команду /setkey
"""

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.database import get_user, set_api_key
from bot.prom_api import validate_api_key
from bot import keyboards as kb

logger = logging.getLogger(__name__)
router = Router()


class SetAPIFSM(StatesGroup):
    waiting_for_key = State()


# ──────────────────────────────────────────────
# Вхідні точки (кнопка + команда)
# ──────────────────────────────────────────────

async def _ask_for_key(target: Message | CallbackQuery, state: FSMContext) -> None:
    """Спільна логіка: пояснює де взяти ключ і переводить у стан очікування."""
    text = (
        "🔑 <b>Налаштування Prom API-ключа</b>\n\n"
        "Де знайти:\n"
        "1. Кабінет Prom.ua → <b>Налаштування</b>\n"
        "2. Розділ <b>API</b> → «Згенерувати токен»\n\n"
        "Надішліть ключ наступним повідомленням:"
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb.cancel_kb())
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb.cancel_kb())

    await state.set_state(SetAPIFSM.waiting_for_key)


@router.callback_query(F.data == "menu:setapi")
async def cb_setapi(callback: CallbackQuery, state: FSMContext) -> None:
    await _ask_for_key(callback, state)


@router.message(Command("setkey"))
async def cmd_setkey(message: Message, state: FSMContext) -> None:
    await _ask_for_key(message, state)


# ──────────────────────────────────────────────
# Отримання ключа → валідація → збереження
# ──────────────────────────────────────────────

@router.message(SetAPIFSM.waiting_for_key)
async def process_api_key(message: Message, state: FSMContext) -> None:
    api_key = (message.text or "").strip()

    # Мінімальна перевірка формату
    if len(api_key) < 20 or " " in api_key:
        await message.answer(
            "❌ Ключ виглядає некоректним.\n"
            "Токен Prom.ua не містить пробілів і має довжину > 20 символів.\n\n"
            "Спробуйте ще раз:",
            reply_markup=kb.cancel_kb(),
        )
        return

    # Показуємо індикатор роботи
    wait_msg = await message.answer("⏳ Перевіряю ключ на Prom.ua…")

    result = await validate_api_key(api_key)

    if result.ok:
        await set_api_key(message.from_user.id, api_key)
        await state.clear()

        products_count = len((result.data or {}).get("products", []))
        await wait_msg.edit_text(
            f"✅ <b>API-ключ підтверджено та збережено!</b>\n\n"
            f"Prom.ua відповів: знайдено товарів у відповіді — <b>{products_count}</b>.\n\n"
            f"Тепер можна додавати товари для моніторингу.",
            reply_markup=kb.back_to_menu(),
        )
        logger.info("Користувач %s успішно зберіг API-ключ.", message.from_user.id)
    else:
        await wait_msg.edit_text(
            f"❌ <b>Ключ не пройшов перевірку</b>\n\n"
            f"Причина: {result.error}\n"
            f"HTTP-статус: <code>{result.status}</code>\n\n"
            f"Перевірте ключ і надішліть ще раз:",
            reply_markup=kb.cancel_kb(),
        )
        logger.warning(
            "Користувач %s — невдала валідація API-ключа: %s",
            message.from_user.id,
            result.error,
        )


# ──────────────────────────────────────────────
# Скасування FSM
# ──────────────────────────────────────────────

@router.callback_query(F.data == "fsm:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "🚫 Дію скасовано.",
        reply_markup=kb.back_to_menu(),
    )
    await callback.answer()
