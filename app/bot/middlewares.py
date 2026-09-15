"""Middleware бота.

1. WhitelistMiddleware — пропускает только разрешённых пользователей.
2. LoggingMiddleware — логирует входящие сообщения и callback-и.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from app.config import settings

logger = logging.getLogger(__name__)


class WhitelistMiddleware(BaseMiddleware):
    """Пропускает только пользователей из TELEGRAM_ALLOWED_USERS.

    Если TELEGRAM_ALLOWED_USERS пуст — бот публичный.
    """

    def __init__(self) -> None:
        super().__init__()
        self._allowed = set(settings.allowed_users_list)
        # Множество user_id, которым уже отправляли отказ (чтобы не спамить)
        self._notified: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self._allowed:
            # Публичный режим
            return await handler(event, data)

        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if user.id in self._allowed:
            return await handler(event, data)

        # Отказ
        logger.warning(
            "Access denied for user_id=%s username=%s",
            user.id,
            user.username,
        )
        if user.id not in self._notified:
            self._notified.add(user.id)
            text = "🔒 Доступ к этому боту ограничен."
            if isinstance(event, Message):
                try:
                    await event.answer(text)
                except Exception:  # noqa: BLE001
                    pass
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer(text, show_alert=True)
                except Exception:  # noqa: BLE001
                    pass
        return None  # не пропускаем дальше


class LoggingMiddleware(BaseMiddleware):
    """Логирует входящие события."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")

        if isinstance(event, Message):
            logger.info(
                "← Message from user_id=%s text=%r",
                user.id if user else None,
                (event.text or "")[:80],
            )
        elif isinstance(event, CallbackQuery):
            logger.info(
                "← Callback from user_id=%s data=%r",
                user.id if user else None,
                event.data,
            )

        return await handler(event, data)