"""CLI: извлечь книгу по lib_id.

Автоматически выбирает источник:
  - локальный ZIP (если есть и доступен)
  - торрент (fallback)

Примеры:
    python -m scripts.download_book --lib-id 811194
    python -m scripts.download_book --lib-id 496588 --output ./test.fb2
    python -m scripts.download_book --lib-id 496588 --prefer-torrent
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import async_session_maker  # noqa: E402
from app.services.library import (  # noqa: E402
    BookContentError,
    BookNotFoundError,
    fetch_book_content,
)
from app.services.torrent_manager import (  # noqa: E402
    setup_torrent_manager,
    shutdown_torrent_manager,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch book content (local or torrent)")
    p.add_argument("--lib-id", type=int, required=True)
    p.add_argument("--torrent-id", type=int, default=None)
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Куда сохранить .fb2 (по умолчанию — не сохранять)",
    )
    p.add_argument(
        "--prefer-torrent",
        action="store_true",
        help="Игнорировать локальный ZIP, всегда качать через торрент",
    )
    p.add_argument(
        "--show-head",
        type=int,
        default=300,
        help="Сколько байт содержимого показать",
    )
    return p.parse_args()


def _progress_printer(done: int, total: int) -> None:
    pct = done / total * 100 if total else 0
    print(f"\r   piece-ы: {done}/{total} ({pct:5.1f}%)", end="", flush=True)


async def main() -> int:
    args = parse_args()

    await setup_torrent_manager()
    try:
        async with async_session_maker() as session:
            t0 = time.perf_counter()
            try:
                content = await fetch_book_content(
                    session,
                    args.lib_id,
                    torrent_id=args.torrent_id,
                    prefer_torrent=args.prefer_torrent,
                    on_progress=_progress_printer,
                )
            except BookNotFoundError as exc:
                print(f"❌ {exc}")
                return 2
            except BookContentError as exc:
                print(f"❌ {exc}")
                return 1
            except Exception as exc:  # noqa: BLE001
                print(f"❌ Unexpected error: {exc!r}")
                raise

            elapsed_ms = (time.perf_counter() - t0) * 1000

            print()  # перевод строки после progress
            print(f"✅ Книга получена за {elapsed_ms:.0f} ms")
            print(f"   lib_id:   {content.lib_id}")
            print(f"   title:    {content.title!r}")
            print(f"   авторы:   {content.authors}")
            print(f"   размер:   {len(content.data):,} байт")
            print(f"   источник: {content.source}")
            print(f"   время:    {content.elapsed_seconds:.2f}s")
            print()

            head = content.data[: args.show_head]
            try:
                text = head.decode("utf-8", errors="replace")
                print("---- начало файла ----")
                print(text)
                print("---- ... ----")
            except Exception:  # noqa: BLE001
                print("---- первые байты (hex) ----")
                print(head.hex())

            if args.output:
                args.output.write_bytes(content.data)
                print(f"\n💾 Сохранено в {args.output}")

            return 0
    finally:
        await shutdown_torrent_manager()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))