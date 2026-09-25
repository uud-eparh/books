"""Хендлер «Все книги серии» + пагинация."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.keyboards import books_list_with_pagination_keyboard
from app.bot.states import ListContext
from app.db.base import async_session_maker
from app.services.search import SearchField, search_books

logger = logging.getLogger(__name__)

router = Router(name="series")

PAGE_SIZE = 20


@router.callback_query(F.data.startswith("series:"))
async def cb_series_books(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if callback.data is None:
        return

    series_name = callback.data.split(":", 1)[1].strip()
    if not series_name:
        await callback.answer("❌ Некорректное имя серии", show_alert=True)
        return

    await callback.answer()

    async with async_session_maker() as session:
        result = await search_books(
            session,
            q=series_name,
            field=SearchField.SERIES,
            page=1,
            page_size=PAGE_SIZE,
        )

    if result.total == 0:
        await callback.message.answer(
            f"📚 Серия «<b>{series_name}</b>» — ничего не найдено.",
            parse_mode="HTML",
        )
        return

    # Сохраняем контекст
    ctx = ListContext(
        kind="series",
        key=series_name,
        title=series_name,
        total=result.total,
        page=1,
        page_size=PAGE_SIZE,
    )
    await state.update_data(list_context=ctx.__dict__)

    # Определяем автора серии (если у всех книг — один автор)
    series_author = _detect_series_author(result.items)

    header_lines = [
        f"📚 <b>Серия</b>: <b>{series_name}</b>",
    ]
    if series_author:
        header_lines.append(f"👤 {series_author}")
    header_lines.append(
        f"Найдено: <b>{result.total}</b> · страница <b>1</b> из <b>{result.total_pages}</b>"
    )

    keyboard = books_list_with_pagination_keyboard(
        result.items,
        kind="series",
        page=1,
        total_pages=result.total_pages,
    )

    await callback.message.answer(
        "\n".join(header_lines),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


def _detect_series_author(books: list) -> str | None:
    """Возвращает автора, если он одинаков у всех книг страницы."""
    if not books:
        return None
    first = books[0].authors or []
    if not first:
        return None
    # Проверяем, что у всех книг тот же список авторов
    for b in books[1:]:
        if (b.authors or []) != first:
            return None
    from app.bot.formatters import normalize_authors
    return normalize_authors(first)


@router.callback_query(F.data.startswith("page:series:"))
async def cb_series_page(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Переключение страницы серии."""
    if callback.data is None:
        return

    try:
        page = int(callback.data.split(":", 2)[2])
    except (ValueError, IndexError):
        await callback.answer("❌ Некорректная страница", show_alert=True)
        return

    data = await state.get_data()
    ctx_dict = data.get("list_context")
    if not ctx_dict or ctx_dict.get("kind") != "series":
        await callback.answer(
            "⚠️ Контекст устарел. Запусти поиск заново.",
            show_alert=True,
        )
        return

    series_name = str(ctx_dict["key"])

    await callback.answer()

    async with async_session_maker() as session:
        result = await search_books(
            session,
            q=series_name,
            field=SearchField.SERIES,
            page=page,
            page_size=PAGE_SIZE,
        )

    ctx = ListContext(
        kind="series",
        key=series_name,
        title=series_name,
        total=result.total,
        page=page,
        page_size=PAGE_SIZE,
    )
    await state.update_data(list_context=ctx.__dict__)

    header = (
        f"📚 <b>Серия</b>: <b>{series_name}</b>\n"
        f"Найдено: <b>{result.total}</b> · страница <b>{page}</b> из <b>{result.total_pages}</b>"
    )

    keyboard = books_list_with_pagination_keyboard(
        result.items,
        kind="series",
        page=page,
        total_pages=result.total_pages,
    )

    await callback.message.answer(
        header,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
