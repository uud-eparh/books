"""FastAPI-зависимости для веб-интерфейса."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_maker


async def get_db() -> AsyncIterator[AsyncSession]:
    """Сессия БД на время запроса."""
    async with async_session_maker() as session:
        yield session


class Pagination:
    """Параметры пагинации."""

    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ) -> None:
        self.page = page
        self.page_size = page_size