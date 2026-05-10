"""
Всі inline- та reply-клавіатури бота в одному місці.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ──────────────────────────────────────────────
# Головне меню
# ──────────────────────────────────────────────

def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔑 Налаштувати API Prom", callback_data="menu:setapi")
    )
    builder.row(
        InlineKeyboardButton(text="➕ Додати товар",   callback_data="menu:addtask"),
        InlineKeyboardButton(text="📋 Мої товари",     callback_data="menu:mytasks"),
    )
    builder.row(
        InlineKeyboardButton(text="📈 Історія", callback_data="menu:history")
    )
    return builder.as_markup()


# ──────────────────────────────────────────────
# Список тасок
# ──────────────────────────────────────────────

def tasks_list(tasks: list) -> InlineKeyboardMarkup:
    """Будує клавіатуру зі списком завдань і кнопками видалення."""
    builder = InlineKeyboardBuilder()
    for t in tasks:
        builder.row(
            InlineKeyboardButton(
                text=f"❌ Видалити #{t['task_id']} ({t['my_sku']})",
                callback_data=f"deltask:{t['task_id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="🏠 Головне меню", callback_data="menu:home")
    )
    return builder.as_markup()


# ──────────────────────────────────────────────
# Кнопка «Скасувати» (для FSM)
# ──────────────────────────────────────────────

def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel"))
    return builder.as_markup()


def strategy_kb() -> InlineKeyboardMarkup:
    """Клавіатура вибору repricing-стратегії."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📉 Дешевше на крок", callback_data="strategy:beat_by_step")
    )
    builder.row(
        InlineKeyboardButton(text="⚖️ Дорівнювати мінімальній", callback_data="strategy:match_lowest")
    )
    builder.row(
        InlineKeyboardButton(text="🔔 Тільки сповіщати", callback_data="strategy:notify_only")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")
    )
    return builder.as_markup()


# ──────────────────────────────────────────────
# Кнопка «Назад до меню»
# ──────────────────────────────────────────────

def back_to_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🏠 Головне меню", callback_data="menu:home"))
    return builder.as_markup()
