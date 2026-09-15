"""Инлайн-клавиатуры для бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Book

from app.bot.formatters import (
    format_book_button,
    format_book_button_by_author,
    format_book_button_by_series,
)


def books_list_keyboard(
    books: list[Book],
    *,
    mode: str = "default",  # "default" | "author" | "series"
) -> InlineKeyboardMarkup:
    """Клавиатура списка книг.

    Args:
        books: список книг
        mode: контекст отображения:
            - "default" — общий поиск: '📖 Название — Автор'
            - "author"  — список автора: '📖 Название — Серия #N'
            - "series"  — список серии: '📖 Название — Автор'
    """
    kb = InlineKeyboardBuilder()

    formatters = {
        "default": format_book_button,
        "author": format_book_button_by_author,
        "series": format_book_button_by_series,
    }
    fmt = formatters.get(mode, format_book_button)

    for book in books:
        kb.button(
            text=fmt(book),
            callback_data=f"book:{book.lib_id}",
        )

    kb.adjust(1)
    return kb.as_markup()


def book_card_keyboard(book: Book, author_id: int | None = None) -> InlineKeyboardMarkup:
    """Клавиатура карточки книги.

    Кнопки:
      - ⬇ Скачать FB2 → download:{lib_id}
      - 👤 Все книги автора → author:{author_id} (если author_id указан)
      - 📚 Все книги серии → series:{series_name} (если есть серия)
    """
    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬇ Скачать FB2",
        callback_data=f"download:{book.lib_id}",
    )

    if author_id is not None:
        kb.button(
            text="👤 Все книги автора",
            callback_data=f"author:{author_id}",
        )

    if book.series:
        # callback_data ограничена 64 байтами — обрезаем имя серии
        series_trunc = book.series[:25]
        kb.button(
            text="📚 Все книги серии",
            callback_data=f"series:{series_trunc}",
        )

    kb.adjust(1)
    return kb.as_markup()

def books_list_with_pagination_keyboard(
    books: list[Book],
    *,
    kind: str,
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Клавиатура списка книг с пагинацией.

    Args:
        kind: "author" или "series" — также используется как mode для кнопок.
    """
    kb = InlineKeyboardBuilder()

    # Формат в зависимости от контекста
    formatters = {
        "author": format_book_button_by_author,
        "series": format_book_button_by_series,
    }
    fmt = formatters.get(kind, format_book_button)

    for book in books:
        kb.button(
            text=fmt(book),
            callback_data=f"book:{book.lib_id}",
        )

    if total_pages > 1:
        if page > 1:
            kb.button(text="⬅️ Назад", callback_data=f"page:{kind}:{page - 1}")
        if page < total_pages:
            kb.button(text="Вперёд ➡️", callback_data=f"page:{kind}:{page + 1}")

    kb.adjust(1)
    return kb.as_markup()