from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


engine = create_async_engine(
    settings.database_url_async,
    echo=False,          # включать только для отладки SQL
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: сессия на время запроса."""
    async with async_session_maker() as session:
        yield session


async def dispose_engine() -> None:
    """Закрыть пул соединений при завершении приложения."""
    await engine.dispose()
