"""Пакетное скачивание книг в ZIP.

Логика:
  1. Создать BatchJob (POST /api/batch).
  2. Запустить воркер в фоне (asyncio.create_task).
  3. Воркер последовательно качает книги через fetch_book_content.
  4. По завершении — упаковка в ZIP (tmp_downloads/batch_{job_id}.zip).
  5. Статус → ready, файл доступен для скачивания.

Ограничения:
  - MAX_BOOKS_PER_BATCH = 20
  - MAX_ZIP_SIZE = 50 МБ (если превышает — оставшиеся книги не качаются,
    пользователю сообщается, что скачано меньше)
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import async_session_maker
from app.db.models import BatchJob
from app.services.filenames import (
    make_batch_filename,
    make_book_filename,
    make_unique_filename,
)
from app.services.library import BookContentError, BookNotFoundError, fetch_book_content

logger = logging.getLogger(__name__)

# Ограничения
MAX_BOOKS_PER_BATCH = 20
MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50 МБ


class BatchError(Exception):
    """Ошибка при работе с batch."""


# ================================================================ public

async def create_job(
    session: AsyncSession,
    lib_ids: list[int],
) -> BatchJob:
    """Создать BatchJob и запустить воркер в фоне.

    Валидация:
      - lib_ids не пустой
      - <= MAX_BOOKS_PER_BATCH

    Returns:
        Созданный BatchJob (уже с запущенным воркером).

    Raises:
        BatchError: если валидация не прошла.
    """
    # Валидация
    if not lib_ids:
        raise BatchError("Список книг пуст")

    # Убираем дубликаты, сохраняя порядок
    seen: set[int] = set()
    unique_ids: list[int] = []
    for lid in lib_ids:
        if lid not in seen:
            seen.add(lid)
            unique_ids.append(lid)

    if len(unique_ids) > MAX_BOOKS_PER_BATCH:
        raise BatchError(
            f"Максимум {MAX_BOOKS_PER_BATCH} книг в одном пакете, "
            f"получено {len(unique_ids)}"
        )

    job_id = str(uuid.uuid4())
    job = BatchJob(
        id=job_id,
        lib_ids=unique_ids,
        status="pending",
        total_books=len(unique_ids),
        done_books=0,
        error_count=0,
        completed_lib_ids=[],
        failed_lib_ids=[],
        cancelled=False,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    logger.info(
        "Batch: created job_id=%s with %d books", job_id, len(unique_ids)
    )

    # Запускаем воркер в фоне
    asyncio.create_task(_run_job(job_id))

    return job


async def get_job(session: AsyncSession, job_id: str) -> BatchJob | None:
    """Получить BatchJob по ID."""
    return await session.get(BatchJob, job_id)


async def cancel_job(session: AsyncSession, job_id: str) -> BatchJob:
    """Отменить batch (устанавливает флаг cancelled)."""
    job = await session.get(BatchJob, job_id)
    if job is None:
        raise BatchError(f"Batch {job_id} не найден")
    if job.status in ("ready", "error", "cancelled"):
        return job  # уже завершён

    job.cancelled = True
    await session.commit()
    await session.refresh(job)
    logger.info("Batch: cancelled job_id=%s", job_id)
    return job


# ================================================================ worker

async def _update_job(job_id: str, **fields) -> None:
    """Обновить поля job в отдельной сессии."""
    async with async_session_maker() as session:
        job = await session.get(BatchJob, job_id)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        await session.commit()


async def _run_job(job_id: str) -> None:
    """Фоновый воркер: скачивает книги, упаковывает в ZIP."""
    try:
        await _process_job(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Batch: job %s failed", job_id)
        await _update_job(
            job_id,
            status="error",
            error=str(exc),
            finished_at=datetime.now(timezone.utc),
        )


async def _process_job(job_id: str) -> None:
    """Основная логика обработки batch."""
    # Загружаем job
    async with async_session_maker() as session:
        job = await session.get(BatchJob, job_id)
        if job is None:
            logger.error("Batch: job %s not found", job_id)
            return
        lib_ids = list(job.lib_ids)
        total = job.total_books

    # Статус → downloading
    await _update_job(job_id, status="downloading")

    files: dict[str, bytes] = {}
    completed: list[int] = []
    failed: list[int] = []
    total_size = 0

    for i, lib_id in enumerate(lib_ids):
        # Проверка отмены
        async with async_session_maker() as session:
            job = await session.get(BatchJob, job_id)
            if job is not None and job.cancelled:
                logger.info("Batch: job %s cancelled by user", job_id)
                await _update_job(
                    job_id,
                    status="cancelled",
                    finished_at=datetime.now(timezone.utc),
                )
                return

        # Обновляем current_lib_id
        await _update_job(job_id, current_lib_id=lib_id)

        # Скачиваем книгу
        try:
            async with async_session_maker() as session:
                content = await fetch_book_content(session, lib_id)

            # Формируем имя файла
            base_filename = make_book_filename(
                content.title, content.authors, ext="fb2"
            )
            filename = make_unique_filename(base_filename, set(files.keys()))

            # Проверяем размер до добавления
            new_total = total_size + len(content.data)
            if new_total > MAX_ZIP_SIZE:
                logger.warning(
                    "Batch %s: size limit reached (%d > %d), stopping at %d books",
                    job_id,
                    new_total,
                    MAX_ZIP_SIZE,
                    len(completed),
                )
                # Оставшиеся книги (включая текущую) — не качаем
                remaining = lib_ids[i:]
                for r in remaining:
                    if r not in failed and r not in completed:
                        failed.append(r)
                break

            # Добавляем
            files[filename] = content.data
            total_size = new_total
            completed.append(lib_id)

            logger.info(
                "Batch %s: fetched lib_id=%d (%d bytes), %d/%d done",
                job_id,
                lib_id,
                len(content.data),
                len(completed),
                total,
            )

        except (BookNotFoundError, BookContentError) as exc:
            logger.warning("Batch %s: lib_id=%d failed: %r", job_id, lib_id, exc)
            failed.append(lib_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Batch %s: lib_id=%d unexpected error", job_id, lib_id)
            failed.append(lib_id)

        # Обновляем прогресс
        await _update_job(
            job_id,
            done_books=len(completed),
            error_count=len(failed),
            completed_lib_ids=completed,
            failed_lib_ids=failed,
        )

    # Если ничего не скачалось — ошибка
    if not files:
        await _update_job(
            job_id,
            status="error",
            error="Не удалось скачать ни одной книги",
            done_books=0,
            error_count=len(failed),
            failed_lib_ids=failed,
            finished_at=datetime.now(timezone.utc),
        )
        return

    # Статус → packing
    await _update_job(job_id, status="packing", current_lib_id=None)

    # Упаковываем в ZIP
    zip_filename = make_batch_filename(job_id)
    zip_path = settings.temp_download_path / zip_filename

    logger.info(
        "Batch %s: packing %d files into %s", job_id, len(files), zip_path
    )

    # Упаковка в отдельном потоке (может быть тяжёлой)
    await asyncio.to_thread(_pack_zip, zip_path, files)

    zip_size = zip_path.stat().st_size
    logger.info(
        "Batch %s: ready, zip_size=%d bytes (%s)", job_id, zip_size, zip_path
    )

    # Статус → ready
    await _update_job(
        job_id,
        status="ready",
        file_path=str(zip_path),
        file_size=zip_size,
        finished_at=datetime.now(timezone.utc),
    )


def _pack_zip(zip_path: Path, files: dict[str, bytes]) -> None:
    """Синхронная упаковка в ZIP (запускается в отдельном потоке)."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)