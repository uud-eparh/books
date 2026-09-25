"""FastAPI-роуты веб-интерфейса."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,  # ← добавить
)
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import async_session_maker
from app.db.models import Book
from app.services.authors import get_author, search_authors
from app.services.batch import (
    BatchError,
    cancel_job,
    create_job,
    get_job,
)
from app.services.filenames import make_batch_filename
from app.services.library import (
    fetch_book_content,
    is_book_local_available,
)
from app.services.progress import (
    DownloadStatus,
    get_progress_tracker,
)
from app.services.search import (
    SearchField,
    get_random_book,
    search_books,
    search_by_author_id,
)
from app.web.deps import Pagination, get_db
from app.web.template_filters import normalize_authors, register_filters

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
register_filters(templates.env)

class BatchCreateRequest(BaseModel):
    lib_ids: list[int]


# ---------------------------------------------------------------- helpers

def _make_filename(title: str, authors: list[str]) -> str:
    """Формирует имя файла для скачивания: "Автор - Название.fb2"."""
    author = normalize_authors(authors) or "Без автора"
    # Чистим от недопустимых символов
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", f"{author} - {title}")
    safe = safe[:150].strip() or "book"
    return f"{safe}.fb2"


# ---------------------------------------------------------------- routes

@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    random_book = await get_random_book(session, torrent_id=None)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "Библиотека FB2",
            "random_book": random_book,
        },
    )


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query("", description="Поисковый запрос"),
    field: str = Query("all", description="Поле поиска: all / title / author / series"),
    pagination: Pagination = Depends(),
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    try:
        search_field = SearchField(field)
    except ValueError:
        search_field = SearchField.ALL

    result = await search_books(
        session,
        q=q,
        field=search_field,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "title": f"Поиск: {q!r}" if q else "Все книги",
            "result": result,
            "q": q,
            "field": search_field,
            "SearchField": SearchField,
        },
    )


@router.get("/book/{lib_id}", response_class=HTMLResponse)
async def book_detail(
    request: Request,
    lib_id: int,
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    book = await session.scalar(
        select(Book)
        .options(selectinload(Book.authors_rel))
        .where(Book.lib_id == lib_id)
        .limit(1)
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Книга не найдена")

    return templates.TemplateResponse(
        request=request,
        name="book.html",
        context={
            "title": book.title,
            "book": book,
        },
    )


@router.get("/book/{lib_id}/download")
async def book_download(
    lib_id: int,
    session: AsyncSession = Depends(get_db),
) -> Response:

    # Проверяем: если локальный ZIP есть — сразу отдаём
    try:
        if await is_book_local_available(session, lib_id):
            content = await fetch_book_content(session, lib_id)
            filename = _make_filename(content.title, content.authors)
            encoded = quote(filename)
            return Response(
                content=content.data,
                media_type="application/fb2+xml",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
                    "Content-Length": str(len(content.data)),
                    "X-Source": content.source,
                },
            )
    except Exception:  # noqa: BLE001
        pass

    # Иначе — редирект на страницу прогресса
    return RedirectResponse(url=f"/download/{lib_id}", status_code=302)


@router.get("/random")
async def random_redirect(
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Редирект на случайную книгу."""

    book = await get_random_book(session, torrent_id=None)
    if book is None:
        raise HTTPException(status_code=404, detail="Нет книг")
    return RedirectResponse(url=f"/book/{book.lib_id}", status_code=302)


# ---------------------------------------------------------------- api

