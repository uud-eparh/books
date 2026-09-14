"""Парсер ZIP-архивов для получения списка файлов внутри.

Использует стандартный zipfile.ZipFile.infolist() — читает только центральный
каталог, без распаковки данных. Очень быстро (~0.5 сек на большой архив).
"""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ZipEntry:
    """Один файл внутри ZIP-архива."""

    filename: str
    compressed_size: int
    uncompressed_size: int
    local_header_offset: int
    compression: int
    crc32: int
    lib_id: int | None


def _parse_lib_id(filename: str) -> int | None:
    """Извлекает LibID из имени файла.

    Ожидаем формат '{lib_id}.fb2' или '{lib_id}.fbd'.
    Если не подходит — возвращаем None.
    """
    base = filename.rsplit("/", 1)[-1]  # на случай вложенных путей
    if "." not in base:
        return None
    stem, ext = base.rsplit(".", 1)
    if ext.lower() not in ("fb2", "fbd"):
        return None
    if not stem.isdigit():
        return None
    try:
        return int(stem)
    except ValueError:
        return None


def scan_zip(zip_path: Path) -> list[ZipEntry]:
    """Читает центральный каталог ZIP и возвращает список файлов.

    Не распаковывает данные. Очень быстро.

    Raises:
        zipfile.BadZipFile: если файл битый или не ZIP.
    """
    entries: list[ZipEntry] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            # Пропускаем директории (в FB2-архивах их обычно нет, но на всякий)
            if info.is_dir():
                continue

            entries.append(
                ZipEntry(
                    filename=info.filename,
                    compressed_size=info.compress_size,
                    uncompressed_size=info.file_size,
                    local_header_offset=info.header_offset,
                    compression=info.compress_type,
                    crc32=info.CRC & 0xFFFFFFFF,  # приводим к беззнаковому
                    lib_id=_parse_lib_id(info.filename),
                )
            )

    return entries


def scan_zip_safe(zip_path: Path) -> tuple[list[ZipEntry], str | None]:
    """Безопасная версия: не бросает исключений, возвращает (entries, error)."""
    try:
        return scan_zip(zip_path), None
    except zipfile.BadZipFile as exc:
        return [], f"BadZipFile: {exc}"
    except FileNotFoundError:
        return [], f"FileNotFoundError: {zip_path}"
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"