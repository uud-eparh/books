# HTTP API — эндпоинты веб-интерфейса

Описание всех HTTP-роутов, форматов запросов и ответов.

## 📋 Содержание

1. [Обзор](#обзор)
2. [HTML-страницы](#html-страницы)
3. [JSON API](#json-api)
4. [SSE (Server-Sent Events)](#sse-server-sent-events)
5. [Batch API](#batch-api)
6. [Файлы и скачивание](#файлы-и-скачивание)
7. [Примеры](#примеры)
8. [Коды ответов](#коды-ответов)
9. [Ограничения](#ограничения)

---

## Обзор

**Базовый URL:** `http://localhost:8000`

**Формат:** HTML (Jinja2-шаблоны) для страниц, JSON для API.

**Аутентификация:** нет (предполагается локальное использование).

**Версия API:** неявная (без `/api/v1`).

---

## HTML-страницы

### `GET /`

**Главная.** Форма поиска + случайная книга.

**Параметры:** нет.

**Ответ:** HTML.

### `GET /search`

**Результаты поиска** с пагинацией.

**Query-параметры:**

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `q` | str | `""` | Поисковый запрос |
| `field` | str | `all` | `all` / `title` / `author` / `series` |
| `page` | int | `1` | Номер страницы |
| `page_size` | int | `50` | Размер страницы (1–200) |

**Пример:**

```
GET /search?q=матриархат&field=title&page=1
```

**Ответ:** HTML с результатами.

### `GET /book/{lib_id}`

**Карточка книги.**

**Параметры пути:**

- `lib_id` — LibID из `.inpx`

**Пример:**

```
GET /book/811194
```

**Ответ:** HTML.

**Ошибки:**

- `404` — книга не найдена

### `GET /author/{author_id}`

**Все книги автора** с пагинацией.

**Параметры пути:**

- `author_id` — ID автора в БД

**Пример:**

```
GET /author/37523?page=1
```

**Ответ:** HTML.

### `GET /authors`

**Список авторов** с поиском.

**Query-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `q` | str | Поиск по имени |
| `page` | int | Номер страницы |

**Пример:**

```
GET /authors?q=Пушкин
```

**Ответ:** HTML.

### `GET /download/{lib_id}`

**Страница прогресса скачивания** (для торрент-режима).

**Параметры пути:**

- `lib_id` — LibID книги

**Ответ:** HTML с SSE-подключением.

### `GET /batch/{job_id}`

**Страница прогресса batch-загрузки.**

**Параметры пути:**

- `job_id` — UUID задачи

**Ответ:** HTML.

---

## JSON API

### `GET /api/search`

**JSON-поиск** (для программного доступа).

**Query-параметры:**

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `q` | str | `""` | Поисковый запрос |
| `field` | str | `all` | `all` / `title` / `author` / `series` |
| `page` | int | `1` | Номер страницы |
| `page_size` | int | `50` | Размер страницы |

**Пример:**

```
GET /api/search?q=Романович&field=author&page=1
```

**Ответ:**

```json
{
  "query": "Романович",
  "field": "author",
  "total": 243,
  "page": 1,
  "page_size": 50,
  "total_pages": 5,
  "items": [
    {
      "lib_id": 73488,
      "title": "Гер",
      "authors": ["Романович,Роман"],
      "series": null,
      "series_num": null,
      "language": "ru",
      "file_size": 1048576,
      "is_deleted": false
    }
  ]
}
```

### `GET /api/cart/preview`

**Информация о книгах в корзине** (для модалки).

**Query-параметры:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `lib_ids` | str | Comma-separated LibID (до 20) |

**Пример:**

```
GET /api/cart/preview?lib_ids=811194,811195,811196
```

**Ответ:**

```json
{
  "items": [
    {
      "lib_id": 811194,
      "title": "Чертова невеста правильного парень",
      "authors_text": "Джейн,О. О."
    }
  ]
}
```

### `GET /health`

**Health check** (для Docker healthcheck).

**Ответ:**

```json
{"status": "ok"}
```

---

## SSE (Server-Sent Events)

### `GET /events/download/{lib_id}`

**Поток прогресса скачивания одной книги.**

**Формат:** `text/event-stream`.

**События:**

```
data: {"lib_id": 811194, "status": "downloading", "pieces_done": 0, "pieces_total": 1, "progress_percent": 0.0, "eta_seconds": null, "elapsed_seconds": 0.0}

data: {"lib_id": 811194, "status": "downloading", "pieces_done": 0, "pieces_total": 1, "progress_percent": 0.0, "eta_seconds": 3, "elapsed_seconds": 2.5}

data: {"lib_id": 811194, "status": "done", "pieces_done": 1, "pieces_total": 1, "progress_percent": 100.0, "elapsed_seconds": 6.1, "source": "torrent"}
```

**Статусы:**

- `pending` — в очереди
- `downloading` — активно качается
- `done` — готово
- `error` — ошибка

### `GET /events/batch/{job_id}`

**Поток прогресса batch-загрузки.**

**События:**

```
data: {"job_id": "e2fe08de-...", "status": "downloading", "done_books": 3, "total_books": 6, "progress_percent": 50.0, "completed_lib_ids": [811194, 811195, 811196], "failed_lib_ids": [], "current_lib_id": 811197}

data: {"job_id": "e2fe08de-...", "status": "ready", "done_books": 6, "total_books": 6, "progress_percent": 100.0, "file_size": 14883018, "completed_lib_ids": [811194, 811199]}
```

**Статусы:**

- `pending`
- `downloading`
- `packing` — упаковка в ZIP
- `ready` — готово
- `error`
- `cancelled`

---

## Batch API

### `POST /api/batch`

**Создать batch-задачу.**

**Тело запроса:**

```json
{
  "lib_ids": [811194, 811195, 811196]
}
```

**Ограничения:**

- **Максимум 20 книг** в одном batch
- **Максимум 50 МБ** на ZIP
- Дубликаты **удаляются** автоматически

**Ответ (200):**

```json
{
  "job_id": "e2fe08de-8f77-412b-a65b-63206351f825",
  "total": 3,
  "status": "pending"
}
```

**Ошибка (400):**

```json
{
  "detail": "Максимум 20 книг в одном пакете, получено 25"
}
```

### `GET /api/batch/{job_id}`

**Статус batch-задачи.**

**Ответ (200):**

```json
{
  "job_id": "e2fe08de-8f77-412b-a65b-63206351f825",
  "status": "downloading",
  "total_books": 6,
  "done_books": 3,
  "error_count": 0,
  "progress_percent": 50.0,
  "current_lib_id": 811197,
  "completed_lib_ids": [811194, 811195, 811196],
  "failed_lib_ids": [],
  "file_size": null,
  "error": null,
  "cancelled": false,
  "created_at": "2026-09-15T10:30:45.706Z",
  "finished_at": null
}
```

**Ошибка (404):**

```json
{"detail": "Batch не найден"}
```

### `POST /api/batch/{job_id}/cancel`

**Отменить batch-задачу.**

**Ответ (200):**

```json
{
  "job_id": "e2fe08de-...",
  "status": "cancelled"
}
```

---

## Файлы и скачивание

### `GET /book/{lib_id}/download`

**Скачать одну книгу в формате `.fb2`.**

**Логика:**

1. Если ZIP **локально** → отдаём **сразу** (~150 мс)
2. Если **нет** → **редирект** на `/download/{lib_id}` (с прогрессом)

**Ответ:**

- **200** — `.fb2`-файл
- **302** — редирект на страницу прогресса

**Заголовки:**

```
Content-Type: application/fb2+xml
Content-Disposition: attachment; filename*=UTF-8''Author%20-%20Title.fb2
Content-Length: 863041
X-Source: local_zip
X-Elapsed: 0.15
```

### `GET /download/{lib_id}/file`

**Скачать готовую книгу** (после SSE-прогресса).

**Ответ:**

- **200** — `.fb2`-файл
- **404** — если файл не готов

### `GET /batch/{job_id}/file`

**Скачать ZIP-архив** с batch-загрузкой.

**Ответ:**

- **200** — ZIP-файл
- **404** — если не готов

**Заголовки:**

```
Content-Type: application/zip
Content-Disposition: attachment; filename*=UTF-8''Flibusta_2026-09-15_e2fe08.zip
Content-Length: 14883018
```

---

## Примеры

### cURL

**Поиск:**

```bash
curl "http://localhost:8000/api/search?q=Романович&field=author"
```

**Создать batch:**

```bash
curl -X POST http://localhost:8000/api/batch \
    -H "Content-Type: application/json" \
    -d '{"lib_ids": [811194, 811195, 811196]}'
```

**Статус batch:**

```bash
curl "http://localhost:8000/api/batch/e2fe08de-8f77-412b-a65b-63206351f825"
```

**Скачать книгу:**

```bash
curl -OJ "http://localhost:8000/book/811194/download"
```

### Python (httpx)

```python
import httpx

# Поиск
async with httpx.AsyncClient() as client:
    r = await client.get(
        "http://localhost:8000/api/search",
        params={"q": "Романович", "field": "author"},
    )
    data = r.json()
    print(f"Найдено: {data['total']}")
    for book in data["items"][:5]:
        print(f"  {book['title']} — {book['authors']}")

# Batch
async with httpx.AsyncClient() as client:
    r = await client.post(
        "http://localhost:8000/api/batch",
        json={"lib_ids": [811194, 811195, 811196]},
    )
    job_id = r.json()["job_id"]
    print(f"Job: {job_id}")

# Скачать ZIP
async with httpx.AsyncClient() as client:
    async with client.stream(
        "GET", f"http://localhost:8000/batch/{job_id}/file"
    ) as r:
        with open("books.zip", "wb") as f:
            async for chunk in r.aiter_bytes():
                f.write(chunk)
```

### JavaScript (fetch + EventSource)

```javascript
// Поиск
const res = await fetch("/api/search?q=Романович");
const data = await res.json();
console.log(`Найдено: ${data.total}`);

// Создать batch
const batchRes = await fetch("/api/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lib_ids: [811194, 811195, 811196] }),
});
const { job_id } = await batchRes.json();

// SSE-прогресс
const es = new EventSource(`/events/batch/${job_id}`);
es.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(`Прогресс: ${data.progress_percent}%`);
    if (data.status === "ready") {
        es.close();
        window.location = `/batch/${job_id}/file`;
    }
};
```

---

## Коды ответов

| Код | Значение |
|-----|----------|
| 200 | OK |
| 302 | Found (редирект) |
| 400 | Bad Request (невалидные параметры) |
| 404 | Not Found |
| 500 | Internal Server Error |

---

## Ограничения

| Ограничение | Значение |
|-------------|----------|
| Batch: макс. книг | 20 |
| Batch: макс. ZIP | 50 МБ |
| Page size (search) | 1–200 |
| Каталог книг | 699 504 |
| Каталог авторов | 169 869 |

---

## См. также

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — как устроено
- **[BOT.md](BOT.md)** — Telegram-бот (параллельный интерфейс)
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — проблемы
- **[SETUP.md](SETUP.md)** — установка