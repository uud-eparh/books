"""CLI: скачать книгу через торрент (точечно) и проверить.

Пример:
    python -m scripts.download_book_via_torrent --lib-id 496588
    python -m scripts.download_book_via_torrent --lib-id 496588 --output test.fb2
    python -m scripts.download_book_via_torrent --lib-id 496588 --compare-local
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db.base import async_session_maker  # noqa: E402
from app.db.models import ArchiveEntry, Book, Torrent, TorrentFile  # noqa: E402
from app.services.torrent_manager import (  # noqa: E402
    get_torrent_manager,
    setup_torrent_manager,
    shutdown_torrent_manager,
)
from app.services.zip_reader import read_zip_entry  # noqa: E402

logger = logging.getLogger(__name__)

# Запас на локальный заголовок ZIP (filename + extra)
# 30 (фиксированная часть) + 255 (max filename) + 1024 (extra + запас)
HEADER_SAFETY = 1300


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download book via torrent (point download)")
    p.add_argument("--lib-id", type=int, required=True)
    p.add_argument("--torrent-id", type=int, default=1)
    p.add_argument("--output", type=Path, default=None, help="Куда сохранить .fb2")
    p.add_argument(
        "--compare-local",
        action="store_true",
        help="Сравнить результат с локальным ZIP (если есть)",
    )
    p.add_argument("--timeout", type=int, default=300, help="Таймаут скачивания, сек")
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def _progress_printer(done: int, total: int) -> None:
    pct = done / total * 100 if total else 0
    print(f"\r   piece-ы: {done}/{total} ({pct:5.1f}%)", end="", flush=True)


async def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 1. Найти книгу, archive_entry, torrent_file
    async with async_session_maker() as session:
        book = await session.scalar(
            select(Book)
            .where(Book.lib_id == args.lib_id, Book.torrent_id == args.torrent_id)
            .limit(1)
        )
        if book is None:
            print(f"❌ Book lib_id={args.lib_id} not found")
            return 2

        tf = await session.scalar(
            select(TorrentFile)
            .where(
                TorrentFile.torrent_id == book.torrent_id,
                TorrentFile.path == book.archive_name,
            )
            .limit(1)
        )
        if tf is None:
            print(f"❌ TorrentFile for {book.archive_name!r} not found")
            return 2

        ae = await session.scalar(
            select(ArchiveEntry)
            .where(
                ArchiveEntry.torrent_file_id == tf.id,
                ArchiveEntry.lib_id == args.lib_id,
            )
            .limit(1)
        )
        if ae is None:
            print(f"❌ ArchiveEntry for lib_id={args.lib_id} not found")
            return 2

        torrent = await session.get(Torrent, book.torrent_id)
        if torrent is None:
            print(f"❌ Torrent id={book.torrent_id} not found")
            return 2

        # 2. Вычислить абсолютные координаты
        abs_start = tf.byte_offset + ae.local_header_offset
        abs_end = abs_start + HEADER_SAFETY + ae.compressed_size

        piece_length = 16 * 1024 * 1024  # 16 MiB
        first_piece = abs_start // piece_length
        last_piece = (abs_end - 1) // piece_length
        num_pieces = last_piece - first_piece + 1

        print(f"📖 Книга: {book.title!r}")
        print(f"   авторы: {book.authors}")
        print(f"   архив:  {tf.path}")
        print(f"   файл:   {ae.filename} ({ae.compressed_size:,} байт сжатый)")
        print()
        print(f"📐 Координаты в торренте:")
        print(f"   ZIP byte_offset:       {tf.byte_offset:>15,}")
        print(f"   local_header_offset:   {ae.local_header_offset:>15,}")
        print(f"   compressed_size:       {ae.compressed_size:>15,}")
        print(f"   abs_start:             {abs_start:>15,}")
        print(f"   abs_end:               {abs_end:>15,}")
        print(f"   piece_length:          {piece_length:>15,}")
        print(f"   first_piece:           {first_piece}")
        print(f"   last_piece:            {last_piece}")
        print(f"   piece-ов к скачиванию: {num_pieces}")
        print(f"   объём:                 ~{num_pieces * piece_length / 1024 / 1024:.1f} MiB")
        print()

        torrent_magnet = torrent.magnet
        torrent_resume = torrent.resume_data

    # 3. Скачать через TorrentManager
    await setup_torrent_manager()
    try:
        mgr = get_torrent_manager()
        print("⏳ Добавляю торрент в сессию…")
        t0 = time.perf_counter()
        await mgr.ensure_torrent(
            args.torrent_id, torrent_magnet, torrent_resume
        )
        print(f"✅ Торрент добавлен за {time.perf_counter() - t0:.1f}s")
        print()

        print(f"⏳ Скачиваю piece-ы {first_piece}..{last_piece}…")
        t0 = time.perf_counter()
        await mgr.download_range(
            args.torrent_id,
            abs_start=abs_start,
            abs_end=abs_end,
            piece_length=piece_length,
            timeout=args.timeout,
            on_progress=_progress_printer,
        )
        elapsed = time.perf_counter() - t0
        print()  # перевод строки после progress
        print(f"✅ Скачано за {elapsed:.1f}s")

        # Даём ОС время на синхронизацию файловой системы
        await asyncio.sleep(0.5)
        
        # 4. Определить путь к файлу на диске
        # libtorrent сохраняет данные в save_path/<torrent_name>/<path>
        # Но у нас torrent_name = "fb2.Flibusta.Net" и save_path = "tmp_downloads"
        # → файл в tmp_downloads/fb2.Flibusta.Net/fb2-495619-497807.zip
        # Проще всего — узнать у libtorrent
        local_path = mgr.get_file_path(args.torrent_id, tf.file_index)
        if local_path is None or not local_path.exists():
            print(f"❌ Файл не найден: {local_path}")
            return 1

        print(f"   путь: {local_path}")
        file_size = local_path.stat().st_size
        print(f"   размер файла на диске: {file_size:,} (должно быть {tf.size:,})")

        # 5. Прочитать данные из sparse-файла
        # abs_start и abs_end — координаты в торренте, а внутри файла это:
        rel_start = abs_start - tf.byte_offset
        rel_end = abs_end - tf.byte_offset

        print(f"⏳ Читаю байты [{rel_start:,} .. {rel_end:,}) из ZIP…")
        with local_path.open("rb") as f:
            f.seek(rel_start)
            buf = f.read(rel_end - rel_start)

        if len(buf) < HEADER_SAFETY + ae.compressed_size:
            print(f"⚠️  Прочитано только {len(buf)} байт (ожидали больше)")
            # Всё равно пробуем — может, данных хватит

        # 6. Распаковать через наш zip_reader
        print(f"⏳ Распаковываю…")
        try:
            data = _extract_from_buffer(
                buf,
                expected_filename=ae.filename,
                expected_compression=ae.compression,
                expected_crc=ae.crc32,
                expected_uncompressed=ae.uncompressed_size,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"❌ Ошибка распаковки: {exc!r}")
            return 1

        print(f"✅ Получено {len(data):,} байт")
        print(f"   заголовок: {data[:80]!r}")

        # 7. Опционально — сравнить с локальной версией
        if args.compare_local:
            local_zip = Path(torrent.save_path) / tf.path
            if local_zip.exists():
                print()
                print(f"⏳ Сравниваю с локальным ZIP {local_zip.name}…")
                local_data = read_zip_entry(
                    local_zip,
                    local_header_offset=ae.local_header_offset,
                    expected_filename=ae.filename,
                )
                if local_data == data:
                    print(f"✅ Данные СОВПАДАЮТ с локальной версией")
                else:
                    print(f"❌ Данные НЕ СОВПАДАЮТ ({len(data)} vs {len(local_data)})")
            else:
                print(f"⚠️  Локального ZIP нет: {local_zip}")

        # 8. Сохранить
        if args.output:
            args.output.write_bytes(data)
            print(f"\n💾 Сохранено в {args.output}")

        return 0
    finally:
        await shutdown_torrent_manager()


def _extract_from_buffer(
    buf: bytes,
    *,
    expected_filename: str,
    expected_compression: int,
    expected_crc: int,
    expected_uncompressed: int,
) -> bytes:
    """Парсит локальный заголовок ZIP из буфера и распаковывает данные.

    Переиспользует логику из zip_reader, но работает с bytes, а не с Path.
    """
    import struct
    import zlib

    if len(buf) < 30:
        raise ValueError(f"Buffer too small: {len(buf)}")

    sig = buf[:4]
    if sig != b"PK\x03\x04":
        raise ValueError(f"Bad signature: {sig!r}")

    (
        _sig, _ver, _flags, compression, _mt, _md, crc32,
        compressed_size, uncompressed_size, fn_len, ex_len,
    ) = struct.unpack_from("<IHHHHHIIIHH", buf, 0)

    if compression != expected_compression:
        print(f"⚠️  Compression mismatch: {compression} != {expected_compression}")

    filename_start = 30
    filename_end = filename_start + fn_len
    filename = buf[filename_start:filename_end].decode("utf-8", errors="replace")

    if filename != expected_filename:
        raise ValueError(f"Filename mismatch: {filename!r} != {expected_filename!r}")

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
        data = zlib.decompress(compressed, -15)
    else:
        raise ValueError(f"Unsupported compression: {compression}")

    actual_crc = zlib.crc32(data) & 0xFFFFFFFF
    if actual_crc != crc32:
        raise ValueError(
            f"CRC32 mismatch: {actual_crc:#010x} != {crc32:#010x}"
        )

    if len(data) != uncompressed_size:
        print(f"⚠️  Uncompressed size mismatch: {len(data)} != {uncompressed_size}")

    return data


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))