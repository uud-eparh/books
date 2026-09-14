# Flibusta Bot

Telegram-бот и веб-интерфейс для локальной библиотеки Flibusta в формате FB2.

## Требования

- Python 3.11+
- Docker и Docker Compose

## Быстрый старт

1. Скопировать `.env.example` в `.env` и заполнить значения.
2. Поднять PostgreSQL и pgAdmin:
   ```bash
   docker compose up -d