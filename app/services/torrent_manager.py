"""Менеджер торрентов: сессия + очередь задач.

Гарантирует, что одновременно скачивается только одна книга.
Все запросы становятся в asyncio.Queue, обрабатываются последовательно.
"""

from __future__ import annotations

import asyncio
import logging
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.services.torrent_session import TorrentSession

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Результат скачивания одного диапазона."""

    file_path: Path
    abs_start: int
    abs_end: int


# Единственный экземпляр менеджера (singleton)
_manager: "TorrentManager | None" = None


def get_torrent_manager() -> "TorrentManager":
    """Получить singleton. Падает, если не инициализирован."""
    if _manager is None:
        raise RuntimeError(
            "TorrentManager not initialized. "
            "Did you forget to call setup_torrent_manager()?"
        )
    return _manager


class TorrentManager:
    """Управляет libtorrent-сессией и очередью задач."""

    def __init__(self) -> None:
        self.session = TorrentSession(save_path=settings.temp_download_path)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._running = False

    # -------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Запустить сессию и воркер очереди."""
        if self._running:
            return
        self._running = True

        # libtorrent — синхронный, поэтому start() в отдельном потоке
        await asyncio.to_thread(self.session.start)

        self._worker_task = asyncio.create_task(self._worker())
        logger.info("TorrentManager started (worker launched)")

    async def stop(self) -> None:
        """Остановить воркер и сессию."""
        if not self._running:
            return
        self._running = False

        # Отправляем «ядовитую пилюлю» в очередь, чтобы воркер вышел
        await self._queue.put(None)

        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._worker_task, timeout=10)
            except asyncio.TimeoutError:
                logger.warning("Worker did not stop in time, cancelling")
                self._worker_task.cancel()

        await asyncio.to_thread(self.session.stop)
        logger.info("TorrentManager stopped")

    # -------------------------------------------------------------- workers

    async def _worker(self) -> None:
        """Один воркер, обрабатывает задачи последовательно."""
        logger.info("Torrent worker started")
        while self._running:
            item = await self._queue.get()
            if item is None:
                # «Ядовитая пилюля» — выход
                self._queue.task_done()
                break

            future, coro_factory = item
            try:
                result = await coro_factory()
                if not future.done():
                    future.set_result(result)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Worker task failed: %r", exc)
                if not future.done():
                    future.set_exception(exc)
            finally:
                self._queue.task_done()

        logger.info("Torrent worker stopped")

    async def read_piece(
        self,
        torrent_id: int,
        piece_index: int,
        timeout: int = 10,
    ) -> bytes:
        """Прочитать piece в память через сессию.

        Проксирует вызов к TorrentSession.read_piece.
        Не встаёт в очередь — read_piece работает с уже скачанными данными.
        """
        return await self.session.read_piece(
            torrent_id, piece_index, timeout=timeout
        )

    # -------------------------------------------------------------- public API

    async def ensure_torrent(
        self,
        torrent_id: int,
        magnet: str,
        resume_data: bytes | None,
    ) -> None:
        """Убедиться, что торрент добавлен в сессию. Идемпотентно."""
        await self.session.add_torrent(
            torrent_id, magnet, resume_data=resume_data
        )

    async def download_range(
        self,
        torrent_id: int,
        *,
        abs_start: int,
        abs_end: int,
        piece_length: int,
        timeout: int = 300,
        on_progress: Callable[[int, int], None] | None = None,
        lib_id: int | None = None,
    ) -> None:
        """Поставить задачу скачивания в очередь и дождаться результата.

        Args:
            lib_id: если указан — прогресс будет писаться в ProgressTracker.
        """
        from app.services.progress import DownloadStatus, get_progress_tracker

        tracker = get_progress_tracker() if lib_id else None

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        if tracker and lib_id is not None:
            state = tracker.get_or_create(lib_id)
            state.status = DownloadStatus.PENDING
            await tracker.notify_and_update(lib_id)

        async def _task() -> None:
            if tracker and lib_id is not None:
                state = tracker.get_or_create(lib_id)
                state.status = DownloadStatus.DOWNLOADING
                state.started_at = time.time()
                tracker._update_queue_positions()

            def _wrapped_progress(done: int, total: int) -> None:
                if on_progress:
                    on_progress(done, total)
                if tracker and lib_id is not None:
                    state = tracker.get_or_create(lib_id)
                    state.pieces_done = done
                    state.pieces_total = total
                    elapsed = time.time() - (state.started_at or time.time())
                    if done > 0 and elapsed > 1.0:
                        rate = done / elapsed
                        remaining = total - done
                        state.eta_seconds = remaining / rate if rate > 0 else None
                    # Не спамим в очередь на каждый piece — только при изменении
                    # (asyncio.create_task безопасен здесь — _task внутри воркера)

            await self.session.download_range(
                torrent_id,
                abs_start=abs_start,
                abs_end=abs_end,
                piece_length=piece_length,
                timeout=timeout,
                on_progress=_wrapped_progress,
            )

        await self._queue.put((future, _task))
        await future  # ждём результата

    def get_file_path(self, torrent_id: int, file_index: int) -> Path | None:
        return self.session.get_file_path(torrent_id, file_index)


# -------------------------------------------------------------- setup

async def setup_torrent_manager() -> TorrentManager:
    """Создать, запустить и зарегистрировать менеджер."""
    global _manager
    if _manager is not None:
        return _manager
    mgr = TorrentManager()
    await mgr.start()
    _manager = mgr
    return mgr


async def shutdown_torrent_manager() -> None:
    """Остановить singleton."""
    global _manager
    if _manager is not None:
        await _manager.stop()
        _manager = None