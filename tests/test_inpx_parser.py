"""Юнит-тесты парсера .inpx."""

from __future__ import annotations

from datetime import date

import pytest

from app.parsers.inpx import Book, InpxParser, LibraryMeta
from tests.fixtures.make_sample import OUT as SAMPLE_PATH

pytestmark = pytest.mark.skipif(
    not SAMPLE_PATH.exists(),
    reason="Run tests/fixtures/make_sample.py first",
)


def test_read_meta() -> None:
    parser = InpxParser(SAMPLE_PATH)
    meta = parser.read_meta()
    assert isinstance(meta, LibraryMeta)
    assert meta.name == "Flibusta FB2 Local"
    assert meta.version == "20260701"
    assert meta.chunk_size == 65536
    assert "Флибуста" in meta.description


def test_iter_books_count() -> None:
    parser = InpxParser(SAMPLE_PATH)
    books = list(parser.iter_books())
    assert len(books) == 5
    assert parser.stats["files"] == 2
    assert parser.stats["parsed"] == 5
    assert parser.stats["skipped"] == 0


def test_book_fields() -> None:
    parser = InpxParser(SAMPLE_PATH)
    books = list(parser.iter_books())
    by_id = {b.lib_id: b for b in books}

    b = by_id[811194]
    assert isinstance(b, Book)
    assert b.title == "Чертова невеста правильного парень"
    assert b.authors == ["Джейн,О. О."]
    assert "love" in b.genres
    assert b.series == "Моя чертова ошибка любви"
    assert b.series_num == 2
    assert b.file_size == 2731545
    assert b.language == "ru"
    assert b.date_added == date(2025, 1, 1)
    assert b.archive_name == "f.fb2-811194-815075.zip"
    assert b.is_deleted is False
    assert b.annotation is not None
    assert "история любви" in b.annotation


def test_deleted_flag_and_empty_series() -> None:
    parser = InpxParser(SAMPLE_PATH)
    books = {b.lib_id: b for b in parser.iter_books()}

    b = books[900001]
    assert b.is_deleted is True
    assert b.series is None
    assert b.series_num is None
    assert b.authors == ["Петров,Пётр", "Сидоров,Семён"]
    assert b.language == "en"


def test_zero_series_num_becomes_none() -> None:
    parser = InpxParser(SAMPLE_PATH)
    books = {b.lib_id: b for b in parser.iter_books()}

    b = books[900002]
    assert b.series == "Сборник"
    assert b.series_num is None  # 0 -> None


def test_empty_author() -> None:
    parser = InpxParser(SAMPLE_PATH)
    books = {b.lib_id: b for b in parser.iter_books()}

    b = books[811196]
    assert b.authors == []
    assert b.genres == []


def test_iter_is_lazy() -> None:
    """Генератор не выполняет всю работу сразу."""
    parser = InpxParser(SAMPLE_PATH)
    gen = parser.iter_books()
    first = next(gen)
    assert first.lib_id == 811194
    # Не докапываемся до конца, просто закрываем
    gen.close()
