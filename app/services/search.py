"""Поиск книг по каталогу с токенизацией.

Логика:
  - Запрос разбивается на токены (слова).
  - Все токены должны найтись (AND), но каждый — в любом из полей (OR).
  - Пользователь может сузить поле поиска: all / title / author / series.
  - Ранжирование: бонусы за точное совпадение + FTS-ранг по title.

Поля:
  - title         — название
  - authors_text  — "Фамилия Имя Отчество" через пробел
  - series_text   — название серии
  - annotation    — аннотация

Индексы:
  - ix_books_title_fts           (GIN, to_tsvector('russian', title))
  - ix_books_title_trgm          (GIN, gin_trgm_ops)
  - ix_books_authors_text_trgm   (GIN, gin_trgm_ops)
  - ix_books_series_text_trgm    (GIN, gin_trgm_ops)
  - ix_books_annotation_trgm     (GIN, gin_trgm_ops)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Author, Book, BookAuthor

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# Разделители токенов (пробелы и большинство знаков, кроме внутренних: ' - _)
_TOKEN_SPLIT_RE = re.compile(r"[\s,;|/\\()\[\]{}]+", re.UNICODE)


class SearchField(StrEnum):
    ALL = "all"
    TITLE = "title"
    AUTHOR = "author"
    SERIES = "series"


@dataclass(frozen=True, slots=True)
class SearchResult:
    items: list[Book]
    total: int
    page: int
    page_size: int
    query: str
    field: SearchField

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


# ------------------------------------------------------------------ tokens

def _tokenize(q: str) -> list[str]:
    """Разбивает запрос на токены длиной >= 2 (или чисел)."""
    if not q:
        return []
    tokens = [t.strip() for t in _TOKEN_SPLIT_RE.split(q) if t.strip()]
    return [t for t in tokens if len(t) >= 2 or t.isdigit()]


# ------------------------------------------------------------------ conditions

def _field_condition(field: SearchField, token: str):
    """Условие для одного токена в зависимости от выбранного поля."""
    like = f"%{token}%"

    if field == SearchField.TITLE:
        return Book.title.ilike(like)

    if field == SearchField.AUTHOR:
        return func.coalesce(Book.authors_text, "").ilike(like)

    if field == SearchField.SERIES:
        return func.coalesce(Book.series_text, "").ilike(like)

    # ALL: токен ищется в любом поле
    return or_(
        Book.title.ilike(like),
        func.coalesce(Book.authors_text, "").ilike(like),
        func.coalesce(Book.series_text, "").ilike(like),
        func.coalesce(Book.annotation, "").ilike(like),
    )


def _build_where(
    q: str,
    field: SearchField,
    include_deleted: bool,
) -> list:
    """Список условий WHERE."""
    conditions = []

    if not include_deleted:
        conditions.append(Book.is_deleted.is_(False))

    tokens = _tokenize(q)
    if tokens:
        # AND между токенами
        conditions.extend(_field_condition(field, t) for t in tokens)

    return conditions


# ------------------------------------------------------------------ score

def _build_score(q: str, field: SearchField):
    """Выражение для ранжирования. Больше бонусов — выше в выдаче."""
    tokens = _tokenize(q)
    if not tokens:
        return None

    score = literal(0.0)

    for token in tokens:
        like = f"%{token}%"

        # Название: +5
        if field in (SearchField.ALL, SearchField.TITLE):
            score = score + case(
                (Book.title.ilike(like), literal(5.0)), else_=literal(0.0)
            )

        # Автор: +4
        if field in (SearchField.ALL, SearchField.AUTHOR):
            score = score + case(
                (func.coalesce(Book.authors_text, "").ilike(like), literal(4.0)),
                else_=literal(0.0),
            )

        # Серия: +3
        if field in (SearchField.ALL, SearchField.SERIES):
            score = score + case(
                (func.coalesce(Book.series_text, "").ilike(like), literal(3.0)),
                else_=literal(0.0),
            )

        # Аннотация: +1 (только для ALL)
        if field == SearchField.ALL:
            score = score + case(
                (func.coalesce(Book.annotation, "").ilike(like), literal(1.0)),
                else_=literal(0.0),
            )

    # Дополнительный бонус за FTS-ранг по названию (только в ALL или TITLE)
    if field in (SearchField.ALL, SearchField.TITLE):
        tsq = func.websearch_to_tsquery("russian", q)
        fts_rank = func.ts_rank(
            func.to_tsvector("russian", Book.title), tsq
        )
        score = score + fts_rank * literal(2.0)

    return score.label("score")


# ------------------------------------------------------------------ public

async def search_books(
    session: AsyncSession,
    q: str,
    *,
    field: SearchField = SearchField.ALL,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    include_deleted: bool = False,
) -> SearchResult:
    """Поиск с токенизацией и фильтром по полю."""
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    offset = (page - 1) * page_size
    q = (q or "").strip()

    conditions = _build_where(q, field, include_deleted)

    # --- total
    count_stmt = select(func.count(Book.id))
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))
    total = int(await session.scalar(count_stmt) or 0)

    if total == 0:
        return SearchResult([], 0, page, page_size, q, field)

    # --- items
    score = _build_score(q, field)

    if score is not None:
        stmt = (
            select(Book)
            .add_columns(score)
            .options(selectinload(Book.authors_rel))
        )
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(
            score.desc(),
            Book.title.asc(),
            Book.lib_id.asc(),
        )
    else:
        stmt = select(Book).options(selectinload(Book.authors_rel))
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(Book.title.asc(), Book.lib_id.asc())

    stmt = stmt.offset(offset).limit(page_size)

    result = await session.execute(stmt)
    if score is not None:
        items = [row[0] for row in result.all()]
    else:
        items = list(result.scalars().all())

    return SearchResult(items, total, page, page_size, q, field)


async def get_random_book(
    session: AsyncSession, *, torrent_id: int | None = None
) -> Book | None:
    conditions = [Book.is_deleted.is_(False)]
    if torrent_id is not None:
        conditions.append(Book.torrent_id == torrent_id)
    stmt = (
        select(Book)
        .options(selectinload(Book.authors_rel))  # ← убедись, что есть
        .where(and_(*conditions))
        .order_by(func.random())
        .limit(1)
    )
    return await session.scalar(stmt)

async def search_by_author_id(
    session: AsyncSession,
    author_id: int,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> SearchResult:
    """Все книги конкретного автора (по ID).

    Сортировка: сначала по серии, потом по номеру в серии, потом по названию.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    offset = (page - 1) * page_size

    # Проверим, что автор существует
    author = await session.get(Author, author_id)
    if author is None:
        return SearchResult([], 0, page, page_size, "", SearchField.AUTHOR)

    # Count
    count_stmt = (
        select(func.count(Book.id))
        .join(BookAuthor, BookAuthor.book_id == Book.id)
        .where(
            BookAuthor.author_id == author_id,
            Book.is_deleted.is_(False),
        )
    )
    total = int(await session.scalar(count_stmt) or 0)

    if total == 0:
        return SearchResult(
            [], 0, page, page_size, author.display_name, SearchField.AUTHOR
        )

    # Items — единый select с join, options и order_by
    stmt = (
        select(Book)
        .options(selectinload(Book.authors_rel))
        .join(BookAuthor, BookAuthor.book_id == Book.id)
        .where(
            BookAuthor.author_id == author_id,
            Book.is_deleted.is_(False),
        )
        .order_by(
            Book.series_text.asc().nulls_last(),
            Book.series_num.asc().nulls_last(),
            Book.title.asc(),
        )
        .offset(offset)
        .limit(page_size)
    )

    result = await session.execute(stmt)
    items = list(result.scalars().all())

    return SearchResult(
        items, total, page, page_size, author.display_name, SearchField.AUTHOR
    )
