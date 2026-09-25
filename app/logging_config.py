"""Настройка логирования.

Убирает шум от healthcheck'ов и других частых запросов.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class HealthCheckFilter(logging.Filter):
    """Скрывает access-логи для /health."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "/health" not in message


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)

    # Приглушаем болтливые логи
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    # Убираем /health из access-логов uvicorn
    logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())
