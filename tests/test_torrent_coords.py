"""Тесты вычисления координат piece-ов и byte_offset."""

from __future__ import annotations


PIECE_LENGTH = 16 * 1024 * 1024  # 16 MiB


def compute_piece_range(
    byte_offset: int,
    local_header_offset: int,
    compressed_size: int,
    piece_length: int = PIECE_LENGTH,
    header_safety: int = 1300,
) -> tuple[int, int]:
    """Дублирует логику из torrent_fetcher для тестирования."""
    abs_start = byte_offset + local_header_offset
    abs_end = abs_start + header_safety + compressed_size
    first_piece = abs_start // piece_length
    last_piece = (abs_end - 1) // piece_length
    return first_piece, last_piece


class TestPieceRange:
    def test_first_piece(self) -> None:
        # Файл в начале первого piece-а
        first, last = compute_piece_range(0, 0, 1000)
        assert first == 0
        assert last == 0

    def test_across_boundary(self) -> None:
        # Файл пересекает границу piece-ов
        first, last = compute_piece_range(
            0, PIECE_LENGTH - 100, 5000
        )
        assert first == 0
        assert last == 1

    def test_large_byte_offset(self) -> None:
        # byte_offset ~230 GB
        first, last = compute_piece_range(
            byte_offset=230_061_334_378,
            local_header_offset=500_003_406,
            compressed_size=1_516_283,
        )
        # abs_start = 230561337784; 230561337784 // 16777216 = 13742
        assert first == 13742
        assert last == 13742  # один piece

    def test_zero_size(self) -> None:
        # Размер 0 — граничный случай
        first, last = compute_piece_range(0, 0, 0)
        assert first == 0
        assert last == 0