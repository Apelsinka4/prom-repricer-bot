"""
Асинхронна робота з PostgreSQL через asyncpg.

Таблиці
-------
users              — зареєстровані користувачі бота.
monitoring_tasks   — завдання моніторингу цін конкурентів.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

from bot.config import DATABASE_URL, DEFAULT_PLAN_LIMIT, DEFAULT_STEP

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Глобальний пул з'єднань
# ──────────────────────────────────────────────
_pool: Optional[asyncpg.Pool] = None


async def get_db() -> asyncpg.Pool:
    """Повертає поточний пул або піднімає помилку."""
    if _pool is None:
        raise RuntimeError("БД не ініціалізована. Спершу викличте init_db().")
    return _pool


async def init_db() -> None:
    """
    Створює пул з'єднань до PostgreSQL та ініціалізує схему.
    """
    global _pool

    _pool = await asyncpg.create_pool(DATABASE_URL)

    # Використовуємо з'єднання з пулу для ініціалізації таблиць
    await _pool.execute(_SCHEMA_SQL)
    await _pool.execute(_MIGRATION_SQL)

    logger.info("Пул з'єднань з PostgreSQL ініціалізовано.")


async def close_db() -> None:
    """Коректно закриває пул."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Пул з'єднань з PostgreSQL закрито.")


# ──────────────────────────────────────────────
# SQL-схема
# ──────────────────────────────────────────────
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id   BIGINT PRIMARY KEY,
    prom_api_key  TEXT    DEFAULT NULL,
    is_active     BOOLEAN DEFAULT TRUE,
    plan_limit    INTEGER DEFAULT {plan_limit}
);

