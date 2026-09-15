"""Хендлер скачивания книги.

Обрабатывает callback `download:{lib_id}`:
  1. Отправляет сообщение «⏳ Скачиваю…»
  2. Обновляет прогресс через ProgressTracker раз в 2 сек
  3. По завершении — удаляет статусное сообщение и отправляет .fb2
"""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.formatters import esc, normalize_authors, format_size
from app.db.base import async_session_maker
from app.services.filenames import make_book_filename
from app.services.library import (
    BookContentError,
    BookNotFoundError,
    fetch_book_content,
)
from app.services.progress import DownloadStatus, get_progress_tracker

logger = logging.getLogger(__name__)

router = Router(name="download")

# Максимальный размер файла для Telegram Bot API
MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024  # 50 МБ


@router.callback_query(F.data.startswith("download:"))
async def cb_download(callback: CallbackQuery) -> None:
    """Скачать книгу и отправить её пользователю."""
    if callback.data is None:
        return

    # Парсим lib_id
    try:
        lib_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Некорректный ID книги", show_alert=True)
        return

    # Отвечаем на callback, чтобы убрать «часики»
    await callback.answer("Начинаю скачивание…")

    # Отправляем статусное сообщение
    status_msg: Message = await callback.message.answer("⏳ Скачиваю книгу…")

    # Запускаем фоновое обновление прогресса
    progress_task = asyncio.create_task(
        _progress_updater(status_msg, lib_id)
    )

    try:
        # Скачиваем
        async with async_session_maker() as session:
            content = await fetch_book_content(session, lib_id)

        # Останавливаем прогресс
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        # Проверяем размер
        if len(content.data) > MAX_TELEGRAM_FILE_SIZE:
            await status_msg.edit_text(
                f"❌ Файл слишком большой ({format_size(len(content.data))}). "
                f"Максимум {format_size(MAX_TELEGRAM_FILE_SIZE)}."
            )
            return

        # Удаляем статусное сообщение
        try:
            await status_msg.delete()
        except Exception:  # noqa: BLE001
            pass

        # Формируем имя файла (транслит)
        filename = make_book_filename(content.title, content.authors)

        # Подпись
        authors = normalize_authors(content.authors)
        caption_parts = [f"📖 <b>{esc(content.title)}</b>"]
        if authors:
            caption_parts.append(f"👤 {esc(authors)}")
        caption_parts.append(
            f"<i>{format_size(len(content.data))} · источник: {content.source}</i>"
        )
        caption = "\n".join(caption_parts)

        # Отправляем документ
        await callback.message.answer_document(
            document=BufferedInputFile(content.data, filename=filename),
            caption=caption,
            parse_mode="HTML",
        )

        logger.info(
            "Sent book lib_id=%d to user_id=%s (%d bytes, %.2fs)",
            lib_id,
            callback.from_user.id if callback.from_user else None,
            len(content.data),
            content.elapsed_seconds,
        )

    except BookNotFoundError:
        progress_task.cancel()
        await _safe_edit(status_msg, "❌ Книга не найдена в каталоге.")
    except BookContentError as exc:
        progress_task.cancel()
        logger.exception("Book content error")
        await _safe_edit(status_msg, f"❌ Не удалось прочитать файл: {esc(str(exc))}")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        progress_task.cancel()
        logger.exception("Download failed")
        await _safe_edit(status_msg, f"❌ Ошибка: {esc(str(exc))}")


async def _progress_updater(msg: Message, lib_id: int) -> None:
    """Обновляет статусное сообщение раз в 2 сек."""
    tracker = get_progress_tracker()
    start = time.monotonic()

    while True:
        await asyncio.sleep(2.0)
        elapsed = time.monotonic() - start

        try:
            state = tracker.get(lib_id)
            if state is not None and state.status == DownloadStatus.DOWNLOADING:
                if state.pieces_total > 0:
                    pct = state.progress_percent
                    eta = state.eta_seconds
                    eta_str = f", ~{eta:.0f} сек" if eta and eta > 1 else ""
                    text = f"⏳ Скачиваю через торрент: {pct:.0f}%{eta_str}"
                else:
                    text = f"⏳ Скачиваю через торрент… {elapsed:.0f} сек"
            elif state is not None and state.status == DownloadStatus.DONE:
                # Уже готово, но прогресс-таск ещё не завершён — просто выходим
                return
            else:
                # Локальный режим или ещё не началось
                if elapsed < 3:
                    text = "⏳ Скачиваю книгу…"
                else:
                    text = f"⏳ Скачиваю… {elapsed:.0f} сек"
        except Exception:
            text = f"⏳ Скачиваю… {elapsed:.0f} сек"

        try:
            await msg.edit_text(text)
        except Exception:
            # Сообщение удалено или не изменилось — игнорируем
            pass


async def _safe_edit(msg: Message, text: str) -> None:
    """Пытается отредактировать сообщение, игнорирует ошибки."""
    try:
        await msg.edit_text(text, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        pass