@router.get("/api/search")
async def api_search(
    q: str = Query("", description="Поисковый запрос"),
    field: str = Query("all"),
    pagination: Pagination = Depends(),
    session: AsyncSession = Depends(get_db),
) -> dict:
    try:
        search_field = SearchField(field)
    except ValueError:
        search_field = SearchField.ALL

    result = await search_books(
        session,
        q=q,
        field=search_field,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return {
        "query": result.query,
        "field": result.field.value,
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "total_pages": result.total_pages,
        "items": [
            {
                "lib_id": b.lib_id,
                "title": b.title,
                "authors": list(b.authors),
                "series": b.series,
                "series_num": b.series_num,
                "language": b.language,
                "file_size": b.file_size,
                "is_deleted": b.is_deleted,
            }
            for b in result.items
        ],
    }


# ================================================================ batch

@router.post("/api/batch")
async def api_batch_create(
    payload: BatchCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Создать batch-задачу и запустить её в фоне."""
    try:
        job = await create_job(session, payload.lib_ids)
    except BatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "job_id": job.id,
        "total": job.total_books,
        "status": job.status,
    }


@router.get("/api/batch/{job_id}")
async def api_batch_status(
    job_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Статус batch-задачи."""
    job = await get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Batch не найден")
    return job.to_dict()


@router.post("/api/batch/{job_id}/cancel")
async def api_batch_cancel(
    job_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Отменить batch."""
    try:
        job = await cancel_job(session, job_id)
    except BatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return job.to_dict()


@router.get("/events/batch/{job_id}")
async def batch_events(job_id: str) -> StreamingResponse:
    """SSE-канал прогресса batch."""
    async def event_generator():
        last_data: dict | None = None
        try:
            while True:
                async with async_session_maker() as session:
                    job = await get_job(session, job_id)
                    if job is None:
                        yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                        return
                    data = job.to_dict()

                if data != last_data:
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    last_data = data

                # Терминальные статусы — закрываем соединение
                if data.get("status") in ("ready", "error", "cancelled"):
                    return

                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/batch/{job_id}", response_class=HTMLResponse)
async def batch_page(
    request: Request,
    job_id: str,
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """HTML-страница прогресса batch."""
    job = await get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Batch не найден")

    return templates.TemplateResponse(
        request=request,
        name="batch.html",
        context={
            "title": "Пакетное скачивание",
            "job": job,
            "job_id": job_id,
        },
    )


@router.get("/batch/{job_id}/file")
async def batch_download(job_id: str, session: AsyncSession = Depends(get_db)) -> FileResponse:
    """Отдать готовый ZIP-архив."""
    job = await get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Batch не найден")
    if job.status != "ready" or not job.file_path:
        raise HTTPException(status_code=404, detail="Файл ещё не готов")

    file_path = Path(job.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл удалён")

    # Имя файла для скачивания
    filename = make_batch_filename(job_id)

    return FileResponse(
        path=file_path,
        media_type="application/zip",
        filename=filename,
    )

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/author/{author_id}", response_class=HTMLResponse)
async def author_detail(
    request: Request,
    author_id: int,
    pagination: Pagination = Depends(),
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    author = await get_author(session, author_id)
    if author is None:
        raise HTTPException(status_code=404, detail="Автор не найден")

    result = await search_by_author_id(
        session,
        author_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )

    return templates.TemplateResponse(
        request=request,
        name="author.html",
        context={
            "title": f"Автор: {author.display_name}",
            "author": author,
            "result": result,
        },
    )


@router.get("/authors", response_class=HTMLResponse)
async def authors_index(
    request: Request,
    q: str = Query("", description="Поиск автора"),
    pagination: Pagination = Depends(),
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    result = await search_authors(
        session,
        q=q,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return templates.TemplateResponse(
        request=request,
        name="authors.html",
        context={
            "title": "Авторы" + (f": {q!r}" if q else ""),
            "result": result,
            "q": q,
        },
    )


@router.get("/download/{lib_id}", response_class=HTMLResponse)
async def download_page(
    request: Request,
    lib_id: int,
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    book = await session.scalar(
        select(Book)
        .options(selectinload(Book.authors_rel))   # ← добавить
        .where(Book.lib_id == lib_id)
        .limit(1)
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Книга не найдена")

    return templates.TemplateResponse(
        request=request,
        name="download.html",
        context={
            "title": f"Скачивание: {book.title}",
            "book": book,
            "lib_id": lib_id,
        },
    )


@router.get("/events/download/{lib_id}")
async def download_events(lib_id: int) -> StreamingResponse:
    tracker = get_progress_tracker()

    async def event_generator():
        last_data = None
        try:
            while True:
                state = tracker.get(lib_id)
                if state is None:
                    data = {"lib_id": lib_id, "status": "unknown"}
                else:
                    data = state.to_dict()

                if data != last_data:
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    last_data = data

                # Если статус завершён — больше не опрашиваем
                if data.get("status") in ("done", "error"):
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    return

                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/download/{lib_id}/file")
async def download_file_final(lib_id: int) -> Response:
    from app.services.progress import DownloadStatus, get_progress_tracker

    tracker = get_progress_tracker()
    state = tracker.get(lib_id)
    if state is None or state.status != DownloadStatus.DONE or state.data is None:
        raise HTTPException(status_code=404, detail="Файл не готов")

    # Берём из ProgressState (там data)
    filename = f"{lib_id}.fb2"  # упрощённо; можно сохранить title из state
    encoded = quote(filename)

    return Response(
        content=state.data,
        media_type="application/fb2+xml",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            "Content-Length": str(len(state.data)),
            "X-Source": "torrent",
        },
    )


@router.post("/download/{lib_id}/start")
async def download_start(lib_id: int) -> dict:
    from app.db.base import async_session_maker

    tracker = get_progress_tracker()
    state = tracker.get(lib_id)

    if state and state.status in (DownloadStatus.PENDING, DownloadStatus.DOWNLOADING):
        return {"status": "already_running", "lib_id": lib_id}

    async def _run() -> None:
        # Новая сессия — не зависит от HTTP-запроса
        async with async_session_maker() as new_session:
            try:
                await fetch_book_content(new_session, lib_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Download failed for lib_id=%d", lib_id)
                st = tracker.get_or_create(lib_id)
                st.status = DownloadStatus.ERROR
                st.error = str(exc)
                st.finished_at = time.time()

    asyncio.create_task(_run())
    return {"status": "started", "lib_id": lib_id}

@router.get("/api/cart/preview")
async def api_cart_preview(
    lib_ids: str = Query("", description="Comma-separated lib_ids"),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Краткая информация о книгах в корзине (для модалки)."""
    if not lib_ids.strip():
        return {"items": []}

    try:
        ids = [int(x) for x in lib_ids.split(",") if x.strip().isdigit()]
    except ValueError:
        return {"items": []}

    if not ids:
        return {"items": []}

    # Ограничим 20
    ids = ids[:20]

    stmt = select(Book).where(Book.lib_id.in_(ids))
    result = await session.execute(stmt)
    books = list(result.scalars().all())

    # Сохраняем порядок, как в корзине
    by_id = {b.lib_id: b for b in books}
    items = []
    for lid in ids:
        b = by_id.get(lid)
        if b is None:
            continue
        items.append({
            "lib_id": b.lib_id,
            "title": b.title,
            "authors_text": ", ".join(b.authors or []),
        })

    return {"items": items}
