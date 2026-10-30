"""Сервис статистики для бота.

SQL-запросы к таблицам:
  - books, authors, torrents — общая информация о библиотеке
  - user_events — события пользователей (start, search, book_view, download, message)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Author, Book, Torrent, TorrentFile, UserEvent

logger = logging.getLogger(__name__)


# ============================================================
# Dataclasses для результатов
# ============================================================

@dataclass(frozen=True, slots=True)
class LibraryStats:
    """Общая статистика библиотеки."""

    books_total: int
    books_active: int
    authors_total: int
    archives_total: int
    languages_total: int
    torrent_size_bytes: int
    torrent_version: str | None


@dataclass(frozen=True, slots=True)
class BotStats:
    """Статистика бота."""

    users_total: int
    users_today: int
    searches_total: int
    downloads_total: int
    messages_total: int


@dataclass(frozen=True, slots=True)
class TodayStats:
    """Статистика за сегодня."""

    searches: int
    downloads: int
    messages: int
    unique_users: int
    book_views: int


@dataclass(frozen=True, slots=True)
class TopBook:
    """Топ книга."""

    lib_id: int
    title: str
    author: str
    downloads: int


@dataclass(frozen=True, slots=True)
class TopAuthor:
    """Топ автор."""

    name: str
    downloads: int


@dataclass(frozen=True, slots=True)
class DayActivity:
    """Активность за день."""

    day: str  # "2026-10-30"
    searches: int
    downloads: int
    users: int


# ============================================================
# Библиотека
# ============================================================

async def get_library_stats(session: AsyncSession) -> LibraryStats:
    """Общая статистика библиотеки."""
    books_total = await session.scalar(select(func.count(Book.id))) or 0
    books_active = await session.scalar(
        select(func.count(Book.id)).where(Book.is_deleted.is_(False))
    ) or 0
    authors_total = await session.scalar(select(func.count(Author.id))) or 0
    archives_total = await session.scalar(select(func.count(TorrentFile.id))) or 0
    languages_total = await session.scalar(
        select(func.count(func.distinct(Book.language)))
    ) or 0

    torrent = await session.scalar(select(Torrent).limit(1))

    return LibraryStats(
        books_total=books_total,
        books_active=books_active,
        authors_total=authors_total,
        archives_total=archives_total,
        languages_total=languages_total,
        torrent_size_bytes=torrent.data_size if torrent else 0,
        torrent_version=torrent.version if torrent else None,
    )


# ============================================================
# Бот
# ============================================================

async def get_bot_stats(session: AsyncSession) -> BotStats:
    """Общая статистика бота (за всё время)."""
    users_total = await session.scalar(
        select(func.count(func.distinct(UserEvent.user_id)))
    ) or 0

    today_start = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    users_today = await session.scalar(
        select(func.count(func.distinct(UserEvent.user_id))).where(
            UserEvent.created_at >= today_start
        )
    ) or 0

    searches_total = await session.scalar(
        select(func.count(UserEvent.id)).where(UserEvent.event_type == "search")
    ) or 0
    downloads_total = await session.scalar(
        select(func.count(UserEvent.id)).where(UserEvent.event_type == "download")
    ) or 0
    messages_total = await session.scalar(
        select(func.count(UserEvent.id)).where(UserEvent.event_type == "message")
    ) or 0

    return BotStats(
        users_total=users_total,
        users_today=users_today,
        searches_total=searches_total,
        downloads_total=downloads_total,
        messages_total=messages_total,
    )


async def get_today_stats(session: AsyncSession) -> TodayStats:
    """Статистика за сегодня."""
    today_start = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    def _count(event_type: str):
        return select(func.count(UserEvent.id)).where(
            UserEvent.event_type == event_type,
            UserEvent.created_at >= today_start,
        )

    searches = await session.scalar(_count("search")) or 0
    downloads = await session.scalar(_count("download")) or 0
    messages = await session.scalar(_count("message")) or 0
    book_views = await session.scalar(_count("book_view")) or 0

    unique_users = await session.scalar(
        select(func.count(func.distinct(UserEvent.user_id))).where(
            UserEvent.created_at >= today_start
        )
    ) or 0

    return TodayStats(
        searches=searches,
        downloads=downloads,
        messages=messages,
        unique_users=unique_users,
        book_views=book_views,
    )


# ============================================================
# Топы
# ============================================================

async def get_top_books(
    session: AsyncSession, limit: int = 10, days: int = 30
) -> list[TopBook]:
    """Топ книг по скачиваниям за N дней."""
    since = datetime.now(UTC) - timedelta(days=days)

    stmt = text("""
        SELECT
            sub.lib_id,
            sub.title,
            sub.author,
            sub.downloads
        FROM (
            SELECT
                (e.payload->>'lib_id')::int AS lib_id,
                b.title,
                COALESCE(b.authors[1], '—') AS author,
                COUNT(*) AS downloads
            FROM user_events e
            JOIN books b ON (e.payload->>'lib_id')::int = b.lib_id
            WHERE e.event_type = 'download'
              AND e.payload ? 'lib_id'
              AND e.created_at >= :since
            GROUP BY (e.payload->>'lib_id')::int, b.title, b.authors
        ) AS sub
        ORDER BY sub.downloads DESC
        LIMIT :limit
    """)

    result = await session.execute(stmt, {"since": since, "limit": limit})
    return [
        TopBook(
            lib_id=row.lib_id,
            title=row.title,
            author=row.author,
            downloads=row.downloads,
        )
        for row in result
    ]


async def get_top_authors(
    session: AsyncSession, limit: int = 10, days: int = 30
) -> list[TopAuthor]:
    """Топ авторов по скачиваниям книг за N дней."""
    since = datetime.now(UTC) - timedelta(days=days)

    stmt = text("""
        SELECT
            sub.name,
            sub.downloads
        FROM (
            SELECT
                unnest(b.authors) AS name,
                COUNT(*) AS downloads
            FROM user_events e
            JOIN books b ON (e.payload->>'lib_id')::int = b.lib_id
            WHERE e.event_type = 'download'
              AND e.payload ? 'lib_id'
              AND e.created_at >= :since
            GROUP BY unnest(b.authors)
        ) AS sub
        ORDER BY sub.downloads DESC
        LIMIT :limit
    """)

    result = await session.execute(stmt, {"since": since, "limit": limit})
    return [
        TopAuthor(name=row.name, downloads=row.downloads)
        for row in result
    ]


# ============================================================
# Активность по дням
# ============================================================

async def get_daily_activity(
    session: AsyncSession, days: int = 7
) -> list[DayActivity]:
    """Активность по дням за последние N дней."""
    since = datetime.now(UTC) - timedelta(days=days)

    stmt = text("""
        SELECT
            sub.day,
            sub.searches,
            sub.downloads,
            sub.users
        FROM (
            SELECT
                TO_CHAR(created_at, 'YYYY-MM-DD') AS day,
                COUNT(*) FILTER (WHERE event_type = 'search') AS searches,
                COUNT(*) FILTER (WHERE event_type = 'download') AS downloads,
                COUNT(DISTINCT user_id) AS users
            FROM user_events
            WHERE created_at >= :since
            GROUP BY TO_CHAR(created_at, 'YYYY-MM-DD')
        ) AS sub
        ORDER BY sub.day DESC
    """)

    result = await session.execute(stmt, {"since": since})
    return [
        DayActivity(
            day=row.day,
            searches=row.searches,
            downloads=row.downloads,
            users=row.users,
        )
        for row in result
    ]