CREATE TABLE IF NOT EXISTS monitoring_tasks (
    task_id        SERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL,
    my_sku         TEXT    NOT NULL,
    competitor_url TEXT    NOT NULL,
    min_price      REAL    NOT NULL,
    step           REAL    DEFAULT {step},
    strategy        TEXT    DEFAULT 'beat_by_step',
    cost_price      REAL    DEFAULT NULL,
    min_margin_percent REAL DEFAULT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users (telegram_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_competitors (
    competitor_id  SERIAL PRIMARY KEY,
    task_id        INTEGER NOT NULL,
    competitor_url TEXT    NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (task_id) REFERENCES monitoring_tasks (task_id)
        ON DELETE CASCADE,
    UNIQUE (task_id, competitor_url)
);

CREATE TABLE IF NOT EXISTS repricing_events (
    event_id         BIGSERIAL PRIMARY KEY,
    task_id          INTEGER,
    user_id          BIGINT NOT NULL,
    my_sku           TEXT NOT NULL,
    status           TEXT NOT NULL,
    strategy         TEXT,
    competitor_url   TEXT,
    competitor_price REAL,
    current_price    REAL,
    new_price        REAL,
    reason           TEXT,
    error            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (task_id) REFERENCES monitoring_tasks (task_id)
        ON DELETE SET NULL
);
""".format(plan_limit=DEFAULT_PLAN_LIMIT, step=DEFAULT_STEP)


_MIGRATION_SQL = """
ALTER TABLE monitoring_tasks
    ADD COLUMN IF NOT EXISTS strategy TEXT DEFAULT 'beat_by_step';

ALTER TABLE monitoring_tasks
    ADD COLUMN IF NOT EXISTS cost_price REAL DEFAULT NULL;

ALTER TABLE monitoring_tasks
    ADD COLUMN IF NOT EXISTS min_margin_percent REAL DEFAULT NULL;

ALTER TABLE monitoring_tasks
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

INSERT INTO task_competitors (task_id, competitor_url)
SELECT task_id, competitor_url
FROM monitoring_tasks
WHERE competitor_url IS NOT NULL
ON CONFLICT (task_id, competitor_url) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_monitoring_tasks_user_id
    ON monitoring_tasks (user_id);

CREATE INDEX IF NOT EXISTS idx_task_competitors_task_id
    ON task_competitors (task_id);

CREATE INDEX IF NOT EXISTS idx_repricing_events_user_created
    ON repricing_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_repricing_events_task_created
    ON repricing_events (task_id, created_at DESC);
"""


# ──────────────────────────────────────────────
# CRUD — users
# ──────────────────────────────────────────────

async def upsert_user(telegram_id: int) -> asyncpg.Record:
    """
    Додає нового користувача або повертає існуючого.
    Використовує INSERT … ON CONFLICT DO NOTHING.
    """
    pool = await get_db()
    await pool.execute(
        """
        INSERT INTO users (telegram_id)
        VALUES ($1)
        ON CONFLICT (telegram_id) DO NOTHING
        """,
        telegram_id,
    )
    user = await get_user(telegram_id)
    if user is None:
        raise RuntimeError("Failed to upsert user")
    return user


async def get_user(telegram_id: int) -> Optional[asyncpg.Record]:
    """Повертає рядок користувача або None."""
    pool = await get_db()
    return await pool.fetchrow(
        "SELECT * FROM users WHERE telegram_id = $1",
        telegram_id,
    )


async def set_api_key(telegram_id: int, api_key: str) -> None:
    """Зберігає Prom API-ключ користувача."""
    pool = await get_db()
    await pool.execute(
        "UPDATE users SET prom_api_key = $1 WHERE telegram_id = $2",
        api_key, telegram_id,
    )


async def set_user_active(telegram_id: int, is_active: bool) -> None:
    """Активує / деактивує користувача."""
    pool = await get_db()
    await pool.execute(
        "UPDATE users SET is_active = $1 WHERE telegram_id = $2",
        is_active, telegram_id,
    )


# ──────────────────────────────────────────────
# CRUD — monitoring_tasks
# ──────────────────────────────────────────────

async def add_task(
    user_id: int,
    my_sku: str,
    competitor_url: str | None,
    min_price: float,
    step: float = DEFAULT_STEP,
    competitor_urls: list[str] | None = None,
    strategy: str = "beat_by_step",
    cost_price: float | None = None,
    min_margin_percent: float | None = None,
) -> int:
    """
    Створює нове завдання моніторингу.
    Повертає task_id.
    Перед викликом перевіряйте plan_limit зовні (у хендлері).
    """
    pool = await get_db()
    urls = [url.strip() for url in (competitor_urls or []) if url.strip()]
    if competitor_url and competitor_url.strip():
        urls.insert(0, competitor_url.strip())
    urls = list(dict.fromkeys(urls))
    if not urls:
        raise ValueError("At least one competitor URL is required")

    async with pool.acquire() as conn:
        async with conn.transaction():
            user = await conn.fetchrow(
                "SELECT plan_limit FROM users WHERE telegram_id = $1 FOR UPDATE",
                user_id,
            )
            if user is None:
                raise ValueError("User does not exist")

            current_count = await conn.fetchval(
                "SELECT COUNT(*) FROM monitoring_tasks WHERE user_id = $1",
                user_id,
            )
            if current_count >= user["plan_limit"]:
                raise ValueError("Plan limit exceeded")

            task_id = await conn.fetchval(
                """
                INSERT INTO monitoring_tasks (
                    user_id, my_sku, competitor_url, min_price, step,
                    strategy, cost_price, min_margin_percent
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING task_id
                """,
                user_id, my_sku, urls[0], min_price, step,
                strategy, cost_price, min_margin_percent,
            )
            await conn.executemany(
                """
                INSERT INTO task_competitors (task_id, competitor_url)
                VALUES ($1, $2)
                ON CONFLICT (task_id, competitor_url) DO NOTHING
                """,
                [(task_id, url) for url in urls],
            )
    return task_id


async def _attach_competitors(rows: list[asyncpg.Record]) -> list[dict[str, Any]]:
    """Додає competitor_urls до рядків задач."""
    tasks = [dict(row) for row in rows]
    if not tasks:
        return tasks

    pool = await get_db()
    task_ids = [task["task_id"] for task in tasks]
    competitor_rows = await pool.fetch(
        """
        SELECT task_id, competitor_url
        FROM task_competitors
        WHERE task_id = ANY($1::int[])
        ORDER BY competitor_id
        """,
        task_ids,
    )
    by_task: dict[int, list[str]] = {task_id: [] for task_id in task_ids}
    for row in competitor_rows:
        by_task[row["task_id"]].append(row["competitor_url"])

    for task in tasks:
        urls = by_task.get(task["task_id"]) or []
        task["competitor_urls"] = urls or [task["competitor_url"]]
    return tasks


async def get_tasks_for_user(user_id: int) -> list[dict[str, Any]]:
    """Повертає всі завдання моніторингу для користувача."""
    pool = await get_db()
    rows = await pool.fetch(
        "SELECT * FROM monitoring_tasks WHERE user_id = $1 ORDER BY task_id",
        user_id,
    )
    return await _attach_competitors(rows)


async def count_tasks_for_user(user_id: int) -> int:
    """Повертає кількість завдань моніторингу для користувача."""
    pool = await get_db()
    return await pool.fetchval(
        "SELECT COUNT(*) FROM monitoring_tasks WHERE user_id = $1",
        user_id,
    )


async def delete_task(task_id: int, user_id: int) -> bool:
    """
    Видаляє завдання по task_id (тільки якщо належить user_id).
    Повертає True якщо рядок було видалено.
    """
    pool = await get_db()
    status = await pool.execute(
        "DELETE FROM monitoring_tasks WHERE task_id = $1 AND user_id = $2",
        task_id, user_id,
    )
    # asyncpg execute returns status command tag, e.g., "DELETE 1"
    return status.split()[-1] != "0"


async def get_all_active_tasks() -> list[dict[str, Any]]:
    """
    Повертає ВСІ завдання для активних користувачів —
    використовується планувальником при масовій перевірці цін.
    """
    pool = await get_db()
    rows = await pool.fetch(
        """
        SELECT t.*, u.prom_api_key
        FROM monitoring_tasks t
        JOIN users u ON u.telegram_id = t.user_id
        WHERE u.is_active = TRUE
          AND u.prom_api_key IS NOT NULL
        ORDER BY t.user_id, t.task_id
        """
    )
    return await _attach_competitors(rows)


async def record_repricing_event(
    *,
    task_id: int | None,
    user_id: int,
    my_sku: str,
    status: str,
    strategy: str | None = None,
    competitor_url: str | None = None,
    competitor_price: float | None = None,
    current_price: float | None = None,
    new_price: float | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> int:
    """Записує історію перевірок, змін ціни та помилок."""
    pool = await get_db()
    return await pool.fetchval(
        """
        INSERT INTO repricing_events (
            task_id, user_id, my_sku, status, strategy,
            competitor_url, competitor_price, current_price, new_price,
            reason, error
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING event_id
        """,
        task_id, user_id, my_sku, status, strategy,
        competitor_url, competitor_price, current_price, new_price,
        reason, error,
    )


async def get_recent_events_for_user(user_id: int, limit: int = 20) -> list[asyncpg.Record]:
    """Повертає останні події repricing для користувача."""
    pool = await get_db()
    return await pool.fetch(
        """
        SELECT *
        FROM repricing_events
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        user_id, limit,
    )
