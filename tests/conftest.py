"""Общие фикстуры для тестов.

Создаёт тестовую БД `flibusta_test`, применяет схему через SQLAlchemy,
отдаёт async-сессию, очищает таблицы после каждого теста.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ВАЖНО: тестовая БД — переопределяем настройки ДО импорта app
os.environ.setdefault("POSTGRES_DB", "flibusta_test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402, F401  — регистрация моделей

# URL тестовой БД (из .env.local / .env)
TEST_DB_URL = (
    f"postgresql+asyncpg://{os.environ.get('POSTGRES_USER', 'flibusta')}:"
    f"{os.environ.get('POSTGRES_PASSWORD', 'flibusta_secret')}@"
    f"{os.environ.get('POSTGRES_HOST', 'localhost')}:"
    f"{os.environ.get('POSTGRES_PORT', '5432')}/flibusta_test"
)


@pytest.fixture(scope="session")
def event_loop():
    """Один event loop на всю сессию тестов."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Движок тестовой БД. Создаёт схему один раз."""
    eng = create_async_engine(TEST_DB_URL, echo=False, pool_pre_ping=True)

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """Сессия на тест. После теста — откат (rollback)."""
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()