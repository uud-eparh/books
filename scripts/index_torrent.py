"""CLI: получить список файлов торрента и сохранить в БД.

Пример:
    python -m scripts.index_torrent --torrent-id 1
    python -m scripts.index_torrent --torrent-id 1 --timeout 600 --force
"""

from __future__ import annotations
from datetime import datetime, timezone

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, update  # noqa: E402

from app.db.base import async_session_maker  # noqa: E402
from app.db.models import Torrent, TorrentFile  # noqa: E402
from app.parsers.torrent import fetch_torrent_metadata  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Index a torrent (files + resume_data)")
    p.add_argument("--torrent-id", type=int, required=True)
    p.add_argument("--timeout", type=int, default=300, help="Метаданные: таймаут в секундах")
    p.add_argument("--force", action="store_true", help="Перезаписать существующие файлы")
    return p.parse_args()


def _progress_printer(status: dict) -> None:
    line = (
        f"\r   peers={status.get('peers', 0):>4}  "
        f"seeds={status.get('seeds', 0):>4}  "
        f"state={status.get('state', '?'):<20}  "
        f"downloaded={status.get('downloaded', 0):>10}"
    )
    print(line, end="", flush=True)


async def main() -> int:
    args = parse_args()

    async with async_session_maker() as session:
        torrent = await session.get(Torrent, args.torrent_id)
        if torrent is None:
            print(f"❌ Торрент id={args.torrent_id} не найден")
            return 2

        if not torrent.magnet:
            print(f"❌ У торрента нет magnet-ссылки")
            return 2

        # Проверим, есть ли уже файлы
        existing_count = await session.scalar(
            select(TorrentFile.id)
            .where(TorrentFile.torrent_id == torrent.id)
            .limit(1)
        )
        if existing_count and not args.force:
            print(
                f"ℹ️  У торрента уже есть файлы в БД. "
                f"Используй --force для переиндексации."
            )
            return 0

        print(f"📦 Торрент: id={torrent.id} name={torrent.name!r}")
        print(f"🧲 Magnet:  {torrent.magnet[:80]}…")
        print(f"💾 Save:    {torrent.save_path}")
        print()
        print("⏳ Получаю метаданные… (это может занять до 5 минут)")

        t0 = time.perf_counter()
        try:
            metadata = await asyncio.to_thread(
                fetch_torrent_metadata,
                torrent.magnet,
                Path(torrent.save_path),
                resume_data=torrent.resume_data,
                timeout=args.timeout,
                download_pieces=False,
                on_progress=_progress_printer,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"\n❌ Ошибка получения метаданных: {exc!r}")
            return 1

        elapsed = time.perf_counter() - t0
        print()  # после progress-строки
        print()
        print(f"✅ Метаданные получены за {elapsed:.1f}s")
        print(f"   name:         {metadata.name!r}")
        print(f"   info_hash:    {metadata.info_hash}")
        print(f"   total_size:   {metadata.total_size:,} bytes ({metadata.total_size/1024/1024/1024:.2f} GiB)")
        print(f"   piece_length: {metadata.piece_length:,} bytes")
        print(f"   num_pieces:   {metadata.num_pieces:,}")
        print(f"   files:        {len(metadata.files)}")
        print(f"   resume_data:  {len(metadata.resume_data) if metadata.resume_data else 0} bytes")

        # Показываем первые 5 и последние 2 файла
        print()
        print("📂 Примеры файлов:")
        for f in metadata.files[:5]:
            print(
                f"   [{f.file_index:>3}] {f.path:<40} "
                f"size={f.size:>12,}  pieces={f.piece_start}..{f.piece_end}"
            )
        if len(metadata.files) > 7:
            print("   ...")
        for f in metadata.files[-2:]:
            print(
                f"   [{f.file_index:>3}] {f.path:<40} "
                f"size={f.size:>12,}  pieces={f.piece_start}..{f.piece_end}"
            )

        # === Сохраняем в БД ===
        print()
        print("💾 Сохраняю в БД…")

        if existing_count:
            await session.execute(
                delete(TorrentFile).where(TorrentFile.torrent_id == torrent.id)
            )

        if metadata.files:
            # Считаем byte_offset: сумма размеров всех предыдущих файлов
            files_sorted = sorted(metadata.files, key=lambda f: f.file_index)
            byte_offset = 0
            offsets: dict[int, int] = {}
            for f in files_sorted:
                offsets[f.file_index] = byte_offset
                byte_offset += f.size

            session.add_all(
                [
                    TorrentFile(
                        torrent_id=torrent.id,
                        file_index=f.file_index,
                        path=f.path,
                        size=f.size,
                        piece_start=f.piece_start,
                        piece_end=f.piece_end,
                        byte_offset=offsets[f.file_index],   # ← новое
                    )
                    for f in metadata.files
                ]
            )

        # Обновляем поля торрента (ORM сам сделает UPDATE при commit)
        now = datetime.now(timezone.utc)
        torrent.data_size = metadata.total_size
        torrent.files_count = len(metadata.files)
        torrent.resume_data = metadata.resume_data
        torrent.last_indexed_at = now
        torrent.resume_updated_at = now

        await session.commit()

        print(
            f"✅ Сохранено: {len(metadata.files)} файлов, "
            f"resume_data={len(metadata.resume_data) if metadata.resume_data else 0} bytes"
        )
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))