"""Хендлер текстового поиска.

Пользователь пишет любой текст → бот ищет книги → показывает до 20 с кнопками.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from app.bot.formatters import format_search_header
from app.bot.keyboards import books_list_keyboard
from app.db.base import async_session_maker
from app.services.search import SearchField, search_books

logger = logging.getLogger(__name__)

router = Router(name="search")

MAX_RESULTS = 20


@router.message(F.text & ~F.text.startswith("/"))
async def handle_search(message: Message) -> None:
    """Ищет книги по тексту сообщения."""
    query = (message.text or "").strip()
    if not query:
        return

    # Слишком длинный запрос — обрезаем
    if len(query) > 200:
        await message.answer("⚠️ Слишком длинный запрос. Максимум 200 символов.")
        return

    logger.info("Search query: %r", query)

    # Отправляем «typing» (пользователь видит, что бот работает)
    await message.bot.send_chat_action(
        chat_id=message.chat.id, action="typing"
    )

    # Ищем
    try:
        async with async_session_maker() as session:
            result = await search_books(
                session,
                q=query,
                field=SearchField.ALL,
                page=1,
                page_size=MAX_RESULTS,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Search failed")
        await message.answer(f"❌ Ошибка поиска: {exc}")
        return

    if not result.items:
        await message.answer(
            f"🔍 По запросу «<b>{query}</b>» ничего не найдено.\n\n"
            f"Попробуй изменить запрос.",
            parse_mode="HTML",
        )
        return

    # Формируем заголовок и клавиатуру
    header = format_search_header(query, result.total, len(result.items))
    keyboard = books_list_keyboard(result.items)

    await message.answer(
        header,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
