"""Низкоуровневая обёртка над libtorrent-сессией.

Одна глобальная сессия на всё приложение. Внутри — словарь торрентов,
загруженных по torrent_id. Каждый торрент добавлен с resume_data из БД,
чтобы не перепроверять piece-ы.

Сессия использует save_path = TEMP_DOWNLOAD_PATH, а не TORRENT_DATA_PATH,
потому что мы качаем только нужные piece-ы в отдельную папку.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import libtorrent as lt

from app.config import settings

logger = logging.getLogger(__name__)

# Сколько ждать метаданные при добавлении торрента (если ещё не загружены)
METADATA_TIMEOUT = 120

# Интервал опроса статуса (сек)
POLL_INTERVAL = 0.5

# Приоритет piece-а: 0 — не качать, 7 — максимальный
PRIORITY_SKIP = 0
PRIORITY_HIGH = 7


@dataclass
class TorrentState:
    """Состояние одного торрента в сессии."""

    torrent_id: int
    handle: lt.torrent_handle
    info_hash: str


class TorrentSession:
    """Глобальная libtorrent-сессия."""

    def __init__(self, save_path: Path) -> None:
        self.save_path = Path(save_path)
        self.save_path.mkdir(parents=True, exist_ok=True)

        self._session: lt.session | None = None
        self._torrents: dict[int, TorrentState] = {}
        self._lock = asyncio.Lock()  # защита от одновременного add_torrent

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Создать сессию libtorrent."""
        if self._session is not None:
            logger.warning("TorrentSession already started")
            return

        logger.info("Starting libtorrent session (save_path=%s)", self.save_path)
        settings_dict = {
            "listen_interfaces": "0.0.0.0:6881,[::]:6881",
            "enable_dht": True,
            "enable_lsd": True,
            "enable_upnp": False,
            "enable_natpmp": False,
            # === НОВОЕ: ускоряем поиск пиров и piece-ов ===
            "connections_limit": 200,
            "active_downloads": 5,
            "active_seeds": 5,
            "peer_connect_timeout": 10,
            "request_timeout": 10,
            "piece_timeout": 10,
            "file_pool_size": 40,
            "alert_mask": (
                lt.alert.category_t.status_notification
                | lt.alert.category_t.error_notification
                | lt.alert.category_t.storage_notification
            ),
        }
        self._session = lt.session(settings_dict)
        logger.info("libtorrent version: %s", lt.__version__)

    def stop(self) -> None:
        """Корректно закрыть сессию."""
        if self._session is None:
            return
        logger.info("Stopping libtorrent session…")
        try:
            self._session.pause()
        except Exception:  # noqa: BLE001
            pass
        self._torrents.clear()
        self._session = None
        logger.info("libtorrent session stopped")

    @property
    def session(self) -> lt.session:
        if self._session is None:
            raise RuntimeError("TorrentSession not started")
        return self._session

    # -------------------------------------------------------------- torrents

    async def add_torrent(
        self,
        torrent_id: int,
        magnet: str,
        *,
        resume_data: bytes | None = None,
        metadata_timeout: int = METADATA_TIMEOUT,
    ) -> TorrentState:
        """Добавить торрент в сессию (с resume_data, если есть).

        Идемпотентно: если торрент уже добавлен — возвращает существующий handle.
        """
        async with self._lock:
            if torrent_id in self._torrents:
                return self._torrents[torrent_id]

            logger.info("Adding torrent id=%d to session", torrent_id)
            t0 = time.monotonic()

            params: lt.add_torrent_params
            if resume_data:
                try:
                    params = lt.read_resume_data(resume_data)
                    logger.info(
                        "Loaded resume_data (%d bytes) for torrent id=%d",
                        len(resume_data),
                        torrent_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to read resume_data for torrent id=%d: %r; "
                        "falling back to magnet",
                        torrent_id,
                        exc,
                    )
                    params = lt.parse_magnet_uri(magnet)
            else:
                params = lt.parse_magnet_uri(magnet)

            public_trackers = [
                "udp://tracker.opentrackr.org:1337/announce",
                "udp://open.stealth.si:80/announce",
                "udp://tracker.torrent.eu.org:451/announce",
                "udp://exodus.desync.com:6969/announce",
                "udp://tracker.moeking.me:6969/announce",
            ]
            params.trackers = list(params.trackers) + public_trackers
            params.tracker_tiers = list(params.tracker_tiers) + [1] * len(public_trackers)                

            params.save_path = str(self.save_path)
            params.storage_mode = lt.storage_mode_t.storage_mode_sparse

            handle = self.session.add_torrent(params)
            info_hash = str(handle.info_hash())

            # Ждём метаданные (если их нет в resume_data)
            while not handle.status().has_metadata:
                if time.monotonic() - t0 > metadata_timeout:
                    raise TimeoutError(
                        f"Torrent id={torrent_id}: metadata not received "
                        f"within {metadata_timeout}s"
                    )
                await asyncio.sleep(POLL_INTERVAL)

            # Сразу отключаем все piece-ы — чтобы ничего не качалось «само»
            ti = handle.torrent_file()
            for i in range(ti.num_pieces()):
                handle.piece_priority(i, PRIORITY_SKIP)

            state = TorrentState(
                torrent_id=torrent_id,
                handle=handle,
                info_hash=info_hash,
            )
            self._torrents[torrent_id] = state
            logger.info(
                "Torrent id=%d added (info_hash=%s) in %.1fs",
                torrent_id,
                info_hash[:12],
                time.monotonic() - t0,
            )
            return state

    def get(self, torrent_id: int) -> TorrentState | None:
        return self._torrents.get(torrent_id)

    # -------------------------------------------------------------- download

    async def download_range(
        self,
        torrent_id: int,
        *,
        abs_start: int,
        abs_end: int,
        piece_length: int,
        timeout: int = 300,
        on_progress: callable | None = None,
    ) -> None:
        """Скачать piece-ы, покрывающие диапазон [abs_start, abs_end).

        Args:
            torrent_id: ID торрента в БД.
            abs_start: абсолютное начало диапазона в торренте (байты).
            abs_end: абсолютный конец (не включительно).
            piece_length: размер piece-а в байтах.
            timeout: сколько секунд ждать.
            on_progress: callback(downloaded_bytes: int, total_bytes: int).

        Raises:
            TimeoutError, RuntimeError.
        """
        state = self._torrents.get(torrent_id)
        if state is None:
            raise RuntimeError(f"Torrent id={torrent_id} not in session")

        handle = state.handle
        ti = handle.torrent_file()

        first_piece = abs_start // piece_length
        last_piece = (abs_end - 1) // piece_length
        needed = list(range(first_piece, last_piece + 1))

        if not needed:
            return

        logger.info(
            "Downloading torrent id=%d pieces %d..%d (%d pieces, %d bytes)",
            torrent_id,
            first_piece,
            last_piece,
            len(needed),
            abs_end - abs_start,
        )

        # Устанавливаем высокий приоритет нужным piece-ам
        # Используем prioritize_pieces для атомарности
        pieces_with_priority = [(p, PRIORITY_HIGH) for p in needed]
        handle.prioritize_pieces(pieces_with_priority)

        # === ВАЖНО: делаем piece-ы time-critical ===
        # Это перемещает их в начало очереди запросов ко всем пирам.
        # Deadline — через 5 секунд (мягкий), но эффект — приоритет.
        for p in needed:
            handle.set_piece_deadline(p, 5000)  # 5 секунд

        # Ждём завершения
        t0 = time.monotonic()
        total_bytes = abs_end - abs_start
        last_report = 0.0
        last_piece_report = 0.0
        start_downloaded = handle.status().total_done

        try:
            while True:
                status = handle.status()

                # Проверяем, все ли нужные piece-ы скачаны
                have_all = all(handle.have_piece(p) for p in needed)
                if have_all:
                    logger.info(
                        "All %d pieces downloaded in %.1fs",
                        len(needed),
                        time.monotonic() - t0,
                    )
                    # Принудительно сбрасываем буферы libtorrent на диск,
                    # иначе данные будут в памяти, а не в файле
                    try:
                        handle.flush_cache()
                        logger.debug("Cache flushed to disk")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("flush_cache failed: %r", exc)
                    # Даём ОС время на синхронизацию буферов
                    await asyncio.sleep(0.5)
                    return

                now = time.monotonic()

                # Отчёт о piece-ах — раз в 0.5 сек
                if on_progress is not None and now - last_piece_report > 0.5:
                    downloaded = sum(1 for p in needed if handle.have_piece(p))
                    on_progress(downloaded, len(needed))
                    last_piece_report = now

                # Диагностика — раз в 5 секунд
                if now - last_report > 5.0:
                    elapsed = now - t0
                    bytes_since_start = status.total_done - start_downloaded
                    rate_kib = status.download_rate / 1024 if status.download_rate else 0
                    have_count = sum(1 for p in needed if handle.have_piece(p))
                    
                    # Дополнительно: сколько пиров имеют этот piece
                    # (не у всех API это доступно, но попробуем)
                    peers_having = 0
                    try:
                        # availability доступно через status или piece_info
                        # в некоторых версиях libtorrent
                        pass
                    except Exception:
                        pass
                    
                    logger.info(
                        "  [%.0fs] pieces: %d/%d · peers: %d/%d · rate: %.0f KiB/s · downloaded: %d B",
                        elapsed,
                        have_count,
                        len(needed),
                        status.num_peers,
                        status.num_seeds,
                        rate_kib,
                        bytes_since_start,
                    )
                    last_report = now

                # Timeout
                if now - t0 > timeout:
                    have_count = sum(1 for p in needed if handle.have_piece(p))
                    raise TimeoutError(
                        f"Torrent id={torrent_id}: pieces {first_piece}..{last_piece} "
                        f"not downloaded within {timeout}s "
                        f"(have {have_count}/{len(needed)}, "
                        f"peers={status.num_peers}, rate={status.download_rate / 1024:.0f} KiB/s)"
                    )

                await asyncio.sleep(POLL_INTERVAL)
        finally:
            # Сбрасываем deadline и приоритеты
            for p in needed:
                try:
                    handle.reset_piece_deadline(p)
                except Exception:
                    pass
                handle.piece_priority(p, PRIORITY_SKIP)

    async def read_piece(
        self,
        torrent_id: int,
        piece_index: int,
        timeout: int = 10,
    ) -> bytes:
        """Прочитать данные piece-а в память через libtorrent.

        Не зависит от того, в каком файле piece лежит на диске.
        Возвращает bytes размером piece_length (для последнего piece — меньше).
        """
        state = self._torrents.get(torrent_id)
        if state is None:
            raise RuntimeError(f"Torrent id={torrent_id} not in session")

        handle = state.handle

        if not handle.have_piece(piece_index):
            raise RuntimeError(
                f"Piece {piece_index} not available (have_piece=False)"
            )

        # Запрашиваем piece в память
        handle.read_piece(piece_index)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            alerts = self.session.pop_alerts()
            for alert in alerts:
                if isinstance(alert, lt.read_piece_alert):
                    if alert.piece == piece_index:
                        # ВАЖНО: alert.error — это error_code, не bool
                        # Проверяем числовой код: 0 = успех
                        if alert.error.value() != 0:
                            raise RuntimeError(
                                f"read_piece error: {alert.error.message()}"
                            )
                        if alert.buffer is None:
                            raise RuntimeError(
                                f"read_piece returned None buffer for piece {piece_index}"
                            )
                        return bytes(alert.buffer)
            await asyncio.sleep(0.05)

        raise TimeoutError(f"read_piece({piece_index}) timed out after {timeout}s")

    # -------------------------------------------------------------- info

    def get_file_path(self, torrent_id: int, file_index: int) -> Path | None:
        """Возвращает путь, куда libtorrent сохраняет файл с данным file_index.

        libtorrent сохраняет данные в save_path/<torrent_name>/<relative_path>.
        На практике для нашего торрента файлы лежат в save_path/<filename>,
        потому что torrent_name = "fb2.Flibusta.Net" и save_path = "tmp_downloads"
        (создаётся подпапка с torrent_name).

        Нам нужно узнать реальный путь на диске. Проще всего — спросить у
        torrent_info.files().file_path(file_index) — но путь относительный.
        Финальный путь = save_path / <путь внутри торрента>.
        """
        state = self._torrents.get(torrent_id)
        if state is None:
            return None
        ti = state.handle.torrent_file()
        fs = ti.files()
        rel_path = fs.file_path(file_index).replace("\\", "/")
        return self.save_path / rel_path