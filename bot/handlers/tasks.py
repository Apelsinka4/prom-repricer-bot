"""
Хендлери управління завданнями моніторингу:
  menu:addtask  — FSM (3 кроки: SKU → URL → мін. ціна)
  menu:mytasks  — список тасок з inline-видаленням
  deltask:<id>  — видалення конкретної таски
"""

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.config import DEFAULT_STEP, MAX_COMPETITORS_PER_TASK, MAX_COMPETITOR_URL_LENGTH
from bot.database import (
    add_task,
    count_tasks_for_user,
    delete_task,
    get_recent_events_for_user,
    get_tasks_for_user,
    get_user,
)
from bot import keyboards as kb

logger = logging.getLogger(__name__)
router = Router()


# ──────────────────────────────────────────────
# FSM — три кроки додавання завдання
# ──────────────────────────────────────────────

class AddTaskFSM(StatesGroup):
    waiting_sku       = State()   # Крок 1
    waiting_urls      = State()   # Крок 2
    waiting_strategy  = State()   # Крок 3
    waiting_min_price = State()   # Крок 4
    waiting_cost_price = State()  # Крок 5
    waiting_margin    = State()   # Крок 6


STRATEGY_LABELS = {
    "beat_by_step": "дешевше на крок",
    "match_lowest": "дорівнювати мінімальній ціні конкурента",
    "notify_only": "тільки сповіщати",
}


# ── Вхід у FSM ────────────────────────────────

