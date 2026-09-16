"""Интеграционные тесты поиска (с тестовой БД)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Book, Torrent
from app.services.search import SearchField, search_books


@pytest.fixture
async def torrent(session: AsyncSession) -> Torrent:
    t = Torrent(
        info_hash="0" * 40,
        name="test",
        save_path="/data",
        source_type="inpx_fb2",
        status="active",
    )
    session.add(t)
    await session.flush()
    return t


@pytest.fixture
async def books(session: AsyncSession, torrent: Torrent) -> list[Book]:
    items = [
        Book(
            torrent_id=torrent.id,
            lib_id=1,
            title="Кристальный матриархат",
            authors=["Нерей,Александр"],
            authors_text="Нерей,Александр",
            genres=["sf"],
            series="Сага о Головастике",
            series_text="Сага о Головастике",
            series_num=2,
            language="ru",
            archive_name="f.fb2-811194-815075.zip",
            file_name="1.fb2",
            is_deleted=False,
        ),
        Book(
            torrent_id=torrent.id,
            lib_id=2,
            title="Алхимик",
            authors=["Романович,Роман"],
            authors_text="Романович,Роман",
            genres=["fantasy"],
            series="Алхимик [Пастырь]",
            series_text="Алхимик [Пастырь]",
            series_num=1,
            language="ru",
            archive_name="f.fb2-811194-815075.zip",
            file_name="2.fb2",
            is_deleted=False,
        ),
        Book(
            torrent_id=torrent.id,
            lib_id=3,
            title="Удалённая книга",
            authors=["Тест,Тест"],
            authors_text="Тест,Тест",
            genres=[],
            language="ru",
            archive_name="f.fb2-811194-815075.zip",
            file_name="3.fb2",
            is_deleted=True,
        ),
    ]
    session.add_all(items)
    await session.flush()
    return items


async def test_search_all(session: AsyncSession, books: list[Book]) -> None:
    result = await search_books(session, "матриархат", field=SearchField.ALL)
    assert result.total == 1
    assert result.items[0].title == "Кристальный матриархат"


async def test_search_by_author(session: AsyncSession, books: list[Book]) -> None:
    result = await search_books(session, "Романович", field=SearchField.AUTHOR)
    assert result.total == 1
    assert result.items[0].title == "Алхимик"


async def test_search_by_series(session: AsyncSession, books: list[Book]) -> None:
    result = await search_books(session, "Алхимик", field=SearchField.SERIES)
    assert result.total == 1
    assert result.items[0].title == "Алхимик"


async def test_search_excludes_deleted(session: AsyncSession, books: list[Book]) -> None:
    result = await search_books(session, "Удалённая", field=SearchField.ALL)
    assert result.total == 0


async def test_search_empty_query(session: AsyncSession, books: list[Book]) -> None:
    result = await search_books(session, "", field=SearchField.ALL)
    # Пустой запрос — все книги, кроме удалённых
    assert result.total == 2