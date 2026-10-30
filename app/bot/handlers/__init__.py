"""Регистрация всех хендлеров бота."""

from aiogram import Dispatcher

from app.bot.handlers.author import router as author_router
from app.bot.handlers.book import router as book_router
from app.bot.handlers.download import router as download_router
from app.bot.handlers.feedback import router as feedback_router
from app.bot.handlers.search import router as search_router
from app.bot.handlers.series import router as series_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.stats import router as stats_router


def register_handlers(dp: Dispatcher) -> None:
    """Подключает все роутеры к диспетчеру."""
    dp.include_router(start_router)
    dp.include_router(stats_router)
    dp.include_router(feedback_router)
    dp.include_router(search_router)
    dp.include_router(book_router)
    dp.include_router(download_router)
    dp.include_router(author_router)
    dp.include_router(series_router)
