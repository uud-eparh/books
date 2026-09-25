import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.bot.main import create_bot_and_dispatcher, start_polling_async
from app.config import settings
from app.logging_config import setup_logging
from app.services.temp_cleaner import background_cleaner
from app.services.torrent_manager import (
    setup_torrent_manager,
    shutdown_torrent_manager,
)
from app.web.routes import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.app_debug)

    # Torrent manager
    await setup_torrent_manager()

    # Фоновый cleaner
    cleaner_task = asyncio.create_task(background_cleaner(interval_seconds=3600))

    # Telegram bot
    bot_task: asyncio.Task | None = None
    bot = None
    if settings.telegram_bot_token:
        try:
            bot, dp = create_bot_and_dispatcher()
            bot_task = asyncio.create_task(start_polling_async(bot, dp))
            print("🤖 Telegram bot started")
        except Exception as exc:
            print(f"⚠️  Telegram bot failed to start: {exc!r}")
    else:
        print("ℹ️  TELEGRAM_BOT_TOKEN не задан — бот не запущен")

    try:
        yield
    finally:
        # Останавливаем бота
        if bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except (asyncio.CancelledError, Exception):
                pass
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass

        cleaner_task.cancel()
        try:
            await cleaner_task
        except asyncio.CancelledError:
            pass

        await shutdown_torrent_manager()


app = FastAPI(title="Flibusta Bot", version="0.7.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.include_router(web_router)
