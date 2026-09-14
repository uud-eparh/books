"""CLI: прогон парсера .inpx на реальном файле.

Пример:
    python -m scripts.parse_inpx
    python -m scripts.parse_inpx --limit 20 --show 5
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from pathlib import Path

# Чтобы можно было запускать как `python scripts/parse_inpx.py` без установки пакета
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.parsers.inpx import InpxParser  # noqa: E402


def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Parse .inpx and print stats")
    p.add_argument("--inpx", type=Path, default=None, help="Path to .inpx (default from .env)")
    p.add_argument("--limit", type=int, default=0, help="Ограничить число книг (0 = все)")
    p.add_argument("--show", type=int, default=5, help="Сколько книг напечатать")
    p.add_argument("--debug", action="store_true", help="Debug-логи")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.debug)

    inpx_path: Path = args.inpx or settings.inpx_path
    if not inpx_path.exists():
        print(f"❌ .inpx не найден: {inpx_path}", file=sys.stderr)
        return 2

    print(f"📖 Читаю {inpx_path} ({inpx_path.stat().st_size / 1024 / 1024:.1f} MB)")

    parser = InpxParser(inpx_path)

    # ---- meta
    t0 = time.perf_counter()
    meta = parser.read_meta()
    t_meta = time.perf_counter() - t0
    print(f"\n📚 Метаданные ({t_meta * 1000:.0f} ms):")
    print(f"   name        = {meta.name!r}")
    print(f"   version     = {meta.version!r}")
    print(f"   chunk_size  = {meta.chunk_size}")
    print(f"   description = {meta.description!r}")

    # ---- books
    print("\n⏳ Парсинг книг...")
    t0 = time.perf_counter()

    languages: Counter[str] = Counter()
    archives: Counter[str] = Counter()
    deleted = 0
    shown = 0

    for i, book in enumerate(parser.iter_books(), start=1):
        languages[book.language] += 1
        archives[book.archive_name] += 1
        if book.is_deleted:
            deleted += 1

        if shown < args.show:
            print(f"\n   [{i}] lib_id={book.lib_id}  archive={book.archive_name}")
            print(f"        title    = {book.title!r}")
            print(f"        authors  = {book.authors}")
            print(f"        genres   = {book.genres[:5]}{'...' if len(book.genres) > 5 else ''}")
            series_num_str = f"#{book.series_num}" if book.series_num is not None else ""
            series_str = f"{book.series!r} {series_num_str}".strip() if book.series else "—"
            print(f"        series   = {series_str}")
            print(f"        size     = {book.file_size} bytes")
            print(f"        lang     = {book.language}  date = {book.date_added}")
            print(f"        deleted  = {book.is_deleted}")
            if book.annotation:
                ann = book.annotation[:120] + ("..." if len(book.annotation) > 120 else "")
                print(f"        annot    = {ann!r}")
            shown += 1

        if args.limit and i >= args.limit:
            break

    elapsed = time.perf_counter() - t0
    total = i if 'i' in dir() else 0
    stats = parser.stats

    print("\n" + "=" * 60)
    print("📊 СТАТИСТИКА")
    print("=" * 60)
    print(f"Время парсинга:      {elapsed:.2f} s")
    print(f"Всего .inp-файлов:   {stats['files']}")
    print(f"Распарсено книг:     {stats['parsed']}")
    print(f"Пропущено строк:     {stats['skipped']}")
    print(f"Удалённых (флаг 1):  {deleted}")
    if elapsed > 0 and total:
        print(f"Скорость:            {total / elapsed:,.0f} книг/сек")
    if parser.last_error:
        print(f"Последняя ошибка:    {parser.last_error}")

    print("\n🌍 Языки (top-10):")
    for lang, cnt in languages.most_common(10):
        print(f"   {lang or '(пусто)':<10} {cnt:>10,}")

    print("\n🗂  Архивов в торренте:")
    print(f"   всего уникальных: {len(archives)}")
    print("   топ-5:")
    for arch, cnt in archives.most_common(5):
        print(f"   {arch:<40} {cnt:>10,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())