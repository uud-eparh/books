"""Регистрация всех хендлеров бота."""

from aiogram import Dispatcher

from app.bot.handlers import (
    author,
    book,
    download,
    feedback,   # ← ДОБАВИТЬ
    search,
    series,
    start,
)


def register_handlers(dp: Dispatcher) -> None:
    """Подключает все роутеры к диспетчеру."""
    dp.include_router(start.router)
    dp.include_router(feedback.router)
    dp.include_router(search.router)
    dp.include_router(book.router)
    dp.include_router(download.router)
    dp.include_router(author.router)
    dp.include_router(series.router)