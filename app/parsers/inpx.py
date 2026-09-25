"""Парсер каталога .inpx (Flibusta FB2 Local).

.inpx — это ZIP-архив, внутри которого:
  - collection.info  — метаданные библиотеки
  - version.info     — версия каталога
  - *.inp            — по одному файлу на каждый ZIP-архив в торренте,
                       строки разделены \\x04

Имя .inp-файла совпадает с именем ZIP-архива в торренте,
только расширение меняется с .inp на .zip.
Файлы внутри ZIP-архива называются {lib_id}.fb2.
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Разделитель полей в .inp-строке
FIELD_SEP = "\x04"

# Минимальное количество полей, чтобы строка считалась валидной
MIN_FIELDS = 9


@dataclass(frozen=True, slots=True)
class LibraryMeta:
    """Метаданные библиотеки из collection.info."""

    name: str
    version: str
    chunk_size: int
    description: str


@dataclass(frozen=True, slots=True)
class Book:
    """Одна книга из каталога .inpx."""

    lib_id: int
    title: str
    authors: list[str]
    genres: list[str]
    series: str | None
    series_num: int | None
    file_size: int
    language: str
    date_added: date | None
    annotation: str | None
    archive_name: str
    is_deleted: bool


class InpxParser:
    """Потоковый парсер .inpx.

    Пример:
        parser = InpxParser(Path("flibusta_fb2_local.inpx"))
        meta = parser.read_meta()
        for book in parser.iter_books():
            ...
    """

    def __init__(self, inpx_path: Path) -> None:
        self.inpx_path = Path(inpx_path)
        if not self.inpx_path.exists():
            raise FileNotFoundError(f".inpx not found: {self.inpx_path}")
        self._stats = {"parsed": 0, "skipped": 0, "files": 0}
        self._last_error: str | None = None

    # ---------------------------------------------------------------- meta

    def read_meta(self) -> LibraryMeta:
        """Прочитать collection.info и version.info."""
        with zipfile.ZipFile(self.inpx_path) as zf:
            names = set(zf.namelist())
            collection = self._read_text(zf, "collection.info") if "collection.info" in names else ""
            version = self._read_text(zf, "version.info") if "version.info" in names else ""

        lines = [line.strip() for line in collection.splitlines() if line.strip()]
        name = lines[0] if len(lines) > 0 else "Unknown"
        version_from_collection = lines[1] if len(lines) > 1 else ""

        chunk_size = 0
        if len(lines) > 2:
            try:
                chunk_size = int(lines[2])
            except ValueError:
                chunk_size = 0

        description = lines[3] if len(lines) > 3 else ""

        # version.info обычно содержит одну строку с датой
        final_version = version.strip() or version_from_collection

        return LibraryMeta(
            name=name,
            version=final_version,
            chunk_size=chunk_size,
            description=description,
        )

    # ---------------------------------------------------------------- books

    def iter_books(self) -> Iterator[Book]:
        """Генератор всех книг из всех .inp-файлов.

        Не держит всё в памяти. Битые строки пропускаются
        с логом в debug.
        """
        self._stats = {"parsed": 0, "skipped": 0, "files": 0}

        with zipfile.ZipFile(self.inpx_path) as zf:
            inp_names = sorted(
                name for name in zf.namelist() if name.lower().endswith(".inp")
            )
            logger.info("Found %d .inp files inside %s", len(inp_names), self.inpx_path.name)

            for inp_name in inp_names:
                self._stats["files"] += 1
                archive_name = self._inp_to_zip_name(inp_name)
                logger.debug("Parsing %s -> archive %s", inp_name, archive_name)

                with zf.open(inp_name) as raw:
                    for line_no, raw_line in enumerate(raw, start=1):
                        try:
                            book = self._parse_line(raw_line, archive_name)
                        except Exception as exc:  # noqa: BLE001
                            self._stats["skipped"] += 1
                            self._last_error = f"{inp_name}:{line_no}: {exc!r}"
                            logger.debug(
                                "Skip broken line %s:%d: %r",
                                inp_name,
                                line_no,
                                exc,
                            )
                            continue

                        if book is None:
                            self._stats["skipped"] += 1
                            continue

                        self._stats["parsed"] += 1
                        yield book

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # ---------------------------------------------------------------- internals

    @staticmethod
    def _read_text(zf: zipfile.ZipFile, name: str) -> str:
        try:
            with zf.open(name) as f:
                data = f.read()
        except KeyError:
            return ""
        # Флибуста пишет в UTF-8, но на всякий случай подстрахуемся.
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("cp1251", errors="replace")

    @staticmethod
    def _inp_to_zip_name(inp_name: str) -> str:
        # f.fb2-811194-815075.inp -> f.fb2-811194-815075.zip
        base = inp_name.rsplit("/", 1)[-1]
        if base.lower().endswith(".inp"):
            base = base[:-4] + ".zip"
        return base

    def _parse_line(self, raw_line: bytes, archive_name: str) -> Book | None:
        # Декодируем
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            line = raw_line.decode("cp1251", errors="replace")

        # Убираем \r\n и финальный разделитель
        line = line.rstrip("\r\n")
        if not line.strip():
            return None

        # Разбиваем по \x04
        fields = line.split(FIELD_SEP)
        if len(fields) < MIN_FIELDS:
            return None

        # ---- lib_id (индекс 5)
        try:
            lib_id = int(fields[5])
        except (ValueError, IndexError):
            return None

        # ---- title (индекс 2)
        title = fields[2].strip() if len(fields) > 2 else ""
        if not title:
            # Книга без названия — пропускаем
            return None

        # ---- authors (индекс 0)
        authors_raw = fields[0].strip() if fields else ""
        authors = self._split_list(authors_raw, sep=":")

        # ---- genres (индекс 1)
        genres_raw = fields[1].strip() if len(fields) > 1 else ""
        genres = self._split_list(genres_raw, sep=":")

        # ---- series (индекс 3), series_num (индекс 4)
        series = fields[3].strip() if len(fields) > 3 else ""
        series = series or None

        series_num: int | None = None
        if len(fields) > 4 and fields[4].strip():
            try:
                series_num = int(fields[4])
                if series_num == 0:
                    series_num = None
            except ValueError:
                series_num = None

        # ---- file_size (индекс 6)
        file_size = 0
        if len(fields) > 6 and fields[6].strip():
            try:
                file_size = int(fields[6])
            except ValueError:
                file_size = 0

        # ---- is_deleted (индекс 8)
        is_deleted = False
        if len(fields) > 8 and fields[8].strip():
            is_deleted = fields[8].strip() not in ("0", "")

        # ---- language (индекс 11)
        language = fields[11].strip() if len(fields) > 11 else ""

        # ---- date_added (индекс 10)
        date_added = self._parse_date(fields[10].strip()) if len(fields) > 10 else None

        # ---- annotation (индекс 13)
        annotation: str | None = None
        if len(fields) > 13:
            ann = fields[13].strip()
            annotation = ann or None

        return Book(
            lib_id=lib_id,
            title=title,
            authors=authors,
            genres=genres,
            series=series,
            series_num=series_num,
            file_size=file_size,
            language=language,
            date_added=date_added,
            annotation=annotation,
            archive_name=archive_name,
            is_deleted=is_deleted,
        )

    @staticmethod
    def _split_list(value: str, sep: str) -> list[str]:
        if not value:
            return []
        parts = [p.strip() for p in value.split(sep)]
        # Убираем пустые (частый хвост вида "Автор1:Автор2:")
        parts = [p for p in parts if p]
        # Чистим хвостовые/ведущие запятые у авторов: "Джейн,О. О.," -> "Джейн,О. О."
        parts = [p.strip(",") for p in parts]
        # Ещё раз убираем пустые после чистки
        return [p for p in parts if p]

    @staticmethod
    def _parse_date(value: str) -> date | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                dt = datetime.strptime(value, fmt)
                return dt.date()
            except ValueError:
                continue
        return None
