"""Точка входа Telegram-бота.

Экспортирует `create_bot_and_dispatcher()` для запуска в lifespan FastAPI
и `start_polling_async()` для автономного запуска.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.handlers import register_handlers
from app.bot.middlewares import LoggingMiddleware, WhitelistMiddleware
from app.config import settings

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

logger = logging.getLogger(__name__)


def create_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    # SOCKS5 от Tor
    proxy_url = settings.telegram_proxy
    logger.info("Using proxy: %s", proxy_url)
    session = AiohttpSession(proxy=proxy_url)

    bot = Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Middleware — сначала whitelist, потом logging
    dp.message.middleware(WhitelistMiddleware())
    dp.callback_query.middleware(WhitelistMiddleware())
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())

    # Регистрация роутеров
    register_handlers(dp)

    return bot, dp


async def start_polling_async(bot: Bot, dp: Dispatcher) -> None:
    """Запустить polling (блокирующий до остановки)."""
    logger.info("Starting Telegram bot polling…")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted")
    except Exception as exc:
        logger.warning("delete_webhook failed: %r", exc)

    try:
        me = await bot.get_me()
        logger.info("Bot started: @%s (id=%s)", me.username, me.id)
    except Exception as exc:
        logger.exception("get_me failed")
        raise

    logger.info("Starting long polling…")
    await dp.start_polling(bot)