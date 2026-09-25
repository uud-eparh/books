"""Хендлер обратной связи.

Команда /message <текст> → пересылает сообщение админу.
"""

from __future__ import annotations

import html
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings

logger = logging.getLogger(__name__)

router = Router(name="feedback")

# Максимальная длина сообщения
MAX_MESSAGE_LEN = 2000


@router.message(Command("message"))
async def cmd_message(message: Message) -> None:
    """Отправить сообщение админу.

    Использование:
        /message Текст сообщения
    """
    # Проверка, что админ задан
    admin_id = settings.admin_id
    if not admin_id:
        await message.answer(
            "⚠️ Обратная связь временно недоступна. "
            "Администратор не настроил приём сообщений."
        )
        logger.warning("TELEGRAM_ADMIN_ID не задан — /message недоступен")
        return

    # Парсим текст после команды
    text = _extract_text(message)
    if not text:
        await message.answer(
            "📝 <b>Как отправить сообщение</b>\n\n"
            "Напиши:\n"
            "<code>/message Твой текст</code>\n\n"
            "Например:\n"
            "<code>/message Добавьте, пожалуйста, книгу «Мастер и Маргарита»</code>",
            parse_mode="HTML",
        )
        return

    if len(text) > MAX_MESSAGE_LEN:
        await message.answer(
            f"⚠️ Сообщение слишком длинное "
            f"({len(text)} символов). Максимум — {MAX_MESSAGE_LEN}."
        )
        return

    # Формируем сообщение админу
    user = message.from_user
    if user is None:
        return

    username = f"@{user.username}" if user.username else "(без username)"
    full_name = " ".join(filter(None, [user.first_name, user.last_name])) or "(без имени)"

    admin_text = (
        "📩 <b>Новое сообщение от пользователя</b>\n\n"
        f"<b>От:</b> {html.escape(full_name)}\n"
        f"<b>Username:</b> {html.escape(username)}\n"
        f"<b>ID:</b> <code>{user.id}</code>\n"
        f"<b>Язык:</b> {user.language_code or '—'}\n\n"
        f"<b>Сообщение:</b>\n"
        f"<blockquote>{html.escape(text)}</blockquote>"
    )

    # Отправляем админу
    try:
        await message.bot.send_message(
            chat_id=admin_id,
            text=admin_text,
            parse_mode="HTML",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось отправить сообщение админу %d", admin_id)
        await message.answer(
            "❌ Не удалось отправить сообщение. Попробуйте позже."
        )
        return

    # Подтверждение пользователю
    await message.answer(
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "Администратор получит его в ближайшее время."
    )

    logger.info(
        "Feedback from user_id=%d (%s) sent to admin %d: %r",
        user.id,
        username,
        admin_id,
        text[:80],
    )


def _extract_text(message: Message) -> str:
    """Извлекает текст после /message."""
    if message.text is None:
        return ""
    # Отрезаем команду
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()
