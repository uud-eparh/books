from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.logging_config import setup_logging
from app.services.torrent_manager import (
    setup_torrent_manager,
    shutdown_torrent_manager,
)
from app.web.routes import router as web_router

import asyncio

from app.services.temp_cleaner import background_cleaner


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.app_debug)
    await setup_torrent_manager()

    # Запуск фоновой очистки кэша
    cleaner_task = asyncio.create_task(background_cleaner(interval_seconds=3600))

    try:
        yield
    finally:
        cleaner_task.cancel()
        try:
            await cleaner_task
        except asyncio.CancelledError:
            pass
        await shutdown_torrent_manager()


app = FastAPI(
    title="Flibusta Bot",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory="app/web/static"),
    name="static",
)

app.include_router(web_router)