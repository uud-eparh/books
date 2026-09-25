"""Хендлер скачивания книги."""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.formatters import esc, format_size, normalize_authors
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

MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024


# ============================================================
# Трекер активных задач: {(user_id, lib_id): start_time}
# ============================================================
_active_downloads: dict[tuple[int, int], float] = {}
_active_lock = asyncio.Lock()

# Сколько секунд считать задачу «активной» (максимум)
ACTIVE_TIMEOUT = 300  # 5 минут

# ============================================================
# Трекер недавних скачиваний (защита от повторов)
# ============================================================
_recent_downloads: dict[tuple[int, int], float] = {}
RECENT_TIMEOUT = 30  # 30 секунд


async def _is_download_active(user_id: int, lib_id: int) -> bool:
    """Проверить, идёт ли уже скачивание этой книги этим пользователем."""
    async with _active_lock:
        key = (user_id, lib_id)
        started = _active_downloads.get(key)
        if started is None:
            return False
        # Если задача «зависла» > ACTIVE_TIMEOUT — считаем её мёртвой
        if time.monotonic() - started > ACTIVE_TIMEOUT:
            _active_downloads.pop(key, None)
            return False
        return True


async def _mark_download_started(user_id: int, lib_id: int) -> None:
    async with _active_lock:
        _active_downloads[(user_id, lib_id)] = time.monotonic()


async def _mark_download_finished(user_id: int, lib_id: int) -> None:
    async with _active_lock:
        _active_downloads.pop((user_id, lib_id), None)


@router.callback_query(F.data.startswith("download:"))
async def cb_download(callback: CallbackQuery) -> None:
    """Скачать книгу и отправить её пользователю."""
    if callback.data is None:
        return
    if callback.from_user is None or callback.message is None:
        return

    try:
        lib_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Некорректный ID книги", show_alert=True)
        return

    user_id = callback.from_user.id

    # === ПРОВЕРКА 1: активная задача ===
    if await _is_download_active(user_id, lib_id):
        await callback.answer(
            "⏳ Книга уже скачивается. Подождите…",
            show_alert=False,
        )
        logger.info("Duplicate download request: user_id=%d lib_id=%d", user_id, lib_id)
        return

    # === ПРОВЕРКА 2: недавно скачивал ===
    if await _is_recently_downloaded(user_id, lib_id):
        await callback.answer(
            "✅ Книга уже отправлена выше ↑",
            show_alert=False,
        )
        logger.info("Recently downloaded: user_id=%d lib_id=%d", user_id, lib_id)
        return

    await _mark_download_started(user_id, lib_id)

    await callback.answer("Начинаю скачивание…")
    status_msg: Message = await callback.message.answer("⏳ Скачиваю книгу…")

    progress_task = asyncio.create_task(
        _progress_updater(status_msg, lib_id)
    )

    try:
        async with async_session_maker() as session:
            content = await fetch_book_content(session, lib_id)

        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        if len(content.data) > MAX_TELEGRAM_FILE_SIZE:
            await status_msg.edit_text(
                f"❌ Файл слишком большой ({format_size(len(content.data))}). "
                f"Максимум {format_size(MAX_TELEGRAM_FILE_SIZE)}."
            )
            return

        try:
            await status_msg.delete()
        except Exception:  # noqa: BLE001
            pass

        filename = make_book_filename(content.title, content.authors)

        authors = normalize_authors(content.authors)
        caption_parts = [f"📖 <b>{esc(content.title)}</b>"]
        if authors:
            caption_parts.append(f"👤 {esc(authors)}")
        caption_parts.append(
            f"<i>{format_size(len(content.data))} · источник: {content.source}</i>"
        )
        caption = "\n".join(caption_parts)

        await callback.message.answer_document(
            document=BufferedInputFile(content.data, filename=filename),
            caption=caption,
            parse_mode="HTML",
        )

        logger.info(
            "Sent book lib_id=%d to user_id=%s (%d bytes, %.2fs)",
            lib_id,
            user_id,
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
    finally:
        # === СНИМАЕМ БЛОКИРОВКУ ВСЕГДА ===
        await _mark_download_finished(user_id, lib_id)
        await _mark_recently_downloaded(user_id, lib_id)


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
                return
            else:
                if elapsed < 3:
                    text = "⏳ Скачиваю книгу…"
                else:
                    text = f"⏳ Скачиваю… {elapsed:.0f} сек"
        except Exception:
            text = f"⏳ Скачиваю… {elapsed:.0f} сек"

        try:
            await msg.edit_text(text)
        except Exception:
            pass


async def _safe_edit(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        pass


async def _is_recently_downloaded(user_id: int, lib_id: int) -> bool:
    """Проверить, скачивал ли пользователь эту книгу недавно."""
    async with _active_lock:
        key = (user_id, lib_id)
        last = _recent_downloads.get(key)
        if last is None:
            return False
        if time.monotonic() - last > RECENT_TIMEOUT:
            _recent_downloads.pop(key, None)
            return False
        return True


async def _mark_recently_downloaded(user_id: int, lib_id: int) -> None:
    async with _active_lock:
        _recent_downloads[(user_id, lib_id)] = time.monotonic()
