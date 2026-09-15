"""Хендлер карточки книги.

Обрабатывает callback `book:{lib_id}` — показывает карточку с кнопками.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.bot.formatters import format_book_card
from app.bot.keyboards import book_card_keyboard
from app.db.base import async_session_maker
from app.db.models import Book

logger = logging.getLogger(__name__)

router = Router(name="book")


@router.callback_query(F.data.startswith("book:"))
async def cb_book_card(callback: CallbackQuery) -> None:
    """Показать карточку книги."""
    if callback.data is None:
        return

    # Парсим lib_id
    try:
        lib_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Некорректный ID книги", show_alert=True)
        return

    await callback.answer()  # убираем «часики»

    # Загружаем книгу с авторами
    async with async_session_maker() as session:
        book = await session.scalar(
            select(Book)
            .options(selectinload(Book.authors_rel))
            .where(Book.lib_id == lib_id)
            .limit(1)
        )

    if book is None:
        await callback.message.answer("❌ Книга не найдена")
        return

    # Определяем первого автора
    author_id: int | None = None
    if book.authors_rel:
        author_id = book.authors_rel[0].id

    # Формируем карточку
    text = format_book_card(book)
    keyboard = book_card_keyboard(book, author_id=author_id)

    # Отправляем новое сообщение (старое со списком остаётся)
    await callback.message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )