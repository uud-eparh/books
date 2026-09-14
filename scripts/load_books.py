"""CLI: загрузить книги из .inpx в БД.

Пример:
    python -m scripts.load_books --torrent-id 1 --inpx "D:/.../flibusta_fb2_local.inpx"
    python -m scripts.load_books --torrent-id 1 --inpx ... --truncate
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, insert, select  # noqa: E402

from app.db.base import async_session_maker  # noqa: E402
from app.db.models import Book, LibraryMeta, Torrent  # noqa: E402
from app.parsers.inpx import InpxParser  # noqa: E402

BATCH_SIZE = 5000


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load .inpx into DB")
    p.add_argument("--torrent-id", type=int, required=True)
    p.add_argument("--inpx", type=Path, required=True)
    p.add_argument(
        "--truncate",
        action="store_true",
        help="Удалить все книги этого торрента перед загрузкой",
    )
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


async def get_torrent(session, torrent_id: int) -> Torrent:
    torrent = await session.get(Torrent, torrent_id)
    if torrent is None:
        raise SystemExit(f"❌ Торрент id={torrent_id} не найден. Сначала register_torrent.")
    return torrent


async def load_books(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.inpx.exists():
        raise SystemExit(f"❌ .inpx не найден: {args.inpx}")

    parser = InpxParser(args.inpx)
    meta = parser.read_meta()
    print(f"📚 Метаданные: name={meta.name!r} version={meta.version!r}")

    t0 = time.perf_counter()
    batch: list[dict] = []
    total = 0
    skipped = 0

    async with async_session_maker() as session:
        torrent = await get_torrent(session, args.torrent_id)
        print(f"📦 Торрент: id={torrent.id} name={torrent.name!r}")

        if args.truncate:
            print(f"🗑  Удаляю существующие книги торрента id={torrent.id}…")
            await session.execute(delete(Book).where(Book.torrent_id == torrent.id))
            await session.execute(
                delete(LibraryMeta).where(LibraryMeta.torrent_id == torrent.id)
            )
            await session.commit()

        print("⏳ Парсинг и вставка батчами…")

        async def flush() -> None:
            nonlocal total
            if not batch:
                return
            await session.execute(insert(Book), batch)
            await session.commit()
            total += len(batch)
            elapsed = time.perf_counter() - t0
            print(
                f"   …вставлено {total:>8,} книг  "
                f"({total / elapsed:>8,.0f} книг/сек)"
            )
            batch.clear()

        for book in parser.iter_books():
            batch.append(
                {
                    "torrent_id": torrent.id,
                    "lib_id": book.lib_id,
                    "title": book.title,
                    "authors": book.authors,
                    "authors_text": " ".join(book.authors) if book.authors else "",
                    "genres": book.genres,
                    "series": book.series,
                    "series_text": book.series or "",
                    "series_num": book.series_num,
                    "file_size": book.file_size,
                    "language": book.language,
                    "date_added": book.date_added,
                    "annotation": book.annotation,
                    "archive_name": book.archive_name,
                    "file_name": f"{book.lib_id}.fb2",
                    "is_deleted": book.is_deleted,
                }
            )
            if len(batch) >= args.batch_size:
                await flush()

        await flush()

        stats = parser.stats
        skipped = stats["skipped"]

        # ---- LibraryMeta
        lib_meta = LibraryMeta(
            torrent_id=torrent.id,
            name=meta.name,
            version=meta.version,
            chunk_size=meta.chunk_size,
            description=meta.description,
            books_count=total,
            archives_count=stats["files"],
        )
        session.add(lib_meta)

        # ---- Обновляем Torrent
        torrent.version = meta.version
        torrent.files_count = stats["files"]
        torrent.last_indexed_at = func.now()

        await session.commit()

    elapsed = time.perf_counter() - t0
    print()
    print("=" * 60)
    print("✅ ЗАГРУЗКА ЗАВЕРШЕНА")
    print("=" * 60)
    print(f"Всего книг:       {total:>10,}")
    print(f"Пропущено строк:  {skipped:>10,}")
    print(f"Время:            {elapsed:.1f} s")
    print(f"Скорость:         {total / elapsed:,.0f} книг/сек")
    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(load_books(args))


if __name__ == "__main__":
    sys.exit(main())