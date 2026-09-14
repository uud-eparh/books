"""Обёртка над libtorrent.

Позволяет:
  - получить метаданные торрента (magnet) без скачивания данных
  - извлечь список файлов с piece-диапазонами
  - сохранить resume_data для быстрого возобновления

libtorrent — синхронная C++ библиотека. Все вызовы блокирующие,
поэтому публичные функции оборачиваем в asyncio.to_thread() при использовании
из async-контекста.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import libtorrent as lt

logger = logging.getLogger(__name__)

# Сколько ждать метаданные (в секундах)
METADATA_TIMEOUT = 300
# Сколько ждать resume_data после запроса
RESUME_TIMEOUT = 30
# Интервал опроса статуса
POLL_INTERVAL = 1.0


@dataclass(frozen=True, slots=True)
class TorrentFileInfo:
    """Один файл внутри торрента."""

    file_index: int
    path: str          # путь внутри торрента, без корневой папки
    size: int          # размер в байтах
    piece_start: int   # первый piece, содержащий данные файла
    piece_end: int     # последний piece


@dataclass(frozen=True, slots=True)
class TorrentMetadata:
    """Результат получения метаданных торрента."""

    info_hash: str
    name: str
    total_size: int
    piece_length: int
    num_pieces: int
    files: list[TorrentFileInfo]
    resume_data: bytes | None
    save_path: str


def _pick_listen_port() -> tuple[int, int]:
    """Возвращает (start, end) для диапазона портов."""
    return 6881, 6891


def _make_session(save_path: Path, session_state_path: Path) -> lt.session:
    """Создаёт сессию libtorrent с разумными настройками."""
    settings: dict[str, Any] = {
        "listen_interfaces": "0.0.0.0:6881,[::]:6881",
        "enable_dht": True,
        "enable_lsd": True,
        "enable_upnp": False,      # на Windows часто ломается
        "enable_natpmp": False,
        "alert_mask": (
            lt.alert.category_t.status_notification
            | lt.alert.category_t.error_notification
            | lt.alert.category_t.storage_notification
        ),
    }
    session = lt.session(settings)
    logger.debug("libtorrent version: %s", lt.__version__)
    return session


def fetch_torrent_metadata(
    magnet: str,
    save_path: Path,
    *,
    resume_data: bytes | None = None,
    timeout: int = METADATA_TIMEOUT,
    download_pieces: bool = False,
    on_progress: Any = None,
) -> TorrentMetadata:
    """Получить метаданные торрента (не скачивая содержимое).

    Args:
        magnet: magnet-ссылка.
        save_path: папка, где libtorrent будет искать существующие файлы
                   (используется, чтобы быстро проверить уже скачанное).
        resume_data: сохранённый ранее resume blob (опционально).
        timeout: сколько секунд ждать метаданные.
        download_pieces: если False — все piece-приоритеты = 0 (ничего не качаем).
                         Метаданные всё равно подтянутся от пиров.
        on_progress: callback(status_dict), вызывается раз в секунду.

    Returns:
        TorrentMetadata со списком файлов и resume_data.
    """
    if save_path is None:
        raise ValueError("save_path must be provided")
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)

    session = _make_session(save_path, save_path / ".libtorrent")
    handle = None
    try:
        params = lt.parse_magnet_uri(magnet)
        params.save_path = str(save_path)
        params.storage_mode = lt.storage_mode_t.storage_mode_sparse

        if resume_data:
            try:
                params = lt.read_resume_data(resume_data)
                params.save_path = str(save_path)
                logger.info("Resume data loaded from DB (%d bytes)", len(resume_data))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load resume data: %r; ignoring", exc)
                params = lt.parse_magnet_uri(magnet)
                params.save_path = str(save_path)

        handle = session.add_torrent(params)
        logger.info("Torrent added to session: %s", handle.info_hash())

        # Ждём метаданные
        deadline = time.monotonic() + timeout
        while not handle.status().has_metadata:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Metadata not received within {timeout}s"
                )
            status = handle.status()
            if on_progress:
                try:
                    on_progress(
                        {
                            "peers": status.num_peers,
                            "seeds": status.num_seeds,
                            "state": str(status.state),
                            "has_metadata": status.has_metadata,
                            "downloaded": status.total_done,
                        }
                    )
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(POLL_INTERVAL)

        ti = handle.torrent_file()
        if ti is None:
            raise RuntimeError("Metadata received but torrent_file() is None")

        # Собираем список файлов
        files = _extract_files_from_info(ti, handle)

        # Если не качаем piece-ы — отключаем их все, чтобы не тянуть данные
        if not download_pieces:
            for i in range(ti.num_pieces()):
                handle.piece_priority(i, 0)

        # Получаем resume_data
        resume_blob = _get_resume_data(handle, session)

        info_hash = str(handle.info_hash())
        metadata = TorrentMetadata(
            info_hash=info_hash,
            name=ti.name(),
            total_size=ti.total_size(),
            piece_length=ti.piece_length(),
            num_pieces=ti.num_pieces(),
            files=files,
            resume_data=resume_blob,
            save_path=str(save_path),
        )

        logger.info(
            "Metadata OK: name=%r files=%d total_size=%d",
            metadata.name,
            len(metadata.files),
            metadata.total_size,
        )
        return metadata

    finally:
        if handle is not None:
            try:
                session.remove_torrent(handle)
            except Exception:  # noqa: BLE001
                pass
        # Не вызываем session.pause() — просто выходим, деструктор всё сделает


def _extract_files_from_info(
    ti: lt.torrent_info, handle: lt.torrent_handle
) -> list[TorrentFileInfo]:
    """Извлекает список файлов с piece-диапазонами.

    Пути нормализуются: убирается корневая папка торрента,
    обратные слеши заменяются на прямые.
    """
    fs = ti.files()
    num_files = fs.num_files()
    result: list[TorrentFileInfo] = []

    # Имя корневой папки торрента — первая компонента пути.
    # Например, для "fb2.Flibusta.Net/fb2-000024-030559.zip" это "fb2.Flibusta.Net".
    root_name = ti.name()

    for i in range(num_files):
        raw_path = fs.file_path(i)
        # Нормализуем слеши
        raw_path = raw_path.replace("\\", "/")
        # Убираем корневую папку, если она есть
        if raw_path.startswith(root_name + "/"):
            path = raw_path[len(root_name) + 1:]
        else:
            path = raw_path

        size = fs.file_size(i)

        if size <= 0:
            piece_start = piece_end = 0
        else:
            piece_start = ti.map_file(i, 0, 1).piece
            piece_end = ti.map_file(i, size - 1, 1).piece

        result.append(
            TorrentFileInfo(
                file_index=i,
                path=path,
                size=size,
                piece_start=piece_start,
                piece_end=piece_end,
            )
        )

    return result


def _get_resume_data(handle: lt.torrent_handle, session: lt.session) -> bytes | None:
    """Запрашивает resume_data у libtorrent и ждёт ответа."""
    try:
        handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
    except Exception as exc:  # noqa: BLE001
        logger.warning("save_resume_data failed: %r", exc)
        return None

    deadline = time.monotonic() + RESUME_TIMEOUT
    while time.monotonic() < deadline:
        alerts = session.pop_alerts()
        for alert in alerts:
            if isinstance(alert, lt.save_resume_data_alert):
                # save_resume_data_alert содержит params
                try:
                    return lt.write_resume_data_buf(alert.params)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("write_resume_data_buf failed: %r", exc)
                    # Fallback: bencode
                    try:
                        import bencodepy  # обычно нет, но на всякий
                        return bencodepy.encode(alert.params)
                    except ImportError:
                        return None
        time.sleep(0.2)

    logger.warning("Timeout waiting for resume_data")
    return None