"""Хендлер «Все книги автора» + пагинация."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.bot.formatters import format_search_header
from app.bot.keyboards import books_list_with_pagination_keyboard
from app.bot.states import ListContext
from app.db.base import async_session_maker
from app.db.models import Author
from app.services.search import search_by_author_id

logger = logging.getLogger(__name__)

router = Router(name="author")

PAGE_SIZE = 20


@router.callback_query(F.data.startswith("author:"))
async def cb_author_books(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Все книги автора — страница 1."""
    if callback.data is None:
        return

    try:
        author_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Некорректный ID автора", show_alert=True)
        return

    await callback.answer()

    # Загружаем автора
    async with async_session_maker() as session:
        author = await session.get(Author, author_id)
        if author is None:
            await callback.message.answer("❌ Автор не найден")
            return

        # Ищем книги
        result = await search_by_author_id(
            session,
            author_id,
            page=1,
            page_size=PAGE_SIZE,
        )

    # Сохраняем контекст
    ctx = ListContext(
        kind="author",
        key=author_id,
        title=author.display_name,
        total=result.total,
        page=1,
        page_size=PAGE_SIZE,
    )
    await state.update_data(list_context=ctx.__dict__)

    # Формируем сообщение
    header = (
        f"📚 <b>Все книги автора</b>\n"
        f"👤 <b>{author.display_name}</b>\n"
        f"Найдено: <b>{result.total}</b> · страница <b>1</b> из <b>{result.total_pages}</b>"
    )

    if not result.items:
        await callback.message.answer(
            f"📚 <b>{author.display_name}</b>\n\nУ автора пока нет книг.",
            parse_mode="HTML",
        )
        return

    keyboard = books_list_with_pagination_keyboard(
        result.items,
        kind="author",
        page=1,
        total_pages=result.total_pages,
    )

    await callback.message.answer(
        header,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("page:author:"))
async def cb_author_page(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Переключение страницы автора."""
    if callback.data is None:
        return

    try:
        page = int(callback.data.split(":", 2)[2])
    except (ValueError, IndexError):
        await callback.answer("❌ Некорректная страница", show_alert=True)
        return

    # Читаем контекст
    data = await state.get_data()
    ctx_dict = data.get("list_context")
    if not ctx_dict or ctx_dict.get("kind") != "author":
        await callback.answer(
            "⚠️ Контекст устарел. Запусти поиск заново.",
            show_alert=True,
        )
        return

    author_id = int(ctx_dict["key"])
    author_title = ctx_dict["title"]

    await callback.answer()

    # Ищем нужную страницу
    async with async_session_maker() as session:
        result = await search_by_author_id(
            session,
            author_id,
            page=page,
            page_size=PAGE_SIZE,
        )

    # Обновляем контекст
    ctx = ListContext(
        kind="author",
        key=author_id,
        title=author_title,
        total=result.total,
        page=page,
        page_size=PAGE_SIZE,
    )
    await state.update_data(list_context=ctx.__dict__)

    header = (
        f"📚 <b>Все книги автора</b>\n"
        f"👤 <b>{author_title}</b>\n"
        f"Найдено: <b>{result.total}</b> · страница <b>{page}</b> из <b>{result.total_pages}</b>"
    )

    keyboard = books_list_with_pagination_keyboard(
        result.items,
        kind="author",
        page=page,
        total_pages=result.total_pages,
    )

    await callback.message.answer(
        header,
        reply_markup=keyboard,
        parse_mode="HTML",
    )