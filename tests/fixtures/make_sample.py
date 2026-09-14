"""Генерирует маленький тестовый .inpx для юнит-тестов.

Запуск:
    python tests/fixtures/make_sample.py
Создаёт:
    tests/fixtures/sample.inpx
"""

from __future__ import annotations

import zipfile
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "sample.inpx"

FIELD_SEP = "\x04"


def _make_line(
    authors: str,
    genres: str,
    title: str,
    series: str = "",
    series_num: str = "",
    lib_id: int = 0,
    file_size: int = 0,
    lib_id_2: int | None = None,
    deleted: int = 0,
    ext: str = "fb2",
    date_added: str = "2025-01-01",
    language: str = "ru",
    empty1: str = "",
    annotation: str = "",
    empty2: str = "",
) -> str:
    if lib_id_2 is None:
        lib_id_2 = lib_id
    fields = [
        authors,
        genres,
        title,
        series,
        series_num,
        str(lib_id),
        str(file_size),
        str(lib_id_2),
        str(deleted),
        ext,
        date_added,
        language,
        empty1,
        annotation,
        empty2,
    ]
    return FIELD_SEP.join(fields) + "\n"


def main() -> None:
    collection_info = (
        "Flibusta FB2 Local\n"
        "flibusta_20260701\n"
        "65536\n"
        "Локальная коллекция библиотеки Флибуста (только FB2)\n"
    )
    version_info = "20260701\n"

    # Файл 1: обычные книги
    f1_lines = [
        _make_line(
            authors="Джейн,О. О.,:",
            genres="love_contemporary:love:",
            title="Чертова невеста правильного парень",
            series="Моя чертова ошибка любви",
            series_num="2",
            lib_id=811194,
            file_size=2731545,
            date_added="2025-01-01",
            language="ru",
            annotation="история любви,романтика любви,сентиментальные романы",
        ),
        _make_line(
            authors="Иванов,Иван,:",
            genres="detective:",
            title="Тайна старого дома",
            lib_id=811195,
            file_size=1500000,
            date_added="2024-05-10",
            language="ru",
        ),
        _make_line(
            authors="",
            genres="",
            title="Анонимная брошюра",
            lib_id=811196,
            file_size=100000,
            date_added="2023",
            language="ru",
        ),
    ]

    # Файл 2: книга с флагом deleted + без серии + с несколькими авторами
    f2_lines = [
        _make_line(
            authors="Петров,Пётр,:Сидоров,Семён,:",
            genres="fantasy:",
            title="Двойное авторство",
            series="",
            series_num="",
            lib_id=900001,
            file_size=2000000,
            deleted=1,
            date_added="2025-06-15",
            language="en",
            annotation="",
        ),
        _make_line(
            authors="Козлов,К.:",
            genres="prose_contemporary:",
            title="Короткая проза",
            series="Сборник",
            series_num="0",
            lib_id=900002,
            file_size=300000,
            date_added="2024-12-31",
            language="ru",
        ),
    ]

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("collection.info", collection_info)
        zf.writestr("version.info", version_info)
        zf.writestr("f.fb2-811194-815075.inp", "".join(f1_lines))
        zf.writestr("fb2-900001-900999.inp", "".join(f2_lines))

    print(f"✅ Создан {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()