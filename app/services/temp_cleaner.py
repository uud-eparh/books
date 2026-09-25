"""Очистка временных файлов.

1. LRU для ZIP-файлов в tmp_downloads: удаляем самые старые,
   если суммарный размер > TEMP_DOWNLOAD_MAX_GB.
2. TTL для .fb2: удаляем через TEMP_FILE_TTL_MINUTES после mtime.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def enforce_cache_limit(max_gb: int | None = None) -> int:
    """Удалить самые старые ZIP, если размер tmp_downloads > max_gb.

    Returns:
        Сколько байт освобождено.
    """
    max_gb = max_gb or settings.temp_download_max_gb
    root = settings.temp_download_path
    if not root.exists():
        return 0

    max_bytes = max_gb * 1024 * 1024 * 1024
    total = _dir_size_bytes(root)

    if total <= max_bytes:
        return 0

    logger.info(
        "TempCleaner: tmp_downloads = %.2f GiB > limit %.2f GiB, cleaning…",
        total / 1024**3,
        max_gb,
    )

    # Собираем все .zip файлы с mtime
    zips = []
    for p in root.rglob("*.zip"):
        if p.is_file():
            try:
                zips.append((p.stat().st_mtime, p.stat().st_size, p))
            except OSError:
                pass

    # Сортируем по mtime (старые первыми)
    zips.sort(key=lambda x: x[0])

    freed = 0
    for _, size, path in zips:
        if total - freed <= max_bytes:
            break
        try:
            path.unlink()
            freed += size
            logger.info("TempCleaner: removed %s (%.1f MiB)", path.name, size / 1024**2)
        except OSError as exc:
            logger.warning("TempCleaner: failed to remove %s: %r", path, exc)

    logger.info("TempCleaner: freed %.2f GiB", freed / 1024**3)
    return freed


def cleanup_old_fb2(ttl_minutes: int | None = None) -> int:
    """Удалить .fb2 старше TTL.

    Returns:
        Сколько файлов удалено.
    """
    ttl_minutes = ttl_minutes or settings.temp_file_ttl_minutes
    root = settings.temp_download_path
    if not root.exists():
        return 0

    cutoff = time.time() - ttl_minutes * 60
    removed = 0

    for p in root.rglob("*.fb2"):
        if not p.is_file():
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
                logger.debug("TempCleaner: removed old .fb2 %s", p.name)
        except OSError:
            pass

    return removed


async def background_cleaner(interval_seconds: int = 3600) -> None:
    """Запускается в фоне: чистит кэш раз в interval_seconds."""
    logger.info(
        "TempCleaner: background cleaner started (interval=%ds)", interval_seconds
    )
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            enforce_cache_limit()
            cleanup_old_fb2()
        except asyncio.CancelledError:
            logger.info("TempCleaner: background cleaner cancelled")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("TempCleaner: background cleaner error")
