"""Хендлер статистики для админа.

Команда /stats → инлайн-кнопки для навигации по разделам.

Доступ только для пользователя с ID == TELEGRAM_ADMIN_ID.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import esc
from app.config import settings
from app.db.base import async_session_maker
from app.services.stats import (
    get_bot_stats,
    get_daily_activity,
    get_library_stats,
    get_today_stats,
    get_top_authors,
    get_top_books,
)

logger = logging.getLogger(__name__)

router = Router(name="stats")


# ============================================================
# Проверка доступа
# ============================================================

def _is_admin(user_id: int | None) -> bool:
    """Проверить, что пользователь — админ."""
    admin_id = settings.admin_id
    return admin_id is not None and user_id == admin_id


# ============================================================
# Форматирование
# ============================================================

def _format_size(bytes_: int) -> str:
    """Байты → человекочитаемый размер."""
    if bytes_ < 1024:
        return f"{bytes_} B"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        bytes_ /= 1024
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
    return f"{bytes_:.1f} PiB"


# ============================================================
# Клавиатуры
# ============================================================

def _main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню статистики."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Бот", callback_data="stats:bot"),
                InlineKeyboardButton(text="📚 Библиотека", callback_data="stats:library"),
            ],
            [
                InlineKeyboardButton(text="📅 Сегодня", callback_data="stats:today"),
                InlineKeyboardButton(text="🔥 Топ книг", callback_data="stats:top_books"),
            ],
            [
                InlineKeyboardButton(text="👤 Топ авторов", callback_data="stats:top_authors"),
                InlineKeyboardButton(text="📈 7 дней", callback_data="stats:activity"),
            ],
        ]
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка «Назад» к главному меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="stats:main")],
        ]
    )


# ============================================================
# Тексты для разделов
# ============================================================

async def _text_main() -> str:
    return (
        "📊 <b>Статистика</b>\n\n"
        "Выбери раздел:"
    )


async def _text_bot(session: AsyncSession) -> str:
    stats = await get_bot_stats(session)
    return (
        "📊 <b>Бот</b>\n\n"
        f"👥 Уникальных пользователей: <b>{stats.users_total}</b>\n"
        f"👤 Активных сегодня: <b>{stats.users_today}</b>\n\n"
        f"🔍 Поисков: <b>{stats.searches_total}</b>\n"
        f"📥 Скачиваний: <b>{stats.downloads_total}</b>\n"
        f"📩 Сообщений: <b>{stats.messages_total}</b>"
    )


async def _text_library(session: AsyncSession) -> str:
    stats = await get_library_stats(session)
    version = stats.torrent_version or "—"
    return (
        "📚 <b>Библиотека</b>\n\n"
        f"📖 Книг всего: <b>{stats.books_total:,}</b>\n"
        f"✅ Активных: <b>{stats.books_active:,}</b>\n"
        f"👤 Авторов: <b>{stats.authors_total:,}</b>\n"
        f"🗂 Архивов: <b>{stats.archives_total:,}</b>\n"
        f"🌐 Языков: <b>{stats.languages_total}</b>\n\n"
        f"💾 Размер торрента: <b>{_format_size(stats.torrent_size_bytes)}</b>\n"
        f"📅 Версия каталога: <b>{esc(version)}</b>"
    )


async def _text_today(session: AsyncSession) -> str:
    stats = await get_today_stats(session)
    return (
        "📅 <b>Сегодня</b>\n\n"
        f"👥 Уникальных: <b>{stats.unique_users}</b>\n"
        f"🔍 Поисков: <b>{stats.searches}</b>\n"
        f"👁 Просмотров: <b>{stats.book_views}</b>\n"
        f"📥 Скачиваний: <b>{stats.downloads}</b>\n"
        f"📩 Сообщений: <b>{stats.messages}</b>"
    )


async def _text_top_books(session: AsyncSession) -> str:
    books = await get_top_books(session, limit=10, days=30)
    if not books:
        return "🔥 <b>Топ книг</b>\n\nПока нет данных о скачиваниях."

    lines = ["🔥 <b>Топ книг (30 дней)</b>\n"]
    for i, b in enumerate(books, start=1):
        lines.append(
            f"{i}. <b>{esc(b.title)}</b>\n"
            f"   <i>{esc(b.author)}</i> — {b.downloads} 📥"
        )
    return "\n".join(lines)


async def _text_top_authors(session: AsyncSession) -> str:
    authors = await get_top_authors(session, limit=10, days=30)
    if not authors:
        return "👤 <b>Топ авторов</b>\n\nПока нет данных о скачиваниях."

    lines = ["👤 <b>Топ авторов (30 дней)</b>\n"]
    for i, a in enumerate(authors, start=1):
        lines.append(f"{i}. {esc(a.name)} — {a.downloads} 📥")
    return "\n".join(lines)


async def _text_activity(session: AsyncSession) -> str:
    activity = await get_daily_activity(session, days=7)
    if not activity:
        return "📈 <b>Активность</b>\n\nПока нет данных."

    lines = ["📈 <b>Активность (7 дней)</b>\n"]
    for a in activity:
        lines.append(
            f"<b>{a.day}</b>: 🔍 {a.searches} · 📥 {a.downloads} · 👥 {a.users}"
        )
    return "\n".join(lines)


# ============================================================
# Команда /stats
# ============================================================

@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Главная страница статистики (только для админа)."""
    if message.from_user is None or not _is_admin(message.from_user.id):
        logger.debug(
            "Non-admin user_id=%s tried /stats",
            message.from_user.id if message.from_user else None,
        )
        return

    await message.answer(
        await _text_main(),
        reply_markup=_main_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# Инлайн-кнопки
# ============================================================

@router.callback_query(F.data.startswith("stats:"))
async def cb_stats(callback: CallbackQuery) -> None:
    """Обработка нажатий на инлайн-кнопки статистики."""
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("🔒 Доступ запрещён", show_alert=True)
        return

    if callback.data is None or callback.message is None:
        return

    section = callback.data.split(":", 1)[1] if ":" in callback.data else "main"

    await callback.answer()

    async with async_session_maker() as session:
        if section == "main":
            text = await _text_main()
            keyboard = _main_keyboard()
        elif section == "bot":
            text = await _text_bot(session)
            keyboard = _back_keyboard()
        elif section == "library":
            text = await _text_library(session)
            keyboard = _back_keyboard()
        elif section == "today":
            text = await _text_today(session)
            keyboard = _back_keyboard()
        elif section == "top_books":
            text = await _text_top_books(session)
            keyboard = _back_keyboard()
        elif section == "top_authors":
            text = await _text_top_authors(session)
            keyboard = _back_keyboard()
        elif section == "activity":
            text = await _text_activity(session)
            keyboard = _back_keyboard()
        else:
            text = "❌ Неизвестный раздел"
            keyboard = _back_keyboard()

    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("edit_text failed: %r", exc)