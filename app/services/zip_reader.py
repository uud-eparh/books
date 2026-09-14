"""Низкоуровневое чтение отдельных файлов из ZIP по offset.

Стандартный zipfile.ZipFile требует полный центральный каталог в конце файла.
Но когда у нас есть точный offset локального заголовка — можно прочитать
только нужный диапазон байт и распаковать файл вручную.

Полезно для точечного скачивания: не тянем весь ZIP (гигабайты),
читаем только нужные piece-ы торрента.
"""

from __future__ import annotations

import logging
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Сигнатура локального заголовка ZIP: PK\x03\x04
LOCAL_HEADER_SIG = b"PK\x03\x04"

# Минимальная длина локального заголовка (без filename и extra)
LOCAL_HEADER_FIXED_SIZE = 30

# Сколько байт читать для заголовка максимум (filename + extra имеют лимиты)
# filename <= 65535, extra <= 65535 (по спеке), но реально нам хватит 4 KiB.
MAX_HEADER_READ = 4096

# Методы сжатия
COMPRESSION_STORED = 0
COMPRESSION_DEFLATE = 8

# Размер "хвоста" после данных, который может содержать data descriptor.
# Если в local header flags & 0x08 — данные после compressed_data содержат
# crc32/comp_size/uncomp_size (12 или 16 байт). Читаем с запасом.
DATA_DESCRIPTOR_MAX = 20


class ZipReadError(Exception):
    """Ошибка чтения ZIP."""


@dataclass(frozen=True, slots=True)
class LocalHeader:
    """Разобранный локальный заголовок ZIP."""

    signature: bytes
    version_needed: int
    flags: int
    compression: int
    mod_time: int
    mod_date: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    filename_len: int
    extra_len: int
    filename: str

    @property
    def data_offset(self) -> int:
        """Смещение сжатых данных относительно начала локального заголовка."""
        return LOCAL_HEADER_FIXED_SIZE + self.filename_len + self.extra_len


def parse_local_header(buf: bytes) -> LocalHeader:
    """Парсит локальный заголовок ZIP из буфера.

    Args:
        buf: байты, начинающиеся с signature локального заголовка.

    Returns:
        LocalHeader с разобранными полями.

    Raises:
        ZipReadError: если сигнатура неверна или буфер слишком мал.
    """
    if len(buf) < LOCAL_HEADER_FIXED_SIZE:
        raise ZipReadError(
            f"Header buffer too small: {len(buf)} < {LOCAL_HEADER_FIXED_SIZE}"
        )
    if buf[:4] != LOCAL_HEADER_SIG:
        raise ZipReadError(
            f"Bad local header signature: {buf[:4]!r} != {LOCAL_HEADER_SIG!r}"
        )

    (
        _sig,
        version_needed,
        flags,
        compression,
        mod_time,
        mod_date,
        crc32,
        compressed_size,
        uncompressed_size,
        filename_len,
        extra_len,
    ) = struct.unpack_from("<IHHHHHIIIHH", buf, 0)

    if len(buf) < LOCAL_HEADER_FIXED_SIZE + filename_len + extra_len:
        raise ZipReadError(
            f"Header buffer too small for filename+extra: "
            f"{len(buf)} < {LOCAL_HEADER_FIXED_SIZE + filename_len + extra_len}"
        )

    filename_bytes = buf[
        LOCAL_HEADER_FIXED_SIZE : LOCAL_HEADER_FIXED_SIZE + filename_len
    ]
    # Обычно UTF-8; если flags & 0x800 — точно UTF-8.
    # Флибуста пишет ASCII-имена (цифры + .fb2), так что проблем нет.
    try:
        filename = filename_bytes.decode("utf-8")
    except UnicodeDecodeError:
        filename = filename_bytes.decode("cp437", errors="replace")

    return LocalHeader(
        signature=_sig.to_bytes(4, "little"),
        version_needed=version_needed,
        flags=flags,
        compression=compression,
        mod_time=mod_time,
        mod_date=mod_date,
        crc32=crc32,
        compressed_size=compressed_size,
        uncompressed_size=uncompressed_size,
        filename_len=filename_len,
        extra_len=extra_len,
        filename=filename,
    )


def read_zip_entry(
    zip_path: Path,
    *,
    local_header_offset: int,
    expected_filename: str | None = None,
    expected_compressed_size: int | None = None,
) -> bytes:
    """Читает один файл из ZIP по offset локального заголовка.

    Args:
        zip_path: путь к ZIP-архиву.
        local_header_offset: смещение локального заголовка от начала файла
                             (из archive_entries.local_header_offset).
        expected_filename: ожидаемое имя файла (для проверки).
        expected_compressed_size: ожидаемый размер сжатых данных (для проверки).

    Returns:
        Распакованное содержимое файла (bytes).

    Raises:
        ZipReadError: если что-то не сходится.
    """
    if local_header_offset < 0:
        raise ZipReadError(f"Negative offset: {local_header_offset}")

    with zip_path.open("rb") as f:
        # 1. Читаем локальный заголовок (с запасом)
        f.seek(local_header_offset)
        header_buf = f.read(MAX_HEADER_READ)
        if not header_buf:
            raise ZipReadError(
                f"Cannot read header at offset {local_header_offset} in {zip_path}"
            )

        header = parse_local_header(header_buf)

        if expected_filename is not None and header.filename != expected_filename:
            raise ZipReadError(
                f"Filename mismatch: {header.filename!r} != {expected_filename!r}"
            )

        if (
            expected_compressed_size is not None
            and header.compressed_size != expected_compressed_size
        ):
            logger.warning(
                "Compressed size mismatch: header says %d, DB says %d",
                header.compressed_size,
                expected_compressed_size,
            )
            # Не падаем — доверяем заголовку. БД могла быть обновлена.
            # Но если разница существенная — это тревожно.

        # 2. Читаем сжатые данные
        data_offset = local_header_offset + header.data_offset
        f.seek(data_offset)
        compressed = f.read(header.compressed_size)
        if len(compressed) != header.compressed_size:
            raise ZipReadError(
                f"Short read: got {len(compressed)} bytes, "
                f"expected {header.compressed_size}"
            )

    # 3. Распаковываем
    if header.compression == COMPRESSION_STORED:
        data = compressed
    elif header.compression == COMPRESSION_DEFLATE:
        try:
            data = zlib.decompress(compressed, -15)  # raw deflate (без zlib-заголовка)
        except zlib.error as exc:
            raise ZipReadError(f"zlib decompress failed: {exc}") from exc
    else:
        raise ZipReadError(
            f"Unsupported compression method: {header.compression}"
        )

    # 4. Проверяем CRC32
    actual_crc = zlib.crc32(data) & 0xFFFFFFFF
    if actual_crc != header.crc32:
        raise ZipReadError(
            f"CRC32 mismatch: computed {actual_crc:#010x}, "
            f"expected {header.crc32:#010x}"
        )

    if len(data) != header.uncompressed_size:
        logger.warning(
            "Uncompressed size mismatch: got %d, expected %d",
            len(data),
            header.uncompressed_size,
        )

    return data