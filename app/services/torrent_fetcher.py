"""Точечное скачивание книги через торрент.

Использует TorrentManager (глобальную сессию + очередь),
скачивает только нужные piece-ы, читает данные из sparse-файла
и распаковывает через zip_reader.
"""

from __future__ import annotations

import logging
import struct
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.db.models import ArchiveEntry, Torrent, TorrentFile
from app.services.torrent_manager import get_torrent_manager

logger = logging.getLogger(__name__)

# Запас на локальный заголовок ZIP: 30 фикс + 255 filename + 1024 extra
HEADER_SAFETY = 1300

# Стандартный piece_length для нашего торрента (можно взять из БД)
DEFAULT_PIECE_LENGTH = 16 * 1024 * 1024  # 16 MiB


class TorrentFetchError(Exception):
    """Ошибка скачивания через торрент."""


@dataclass(frozen=True, slots=True)
class TorrentFetchResult:
    """Результат скачивания книги через торрент."""

    data: bytes
    pieces_downloaded: int
    piece_length: int
    abs_start: int
    abs_end: int
    elapsed_seconds: float
    file_path: Path | None = None
    from_cache: bool = False


async def fetch_book_via_torrent(
    torrent: Torrent,
    torrent_file: TorrentFile,
    entry: ArchiveEntry,
    *,
    piece_length: int = DEFAULT_PIECE_LENGTH,
    timeout: int = 300,
    on_progress: Callable[[int, int], None] | None = None,
    lib_id: int | None = None,
) -> TorrentFetchResult:
    """Скачать .fb2 из торрента точечно.

    Args:
        torrent: модель торрента (нужны id, magnet, resume_data)
        torrent_file: файл внутри торрента (нужен byte_offset, file_index)
        entry: запись в archive_entries (нужны local_header_offset, compressed_size, filename)
        piece_length: размер piece-а
        timeout: таймаут скачивания
        on_progress: callback(downloaded_pieces, total_pieces)

    Returns:
        TorrentFetchResult с содержимым .fb2
    """
    # 1. Вычисляем абсолютные координаты
    abs_start = torrent_file.byte_offset + entry.local_header_offset
    abs_end = abs_start + HEADER_SAFETY + entry.compressed_size
    first_piece = abs_start // piece_length
    last_piece = (abs_end - 1) // piece_length
    num_pieces = last_piece - first_piece + 1

    logger.info(
        "fetch_book_via_torrent: lib_id=%s archive=%s abs=[%d..%d] pieces=[%d..%d] (%d pieces)",
        entry.lib_id,
        torrent_file.path,
        abs_start,
        abs_end,
        first_piece,
        last_piece,
        num_pieces,
    )

    # 2. Скачиваем через TorrentManager
    mgr = get_torrent_manager()

    t0 = time.perf_counter()
    await mgr.ensure_torrent(torrent.id, torrent.magnet, torrent.resume_data)
    await mgr.download_range(
        torrent.id,
        abs_start=abs_start,
        abs_end=abs_end,
        lib_id=lib_id,
        piece_length=piece_length,
        timeout=timeout,
        on_progress=on_progress,
    )
    elapsed = time.perf_counter() - t0

    # После download_range — собираем данные piece-ов
    data_pieces = []
    for p in range(first_piece, last_piece + 1):
        piece_data = await mgr.read_piece(torrent.id, p)
        data_pieces.append(piece_data)

    # Склеиваем и извлекаем нужный диапазон
    full_piece_data = b"".join(data_pieces)
    rel_start = abs_start - first_piece * piece_length
    rel_end = abs_end - first_piece * piece_length
    buf = full_piece_data[rel_start:rel_end]


    # 4. Читаем нужные piece-ы в память через libtorrent
    pieces_data: list[bytes] = []
    for p in range(first_piece, last_piece + 1):
        piece_bytes = await mgr.read_piece(torrent.id, p)
        pieces_data.append(piece_bytes)

    full = b"".join(pieces_data)
    # Координаты внутри первого piece-а
    rel_start = abs_start - first_piece * piece_length
    rel_end = abs_end - first_piece * piece_length
    buf = full[rel_start:rel_end]

    if not buf:
        raise TorrentFetchError(
            f"Read 0 bytes from piece {first_piece} "
            f"at [{rel_start}..{rel_end})"
        )

    # 5. Распаковываем
    try:
        data = _parse_and_extract(
            buf,
            expected_filename=entry.filename,
            expected_compression=entry.compression,
            expected_crc=entry.crc32,
            expected_uncompressed=entry.uncompressed_size,
        )
    except Exception as exc:
        raise TorrentFetchError(f"Extract failed: {exc}") from exc

    logger.info(
        "fetch_book_via_torrent: lib_id=%s done in %.1fs, %d bytes",
        entry.lib_id,
        elapsed,
        len(data),
    )

    return TorrentFetchResult(
        data=data,
        pieces_downloaded=num_pieces,
        piece_length=piece_length,
        abs_start=abs_start,
        abs_end=abs_end,
        elapsed_seconds=elapsed,
        file_path=None,
        from_cache=False,
    )


def _parse_and_extract(
    buf: bytes,
    *,
    expected_filename: str,
    expected_compression: int,
    expected_crc: int,
    expected_uncompressed: int,
) -> bytes:
    """Парсит локальный заголовок ZIP и распаковывает данные."""
    if len(buf) < 30:
        raise ValueError(f"Buffer too small: {len(buf)}")

    sig = buf[:4]
    if sig != b"PK\x03\x04":
        raise ValueError(f"Bad signature: {sig!r} (expected b'PK\\x03\\x04')")

    (
        _sig, _ver, _flags, compression, _mt, _md, crc32,
        compressed_size, uncompressed_size, fn_len, ex_len,
    ) = struct.unpack_from("<IHHHHHIIIHH", buf, 0)

    if compression != expected_compression:
        logger.warning(
            "Compression mismatch: %d != %d", compression, expected_compression
        )

    filename_start = 30
    filename_end = filename_start + fn_len
    filename = buf[filename_start:filename_end].decode("utf-8", errors="replace")

    if filename != expected_filename:
        raise ValueError(
            f"Filename mismatch: {filename!r} != {expected_filename!r}"
        )

    data_start = filename_end + ex_len
    data_end = data_start + compressed_size

    if data_end > len(buf):
        raise ValueError(
            f"Buffer too small for data: need {data_end}, have {len(buf)}"
        )

    compressed = buf[data_start:data_end]

    if compression == 0:
        data = compressed
    elif compression == 8:
        try:
            data = zlib.decompress(compressed, -15)
        except zlib.error as exc:
            raise ValueError(f"zlib decompress failed: {exc}") from exc
    else:
        raise ValueError(f"Unsupported compression: {compression}")

    actual_crc = zlib.crc32(data) & 0xFFFFFFFF
    if actual_crc != crc32:
        raise ValueError(
            f"CRC32 mismatch: {actual_crc:#010x} != {crc32:#010x}"
        )

    if len(data) != uncompressed_size:
        logger.warning(
            "Uncompressed size mismatch: %d != %d", len(data), uncompressed_size
        )

    return data
