"""Сервис работы с авторами."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Author

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthorSearchResult:
    items: list[Author]
    total: int
    page: int
    page_size: int
    query: str


async def get_author(session: AsyncSession, author_id: int) -> Author | None:
    return await session.get(Author, author_id)


async def search_authors(
    session: AsyncSession,
    q: str,
    *,
    page: int = 1,
    page_size: int = 50,
) -> AuthorSearchResult:
    """Поиск авторов по имени (для навигации)."""
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size
    q = (q or "").strip()

    conditions = []
    if q:
        like = f"%{q}%"
        conditions.append(
            or_(
                Author.name.ilike(like),
                Author.display_name.ilike(like),
            )
        )

    count_stmt = select(func.count(Author.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = int(await session.scalar(count_stmt) or 0)

    if total == 0:
        return AuthorSearchResult([], 0, page, page_size, q)

    stmt = select(Author)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Author.books_count.desc(), Author.display_name.asc())
    stmt = stmt.offset(offset).limit(page_size)

    result = await session.execute(stmt)
    items = list(result.scalars().all())
    return AuthorSearchResult(items, total, page, page_size, q)
