"""Трекер прогресса скачиваний.

Хранит состояние по каждому lib_id:
  - позиция в очереди
  - статус (pending / downloading / done / error)
  - прогресс (piece-ы / процент)
  - результат (bytes) или ошибка

WebSocket/SSE читает состояние через subscribe().
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class DownloadStatus(str, Enum):
    PENDING = "pending"           # в очереди
    DOWNLOADING = "downloading"   # активно качается
    DONE = "done"                 # готово
    ERROR = "error"               # ошибка


@dataclass
class ProgressState:
    """Состояние одного скачивания."""

    lib_id: int
    status: DownloadStatus = DownloadStatus.PENDING
    queued_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    # Прогресс piece-ов
    pieces_done: int = 0
    pieces_total: int = 0

    # Позиция в очереди (0 = обрабатывается прямо сейчас)
    queue_position: int = 0
    queue_total: int = 0

    # Оценка времени
    eta_seconds: float | None = None

    # Результат
    error: str | None = None
    data: bytes | None = None       # для передачи в /download/file
    source: str | None = None

    @property
    def progress_percent(self) -> float:
        if self.pieces_total <= 0:
            return 0.0
        return min(100.0, self.pieces_done / self.pieces_total * 100)

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.time()
        return end - self.started_at

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для SSE/JSON."""
        return {
            "lib_id": self.lib_id,
            "status": self.status.value,
            "pieces_done": self.pieces_done,
            "pieces_total": self.pieces_total,
            "progress_percent": round(self.progress_percent, 1),
            "queue_position": self.queue_position,
            "queue_total": self.queue_total,
            "eta_seconds": round(self.eta_seconds, 1) if self.eta_seconds else None,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "error": self.error,
            "source": self.source,
        }


class ProgressTracker:
    """Глобальный трекер прогресса (singleton)."""

    def __init__(self) -> None:
        self._states: dict[int, ProgressState] = {}
        self._lock = asyncio.Lock()
        # Подписчики по lib_id: list[asyncio.Queue]
        self._subscribers: dict[int, list[asyncio.Queue]] = {}

    # ------------------------------------------------------------ state

    def get(self, lib_id: int) -> ProgressState | None:
        return self._states.get(lib_id)

    def get_or_create(self, lib_id: int) -> ProgressState:
        state = self._states.get(lib_id)
        if state is None:
            state = ProgressState(lib_id=lib_id)
            self._states[lib_id] = state
            logger.info("Progress: created state for lib_id=%d", lib_id)
        return state

    def remove(self, lib_id: int) -> None:
        self._states.pop(lib_id, None)

    def _update_queue_positions(self) -> None:
        """Обновляет позиции в очереди для всех PENDING."""
        pending = [
            s for s in self._states.values()
            if s.status == DownloadStatus.PENDING
        ]
        pending.sort(key=lambda s: s.queued_at)
        for i, s in enumerate(pending):
            s.queue_position = i
            s.queue_total = len(pending)

    # ------------------------------------------------------------ notify

    async def _notify(self, lib_id: int) -> None:
        """Разослать текущее состояние всем подписчикам."""
        state = self._states.get(lib_id)
        if state is None:
            return
        data = state.to_dict()
        for q in self._subscribers.get(lib_id, []):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                # Пропускаем — подписчик не успевает
                pass

    async def notify_and_update(self, lib_id: int) -> None:
        """Обновить позиции в очереди и разослать всем."""
        self._update_queue_positions()
        await self._notify(lib_id)

    # ------------------------------------------------------------ subscription

    async def subscribe(self, lib_id: int) -> asyncio.Queue:
        """Подписаться на обновления lib_id. Возвращает queue."""
        async with self._lock:
            q: asyncio.Queue = asyncio.Queue(maxsize=32)
            self._subscribers.setdefault(lib_id, []).append(q)
            # Сразу шлём текущее состояние
            state = self._states.get(lib_id)
            if state:
                await q.put(state.to_dict())
            return q

    async def unsubscribe(self, lib_id: int, q: asyncio.Queue) -> None:
        async with self._lock:
            subs = self._subscribers.get(lib_id, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subscribers.pop(lib_id, None)


# Singleton
_tracker: ProgressTracker | None = None


def get_progress_tracker() -> ProgressTracker:
    global _tracker
    if _tracker is None:
        _tracker = ProgressTracker()
    return _tracker