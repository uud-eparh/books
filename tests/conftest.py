"""Общие фикстуры для тестов.

ВАЖНО для Windows + pytest-asyncio:
  - engine создаётся на каждый тест (function-scope), чтобы совпадать с loop
  - используется NullPool, чтобы asyncpg не привязывал соединения к чужому loop
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# ============================================================
# Windows: asyncpg требует SelectorEventLoop, не Proactor
# ============================================================
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Тестовая БД
os.environ.setdefault("POSTGRES_DB", "flibusta_test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

from app.db import models  # noqa: E402, F401
from app.db.base import Base  # noqa: E402

TEST_DB_URL = (
    f"postgresql+asyncpg://{os.environ.get('POSTGRES_USER', 'flibusta')}:"
    f"{os.environ.get('POSTGRES_PASSWORD', 'flibusta_secret')}@"
    f"{os.environ.get('POSTGRES_HOST', 'localhost')}:"
    f"{os.environ.get('POSTGRES_PORT', '5432')}/flibusta_test"
)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator:
    """Движок тестовой БД. Создаётся на каждый тест (function-scope).

    Схема уже создана (мы её создадим отдельным скриптом/фикстурой).
    NullPool — каждое соединение новое, не привязано к loop'у.
    """
    eng = create_async_engine(
        TEST_DB_URL,
        echo=False,
        poolclass=NullPool,
    )

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """Сессия на тест. После теста — откат."""
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()


# ============================================================
# Одноразовое создание схемы (запускается вручную: pytest --create-schema)
# ============================================================
@pytest_asyncio.fixture(scope="session", autouse=False)
async def _create_schema():
    """Создать схему в тестовой БД. Запускается один раз.

    Использование: pytest --create-schema (см. ниже)
    """
    eng = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()

def pytest_addoption(parser):
    parser.addoption(
        "--create-schema",
        action="store_true",
        default=False,
        help="Пересоздать схему в тестовой БД перед запуском",
    )


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _maybe_create_schema(request):
    if request.config.getoption("--create-schema"):
        eng = create_async_engine(TEST_DB_URL, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()
