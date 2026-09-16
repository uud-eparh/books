# Troubleshooting — решение типовых проблем

Что делать, если что-то не работает.

## 📋 Содержание

1. [Docker не запускается](#docker-не-запускается)
2. [PostgreSQL](#postgresql)
3. [Tor / Telegram-бот](#tor--telegram-бот)
4. [Веб-интерфейс](#веб-интерфейс)
5. [Скачивание книг](#скачивание-книг)
6. [Batch-загрузка](#batch-загрузка)
7. [Производительность](#производительность)
8. [Полезные команды](#полезные-команды)

---

## Docker не запускается

### `docker: command not found`

**Причина:** Docker не установлен или не в PATH.

**Решение:**

- **Windows/macOS:** установи [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **Linux:** `curl -fsSL https://get.docker.com | sh`

**Проверка:**

```bash
docker --version
docker compose version
```

### `Cannot connect to the Docker daemon`

**Причина:** Docker Desktop не запущен.

**Решение:**

1. Открой **Docker Desktop**
2. Дождись **зелёной иконки** в трее
3. Проверь: `docker ps`

### `Port 5432 is already in use`

**Причина:** порт 5432 занят — вероятно, **другой PostgreSQL** или **второй контейнер**.

**Решение A:** останови локальный PostgreSQL.

**Windows:**

```bash
# Открой services.msc → PostgreSQL → Stop
```

**Linux:**

```bash
sudo systemctl stop postgresql
```

**Решение B:** измени порт в `docker-compose.yml`:

```yaml
postgres:
  ports:
    - "5433:5432"   # ← 5433 вместо 5432
```

И в `.env`: `POSTGRES_PORT=5433`.

### `Port 8000 is already in use`

**Причина:** порт 8000 занят (например, локальным `uvicorn`).

**Решение:**

```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Linux / Git Bash
lsof -i :8000
kill -9 <PID>
```

Или измени порт в `docker-compose.yml`:

```yaml
app:
  ports:
    - "8001:8000"
```

---

## PostgreSQL

### `Connection refused` при старте `app`

**Симптомы:**

```
asyncpg.exceptions.ConnectionDoesNotExistError: connection was closed in the middle of operation
ConnectionRefusedError: [Errno 111] Connection refused
```

**Причина:** `app` подключается к `localhost:5432` вместо `postgres:5432`.

**Решение:** в `docker-compose.yml` для `app` должно быть:

```yaml
environment:
  POSTGRES_HOST: postgres     # ← НЕ localhost, НЕ ${POSTGRES_HOST}
  POSTGRES_PORT: 5432
```

**Проверка:**

```bash
docker compose exec app env | grep POSTGRES_HOST
# Ожидаем: POSTGRES_HOST=postgres
```

**Если `localhost`** — правь `docker-compose.yml` и:

```bash
docker compose --env-file .env.docker up -d --force-recreate app
```

### `FATAL: password authentication failed`

**Причина:** пароль в `.env.docker` **не совпадает** с паролем в volume БД.

**Решение:** **если БД пустая** — удали volume и пересоздай:

```bash
docker compose down -v
docker compose --env-file .env.docker up -d
```

⚠️ **Внимание:** `-v` удаляет **все данные БД**. Придётся **загружать `.inpx` заново**.

**Если данные важны** — узнай пароль из volume:

```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c "\du"
```

### `database "flibusta" does not exist`

**Причина:** volume БД не инициализирован.

**Решение:**

```bash
docker compose down -v
docker compose --env-file .env.docker up -d
sleep 30
docker compose logs postgres | grep "database system is ready"
```

### `flibusta_test` не создаётся для тестов

**Решение:**

```bash
docker exec -it flibusta_postgres psql -U flibusta -d postgres -c "CREATE DATABASE flibusta_test;"
python -m scripts.init_test_db
```

---

## Tor / Telegram-бот

### Бот не отвечает на `/start`

**Шаги диагностики:**

**1. Проверь, что бот запущен:**

```bash
docker compose logs app | grep "Bot started"
```

**Ожидаем:**

```
Bot started: @flibusta_fb2_bot (id=8724273214)
```

**Если нет** — бот **не подключился** к Telegram. См. ниже.

**2. Проверь Tor:**

```bash
docker compose logs tor | grep "Bootstrapped 100%"
```

**Ожидаем:** `Bootstrapped 100% (done): Done`.

**Если нет** — Tor **не подключился**. См. следующий пункт.

**3. Проверь связь `app` → `tor`:**

```bash
docker compose exec app python -c "
import socket
s = socket.socket(); s.settimeout(5)
s.connect(('tor', 9050)); print('OK: tor:9050 доступен')
"
```

**Ожидаем:** `OK: tor:9050 доступен`.

### Tor не подключается (Bootstrapped 0–99%)

**Симптомы в логах `tor`:**

```
[warn] Proxy Client: unable to connect OR connection ... ("general SOCKS server failure")
[notice] Failed to find node for hop #1 of our path.
```

**Причина:** мосты **заблокированы** провайдером или **устарели**.

**Решение:**

**1. Возьми свежие мосты:**

- Открой [@GetBridgesBot](https://t.me/GetBridgesBot) в Telegram
- Отправь `/webtunnel` (WebTunnel **лучше всего работает в РФ**)
- Получи 3–5 мостов

**2. Обнови `docker/torrc`:**

```
SocksPort 0.0.0.0:9050
ControlPort 0.0.0.0:9051

UseBridges 1
ClientTransportPlugin webtunnel exec /usr/bin/lyrebird

Bridge webtunnel <НОВЫЙ_МОСТ_1> ...
Bridge webtunnel <НОВЫЙ_МОСТ_2> ...
Bridge webtunnel <НОВЫЙ_МОСТ_3> ...
```

**3. Перезапусти Tor:**

```bash
docker compose restart tor
sleep 40
docker compose logs tor --tail=20
```

### `Couldn't connect to proxy 127.0.0.1:9050`

**Симптомы:**

```
aiohttp_socks._errors.ProxyConnectionError: [Errno 111] Couldn't connect to proxy 127.0.0.1:9050
```

**Причина:** в коде или `.env` **захардкожен** `127.0.0.1:9050` вместо `tor:9050`.

**Решение:**

**1. Проверь `config.py`:**

```python
telegram_proxy: str = "socks5://tor:9050"   # ← правильный дефолт
```

**2. Проверь `app/bot/main.py`:**

```python
session = AiohttpSession(proxy=settings.telegram_proxy)   # ← читаем из настроек
```

**3. Проверь `.env.docker`:**

```env
TELEGRAM_PROXY=socks5://tor:9050
```

**4. Проверь, что реально попадает в контейнер:**

```bash
docker compose exec app env | grep TELEGRAM_PROXY
# Ожидаем: TELEGRAM_PROXY=socks5://tor:9050
```

**5. Пересоздай контейнер:**

```bash
docker compose --env-file .env.docker up -d --force-recreate app
```

### `ModuleNotFoundError: No module named 'aiohttp_socks'`

**Причина:** пакет не установлен.

**Решение:**

```bash
docker compose exec app pip install aiohttp-socks
```

**Или** пересобери образ:

```bash
docker compose --env-file .env.docker build app
docker compose --env-file .env.docker up -d --force-recreate app
```

### `Conflict: terminated by other getUpdates`

**Причина:** **два экземпляра** бота слушают Telegram. Например, локальный `uvicorn` + Docker.

**Решение:**

**1. Останови локальный `uvicorn`:**

```bash
# Ctrl+C в терминале с uvicorn
```

**2. Проверь, что только один `app`:**

```bash
docker ps | grep flibusta_app
```

**3. Перезапусти:**

```bash
docker compose restart app
```

---

## Веб-интерфейс

### http://localhost:8000 не открывается

**1. Проверь, что контейнер `app` работает:**

```bash
docker compose ps
# flibusta_app ... Up (healthy)
```

**2. Проверь логи:**

```bash
docker compose logs app --tail=30
```

**3. Проверь, что порт проброшен:**

```bash
docker compose ps | grep 8000
# 0.0.0.0:8000->8000/tcp
```

**4. Проверь, что uvicorn слушает:**

```bash
docker compose exec app curl -s http://localhost:8000/health
# {"status":"ok"}
```

### 500 Internal Server Error

**Симптомы:** в браузере — ошибка **500**. В логах `app`:

```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called
```

**или**

```
RuntimeError: Task ... attached to a different loop
```

**Причина:** `lazy loading` async-объектов без `selectinload`.

**Решение:** в роутах **всегда** используй:

```python
stmt = select(Book).options(selectinload(Book.authors_rel))
```

**Проверь все места:**

```bash
grep -rn "authors_rel" app/
```

### Пустая страница / стили не загружаются

**Причина:** кэш браузера.

**Решение:**

- **Ctrl+Shift+R** (hard reload)
- Или открой **http://localhost:8000/static/style.css** — если 404, проблема в mount

### «Ничего не найдено» при поиске

**1. Проверь, что книги загружены:**

```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c "SELECT COUNT(*) FROM books;"
# Ожидаем: 699504
```

**2. Если 0** — загрузи `.inpx`:

```bash
docker compose exec app python -m scripts.load_books \
    --torrent-id 1 --inpx /data/flibusta_fb2_local.inpx
```

**3. Проверь FTS:**

```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT COUNT(*) FROM books WHERE to_tsvector('russian', title) @@ plainto_tsquery('russian', 'матриархат');"
```

---

## Скачивание книг

### `file not found` при скачивании

**Причина:** в БД `save_path` не совпадает с фактическим путём в контейнере.

**Решение:**

```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "UPDATE torrents SET save_path = '/data' WHERE id = 1;"
docker compose restart app
```

### Скачивание «висит» на 0%

**Симптомы в логах `app`:**

```
[5s] pieces: 0/1 · peers: 0/0 · rate: 0 KiB/s
[30s] pieces: 0/1 · peers: 0/0 · rate: 0 KiB/s
```

**Причина:** **нет пиров** для нужного piece-а. Torrent **не может найти данные**.

**Решение:**

**1. Убедись, что торрент активен** в µTorrent/qBittorrent на хосте. Если активен — **он может «забирать» пиров** у нашего libtorrent.

**2. Проверь статус торрента:**

```bash
docker compose logs app | grep "peers"
```

**3. Если пиров нет долго** — подожди 1–2 минуты (DHT ищет).

**4. Если у тебя есть локальный µTorrent** — временно **останови его** на время скачивания.

**5. Если совсем плохо** — **добавь публичные трекеры** в `torrent_session.py`:

```python
public_trackers = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.torrent.eu.org:451/announce",
]
params.trackers = list(params.trackers) + public_trackers
```

### `read_piece error: Operation not permitted`

**Причина:** `read_piece` вызван **до** того, как piece **полностью скачан**.

**Решение:** проверяй `handle.have_piece(piece_index)` **до** `read_piece`.

**Уже сделано** в `torrent_session.py`:

```python
if not handle.have_piece(piece_index):
    raise RuntimeError(f"Piece {piece_index} not available")
```

### Файл скачался, но **не открывается**

**Причина:** повреждён ZIP или неверный offset.

**Решение:** проверь логи:

```bash
docker compose logs app | grep "CRC32"
```

**Если `CRC32 mismatch`** — offset в `archive_entries` неверный. Переиндексируй:

```bash
docker compose exec app python -m scripts.index_archives --torrent-id 1 --force
```

---

## Batch-загрузка

### `Batch job not found`

**Причина:** job удалён или устарел.

**Решение:** создай новый batch через веб-интерфейс (добавь книги в корзину и нажми «Скачать ZIP»).

### ZIP-архив не скачивается

**1. Проверь статус job:**

```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT id, status, done_books, total_books FROM batch_jobs ORDER BY created_at DESC LIMIT 5;"
```

**Ожидаем:** `status = 'ready'`.

**2. Проверь, что файл существует:**

```bash
docker compose exec app ls -la /app/tmp_downloads/ | grep Flibusta
```

**3. Если `status = 'error'`** — смотри логи:

```bash
docker compose logs app | grep "Batch"
```

### ZIP превышает 50 МБ, часть книг не попала

**Это by design.** Лимит **50 МБ** на один batch.

**Решение:** раздели на **два batch** по 10 книг.

---

## Производительность

### Поиск медленный (>1 сек)

**Проверь индексы:**

```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT indexname FROM pg_indexes WHERE tablename='books' ORDER BY indexname;"
```

**Ожидаем 14 индексов**, включая `ix_books_title_fts`, `ix_books_authors_text_trgm`, `ix_books_genres_gin`.

**Если индексов нет** — создай вручную:

```sql
CREATE INDEX ix_books_title_fts ON books USING GIN (to_tsvector('russian', title));
CREATE INDEX ix_books_authors_text_trgm ON books USING GIN (authors_text gin_trgm_ops);
```

### `tmp_downloads` растёт до гигабайт

**Причина:** LRU-кэш **не срабатывает** (лимит 20 ГБ).

**Проверь `TEMP_DOWNLOAD_MAX_GB`:**

```bash
docker compose exec app env | grep TEMP_DOWNLOAD_MAX_GB
# Ожидаем: 20
```

**Ручная очистка:**

```bash
docker compose exec app python -c "
from app.services.temp_cleaner import enforce_cache_limit, cleanup_old_fb2
enforce_cache_limit(20)
cleanup_old_fb2(10)
"
```

### `libtorrent` жрёт CPU

**Причина:** DHT-запросы, поиск пиров.

**Решение:** в `torrent_session.py`:

```python
"dht_bootstrap_nodes": "",
"enable_dht": False,   # ← отключить DHT (если не нужен)
```

---

## Полезные команды

### Логи

```bash
# Все сервисы
docker compose logs -f

# Только app
docker compose logs -f app

# Только последние 50 строк
docker compose logs --tail=50 app

# С фильтром
docker compose logs app | grep ERROR
```

### Bash внутрь контейнера

```bash
# В app
docker compose exec app bash

# В postgres
docker compose exec postgres psql -U flibusta -d flibusta

# В tor
docker compose exec tor sh
```

### Перезапуск

```bash
# Перезапустить app
docker compose restart app

# Пересоздать (с новым env)
docker compose --env-file .env.docker up -d --force-recreate app

# Полный рестарт
docker compose --env-file .env.docker down
docker compose --env-file .env.docker up -d
```

### Очистка

```bash
# Только контейнеры (сохранить БД)
docker compose down

# С удалением БД
docker compose down -v

# Удалить все неиспользуемые образы
docker image prune -a
```

### Проверка БД

```bash
# Количество книг
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT COUNT(*) FROM books;"

# Топ-10 авторов
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT display_name, books_count FROM authors ORDER BY books_count DESC LIMIT 10;"

# Размер БД
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT pg_size_pretty(pg_database_size('flibusta'));"
```

### Тесты

```bash
# Все тесты
pytest tests/ -v

# Конкретный файл
pytest tests/test_search.py -v

# С покрытием
pytest tests/ --cov=app --cov-report=html
```

---

## Что-то ещё?

Если проблема **не описана** здесь:

1. **Собери логи:**

```bash
docker compose logs > debug.log
```

2. **Проверь, что версии актуальны:**

```bash
docker --version
docker compose version
docker images | grep flibusta
```

3. **Ищи в issues** репозитория (если публичный).

4. **Проверь** [ARCHITECTURE.md](ARCHITECTURE.md) и [SETUP.md](SETUP.md) — возможно, ответ там.

---

## См. также

- **[SETUP.md](SETUP.md)** — установка
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — как устроено
- **[API.md](API.md)** — HTTP-эндпоинты
- **[BOT.md](BOT.md)** — Telegram-бот
- **[UPDATE.md](UPDATE.md)** — обновление