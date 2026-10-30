"""Сервис логирования событий пользователей.

Собирает значимые события в таблицу `user_events` для статистики.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram.types import CallbackQuery, Message, User

from app.db.base import async_session_maker
from app.db.models import UserEvent

logger = logging.getLogger(__name__)


async def log_event(
    user: User | None,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Записать событие в БД.

    Args:
        user: пользователь Telegram (может быть None)
        event_type: тип события (start, search, book_view, download, message)
        payload: дополнительные данные (query, lib_id, elapsed_ms, ...)
    """
    if user is None:
        return

    try:
        async with async_session_maker() as session:
            session.add(
                UserEvent(
                    user_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    event_type=event_type,
                    payload=payload or {},
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to log event %r for user_id=%s: %r",
            event_type,
            user.id,
            exc,
        )


async def log_message_event(
    message: Message, event_type: str, payload: dict[str, Any] | None = None
) -> None:
    """Обёртка для Message."""
    await log_event(message.from_user, event_type, payload)


async def log_callback_event(
    callback: CallbackQuery, event_type: str, payload: dict[str, Any] | None = None
) -> None:
    """Обёртка для CallbackQuery."""
    await log_event(callback.from_user, event_type, payload)
