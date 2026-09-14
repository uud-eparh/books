"""CLI: просканировать ZIP-архивы торрента и сохранить содержимое в БД.

Пример:
    python -m scripts.index_archives --torrent-id 1
    python -m scripts.index_archives --torrent-id 1 --force
    python -m scripts.index_archives --torrent-id 1 --only fb2-000024-030559.zip
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402

from app.db.base import async_session_maker  # noqa: E402
from app.db.models import ArchiveEntry, Torrent, TorrentFile  # noqa: E402
from app.parsers.zip_indexer import scan_zip_safe  # noqa: E402

# Сколько записей вставлять за раз
BATCH_SIZE = 5000

# Расширения, которые индексируем (остальные — пропускаем)
INDEXED_EXTENSIONS = (".zip",)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Index ZIP archives of a torrent")
    p.add_argument("--torrent-id", type=int, required=True)
    p.add_argument("--force", action="store_true", help="Переиндексировать всё")
    p.add_argument(
        "--only",
        action="append",
        default=[],
        help="Обработать только конкретный файл (можно указать несколько)",
    )
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


async def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async with async_session_maker() as session:
        torrent = await session.get(Torrent, args.torrent_id)
        if torrent is None:
            print(f"❌ Торрент id={args.torrent_id} не найден")
            return 2

        print(f"📦 Торрент: id={torrent.id} name={torrent.name!r}")
        print(f"💾 Save:    {torrent.save_path}")

        # Получаем список файлов торрента, которые будем индексировать
        stmt = select(TorrentFile).where(TorrentFile.torrent_id == torrent.id)
        if args.only:
            stmt = stmt.where(TorrentFile.path.in_(args.only))
        else:
            # Фильтруем по расширению — берём только .zip
            stmt = stmt.where(
                func.lower(TorrentFile.path).endswith(INDEXED_EXTENSIONS[0])
            )
        stmt = stmt.order_by(TorrentFile.file_index)

        result = await session.execute(stmt)
        torrent_files: list[TorrentFile] = list(result.scalars().all())

        if not torrent_files:
            print("❌ Нет файлов для индексации (проверь --only или расширения)")
            return 2

        print(f"📚 Файлов для индексации: {len(torrent_files)}")
        print()

        if args.force:
            print("🗑  Удаляю старые записи archive_entries…")
            tf_ids = [tf.id for tf in torrent_files]
            await session.execute(
                delete(ArchiveEntry).where(ArchiveEntry.torrent_file_id.in_(tf_ids))
            )
            await session.commit()

        # Определяем save_path — путь к папке торрента
        # В БД: "D:/Users/Downloads/fb2.Flibusta.Net"
        # Файлы внутри: "fb2.Flibusta.Net/fb2-000024-030559.zip" — но path уже нормализован (без префикса).
        # Значит, полный путь = save_path + / + path? Нет:
        # save_path — это корень торрента. Внутри торрента файлы лежат по путям типа "fb2-000024-030559.zip"
        # (после нормализации). Реальный путь на диске: save_path/<torrent_name>/<path>?
        # В нашем случае торрент имеет корневую папку "fb2.Flibusta.Net", и save_path её включает.
        # Реально файлы лежат в save_path (который = D:/Users/Downloads/fb2.Flibusta.Net),
        # а имена файлов внутри — просто "fb2-000024-030559.zip".
        # Но так как мы нормализовали пути (убрали префикс), получается:
        # реальный_путь = save_path / normalized_path
        # Проверим для первого файла.
        base_path = Path(torrent.save_path)

        t0 = time.perf_counter()
        total_entries = 0
        total_files = 0
        errors: list[tuple[str, str]] = []

        for i, tf in enumerate(torrent_files, start=1):
            # Собираем реальный путь
            # ВАЖНО: "path" в torrent_files — без префикса.
            # Но реальный файл на диске лежит по пути: save_path/<original_path_with_prefix>.
            # Так как торрент имеет корневую папку "fb2.Flibusta.Net", оригинальный путь = "fb2.Flibusta.Net/<path>"
            # Поэтому:
            #   реальный_путь = base_path / path  # где path уже без префикса, и base_path = .../fb2.Flibusta.Net
            # Это совпадает, если в торренте нет доп. вложенности.
            zip_path = base_path / tf.path

            if not zip_path.exists():
                errors.append((tf.path, f"file not found: {zip_path}"))
                continue

            entries, error = scan_zip_safe(zip_path)
            if error:
                errors.append((tf.path, error))
                continue

            # Формируем записи для вставки
            rows = [
                ArchiveEntry(
                    torrent_file_id=tf.id,
                    filename=e.filename,
                    lib_id=e.lib_id,
                    compressed_size=e.compressed_size,
                    uncompressed_size=e.uncompressed_size,
                    local_header_offset=e.local_header_offset,
                    compression=e.compression,
                    crc32=e.crc32,
                )
                for e in entries
            ]

            # Батчами
            for j in range(0, len(rows), BATCH_SIZE):
                chunk = rows[j : j + BATCH_SIZE]
                session.add_all(chunk)
                await session.commit()

            total_entries += len(entries)
            total_files += 1

            print(
                f"   [{i:>3}/{len(torrent_files)}] {tf.path:<40} "
                f"{len(entries):>6} файлов  {_fmt_bytes(tf.size)}"
            )

        elapsed = time.perf_counter() - t0
        print()
        print("=" * 60)
        print("✅ ИНДЕКСАЦИЯ ЗАВЕРШЕНА")
        print("=" * 60)
        print(f"Обработано ZIP:        {total_files}")
        print(f"Записей в archive_entries: {total_entries:,}")
        print(f"Время:                 {elapsed:.1f} s")
        if total_files:
            print(f"Скорость:              {total_files / elapsed:.1f} архивов/сек")
        if errors:
            print()
            print(f"⚠️  Ошибок: {len(errors)}")
            for path, err in errors[:10]:
                print(f"   {path}: {err}")

        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))