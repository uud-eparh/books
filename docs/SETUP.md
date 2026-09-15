# Установка и запуск Book Hub

Подробная инструкция по развёртыванию проекта.

## 📋 Содержание

1. [Требования](#требования)
2. [Подготовка библиотеки](#подготовка-библиотеки)
3. [Установка Docker](#установка-docker)
4. [Настройка окружения](#настройка-окружения)
5. [Запуск](#запуск)
6. [Первичная инициализация БД](#первичная-инициализация-бд)
7. [Проверка работы](#проверка-работы)
8. [Обновление](#обновление)
9. [Остановка и удаление](#остановка-и-удаление)

---

## Требования

### Аппаратные

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| **CPU** | 2 ядра | 4+ ядра |
| **RAM** | 4 ГБ | 8+ ГБ |
| **Диск** | 10 ГБ (без библиотеки) | 50+ ГБ (с библиотекой) |
| **Интернет** | 10 Мбит/с | 100+ Мбит/с |

**Важно:** если планируешь **хранить ZIP-архивы локально** — нужно **~600 ГБ**. Если только **скачивать по запросу** — **10–50 ГБ**.

### Программные

- **Docker Desktop** — [Windows](https://docs.docker.com/desktop/install/windows-install/) / [macOS](https://docs.docker.com/desktop/install/mac-install/) / [Linux](https://docs.docker.com/engine/install/)
- **Git** — [git-scm.com](https://git-scm.com/downloads)
- **Python 3.11+** (только для локальной разработки и тестов)

### Данные

- **`.inpx`-файл** Флибусты (~40 МБ) — `flibusta_fb2_local.inpx`
- **Торрент** Флибусты (~568 ГБ) — magnet-ссылка
- **Telegram-бот** — токен от [@BotFather](https://t.me/BotFather)

---

## Подготовка библиотеки

### Где взять `.inpx`?

`.inpx` — это **каталог** Флибусты. Обычно он **лежит в торренте** вместе с ZIP-архивами.

**Если у тебя уже есть торрент** — `.inpx` **внутри** него (`flibusta_fb2_local.inpx`).

### Где взять торрент?

Ищи magnet-ссылку:
- `fb2.Flibusta.Net` — **основная раздача** (~568 ГБ)
- На трекерах: `booktracker.work`, `rutracker.org`

**Пример magnet:**
magnet:?xt=urn:btih:<INFOHASH>&dn=fb2.Flibusta.Net&tr=...

text

**Сохрани** `INFOHASH` (40 hex-символов) — понадобится.

### Структура файлов

После скачивания торрента папка **выглядит так:**
fb2.Flibusta.Net/
├── fb2-000024-030559.zip
├── fb2-030560-060423.zip
├── ...
├── f.fb2-875653-879581.zip
└── flibusta_fb2_local.inpx

text

**Путь к этой папке** пойдёт в `LIBRARY_PATH` (см. ниже).

---

## Установка Docker

### Windows

1. Скачай [Docker Desktop для Windows](https://docs.docker.com/desktop/install/windows-install/)
2. Установи
3. **Перезагрузи** компьютер
4. Запусти **Docker Desktop** → дождись иконки «зелёная» в трее

**Проверка:**

```bash
docker --version
docker compose version
Ожидаем:

text
Docker version 27.x.x
Docker Compose version v2.x.x
WSL2 (обязательно для Windows)
Docker Desktop использует WSL2. Проверь:

bash
wsl --status
Если WSL не установлен:

bash
wsl --install
Linux
bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
Настройка окружения
1. Клонируй репозиторий
bash
git clone <your-repo-url> book-hub
cd book-hub
2. Создай .env (для локальной разработки)
bash
cp .env.example .env
Открой .env:

env
# === PostgreSQL ===
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=flibusta
POSTGRES_PASSWORD=flibusta_secret
POSTGRES_DB=flibusta

# === Telegram ===
TELEGRAM_BOT_TOKEN=<ТОКЕН>
TELEGRAM_ALLOWED_USERS=<ТВОЙ_ID>
TELEGRAM_PROXY=socks5://127.0.0.1:9050   # локальный Tor

# === Пути (Windows-стиль) ===
INPX_PATH=D:/Users/Downloads/fb2.Flibusta.Net/flibusta_fb2_local.inpx
TORRENT_DATA_PATH=D:/Users/Downloads/fb2.Flibusta.Net
TEMP_DOWNLOAD_PATH=./tmp_downloads

# === Torrent ===
TORRENT_HASH=<INFOHASH>
TORRENT_MAGNET=<MAGNET>
3. Создай .env.docker (для Docker)
bash
cp .env.example .env.docker
Открой .env.docker:

env
# === PostgreSQL (внутри Docker-сети) ===
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=flibusta
POSTGRES_PASSWORD=flibusta_secret
POSTGRES_DB=flibusta

# === Telegram ===
TELEGRAM_BOT_TOKEN=<ТОКЕН>
TELEGRAM_ALLOWED_USERS=<ТВОЙ_ID>
TELEGRAM_PROXY=socks5://tor:9050   # Tor-контейнер

# === Пути (внутри контейнера) ===
INPX_PATH=/data/flibusta_fb2_local.inpx
TORRENT_DATA_PATH=/data
TEMP_DOWNLOAD_PATH=/app/tmp_downloads

# === Docker volumes ===
LIBRARY_PATH=D:/Users/Downloads/fb2.Flibusta.Net   # ← путь на ХОСТЕ
Где взять Telegram-токен и ID
Токен:

Открой @BotFather

/newbot → придумай имя

Скопируй токен (вида 123456:ABC-DEF...)

Свой ID:

Открой @userinfobot

/start → получишь ID (число)

Вставь в TELEGRAM_ALLOWED_USERS

Запуск
1. Собери образы
bash
docker compose --env-file .env.docker build
Первая сборка — 5–15 минут. Скачается Ubuntu, Python, libtorrent, Alpine.

2. Запусти контейнеры
bash
docker compose --env-file .env.docker up -d
3. Проверь статус
bash
docker compose --env-file .env.docker ps
Ожидаем:

text
NAME                STATUS
flibusta_postgres   Up (healthy)
flibusta_tor        Up
flibusta_app        Up (healthy)
4. Проверь логи
bash
docker compose logs -f app
Ожидаем:

text
🤖 Telegram bot started
Bot started: @your_bot_name (id=...)
INFO aiogram.dispatcher: Start polling
Если бот не запустился — смотри TROUBLESHOOTING.md.

Первичная инициализация БД
Один раз — загрузить данные из .inpx в PostgreSQL.

1. Зарегистрируй торрент
bash
docker compose exec app python -m scripts.register_torrent \
    --hash <INFOHASH> \
    --name "fb2.Flibusta.Net" \
    --magnet "<MAGNET>" \
    --save-path /data
Ожидаем:

text
✅ Торрент зарегистрирован: id=1
2. Индексируй торрент
bash
docker compose exec app python -m scripts.index_torrent --torrent-id 1
Займёт 1–3 минуты. Получим 221 файл с byte_offset и piece_start/end.

Ожидаем:

text
✅ Сохранено: 221 файлов, resume_data=728273 bytes
3. Загрузи книги
bash
docker compose exec app python -m scripts.load_books \
    --torrent-id 1 \
    --inpx /data/flibusta_fb2_local.inpx
Займёт 5–15 минут. Загрузим 699 504 книги.

4. Индексируй ZIP-архивы
bash
docker compose exec app python -m scripts.index_archives --torrent-id 1
Займёт 2–5 минут. Получим 699 560 записей в archive_entries.

5. Обнови save_path
bash
docker exec -it flibusta_postgres psql -U flibusta -d flibusta -c \
    "UPDATE torrents SET save_path = '/data' WHERE id = 1;"
docker compose restart app
Проверка работы
Веб-интерфейс
Открой http://localhost:8000

Попробуй:

Введи Романович → нажми «Найти»

Кликни на книгу → карточка

Добавь 3 книги в корзину → «Скачать ZIP»

Telegram-бот
Открой @your_bot_name → /start

Попробуй:

Напиши Ремарк → выбери книгу → «⬇ Скачать FB2»

Проверка скачивания
Если книга есть локально (ZIP-архив на диске) — скачается за 50–150 мс.
Если нет — скачается через торрент (2–30 секунд).

Обновление
Обновление кода
bash
git pull
docker compose --env-file .env.docker build app
docker compose --env-file .env.docker up -d --force-recreate app
Обновление каталога .inpx
См. UPDATE.md.

Остановка и удаление
Остановить (сохранить данные)
bash
docker compose --env-file .env.docker down
Остановить и удалить БД
bash
docker compose --env-file .env.docker down -v
Внимание: -v удаляет volume postgres_data — все данные из БД пропадут. Их придётся загружать заново из .inpx.

Полное удаление образов
bash
docker compose --env-file .env.docker down -v --rmi all
Что дальше?
ARCHITECTURE.md — как устроено

BOT.md — сценарии Telegram-бота

API.md — HTTP-эндпоинты

TROUBLESHOOTING.md — если что-то не работает

UPDATE.md — обновление библиотеки

text

---

## 🚦 Что делаешь

### 1. Удали `build.log`

```bash
rm build.log
И добавь в .gitignore:

text
build.log