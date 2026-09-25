"""Тесты транслитерации и формирования имён файлов."""

from __future__ import annotations

from app.services.filenames import (
    make_batch_filename,
    make_book_filename,
    make_unique_filename,
    sanitize_filename,
    transliterate,
)


class TestTransliterate:
    def test_basic_russian(self) -> None:
        assert transliterate("Привет") == "Privet"
        assert transliterate("Мир") == "Mir"
        assert transliterate("Книга") == "Knigha" or transliterate("Книга") == "Kniga"

    def test_latin_unchanged(self) -> None:
        assert transliterate("Hello") == "Hello"
        assert transliterate("abc123") == "abc123"

    def test_mixed(self) -> None:
        assert transliterate("Книга 1") == "Kniga 1" or "Kniga" in transliterate("Книга 1")

    def test_empty(self) -> None:
        assert transliterate("") == ""

    def test_yo_and_soft_sign(self) -> None:
        # ё → e, ь → ''
        assert transliterate("ёж") == "ezh" or transliterate("ёж") == "yezh"
        assert transliterate("моль") == "mol"


class TestSanitizeFilename:
    def test_removes_illegal_chars(self) -> None:
        assert sanitize_filename('test<>:"/\\|?*file') == "testfile"

    def test_collapses_spaces(self) -> None:
        assert sanitize_filename("a   b") == "a b"

    def test_strips_trailing_dot(self) -> None:
        assert sanitize_filename("file.") == "file"

    def test_empty(self) -> None:
        assert sanitize_filename("") == ""


class TestMakeBookFilename:
    def test_simple(self) -> None:
        name = make_book_filename("Книга", ["Иванов,Иван"])
        assert name.endswith(".fb2")
        assert "Ivanov" in name
        assert "Kniga" in name

    def test_no_authors(self) -> None:
        name = make_book_filename("Книга", [])
        assert "Unknown" in name

    def test_custom_ext(self) -> None:
        name = make_book_filename("Книга", ["Иванов"], ext="epub")
        assert name.endswith(".epub")


class TestMakeUniqueFilename:
    def test_unique(self) -> None:
        existing: set[str] = {"file.fb2"}
        assert make_unique_filename("file.fb2", existing) == "file (1).fb2"

    def test_already_unique(self) -> None:
        assert make_unique_filename("file.fb2", set()) == "file.fb2"

    def test_multiple(self) -> None:
        existing = {"file.fb2", "file (1).fb2"}
        assert make_unique_filename("file.fb2", existing) == "file (2).fb2"


class TestMakeBatchFilename:
    def test_format(self) -> None:
        name = make_batch_filename("a3f7c9d1-1234-5678-9abc-0123456789ab")
        assert name.startswith("Flibusta_")
        assert name.endswith(".zip")
        assert "a3f7c9" in name
