from __future__ import annotations

import logging
from collections import defaultdict, deque
from time import monotonic
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import config

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseMiddleware):
    """Simple in-memory per-user rate limit for Telegram updates."""

    def __init__(self) -> None:
        self._events: dict[int, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[int, float] = {}
        self._last_notice_at: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        user_id = user.id
        now = monotonic()

        blocked_until = self._blocked_until.get(user_id, 0)
        if blocked_until > now:
            await self._send_notice(event, user_id, blocked_until - now)
            return None

        window = config.RATE_LIMIT_WINDOW_SECONDS
        events = self._events[user_id]
        while events and now - events[0] > window:
            events.popleft()

        events.append(now)
        if len(events) > config.RATE_LIMIT_MAX_EVENTS:
            self._blocked_until[user_id] = now + config.RATE_LIMIT_BLOCK_SECONDS
            logger.warning("Rate limit triggered for Telegram user %s", user_id)
            await self._send_notice(event, user_id, config.RATE_LIMIT_BLOCK_SECONDS)
            return None

        return await handler(event, data)

    async def _send_notice(self, event: TelegramObject, user_id: int, wait_seconds: float) -> None:
        now = monotonic()
        last_notice = self._last_notice_at.get(user_id, 0)
        if now - last_notice < 5:
            return

        self._last_notice_at[user_id] = now
        text = f"⏳ Забагато дій за короткий час. Спробуйте через {int(wait_seconds) + 1} сек."

        try:
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
        except Exception as exc:
            logger.debug("Failed to send rate limit notice to %s: %s", user_id, exc)
