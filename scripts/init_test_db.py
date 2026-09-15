"""Создать схему в тестовой БД. Запускать один раз перед тестами."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("POSTGRES_DB", "flibusta_test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402, F401


TEST_DB_URL = (
    f"postgresql+asyncpg://{os.environ.get('POSTGRES_USER', 'flibusta')}:"
    f"{os.environ.get('POSTGRES_PASSWORD', 'flibusta_secret')}@"
    f"{os.environ.get('POSTGRES_HOST', 'localhost')}:"
    f"{os.environ.get('POSTGRES_PORT', '5432')}/flibusta_test"
)


async def main() -> None:
    eng = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()
    print("OK: schema created in flibusta_test")


if __name__ == "__main__":
    asyncio.run(main())