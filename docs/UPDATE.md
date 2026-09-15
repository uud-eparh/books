# Обновление библиотеки и добавление торрентов

Как обновлять каталог `.inpx`, добавлять новые торренты и управлять библиотекой.

## 📋 Содержание

1. [Обзор](#обзор)
2. [Обновление существующего торрента](#обновление-существующего-торрента)
3. [Добавление второго торрента](#добавление-второго-торрента)
4. [Удаление торрента](#удаление-торрента)
5. [Инкрементальные обновления](#инкрементальные-обновления)
6. [Управление через SQL](#управление-через-sql)
7. [Резервное копирование](#резервное-копирование)

---

## Обзор

**Библиотека Флибусты** обновляется **раз в месяц**. Каждое обновление:
- Добавляет **новые книги**
- Помечает **удалённые** (`is_deleted=true`)
- Обновляет **метаданные** (аннотации, авторы)

**Наша БД** хранит **снимок** на определённую дату (`library_meta.version`).

**ZIP-архивы** в торренте **дополняются** новыми файлами, но **старые не удаляются** — так что обновление `.inpx` **не требует** перекачивать всё заново.

---

## Обновление существующего торрента

**Сценарий:** вышла новая версия `.inpx` (`flibusta_fb2_local.inpx` от 2026-10-01).

### 1. Скачай новый `.inpx`

**Из торрента** (обновление торрента) или **отдельно** (если раздача обновляется).

**Путь:** `D:/Users/Downloads/fb2.Flibusta.Net/flibusta_fb2_local.inpx`

### 2. Проверь версию

```bash
# В Git Bash
unzip -p /d/Users/Downloads/fb2.Flibusta.Net/flibusta_fb2_local.inpx version.info
```
Ожидаем:

```text
20261001
```
### 3. Сравни с текущей версией в БД
```
```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT version, books_count, loaded_at FROM library_meta;"
```
Ожидаем:

```text
 version  | books_count |          loaded_at
----------+-------------+---------------------------
 20260701 |      699504 | 2026-09-11 07:06:54+00
```
Если 20261001 — обновляем.

### 4. Загрузи новый .inpx
```bash
docker compose exec app python -m scripts.load_books \
    --torrent-id 1 \
    --inpx /data/flibusta_fb2_local.inpx \
    --truncate
⚠️ --truncate — удалит все книги текущего торрента и загрузит заново.
```
Что произойдёт:

DROP всех 699k книг торрента

INSERT нового .inpx (~700k книг)

Время: 5–15 минут

Books_id последовательность — сбросится

### 5. Переиндексируй archive_entries
Так как книги новые — нужно обновить индексы ZIP.

```bash
docker compose exec app python -m scripts.index_archives --torrent-id 1 --force
```
Время: 2–5 минут.

### 6. Проверь результат
```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT COUNT(*) FROM books;"
```
Ожидаем: новое количество (может быть больше или меньше).

```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT version, books_count, loaded_at FROM library_meta;"
```
Ожидаем:

```text
 version  | books_count |          loaded_at
----------+-------------+---------------------------
 20261001 |      712345 | 2026-10-01 12:00:00+00
```
### 7. Перезапусти app
```bash
docker compose restart app
```
Добавление второго торрента
Сценарий: нашёл ещё одну библиотеку FB2 (например, «Либрусек» или другой снапшот Флибусты).

1. Скачай торрент
Через µTorrent/qBittorrent — в отдельную папку:

```text
D:/Users/Downloads/LibRusEks/
├── lib.rus.ec.inpx
├── lib.rus.ec-000001-010000.zip
├── ...
```
Узнай INFOHASH:

qBittorrent → ПКМ по торренту → «Copy info-hash»

µTorrent → вкладка «Общее» → Hash

2. Зарегистрируй торрент
```bash
docker compose exec app python -m scripts.register_torrent \
    --hash <INFOHASH_2> \
    --name "LibRusEks" \
    --magnet "<MAGNET_2>" \
    --save-path /data \
    --source-type inpx_fb2
```
Ожидаем:

```text
✅ Торрент зарегистрирован: id=2 hash=<...>
```
3. Обнови docker-compose.yml — добавь второй volume
Открой docker-compose.yml и в сервисе app.volumes добавь:

```yaml
volumes:
  - ${LIBRARY_PATH}:/data:ro
  - ${LIBRARY_2_PATH}:/data2:ro     # ← второй торрент
  - ./tmp_downloads:/app/tmp_downloads
  - ./logs:/app/logs
```
И в .env.docker:

```env
LIBRARY_2_PATH=D:/Users/Downloads/LibRusEks
```
4. Перезапусти app
```bash
docker compose --env-file .env.docker up -d --force-recreate app
```
5. Индексируй торрент
```bash
docker compose exec app python -m scripts.index_torrent --torrent-id 2
```
Внимание: save_path в БД будет /data, но файлы в /data2.

Обнови save_path:

```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "UPDATE torrents SET save_path = '/data2' WHERE id = 2;"
```
6. Загрузи книги второго торрента
```bash
docker compose exec app python -m scripts.load_books \
    --torrent-id 2 \
    --inpx /data2/lib.rus.ec.inpx
```
7. Индексируй ZIP-архивы второго торрента
```bash
docker compose exec app python -m scripts.index_archives --torrent-id 2
```
8. Проверь
```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT t.id, t.name, COUNT(b.id) AS books FROM torrents t LEFT JOIN books b ON b.torrent_id = t.id GROUP BY t.id, t.name;"
```
Ожидаем:

```text
 id |     name      | books
----+---------------+--------
  1 | Flibusta      | 699504
  2 | LibRusEks     | 500000
```
9. Проверь поиск
Поиск теперь ищет по обоим торрентам. Проверь через веб или бота:

```text
GET /api/search?q=Пушкин
```
Ожидаем: результаты из обоих торрентов (если книга есть в обоих — дубликаты).

Дедупликация — не реализована. Если это проблема — см. ниже.

10. Дедупликация (опционально)
Если один и тот же lib_id есть в двух торрентах, при поиске будут два результата.

Решение: фильтровать при поиске по приоритету торрента:

```sql
-- В search_books добавить:
ORDER BY 
    CASE torrent_id WHEN 1 THEN 0 ELSE 1 END,   -- приоритет торрента 1
    ts_rank(...) DESC
```
Или через DISTINCT ON (lib_id):

```sql
SELECT DISTINCT ON (b.lib_id) b.*
FROM books b
WHERE ...
ORDER BY b.lib_id, b.torrent_id;
```
Не реализовано. Обсудим отдельно.

### Удаление торрента
1. Удали из БД
```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "DELETE FROM torrents WHERE id = 2;"
```
Что произойдёт:

CASCADE удалит torrent_files, books, library_meta, archive_entries торрента

Внимание: операция необратима

2. Удали volume (если нужно)
Если торрент был в отдельной папке — удали из docker-compose.yml:

```yaml
volumes:
  - ${LIBRARY_PATH}:/data:ro
  # - ${LIBRARY_2_PATH}:/data2:ro   ← удалить
```
И LIBRARY_2_PATH из .env.docker.

Перезапусти:

```bash
docker compose --env-file .env.docker up -d --force-recreate app
```
3. Удали файлы с хоста (если нужно)
Вручную через проводник / rm -rf.

Инкрементальные обновления
Проблема: полная переиндексация .inpx занимает 5–15 минут, и все книги удаляются-вставляются заново (что меняет books.id).

Идея: обновлять только изменения — INSERT новых, UPDATE изменённых, MARK удалённых.

Не реализовано. Требует:

Сравнения .inpx версии

Парсинга диффов

Сложной логики UPSERT

Пока — используем --truncate (полная перезагрузка).

На практике: 5–15 минут раз в месяц — приемлемо.

Управление через SQL
Полезные запросы
Размер БД:

```sql
SELECT pg_size_pretty(pg_database_size('flibusta'));
```
Количество книг по торрентам:

```sql
SELECT 
    t.id, t.name, 
    COUNT(b.id) AS total,
    COUNT(CASE WHEN NOT b.is_deleted THEN 1 END) AS active
FROM torrents t
LEFT JOIN books b ON b.torrent_id = t.id
GROUP BY t.id, t.name;
```
Топ-10 авторов:

```sql
SELECT display_name, books_count
FROM authors
ORDER BY books_count DESC
LIMIT 10;
```
Дубликаты lib_id между торрентами:

```sql
SELECT lib_id, COUNT(DISTINCT torrent_id) AS copies
FROM books
GROUP BY lib_id
HAVING COUNT(DISTINCT torrent_id) > 1
LIMIT 20;
```
Размер каждой таблицы:

```sql
SELECT 
    relname AS table,
    pg_size_pretty(pg_total_relation_size(relid)) AS size
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```
Обновить save_path торрента:

```sql
UPDATE torrents SET save_path = '/data' WHERE id = 1;
```
Пометить все книги удалёнными:

```sql
UPDATE books SET is_deleted = true WHERE torrent_id = 1;
```
Восстановить из резервной копии:

```bash
docker exec -i flibusta_postgres psql -U flibusta -d flibusta < backup.sql
```
Резервное копирование
Что нужно бэкапить
| Данные | Где | Как |
|--------|-----|-----|
|PostgreSQL |	volume: postgres_data | pg_dump|
|Resume-данные торрентов | torrents.resume_data |	Входит в pg_dump|
ZIP-архивы	| /data на хосте	| Уже на хосте|
|.inpx	| /data на хосте	| Уже на хосте|
|.env / .env.docker	| Корень проекта	| Вручную (там токены!)|

Восстановление возможно из .inpx + .env — БД можно пересоздать.

Дамп PostgreSQL
```bash
docker exec -t flibusta_postgres pg_dump -U flibusta flibusta > backup_$(date +%Y%m%d).sql
```
Размер: ~200 МБ (сжатый).

С сжатием:

```bash
docker exec -t flibusta_postgres pg_dump -U flibusta flibusta | gzip > backup_$(date +%Y%m%d).sql.gz
```
Размер: ~80 МБ.

Восстановление
```bash
# Создать чистую БД
docker compose down -v
docker compose --env-file .env.docker up -d postgres
sleep 20

# Восстановить
docker exec -i flibusta_postgres psql -U flibusta -d flibusta < backup_20260915.sql
```
Автоматизация

Скрипт scripts/backup.sh:

```bash
#!/bin/bash
BACKUP_DIR="/d/Projects/books/backups"
mkdir -p "$BACKUP_DIR"

DATE=$(date +%Y%m%d_%H%M)
FILE="$BACKUP_DIR/flibusta_${DATE}.sql.gz"

docker exec -t flibusta_postgres pg_dump -U flibusta flibusta | gzip > "$FILE"

# Оставить только 7 последних
ls -t "$BACKUP_DIR"/flibusta_*.sql.gz | tail -n +8 | xargs -r rm

echo "Backup saved: $FILE"
```
Запуск (Windows Task Scheduler / cron):

```bash
# Ежедневно в 03:00
0 3 * * * /d/Projects/books/scripts/backup.sh
```
Частые сценарии
Проверить версию .inpx в БД
```bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "SELECT torrent_id, name, version, books_count, loaded_at FROM library_meta ORDER BY torrent_id;"
```
Переиндексировать только archive_entries

Если save_path изменился или ZIP-файлы переместились:

```bash
docker compose exec app python -m scripts.index_archives --torrent-id 1 --force
```
Переиндексировать только torrent_files (piece-диапазоны)

Если торрент пересоздан:

```bash
docker compose exec app python -m scripts.index_torrent --torrent-id 1 --force
```
Очистить весь кэш tmp_downloads
```bash
docker compose exec app python -c "
from app.services.temp_cleaner import enforce_cache_limit, cleanup_old_fb2
enforce_cache_limit(0)
cleanup_old_fb2(0)
"
```
Полный сброс и пересоздание
```bash
docker compose --env-file .env.docker down -v
docker compose --env-file .env.docker up -d
sleep 30

# Пересоздать всё с нуля
docker compose exec app python -m scripts.register_torrent \
    --hash <INFOHASH> --name "Flibusta" --magnet "<MAGNET>" --save-path /data
docker compose exec app python -m scripts.index_torrent --torrent-id 1
docker compose exec app python -m scripts.load_books --torrent-id 1 --inpx /data/flibusta_fb2_local.inpx
docker compose exec app python -m scripts.index_archives --torrent-id 1
```
Время: ~20 минут.

Скрипты проекта

| Скрипт	| Назначение |	Время |
|-----------|------------|--------|
|scripts/register_torrent.py	| Регистрация торрента в БД |	1 сек |
|scripts/index_torrent.py	| Метаданные торрента (piece-диапазоны)	| 1–3 мин |
|scripts/load_books.py	| Загрузка .inpx в БД	| 5–15 мин |
|scripts/index_archives.py	| Индексация ZIP-архивов	| 2–5 мин |
|scripts/init_test_db.py	| Создание схемы тестовой БД	| 5 сек |

Все скрипты запускаются через:

```bash
docker compose exec app python -m scripts.<name>
```
Все поддерживают --help.


| Документ | О чём |
|----------|-------|
| [SETUP.md](docs/SETUP.md) | Подробная инструкция по установке (Windows + Linux + Docker) |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Как устроено: БД, сервисы, потоки данных |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Типовые проблемы и их решения |
| [API.md](docs/API.md) | HTTP-эндпоинты веб-интерфейса |
| [BOT.md](docs/BOT.md) | Команды и сценарии Telegram-бота |
| [UPDATE.md](docs/UPDATE.md) | Обновление библиотеки, добавление торрентов |