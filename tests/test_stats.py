"""Тесты сервиса статистики."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserEvent
from app.services.stats import (
    get_bot_stats,
    get_daily_activity,
    get_today_stats,
    get_top_books,
)


async def test_empty_stats(session: AsyncSession) -> None:
    """Пустая БД — нули."""
    bot = await get_bot_stats(session)
    assert bot.users_total == 0
    assert bot.searches_total == 0
    assert bot.downloads_total == 0


async def test_bot_stats(session: AsyncSession) -> None:
    """Несколько событий — считаем."""
    session.add_all([
        UserEvent(user_id=1, event_type="start"),
        UserEvent(user_id=1, event_type="search", payload={"query": "x"}),
        UserEvent(user_id=2, event_type="search", payload={"query": "y"}),
        UserEvent(user_id=1, event_type="download", payload={"lib_id": 1}),
    ])
    await session.flush()

    bot = await get_bot_stats(session)
    assert bot.users_total == 2
    assert bot.searches_total == 2
    assert bot.downloads_total == 1


async def test_today_stats(session: AsyncSession) -> None:
    """События за сегодня."""
    session.add_all([
        UserEvent(user_id=1, event_type="search", payload={"query": "x"}),
        UserEvent(user_id=2, event_type="download", payload={"lib_id": 1}),
    ])
    await session.flush()

    today = await get_today_stats(session)
    assert today.searches == 1
    assert today.downloads == 1
    assert today.unique_users == 2


async def test_top_books_empty(session: AsyncSession) -> None:
    """Пустая БД — пустой топ."""
    books = await get_top_books(session, limit=10, days=30)
    assert books == []


async def test_daily_activity_empty(session: AsyncSession) -> None:
    """Пустая БД — пустая активность."""
    activity = await get_daily_activity(session, days=7)
    assert activity == []
