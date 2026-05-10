"""
Конфігурація бота — читає змінні оточення та надає константи.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Завантажуємо .env із кореня проєкту
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
SCRAPER_API_KEY: str = os.getenv("SCRAPER_API_KEY", "")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# Дефолти для нових користувачів
DEFAULT_PLAN_LIMIT: int = 3       # безкоштовний тріал — 3 товари
DEFAULT_STEP: float = 1.0         # крок зниження ціни, грн


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


# Production/runtime limits
MAX_COMPETITORS_PER_TASK: int = _env_int("MAX_COMPETITORS_PER_TASK", 5)
MAX_COMPETITOR_URL_LENGTH: int = _env_int("MAX_COMPETITOR_URL_LENGTH", 2048)
RATE_LIMIT_WINDOW_SECONDS: float = _env_float("RATE_LIMIT_WINDOW_SECONDS", 10.0)
RATE_LIMIT_MAX_EVENTS: int = _env_int("RATE_LIMIT_MAX_EVENTS", 8)
RATE_LIMIT_BLOCK_SECONDS: float = _env_float("RATE_LIMIT_BLOCK_SECONDS", 20.0)
WORKER_INTERVAL_SECONDS: int = max(_env_int("WORKER_INTERVAL_SECONDS", 3600), 300)
WORKER_TASK_DELAY_SECONDS: float = max(_env_float("WORKER_TASK_DELAY_SECONDS", 2.0), 0.5)
HEALTHCHECK_TIMEOUT_SECONDS: float = _env_float("HEALTHCHECK_TIMEOUT_SECONDS", 10.0)
SCRAPER_HEADLESS: bool = _env_bool("SCRAPER_HEADLESS", True)


def validate() -> None:
    """Перевіряє обов'язкові змінні. Викликати лише при старті бота."""
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не задано. "
            "Скопіюй .env.example → .env та встав токен від @BotFather."
        )
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL не задано. "
            "Додай PostgreSQL connection string у .env."
        )
