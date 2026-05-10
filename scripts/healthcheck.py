"""
Production healthcheck.

Checks that DATABASE_URL is configured and PostgreSQL accepts a simple query.
Run:
    python -m scripts.healthcheck
"""

from __future__ import annotations

import asyncio
import sys

import asyncpg

from bot import config


async def main() -> int:
    if not config.DATABASE_URL:
        print("DATABASE_URL is not configured")
        return 1

    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(config.DATABASE_URL),
            timeout=config.HEALTHCHECK_TIMEOUT_SECONDS,
        )
        result = await asyncio.wait_for(
            conn.fetchval("SELECT 1"),
            timeout=config.HEALTHCHECK_TIMEOUT_SECONDS,
        )
        if result != 1:
            print("PostgreSQL health query returned unexpected result")
            return 1
        print("ok")
        return 0
    except Exception as exc:
        print(f"healthcheck failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if conn is not None:
            await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
