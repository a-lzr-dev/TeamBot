# ============================================================
# TeamBot - Production Dockerfile
# ============================================================

# ============ Установка зависимостей (builder) ============

FROM python:3.14-slim AS builder

# Установка UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Установка системных зависимостей для сборки
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Настройка ODBC (только необходимые пакеты)
RUN curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && sed -i 's/deb \[arch=amd64,armhf,arm64\] https:\/\/packages.microsoft.com\/debian\/12\/prod bookworm main/deb [arch=amd64,armhf,arm64] signed-by=\/usr\/share\/keyrings\/microsoft-prod.gpg https:\/\/packages.microsoft.com\/debian\/12\/prod bookworm main/' /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Копирование файлов зависимостей
COPY pyproject.toml uv.lock ./

# Создание виртуального окружения и установка зависимостей
RUN uv venv .venv && \
    . .venv/bin/activate && \
    uv pip install --no-cache-dir \
        aiogram \
        aiosqlite \
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

FROM python:3.14-slim

# Копирование только ODBC-драйвера и системных зависимостей из builder
COPY --from=builder /usr/share/keyrings/microsoft-prod.gpg /usr/share/keyrings/microsoft-prod.gpg
COPY --from=builder /etc/apt/sources.list.d/mssql-release.list /etc/apt/sources.list.d/mssql-release.list
RUN apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Копирование виртуального окружения из builder
COPY --from=builder /build/.venv /app/.venv

# Установка переменных окружения
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    LOG_DIR=/app/logs \
    AUTOMATION_TEMP_DIR=/app/temp/automation

WORKDIR /app

# Создание необходимых директорий
RUN mkdir -p /app/logs /app/temp/automation

# Копирование кода (последним слоем для максимального кеширования)
COPY app/ ./app/
COPY run.py ./
COPY run.sh ./

# Создание непривилегированного пользователя
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app

USER botuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "run.py"]
CMD ["--mode", "full"]