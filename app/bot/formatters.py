"""Форматирование текста для сообщений бота.

В отличие от веб-шаблонов, здесь мы имеем дело с ограничениями Telegram:
  - длина сообщения 4096 символов
  - длина текста кнопки 64 символа
  - HTML/MarkdownV2 для форматирования
"""

from __future__ import annotations

import html
from typing import Sequence

from app.db.models import Book

# Максимальная длина текста кнопки
MAX_BUTTON_TEXT = 64

# Максимальная длина имени автора в строке
MAX_AUTHORS_LEN = 60


def esc(text: str | None) -> str:
    """Экранирует HTML-символы."""
    if not text:
        return ""
    return html.escape(str(text), quote=False)


def normalize_author(raw: str) -> str:
    """'Фамилия,Имя,Отчество' → 'Фамилия Имя Отчество'."""
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return " ".join(parts)


def normalize_authors(raw_list: Sequence[str] | None) -> str:
    """Список авторов → строка 'Автор1; Автор2'."""
    if not raw_list:
        return ""
    return "; ".join(normalize_author(a) for a in raw_list if a)


def truncate(text: str, max_len: int) -> str:
    """Обрезает текст до max_len, добавляя '…'."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def format_size(num_bytes: int | None) -> str:
    """Человекочитаемый размер."""
    if not num_bytes:
        return "—"
    n = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


def format_book_button(book: Book) -> str:
    """Текст для кнопки книги: '📖 {title} — {authors}'.

    Обрезается до MAX_BUTTON_TEXT символов.
    """
    title = truncate(book.title, 40)
    authors = truncate(normalize_authors(book.authors), 30)
    text = f"📖 {title}"
    if authors:
        text += f" — {authors}"
    return truncate(text, MAX_BUTTON_TEXT)


def format_book_card(book: Book) -> str:
    """Текст карточки книги (HTML)."""
    lines = [f"<b>{esc(book.title)}</b>"]

    authors = normalize_authors(book.authors)
    if authors:
        lines.append(f"👤 {esc(authors)}")

    if book.series:
        series_line = f"📚 {esc(book.series)}"
        if book.series_num:
            series_line += f" #{book.series_num}"
        lines.append(series_line)

    # Метаданные
    meta_parts = []
    if book.language:
        meta_parts.append(book.language)
    if book.file_size:
        meta_parts.append(format_size(book.file_size))
    if book.date_added:
        meta_parts.append(str(book.date_added))
    if meta_parts:
        lines.append(f"<i>{' · '.join(meta_parts)}</i>")

    # Аннотация
    if book.annotation:
        ann = truncate(book.annotation, 600)
        lines.append("")
        lines.append(f"<blockquote>{esc(ann)}</blockquote>")

    return "\n".join(lines)


def format_search_header(query: str, total: int, shown: int) -> str:
    """Заголовок для результатов поиска."""
    if total == 0:
        return f"🔍 По запросу «<b>{esc(query)}</b>» ничего не найдено."
    if total <= shown:
        return f"🔍 Найдено <b>{total}</b> по запросу «<b>{esc(query)}</b>»:"
    return (
        f"🔍 Найдено <b>{total}</b> по запросу «<b>{esc(query)}</b>».\n"
        f"Показано <b>{shown}</b> из <b>{total}</b>:"
    )

def format_book_button_default(book: Book) -> str:
    """Для общего поиска: '📖 {title} — {authors}'."""
    return format_book_button(book)  # уже есть


def format_book_button_by_author(book: Book) -> str:
    """Для списка автора: '📖 {title} — {series} #N' (без автора)."""
    title = truncate(book.title, 45)
    text = f"📖 {title}"
    if book.series:
        series_part = truncate(book.series, 20)
        if book.series_num:
            series_part += f" #{book.series_num}"
        text += f" — {series_part}"
    return truncate(text, MAX_BUTTON_TEXT)


def format_book_button_by_series(book: Book) -> str:
    """Для списка серии: '📖 {title} — {series} #{num}' (без автора)."""
    title = truncate(book.title, 40)
    text = f"📖 {title}"

    if book.series:
        series_part = truncate(book.series, 25)
        if book.series_num:
            series_part += f" #{book.series_num}"
        text += f" — {series_part}"

    return truncate(text, MAX_BUTTON_TEXT)