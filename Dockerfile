# ============================================================
# TeamBot - Production Dockerfile (Alpine) с Alembic
# ============================================================

# ============ Установка зависимостей (builder) ============

FROM python:3.14-alpine AS builder

# Установка UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Установка системных зависимостей для сборки (Alpine)
RUN apk add --no-cache \
    gcc \
    g++ \
    libpq-dev \
    curl \
    gnupg \
    musl-dev \
    postgresql-dev \
    && rm -rf /var/cache/apk/*

# ============================================================
# ВНИМАНИЕ: ODBC Driver для Alpine сложнее
# Альтернатива: использовать pyodbc с unixODBC
# ============================================================
# Вариант 1: Установка unixODBC (для pyodbc)
RUN apk add --no-cache \
    unixodbc \
    unixodbc-dev \
    && rm -rf /var/cache/apk/*

# Вариант 2: Microsoft ODBC для Alpine (если нужен)
# Microsoft не предоставляет официальные пакеты для Alpine
# Используйте альтернативный образ или pyodbc с unixODBC

WORKDIR /build

# Копирование файлов зависимостей
COPY pyproject.toml uv.lock ./

# Создание виртуального окружения и установка зависимостей
# Добавлен alembic для миграций
RUN uv venv .venv && \
    . .venv/bin/activate && \
    uv pip install --no-cache-dir \
        aiogram \
        aiosqlite \
        alembic \
        asyncpg \
        bcrypt \
        fastapi \
        psycopg2-binary \
        pydantic-settings \
        pyodbc \
        python-decouple \
        python-dotenv \
        python-multipart \
        sqlalchemy \
        telethon \
        uvicorn \
        comtypes \
        cryptography \
        httpx

# ============ Финальный образ (Runtime) ============

FROM python:3.14-alpine

# Установка runtime зависимостей
RUN apk add --no-cache \
    libpq \
    unixodbc \
    curl \
    && rm -rf /var/cache/apk/*

# Копирование виртуального окружения из builder
COPY --from=builder /build/.venv /app/.venv

# Установка переменных окружения
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    LOG_DIR=/app/logs \
    AUTOMATION_TEMP_DIR=/app/temp/automation \
    ALEMBIC_CONFIG=/app/alembic.ini

WORKDIR /app

# Создание необходимых директорий
RUN mkdir -p /app/logs /app/temp/automation

# Копирование кода (последним слоем для максимального кеширования)
COPY app/ ./app/
COPY run.py ./
COPY run.sh ./

# Копирование Alembic файлов (если существуют)
COPY alembic.ini ./
COPY migrations/ ./migrations/

# Создание непривилегированного пользователя
RUN adduser -D -u 1000 botuser && \
    chown -R botuser:botuser /app

USER botuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ============================================================
# Точка входа с поддержкой миграций
# ============================================================

# Скрипт для запуска с миграциями
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["--mode", "full"]