async def _start_addtask(target: Message | CallbackQuery, state: FSMContext) -> None:
    """Перевіряє передумови та запускає FSM."""
    user_id = target.from_user.id
    user = await get_user(user_id)

    if not user:
        text = "⚠️ Спочатку запустіть /start"
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    if not user["prom_api_key"]:
        text = "🔑 Спочатку налаштуйте Prom API-ключ."
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=kb.back_to_menu())
            await target.answer()
        else:
            await target.answer(text, reply_markup=kb.back_to_menu())
        return

    current = await count_tasks_for_user(user_id)
    limit: int = user["plan_limit"]

    if current >= limit:
        text = (
            f"❌ <b>Ліміт тарифу вичерпано</b>: {current}/{limit} товарів.\n"
            "Зверніться до адміністратора для розширення плану."
        )
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=kb.back_to_menu())
            await target.answer()
        else:
            await target.answer(text, reply_markup=kb.back_to_menu())
        return

    step1_text = (
        f"➕ <b>Новий товар для моніторингу</b>\n"
        f"Слотів використано: <b>{current}/{limit}</b>\n\n"
        f"<b>Крок 1/6</b> — Введіть <b>артикул (SKU)</b> або ID "
        f"вашого товару на Prom.ua:"
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(step1_text, reply_markup=kb.cancel_kb())
        await target.answer()
    else:
        await target.answer(step1_text, reply_markup=kb.cancel_kb())

    await state.set_state(AddTaskFSM.waiting_sku)


@router.callback_query(F.data == "menu:addtask")
async def cb_addtask(callback: CallbackQuery, state: FSMContext) -> None:
    await _start_addtask(callback, state)


@router.message(Command("addtask"))
async def cmd_addtask(message: Message, state: FSMContext) -> None:
    await _start_addtask(message, state)


# ── Крок 1: SKU ───────────────────────────────

@router.message(AddTaskFSM.waiting_sku)
async def process_sku(message: Message, state: FSMContext) -> None:
    sku = (message.text or "").strip()
    if not sku:
        await message.answer("❌ Артикул не може бути порожнім. Спробуйте ще раз:", reply_markup=kb.cancel_kb())
        return
    if len(sku) > 128:
        await message.answer("❌ Артикул занадто довгий. Максимум 128 символів:", reply_markup=kb.cancel_kb())
        return

    await state.update_data(my_sku=sku)
    await message.answer(
        f"✅ Артикул: <code>{sku}</code>\n\n"
        f"<b>Крок 2/6</b> — Вставте <b>посилання на товари конкурентів</b>.\n"
        f"Можна одне або кілька, кожне з нового рядка:",
        reply_markup=kb.cancel_kb(),
    )
    await state.set_state(AddTaskFSM.waiting_urls)


# ── Крок 2: URL ───────────────────────────────

@router.message(AddTaskFSM.waiting_urls)
async def process_urls(message: Message, state: FSMContext) -> None:
    raw_urls = (message.text or "").splitlines()
    urls = list(dict.fromkeys(url.strip() for url in raw_urls if url.strip()))

    if not urls or any(not url.startswith("http") for url in urls):
        await message.answer(
            "❌ Введіть коректні посилання, кожне має починатися з http або https:",
            reply_markup=kb.cancel_kb(),
        )
        return
    if len(urls) > MAX_COMPETITORS_PER_TASK:
        await message.answer(
            f"❌ Забагато конкурентів для одного товару. Максимум: <b>{MAX_COMPETITORS_PER_TASK}</b>.\n"
            "Залиште найважливіші посилання і спробуйте ще раз:",
            reply_markup=kb.cancel_kb(),
        )
        return
    if any(len(url) > MAX_COMPETITOR_URL_LENGTH for url in urls):
        await message.answer(
            f"❌ Одне з посилань занадто довге. Максимум: <b>{MAX_COMPETITOR_URL_LENGTH}</b> символів.",
            reply_markup=kb.cancel_kb(),
        )
        return

    await state.update_data(competitor_urls=urls)
    await message.answer(
        f"✅ Збережено конкурентів: <b>{len(urls)}</b>\n\n"
        f"<b>Крок 3/6</b> — Оберіть repricing-стратегію:",
        reply_markup=kb.strategy_kb(),
    )
    await state.set_state(AddTaskFSM.waiting_strategy)


# ── Крок 3: стратегія ─────────────────────────

@router.callback_query(AddTaskFSM.waiting_strategy, F.data.startswith("strategy:"))
async def process_strategy(callback: CallbackQuery, state: FSMContext) -> None:
    strategy = callback.data.split(":", 1)[1]
    if strategy not in STRATEGY_LABELS:
        await callback.answer("❌ Невідома стратегія.", show_alert=True)
        return

    await state.update_data(strategy=strategy)
    await callback.message.edit_text(
        f"✅ Стратегія: <b>{STRATEGY_LABELS[strategy]}</b>\n\n"
        f"<b>Крок 4/6</b> — Введіть <b>мінімальну ціну</b> (грн), "
        f"нижче якої бот <u>не знизить</u> вашу ціну:\n"
        f"<i>Приклад: 199.50</i>",
        reply_markup=kb.cancel_kb(),
    )
    await callback.answer()
    await state.set_state(AddTaskFSM.waiting_min_price)


# ── Крок 4: мін. ціна ───────────────────────

@router.message(AddTaskFSM.waiting_min_price)
async def process_min_price(message: Message, state: FSMContext) -> None:
    try:
        min_price = float((message.text or "").replace(",", "."))
        if min_price <= 0:
            raise ValueError("price must be > 0")
    except ValueError:
        await message.answer(
            "❌ Введіть число більше 0 (наприклад: 199.99):",
            reply_markup=kb.cancel_kb(),
        )
        return

    await state.update_data(min_price=min_price)
    await message.answer(
        f"✅ Мін. ціна: <b>{min_price:.2f} грн</b>\n\n"
        f"<b>Крок 5/6</b> — Введіть <b>собівартість</b> товару для захисту маржі.\n"
        f"Якщо не хочете задавати — надішліть <code>-</code>.",
        reply_markup=kb.cancel_kb(),
    )
    await state.set_state(AddTaskFSM.waiting_cost_price)


# ── Крок 5: собівартість ─────────────────────

@router.message(AddTaskFSM.waiting_cost_price)
async def process_cost_price(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if raw in ("-", "—", "skip", "пропустити"):
        await state.update_data(cost_price=None, min_margin_percent=None)
        await _finish_add_task(message, state)
        return

    try:
        cost_price = float(raw.replace(",", "."))
        if cost_price <= 0:
            raise ValueError("cost must be > 0")
    except ValueError:
        await message.answer(
            "❌ Введіть число більше 0 або <code>-</code>, щоб пропустити:",
            reply_markup=kb.cancel_kb(),
        )
        return

    await state.update_data(cost_price=cost_price)
    await message.answer(
        f"✅ Собівартість: <b>{cost_price:.2f} грн</b>\n\n"
        f"<b>Крок 6/6</b> — Введіть мінімальну маржу у відсотках.\n"
        f"Наприклад, <code>15</code> означає, що ціна не впаде нижче собівартість + 15%.\n"
        f"Щоб пропустити — надішліть <code>-</code>.",
        reply_markup=kb.cancel_kb(),
    )
    await state.set_state(AddTaskFSM.waiting_margin)


# ── Крок 6: мін. маржа → збереження ──────────

@router.message(AddTaskFSM.waiting_margin)
async def process_margin(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if raw in ("-", "—", "skip", "пропустити"):
        await state.update_data(min_margin_percent=None)
        await _finish_add_task(message, state)
        return

    try:
        min_margin_percent = float(raw.replace(",", "."))
        if min_margin_percent < 0:
            raise ValueError("margin must be >= 0")
    except ValueError:
        await message.answer(
            "❌ Введіть число 0 або більше, або <code>-</code>, щоб пропустити:",
            reply_markup=kb.cancel_kb(),
        )
        return

    await state.update_data(min_margin_percent=min_margin_percent)
    await _finish_add_task(message, state)


async def _finish_add_task(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    competitor_urls = data["competitor_urls"]

    try:
        task_id = await add_task(
            user_id=message.from_user.id,
            my_sku=data["my_sku"],
            competitor_url=competitor_urls[0],
            competitor_urls=competitor_urls,
            min_price=data["min_price"],
            step=DEFAULT_STEP,
            strategy=data["strategy"],
            cost_price=data.get("cost_price"),
            min_margin_percent=data.get("min_margin_percent"),
        )
    except ValueError as exc:
        logger.warning("Не вдалося додати завдання для %s: %s", message.from_user.id, exc)
        await message.answer(
            "❌ Не вдалося додати завдання. Ймовірно, ліміт тарифу вже вичерпано.",
            reply_markup=kb.back_to_menu(),
        )
        return

    cost_line = (
        f"🧾 Собівартість: <b>{data['cost_price']:.2f} грн</b>\n"
        if data.get("cost_price") is not None else ""
    )
    margin_line = (
        f"🛡 Мін. маржа: <b>{data['min_margin_percent']:.2f}%</b>\n"
        if data.get("min_margin_percent") is not None else ""
    )

    await message.answer(
        f"🎉 <b>Завдання #{task_id} додано!</b>\n\n"
        f"🏷  Артикул:    <code>{data['my_sku']}</code>\n"
        f"🔗 Конкурентів: <b>{len(competitor_urls)}</b>\n"
        f"🎛 Стратегія:  <b>{STRATEGY_LABELS[data['strategy']]}</b>\n"
        f"💰 Мін. ціна:  <b>{data['min_price']:.2f} грн</b>\n"
        f"{cost_line}"
        f"{margin_line}"
        f"📉 Крок:       <b>{DEFAULT_STEP} грн</b>\n\n"
        f"Бот стежитиме за ціною та автоматично оновлюватиме вашу.",
        reply_markup=kb.back_to_menu(),
    )
    logger.info("Користувач %s додав завдання #%s (SKU=%s).", message.from_user.id, task_id, data["my_sku"])


# ──────────────────────────────────────────────
# Список завдань
# ──────────────────────────────────────────────

async def _show_tasks(target: Message | CallbackQuery) -> None:
    user_id = target.from_user.id
    tasks = await get_tasks_for_user(user_id)
    user  = await get_user(user_id)
    limit = user["plan_limit"] if user else 0

    if not tasks:
        text = (
            "📭 <b>У вас немає активних завдань.</b>\n\n"
            "Натисніть «Додати товар», щоб почати моніторинг."
        )
        markup = kb.back_to_menu()
    else:
        lines = [f"📋 <b>Ваші завдання ({len(tasks)}/{limit}):</b>\n"]
        for t in tasks:
            lines.append(
                f"🔹 <b>#{t['task_id']}</b> | <code>{t['my_sku']}</code>\n"
                f"   🔗 Конкурентів: <b>{len(t.get('competitor_urls') or [t['competitor_url']])}</b>\n"
                f"   🎛 Стратегія: <b>{STRATEGY_LABELS.get(t.get('strategy'), t.get('strategy'))}</b>\n"
                f"   💰 Мін: <b>{t['min_price']:.2f} грн</b> "
                f"| 📉 Крок: <b>{t['step']} грн</b>\n"
                f"   🛡 Маржа: <b>{_margin_text(t)}</b>"
            )
        lines.append("\n⬇️ Натисніть кнопку нижче, щоб видалити завдання:")
        text   = "\n".join(lines)
        markup = kb.tasks_list(tasks)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup, disable_web_page_preview=True)


@router.callback_query(F.data == "menu:mytasks")
async def cb_mytasks(callback: CallbackQuery) -> None:
    await _show_tasks(callback)


@router.message(Command("mytasks"))
async def cmd_mytasks(message: Message) -> None:
    await _show_tasks(message)


def _margin_text(task: dict) -> str:
    if task.get("cost_price") is None:
        return "не задано"
    if task.get("min_margin_percent") is None:
        return f"собівартість {task['cost_price']:.2f} грн"
    return f"{task['min_margin_percent']:.2f}% від {task['cost_price']:.2f} грн"


async def _show_history(target: Message | CallbackQuery) -> None:
    user_id = target.from_user.id
    events = await get_recent_events_for_user(user_id, limit=15)

    if not events:
        text = "📭 <b>Історія поки порожня.</b>"
    else:
        lines = ["📈 <b>Останні події repricing:</b>\n"]
        for event in events:
            price_part = ""
            if event["new_price"] is not None:
                price_part = f" → <b>{event['new_price']:.2f} грн</b>"
            elif event["competitor_price"] is not None:
                price_part = f" | конкурент: <b>{event['competitor_price']:.2f} грн</b>"

            detail = event["reason"] or event["error"] or ""
            lines.append(
                f"🔹 <code>{event['my_sku']}</code> | {event['status']}{price_part}\n"
                f"   {detail}"
            )
        text = "\n".join(lines)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb.back_to_menu(), disable_web_page_preview=True)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb.back_to_menu(), disable_web_page_preview=True)


@router.callback_query(F.data == "menu:history")
async def cb_history(callback: CallbackQuery) -> None:
    await _show_history(callback)


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    await _show_history(message)


# ──────────────────────────────────────────────
# Видалення завдання (inline-кнопка)
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("deltask:"))
async def cb_deltask(callback: CallbackQuery) -> None:
    raw_id = callback.data.split(":")[1]

    if not raw_id.isdigit():
        await callback.answer("❌ Некоректний ID завдання.", show_alert=True)
        return

    task_id  = int(raw_id)
    user_id  = callback.from_user.id
    deleted  = await delete_task(task_id, user_id)

    if deleted:
        await callback.answer(f"✅ Завдання #{task_id} видалено.")
        logger.info("Користувач %s видалив завдання #%s.", user_id, task_id)
        # Оновлюємо список після видалення
        await _show_tasks(callback)
    else:
        await callback.answer("⚠️ Завдання не знайдено або не належить вам.", show_alert=True)
