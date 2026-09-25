"""Высокоуровневый сервис: доступ к книгам библиотеки.

Объединяет БД, локальные ZIP-файлы и (в будущем) торрент-скачивание.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ArchiveEntry, Book, Torrent, TorrentFile
from app.services.torrent_fetcher import fetch_book_via_torrent
from app.services.zip_reader import ZipReadError, read_zip_entry

logger = logging.getLogger(__name__)


class BookNotFoundError(Exception):
    """Книга не найдена в БД."""


class BookContentError(Exception):
    """Не удалось получить содержимое книги."""


@dataclass(frozen=True, slots=True)
class BookContent:
    lib_id: int
    title: str
    authors: list[str]
    data: bytes
    source: str  # "local_zip" | "torrent"
    elapsed_seconds: float = 0.0


async def fetch_book_content(
    session: AsyncSession,
    lib_id: int,
    *,
    torrent_id: int | None = None,
    prefer_torrent: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> BookContent:
    """Извлекает содержимое книги.

    Сначала пробует локальный ZIP. Если его нет (или prefer_torrent=True) —
    скачивает через торрент.
    """
    # 1. Находим книгу
    stmt = select(Book).where(Book.lib_id == lib_id)
    if torrent_id is not None:
        stmt = stmt.where(Book.torrent_id == torrent_id)
    stmt = stmt.limit(1)
    book = await session.scalar(stmt)
    if book is None:
        raise BookNotFoundError(f"Book lib_id={lib_id} not found")

    # 2. TorrentFile
    tf = await session.scalar(
        select(TorrentFile)
        .where(
            TorrentFile.torrent_id == book.torrent_id,
            TorrentFile.path == book.archive_name,
        )
        .limit(1)
    )
    if tf is None:
        raise BookContentError(f"TorrentFile for {book.archive_name!r} not found")

    # 3. ArchiveEntry
    ae = await session.scalar(
        select(ArchiveEntry)
        .where(
            ArchiveEntry.torrent_file_id == tf.id,
            ArchiveEntry.lib_id == book.lib_id,
        )
        .limit(1)
    )
    if ae is None:
        raise BookContentError(f"ArchiveEntry for lib_id={book.lib_id} not found")

    # 4. Torrent
    torrent = await session.get(Torrent, book.torrent_id)
    if torrent is None:
        raise BookContentError(f"Torrent id={book.torrent_id} not found")

    # 5. Локальный ZIP
    local_zip = Path(torrent.save_path) / tf.path
    use_local = local_zip.exists() and not prefer_torrent

    t0 = time.perf_counter()

    if use_local:
        try:
            data = read_zip_entry(
                local_zip,
                local_header_offset=ae.local_header_offset,
                expected_filename=ae.filename,
                expected_compressed_size=ae.compressed_size,
            )
            elapsed = time.perf_counter() - t0
            logger.info(
                "Fetched book lib_id=%d from local ZIP (%d bytes, %.0f ms)",
                lib_id, len(data), elapsed * 1000,
            )
            _mark_progress_done(lib_id, data, "local_zip", elapsed)
            return BookContent(
                lib_id=book.lib_id,
                title=book.title,
                authors=list(book.authors),
                data=data,
                source="local_zip",
                elapsed_seconds=elapsed,
            )
        except ZipReadError as exc:
            logger.warning("Local ZIP read failed (%r), falling back to torrent", exc)

    # 6. Торрент
    logger.info("Fetching book lib_id=%d via torrent…", lib_id)
    result = await fetch_book_via_torrent(
        torrent=torrent,
        torrent_file=tf,
        entry=ae,
        on_progress=on_progress,
        lib_id=lib_id,
    )

    _mark_progress_done(lib_id, result.data, "torrent", result.elapsed_seconds)

    return BookContent(
        lib_id=book.lib_id,
        title=book.title,
        authors=list(book.authors),
        data=result.data,
        source="torrent",
        elapsed_seconds=result.elapsed_seconds,
    )

async def is_book_local_available(
    session: AsyncSession, lib_id: int
) -> bool:
    """Проверить, доступен ли локальный ZIP для книги."""
    book = await session.scalar(select(Book).where(Book.lib_id == lib_id).limit(1))
    if book is None:
        return False
    tf = await session.scalar(
        select(TorrentFile).where(
            TorrentFile.torrent_id == book.torrent_id,
            TorrentFile.path == book.archive_name,
        ).limit(1)
    )
    if tf is None:
        return False
    torrent = await session.get(Torrent, book.torrent_id)
    if torrent is None:
        return False
    return (Path(torrent.save_path) / tf.path).exists()


def _mark_progress_done(
    lib_id: int,
    data: bytes,
    source: str,
    elapsed: float,
) -> None:
    """Обновить ProgressState после успешного скачивания."""
    try:
        from app.services.progress import DownloadStatus, get_progress_tracker
        tracker = get_progress_tracker()
        state = tracker.get_or_create(lib_id)
        state.status = DownloadStatus.DONE
        state.finished_at = time.time()
        state.source = source
        state.data = data
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to update progress: %r", exc)
