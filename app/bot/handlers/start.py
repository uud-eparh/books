"""Команды /start и /help."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

logger = logging.getLogger(__name__)

router = Router(name="start")


START_TEXT = """📚 <b>Book Hub</b> — библиотека FB2

Я помогу найти и скачать книгу из локальной библиотеки.

<b>Как пользоваться:</b>
1. Просто напиши <b>название книги</b>, <b>автора</b> или <b>серию</b>
2. Я покажу до 10 результатов
3. Выбери книгу и нажми «Скачать»

<b>Команды:</b>
/start — это сообщение
/help — помощь
/about — о проекте
/message — написать администратору
"""

HELP_TEXT = """ℹ️ <b>Помощь</b>

<b>Поиск</b>
Просто напиши мне запрос в чат. Например:
• <code>Романович</code> — найду все книги автора
• <code>Алхимик</code> — найду по названию
• <code>Шиноби [Пастырь]</code> — найду все книги серии

<b>Скачивание</b>
Кликни на книгу в результатах поиска. Я покажу карточку и кнопки:
• <b>⬇ Скачать FB2</b> — отправить файл
• <b>👤 Автор</b> — все книги автора
• <b>📚 Серия</b> — все книги серии

<b>Как это работает</b>
Книга скачивается <b>точечно</b> из торрент-библиотеки (только нужный кусочек). Обычно 3–30 секунд.

<b>Обратная связь</b>
Если нашли ошибку или хотите предложить книгу:
<code>/message Ваше сообщение</code>
"""

ABOUT_TEXT = """📚 <b>Book Hub</b>

Локальная библиотека FB2 на 700 000+ книг.
Точечное скачивание через BitTorrent.

<b>Технологии:</b>
• PostgreSQL + FTS
• FastAPI + aiogram
• libtorrent
• Флибуста .inpx-каталог

<b>Версия:</b> 0.7.0
"""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(START_TEXT, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="HTML")


@router.message(Command("about"))
async def cmd_about(message: Message) -> None:
    await message.answer(ABOUT_TEXT, parse_mode="HTML")