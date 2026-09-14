"""Проверка: сессия стартует и добавляет торрент."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.base import async_session_maker
from app.db.models import Torrent
from app.services.torrent_manager import (
    get_torrent_manager,
    setup_torrent_manager,
    shutdown_torrent_manager,
)


async def main() -> int:
    await setup_torrent_manager()

    try:
        mgr = get_torrent_manager()

        async with async_session_maker() as session:
            torrent = await session.scalar(
                select(Torrent).where(Torrent.id == 1)
            )
            if torrent is None:
                print("❌ Торрент id=1 не найден")
                return 2

            print(f"📦 Торрент: {torrent.name!r}")
            print(f"   data_size: {torrent.data_size:,} bytes")
            print(f"   resume_data: {len(torrent.resume_data or b'')} bytes")
            print()
            print("⏳ Добавляю в сессию…")

            import time
            t0 = time.perf_counter()
            await mgr.ensure_torrent(
                torrent.id, torrent.magnet, torrent.resume_data
            )
            elapsed = time.perf_counter() - t0

            print(f"✅ Торрент добавлен за {elapsed:.1f}s")
            state = mgr.session.get(torrent.id)
            if state:
                status = state.handle.status()
                print(f"   info_hash:    {state.info_hash}")
                print(f"   has_metadata: {status.has_metadata}")
                print(f"   num_pieces:   {status.num_pieces}")
                print(f"   num_peers:    {status.num_peers}")

        return 0
    finally:
        await shutdown_torrent_manager()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))