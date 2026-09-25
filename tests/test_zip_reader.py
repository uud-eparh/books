"""Тесты чтения файлов из ZIP по offset."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.services.zip_reader import (
    ZipReadError,
    read_zip_entry,
)


@pytest.fixture
def sample_zip(tmp_path: Path) -> Path:
    """Создаёт ZIP с двумя файлами."""
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("file1.fb2", b"<?xml version='1.0'?><FictionBook>content1</FictionBook>")
        zf.writestr("file2.fb2", b"<?xml version='1.0'?><FictionBook>content2</FictionBook>")
    return zip_path


def test_read_first_file(sample_zip: Path) -> None:
    # Первый файл — offset 0
    data = read_zip_entry(
        sample_zip,
        local_header_offset=0,
        expected_filename="file1.fb2",
    )
    assert b"content1" in data


def test_read_second_file(sample_zip: Path) -> None:
    with zipfile.ZipFile(sample_zip) as zf:
        info = zf.infolist()[1]
        offset = info.header_offset
        name = info.filename

    data = read_zip_entry(
        sample_zip,
        local_header_offset=offset,
        expected_filename=name,
    )
    assert b"content2" in data


def test_bad_offset(sample_zip: Path) -> None:
    with pytest.raises(ZipReadError):
        read_zip_entry(sample_zip, local_header_offset=999999, expected_filename="x")


def test_wrong_filename(sample_zip: Path) -> None:
    with pytest.raises(ZipReadError):
        read_zip_entry(
            sample_zip,
            local_header_offset=0,
            expected_filename="wrong.fb2",
        )
