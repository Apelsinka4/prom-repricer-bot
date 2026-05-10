"""
Smoke-тест роботи PostgreSQL-шару без запуску Telegram-бота.

Запуск:
    python -m scripts.test_db
"""

import asyncio
import io
import sys
from pathlib import Path

# UTF-8 для Windows-консолі
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Додаємо корінь проєкту до PYTHONPATH при прямому запуску
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.database import (
    add_task,
    close_db,
    count_tasks_for_user,
    delete_task,
    get_all_active_tasks,
    get_db,
    get_recent_events_for_user,
    get_tasks_for_user,
    get_user,
    init_db,
    record_repricing_event,
    set_api_key,
    upsert_user,
)


TEST_ID = 999_999_001
FAKE_KEY = "fake_api_key_1234567890_test"


async def cleanup_test_data() -> None:
    pool = await get_db()
    await pool.execute("DELETE FROM monitoring_tasks WHERE user_id = $1", TEST_ID)
    await pool.execute("DELETE FROM repricing_events WHERE user_id = $1", TEST_ID)
    await pool.execute("DELETE FROM users WHERE telegram_id = $1", TEST_ID)


async def run_tests() -> None:
    print("=" * 50)
    print("  Smoke-тест БД — Prom Repricer Bot")
    print("=" * 50)

    try:
        await init_db()
    except Exception as exc:
        print("❌ Не вдалося підключитися до PostgreSQL.")
        print(f"   Причина: {type(exc).__name__}: {exc}")
        print("   Перевірте DATABASE_URL у .env і доступність бази з цієї машини.")
        raise SystemExit(1) from None

    try:
        await cleanup_test_data()
        print("✅ БД ініціалізована, тестові дані очищені")

        user = await upsert_user(TEST_ID)
        assert user is not None, "upsert_user повернув None"
        assert user["telegram_id"] == TEST_ID
        assert user["plan_limit"] == 3
        assert user["is_active"] is True
        print(f"✅ Користувач створений: id={user['telegram_id']}, ліміт={user['plan_limit']}")

        user2 = await upsert_user(TEST_ID)
        assert user2["telegram_id"] == TEST_ID
        print("✅ Повторне створення користувача ідемпотентне")

        await set_api_key(TEST_ID, FAKE_KEY)
        user = await get_user(TEST_ID)
        assert user is not None
        assert user["prom_api_key"] == FAKE_KEY
        print("✅ API-ключ збережено")

        t1 = await add_task(
            TEST_ID,
            "SKU-001",
            "https://prom.ua/p1111111",
            199.0,
            1.0,
            competitor_urls=["https://prom.ua/p1111111", "https://prom.ua/p1111112"],
            strategy="match_lowest",
            cost_price=150.0,
            min_margin_percent=20.0,
        )
        t2 = await add_task(TEST_ID, "SKU-002", "https://prom.ua/p2222222", 350.0, 5.0)
        t3 = await add_task(TEST_ID, "SKU-003", "https://prom.ua/p3333333", 99.5, 2.5)
        print(f"✅ Додано 3 завдання: ids={t1}, {t2}, {t3}")

        count = await count_tasks_for_user(TEST_ID)
        assert count == 3, f"Очікувано 3, отримано {count}"
        print("✅ count_tasks_for_user повертає коректну кількість")

        tasks = await get_tasks_for_user(TEST_ID)
        assert len(tasks) == 3
        assert tasks[0]["my_sku"] == "SKU-001"
        assert len(tasks[0]["competitor_urls"]) == 2
        assert tasks[0]["strategy"] == "match_lowest"
        assert tasks[0]["cost_price"] == 150.0
        assert tasks[0]["min_margin_percent"] == 20.0
        print("✅ get_tasks_for_user повертає завдання користувача")

        active = await get_all_active_tasks()
        assert any(t["user_id"] == TEST_ID for t in active)
        print("✅ get_all_active_tasks бачить активне завдання з API-ключем")

        await record_repricing_event(
            task_id=t1,
            user_id=TEST_ID,
            my_sku="SKU-001",
            status="updated",
            strategy="match_lowest",
            competitor_url="https://prom.ua/p1111112",
            competitor_price=210.0,
            current_price=220.0,
            new_price=210.0,
            reason="Тестовий запис історії",
        )
        events = await get_recent_events_for_user(TEST_ID)
        assert len(events) == 1
        assert events[0]["status"] == "updated"
        print("✅ repricing_events записує історію подій")

        deleted = await delete_task(t2, TEST_ID)
        assert deleted is True
        count_after = await count_tasks_for_user(TEST_ID)
        assert count_after == 2
        print("✅ delete_task видаляє тільки власне завдання")

        deleted_wrong = await delete_task(t1, TEST_ID + 1)
        assert deleted_wrong is False
        print("✅ Спроба видалити чуже завдання відхиляється")

        print("\n🎉 Smoke-тест БД пройдено успішно")

    finally:
        await cleanup_test_data()
        await close_db()
        print("🧹 Тестові дані прибрано")


if __name__ == "__main__":
    asyncio.run(run_tests())
