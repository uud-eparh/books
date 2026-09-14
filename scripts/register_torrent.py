"""CLI: зарегистрировать торрент в БД.

Пример:
    python -m scripts.register_torrent \
        --hash 85E99AB1E0D6ED9DE11D96E1A1C48F145986B64C \
        --name "fb2.Flibusta.Net" \
        --magnet "magnet:?xt=urn:btih:..." \
        --save-path "D:/Users/Downloads/fb2.Flibusta.Net"

Идемпотентно: если торрент с таким info_hash уже есть, выведет его id.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db.base import async_session_maker  # noqa: E402
from app.db.models import Torrent  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Register a torrent in DB")
    p.add_argument("--hash", dest="info_hash", required=True, help="Info-hash (hex)")
    p.add_argument("--name", required=True)
    p.add_argument("--magnet", default=None)
    p.add_argument("--save-path", dest="save_path", required=True)
    p.add_argument("--source-type", default="inpx_fb2")
    p.add_argument("--version", default=None)
    return p.parse_args()


async def main() -> int:
    args = parse_args()
    info_hash = args.info_hash.lower()

    async with async_session_maker() as session:
        existing = await session.scalar(
            select(Torrent).where(Torrent.info_hash == info_hash)
        )
        if existing:
            print(f"ℹ️  Торрент уже зарегистрирован: id={existing.id} name={existing.name!r}")
            return 0

        torrent = Torrent(
            info_hash=info_hash,
            name=args.name,
            magnet=args.magnet,
            save_path=args.save_path,
            source_type=args.source_type,
            version=args.version,
            status="active",
        )
        session.add(torrent)
        await session.commit()
        await session.refresh(torrent)

        print(f"✅ Торрент зарегистрирован: id={torrent.id} hash={info_hash[:12]}…")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))