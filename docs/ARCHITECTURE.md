# Архитектура Book Hub

Как устроен проект: компоненты, схема БД, потоки данных.

## 📋 Содержание

1. [Общая схема](#общая-схема)
2. [Компоненты](#компоненты)
3. [Схема БД](#схема-бд)
4. [Потоки данных](#потоки-данных)
5. [Модули приложения](#модули-приложения)
6. [Хранение данных](#хранение-данных)
7. [Безопасность](#безопасность)

---

## Общая схема

```mermaid
flowchart TB
    User[👤 Пользователь]
    Browser[🌐 Браузер]
    Telegram[✈️ Telegram]

    subgraph Docker["🐳 Docker Compose"]
        direction TB

        subgraph App["flibusta_app (Ubuntu 24.04)"]
            direction LR
            FastAPI[FastAPI<br/>веб]
            Aiogram[aiogram 3<br/>бот]
            Libtorrent[libtorrent<br/>скачивание]

            Services[Services Python:<br/>search, library,<br/>torrent_manager, batch]
            SQLAlchemy[SQLAlchemy 2.x<br/>async]

            FastAPI --> Services
            Aiogram --> Services
            Libtorrent --> Services
            Services --> SQLAlchemy
        end

        Postgres[(flibusta_postgres<br/>PostgreSQL 16)]
        Tor[flibusta_tor<br/>Alpine + lyrebird]

        Data[/data ro<br/>ZIP-архивы + .inpx/]
        Tmp[/app/tmp_downloads<br/>volume/]

        SQLAlchemy --> Postgres
        Aiogram -.SOCKS5.-> Tor
    end

    User --> Browser
    User --> Telegram
    Browser -->|HTTP| FastAPI
    Telegram -->|HTTPS| Aiogram
    App -.mount.-> Data
    App -.mount.-> Tmp

    style User fill:#e0f2fe
    style Docker fill:#f0f9ff
    style App fill:#fff
    style Postgres fill:#dbeafe
    style Tor fill:#fce7f3

```

---

## Компоненты

### `flibusta_app`

**Главный контейнер.** Ubuntu 24.04 + Python 3.12 + libtorrent 2.0.10.

**Внутри:**
- **FastAPI** — HTTP-сервер на `:8000`
- **aiogram 3** — Telegram-бот (long polling через SOCKS5)
- **libtorrent** — скачивание кусков торрента
- **SQLAlchemy 2 (async)** — работа с PostgreSQL

**Запуск:** `uvicorn app.main:app` → в `lifespan` стартуют `TorrentManager` и `aiogram` polling.

### `flibusta_postgres`

**PostgreSQL 16** в Alpine. Хранит:
- **Книги** (`books`)
- **Авторы** (`authors`, `book_authors`)
- **Торренты** (`torrents`, `torrent_files`)
- **Оглавления ZIP** (`archive_entries`)
- **Batch-задачи** (`batch_jobs`)
- **Метаданные** (`library_meta`)

**Порты:** `5432` проброшен наружу (для локальной разработки и тестов).

### `flibusta_tor`

**Tor-прокси** для обхода блокировок Telegram API.

**Образ:** Alpine + Tor + **lyrebird** (WebTunnel-транспорт).

**Порты:** `9050` (SOCKS5) — **только внутри Docker-сети**, `9051` (Control).

**Зачем:** Telegram API **заблокирован** в РФ. Tor **маскирует трафик** под HTTPS.

---

## Схема БД

### ER-диаграмма

```mermaid
erDiagram
    torrents ||--o{ torrent_files : "1:N"
    torrents ||--o{ books : "1:N"
    torrents ||--o{ library_meta : "1:N"
    torrent_files ||--o{ archive_entries : "1:N"
    books ||--o{ book_authors : "M:N"
    authors ||--o{ book_authors : "M:N"

    torrents {
        int id PK
        string info_hash "SHA1 info-hash"
        string name "Название раздачи"
        text magnet "Magnet-ссылка"
        text save_path "/data"
        bytea resume_data "708 KB для libtorrent"
        bigint data_size "568 GB"
        int files_count "221"
    }

    torrent_files {
        bigint id PK
        int torrent_id FK
        int file_index "0..220"
        text path "f.fb2-xxx.zip"
        bigint size "Размер ZIP"
        bigint byte_offset "Смещение в торренте"
        int piece_start
        int piece_end
    }

    archive_entries {
        bigint id PK
        bigint torrent_file_id FK
        text filename "811194.fb2"
        int lib_id
        bigint local_header_offset
        bigint compressed_size
        bigint uncompressed_size
        int compression "0=stored, 8=deflate"
        bigint crc32
    }

    books {
        bigint id PK
        int torrent_id FK
        int lib_id "ID из .inpx"
        text title
        text_array authors
        text authors_text "Для ILIKE"
        text_array genres
        text series
        text series_text "Для ILIKE"
        int series_num
        string language
        bigint file_size
        text annotation
        text archive_name
        bool is_deleted
    }

    authors {
        bigint id PK
        text name "Фамилия,Имя,Отчество"
        text display_name "Фамилия Имя Отчество"
        int books_count
    }

    book_authors {
        bigint book_id FK
        bigint author_id FK
    }

    library_meta {
        int id PK
        int torrent_id FK
        text name
        string version
        int chunk_size
        text description
        int books_count
        int archives_count
    }

    batch_jobs {
        uuid id PK
        int_array lib_ids
        string status "pending/downloading/.../ready"
        int total_books
        int done_books
        int_array completed_lib_ids
        int_array failed_lib_ids
        text file_path
        bigint file_size
        bool cancelled
    }

```


### Таблицы — подробно

#### `torrents`

**Реестр торрентов.**

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | INTEGER PK | |
| `info_hash` | VARCHAR(40) | SHA1 info-hash |
| `name` | VARCHAR(500) | Название раздачи |
| `magnet` | TEXT | Magnet-ссылка |
| `save_path` | TEXT | Путь к данным (`/data`) |
| `resume_data` | BYTEA | Resume-данные libtorrent (708 КБ) |
| `data_size` | BIGINT | 568 ГБ |
| `files_count` | INTEGER | 221 |
| `version` | VARCHAR(64) | Версия `.inpx` |

#### `torrent_files`

**Файлы внутри торрента (ZIP-архивы).**

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `torrent_id` | INTEGER FK | → `torrents.id` |
| `file_index` | INTEGER | Индекс в торренте (0..220) |
| `path` | TEXT | `f.fb2-811194-815075.zip` |
| `size` | BIGINT | Размер ZIP |
| `byte_offset` | BIGINT | Смещение от начала торрента |
| `piece_start` | INTEGER | Первый piece |
| `piece_end` | INTEGER | Последний piece |

**UNIQUE:** `(torrent_id, file_index)`, `(torrent_id, path)`.

#### `archive_entries`

**Файлы внутри ZIP-архивов** (`.fb2`).

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `torrent_file_id` | BIGINT FK | → `torrent_files.id` |
| `filename` | TEXT | `811194.fb2` |
| `lib_id` | INTEGER | ID книги |
| `local_header_offset` | BIGINT | Смещение в ZIP |
| `compressed_size` | BIGINT | Размер сжатых данных |
| `uncompressed_size` | BIGINT | Размер распакованного |
| `compression` | INTEGER | 0=stored, 8=deflate |
| `crc32` | BIGINT | Контрольная сумма |

**UNIQUE:** `(torrent_file_id, filename)`.

#### `books`

**Каталог книг** (699 504 записи).

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `torrent_id` | INTEGER FK | → `torrents.id` |
| `lib_id` | INTEGER | ID из `.inpx` |
| `title` | TEXT | Название |
| `authors` | TEXT[] | `["Джейн,О. О."]` |
| `authors_text` | TEXT | `"Джейн,О. О."` (для ILIKE) |
| `genres` | TEXT[] | Жанры |
| `series` | TEXT | Серия |
| `series_text` | TEXT | Серия (для ILIKE) |
| `series_num` | INTEGER | Номер в серии |
| `language` | VARCHAR(16) | `ru` |
| `file_size` | BIGINT | Размер `.fb2` |
| `annotation` | TEXT | Аннотация |
| `archive_name` | TEXT | `f.fb2-811194-815075.zip` |
| `is_deleted` | BOOLEAN | Удалена из Флибусты |

**Индексы:**
- **GIN** `to_tsvector('russian', title)` — FTS
- **GIN** `authors` — массив
- **GIN** `genres` — массив
- **GIN trigram** `authors_text`, `series_text`, `annotation`, `title`
- **B-tree** `lib_id`, `(torrent_id, archive_name)`, `language`, `is_deleted`

#### `authors`, `book_authors`

**Авторы** (170 000) и связь M:N с книгами.

| `authors.name` | `display_name` | `books_count` |
|---------------|---------------|---------------|
| `Романович,Роман` | `Романович Роман` | 243 |

#### `batch_jobs`

**Пакетная загрузка** (20 книг → ZIP).

| Поле | Описание |
|------|----------|
| `id` | UUID |
| `lib_ids` | INTEGER[] — список книг |
| `status` | `pending` / `downloading` / `packing` / `ready` / `error` / `cancelled` |
| `completed_lib_ids` | Успешно скачанные |
| `failed_lib_ids` | Не скачанные |
| `file_path` | Путь к ZIP |
| `file_size` | Размер ZIP |

---

## Потоки данных

### 1. Поиск книги

```mermaid
sequenceDiagram
    autonumber
    participant U as 👤 Пользователь
    participant F as 🌐 FastAPI
    participant S as 🔍 search_books()
    participant DB as 💾 SQLAlchemy
    participant PG as 🐘 PostgreSQL

    U->>F: GET /search?q=Романович
    F->>S: search_books(q="Романович")
    S->>DB: SELECT * FROM books
    Note over DB: WHERE to_tsvector('russian', title)<br/>@@ plainto_tsquery('russian', :q)<br/>OR array_to_string(authors,' ') ILIKE '%Романович%'<br/>OR series_text ILIKE '%Романович%'<br/>ORDER BY ts_rank(...) DESC LIMIT 50
    DB->>PG: SQL
    Note over PG: Bitmap Index Scan<br/>(ix_books_title_fts,<br/>ix_books_authors_text_trgm)
    PG-->>DB: 50 rows
    DB-->>S: results
    S-->>F: SearchResult
    F-->>U: HTML (50 книг)
    Note over PG,U: ⏱ < 1 мс
```

### 2. Скачивание через торрент (точечное)

```mermaid
sequenceDiagram
    autonumber
    participant U as 👤 Пользователь
    participant F as 🌐 FastAPI
    participant L as 📚 library.py
    participant TM as 🎯 TorrentManager
    participant LT as ⚡ libtorrent
    participant Z as 📦 zip_reader
    participant TG as ✈️ Telegram

    U->>F: Клик «⬇ Скачать FB2» (lib_id=811194)
    F->>L: fetch_book_content(session, 811194)

    Note over L: 1. Находим book<br/>→ archive_name = "f.fb2-811194-815075.zip"<br/>2. Находим torrent_file<br/>→ byte_offset = 230 061 334 378<br/>→ piece_start = 13742<br/>3. Находим archive_entry<br/>→ local_header_offset = 500 003 406<br/>→ compressed_size = 1 516 283

    Note over L: Вычисляем:<br/>abs_start = 230 561 337 784<br/>abs_end   = 230 562 855 367<br/>first_piece = 13742<br/>last_piece  = 13742

    L->>TM: download_range(torrent_id=1, 13742, 13742)
    TM->>LT: piece_priority(13742, HIGH)
    Note over LT: Скачивает 1 piece<br/>(16 МБ) за 3–6 сек
    LT-->>TM: have_piece(13742) == True
    TM-->>L: pieces ready

    L->>TM: read_piece(13742)
    TM->>LT: read_piece
    LT-->>TM: bytes (16 MiB)
    TM-->>L: piece bytes

    L->>Z: parse_local_header(buf)
    Z-->>L: compressed data
    L->>L: zlib.decompress(data, -15)<br/>→ 863 041 байт (.fb2)

    L-->>F: bytes (863 KB)
    F->>TG: send_document(BufferedInputFile(data, filename="...fb2"))
    TG-->>U: [📎 Romanovich,Roman - Klan.fb2]
```



### 3. Batch-загрузка,

```mermaid
sequenceDiagram
    autonumber
    participant U as 👤 Пользователь
    participant F as 🌐 FastAPI
    participant B as 📦 batch.py
    participant L as 📚 library.py
    participant DB as 💾 PostgreSQL
    participant FS as 📁 tmp_downloads

    U->>F: POST /api/batch {lib_ids: [1,2,3,4,5,6]}
    F->>B: create_job(session, lib_ids)
    B->>DB: INSERT batch_jobs (status=pending)
    DB-->>B: job_id = "e2fe08de-..."
    B->>B: asyncio.create_task(_process_job)
    B-->>F: BatchJob
    F-->>U: {job_id, total: 6}

    Note over B,L: Для каждой из 6 книг:

    loop 6 раз
        B->>L: fetch_book_content(session, lib_id)
        alt local_zip
            L-->>B: bytes (~50 мс)
        else torrent
            L-->>B: bytes (3–30 сек)
        end
        B->>B: files[filename] = bytes
        B->>DB: UPDATE batch_jobs SET completed_lib_ids=[...]
    end

    B->>B: Упаковка в ZIP
    B->>FS: Flibusta_2026-09-15_e2fe08.zip
    FS-->>B: file_size = 14883018
    B->>DB: UPDATE status='ready', file_path, file_size

    U->>F: GET /batch/{job_id}/file
    F->>FS: FileResponse
    FS-->>U: ZIP (14.1 МБ)
```

---

## Модули приложения

### `app/services/`

| Модуль | Ответственность |
|--------|-----------------|
| `search.py` | FTS + trigram + токенизация |
| `authors.py` | Работа с авторами (поиск, пагинация) |
| `library.py` | `fetch_book_content` — local_zip / torrent |
| `torrent_session.py` | Обёртка над libtorrent-сессией |
| `torrent_manager.py` | Singleton + очередь задач |
| `torrent_fetcher.py` | Точечное скачивание + распаковка |
| `zip_reader.py` | Чтение `.fb2` из ZIP по offset |
| `batch.py` | Пакетная загрузка (20 книг → ZIP) |
| `filenames.py` | Транслитерация, sanitize, уникальность |
| `progress.py` | ProgressTracker для SSE |
| `temp_cleaner.py` | LRU-кэш временных ZIP |

### `app/parsers/`

| Модуль | Ответственность |
|--------|-----------------|
| `inpx.py` | Парсер `.inpx` |
| `torrent.py` | Метаданные торрента через libtorrent |
| `zip_indexer.py` | Сканирование ZIP (оглавление) |

### `app/web/`

| Модуль | Ответственность |
|--------|-----------------|
| `routes.py` | HTTP-эндпоинты (FastAPI) |
| `deps.py` | Зависимости (сессия БД, пагинация) |
| `template_filters.py` | Jinja2-фильтры (нормализация, размер) |

### `app/bot/`

| Модуль | Ответственность |
|--------|-----------------|
| `main.py` | Создание Bot + Dispatcher |
| `middlewares.py` | Whitelist + логирование |
| `handlers/start.py` | `/start`, `/help`, `/about` |
| `handlers/search.py` | Поиск по тексту |
| `handlers/book.py` | Карточка книги |
| `handlers/download.py` | Скачивание `.fb2` |
| `handlers/author.py` | Список книг автора + пагинация |
| `handlers/series.py` | Список книг серии |
| `keyboards.py` | Инлайн-клавиатуры |
| `formatters.py` | Форматирование текста |

---

## Хранение данных

### Постоянные данные

| Данные | Где | Размер | Backup |
|--------|-----|--------|--------|
| **PostgreSQL** | `volume: postgres_data` | ~1 ГБ | `pg_dump` |
| **ZIP-архивы** | `/data` (mount с хоста) | 568 ГБ | Уже на хосте |
| **`.inpx`** | `/data` | 40 МБ | Уже на хосте |

### Временные данные

| Данные | Где | TTL |
|--------|-----|-----|
| **Скачанные `.zip`** | `/app/tmp_downloads` | Удаляются при >20 ГБ (LRU) |
| **Batch-ZIP** | `/app/tmp_downloads` | Удаляются через 10 мин (TTL) |
| **Resume-данные** | `torrents.resume_data` (BYTEA) | Постоянно |

---

## Безопасность

### Whitelist

**`TELEGRAM_ALLOWED_USERS`** — список ID через запятую.

**Если пусто** — бот **публичный** (любой может пользоваться).

**Middleware** проверяет `user.id` **до** обработки команды.

### Пароли

**PostgreSQL** — `POSTGRES_PASSWORD` в `.env`. **Не коммитится** (в `.gitignore`).

**Telegram-токен** — `TELEGRAM_BOT_TOKEN`. **Никогда не публиковать.**

**При компрометации** — `/revoke` в `@BotFather`.

### Tor

**Tor-контейнер** не пробрасывает `9050` наружу — только **внутри Docker-сети**. **Безопасно.**

### SQL-инъекции

**SQLAlchemy** использует **параметризованные запросы**. **Прямых конкатенаций** нет.

**Исключение:** `search.py` собирает **`where`-условия** программно, но через **SQLAlchemy-выражения** — тоже **безопасно**.

---

## См. также

- **[SETUP.md](SETUP.md)** — установка
- **[API.md](API.md)** — HTTP-эндпоинты
- **[BOT.md](BOT.md)** — Telegram-бот
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — проблемы
- **[UPDATE.md](UPDATE.md)** — обновление