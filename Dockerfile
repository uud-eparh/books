# Используем Ubuntu 24.04 (LTS) — там libtorrent 2.0+ в apt
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Системные пакеты
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3-pip \
    # libtorrent (важно!)
    python3-libtorrent \
    # сборка
    build-essential \
    gcc \
    g++ \
    # Postgres-клиент (для pg_isready)
    postgresql-client \
    # Утилиты
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Создаём виртуальное окружение (чтобы использовать системный libtorrent)
RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Копируем зависимости
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./
COPY README.md ./

# Устанавливаем Python-зависимости (без libtorrent — он в системе)
RUN pip install --upgrade pip && \
    pip install -e "."

# Временные файлы (том будет смонтирован)
RUN mkdir -p /app/tmp_downloads /app/logs

# Порт веб-интерфейса
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Запуск (в lifespan стартует и бот, и torrent manager)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]