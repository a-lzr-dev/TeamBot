# ============================================================
# TeamBot — Production Dockerfile
# ============================================================
# Multi-stage build:
#   1. builder — ставит зависимости из pyproject.toml + uv.lock
#   2. runtime — копирует venv, ставит ODBC Driver + LibreOffice
#
# Сборка:
#   docker build -t teambot:latest .
#   docker build -t teambot:latest --build-arg PYTHON_VERSION=3.12 .
#
# Сборка с гарантией свежего кода (инвалидирует только COPY-слои ниже):
#   docker build --build-arg CACHEBUST=$(Get-Date -Format "yyyyMMddHHmmss") -t team-bot:latest .
#
# Запуск:
#   docker run --env-file .env -p 8000:8000 teambot:latest
# ============================================================

ARG PYTHON_VERSION=3.12

# ============================================================
# STAGE 1: BUILDER — установка Python-зависимостей
# ============================================================
FROM python:${PYTHON_VERSION}-slim AS builder

# UV для быстрой установки зависимостей
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Системные зависимости для сборки пакетов с C-расширениями:
#   - gcc, g++, libpq-dev — psycopg2-binary
#   - unixodbc-dev        — pyodbc / aioodbc
#   - curl, gnupg         — на случай будущих нужд
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libpq-dev \
        unixodbc-dev \
        curl \
        gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 1. Копируем только манифесты — это кеширует слой с зависимостями,
#    если код изменился, но pyproject.toml/uv.lock — нет.
COPY pyproject.toml uv.lock ./

# 2. Устанавливаем ТОЛЬКО production-зависимости из lock-файла.
#    --no-dev      — не тащить pytest/mypy/ruff/grpcio-tools
#    --frozen      — не обновлять lock, использовать как есть
#    --no-install-project — не устанавливать сам teambot (он не пакет)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-install-project

# 3. Генерируем protobuf/gRPC-код из model.proto.
#    grpcio-tools устанавливаем временно, только в builder.
#    Если app/model_pb2*.py уже в репозитории — этот шаг можно убрать.
COPY proto/model.proto ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv grpcio-tools && \
    mkdir -p /build/generated && \
    /app/.venv/bin/python -m grpc_tools.protoc \
        -I. \
        --python_out=/build/generated \
        --grpc_python_out=/build/generated \
        model.proto

# ============================================================
# STAGE 2: RUNTIME — минимальный образ для запуска
# ============================================================
FROM python:${PYTHON_VERSION}-slim AS runtime

# ---- Runtime-зависимости ----
#   libpq5            — psycopg2 / asyncpg (клиентская библиотека)
#   unixodbc          — pyodbc / aioodbc
#   curl              — healthcheck
#   gnupg, apt-transport-https, ca-certificates — для подключения репо Microsoft
#   libreoffice       — конвертация DOC/DOCX → PDF (см. automation_service.py)
#   fonts-dejavu      — корректный рендер кириллицы в PDF
#   tini              — корректная обработка сигналов (PID 1)
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        unixodbc \
        curl \
        gnupg \
        apt-transport-https \
        ca-certificates \
        tini \
        libreoffice \
        libreoffice-writer \
        fonts-dejavu \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ---- Копирование venv из builder ----
COPY --from=builder /app/.venv /app/.venv

# ---- Копирование сгенерированных protobuf/gRPC-модулей ----
COPY --from=builder /build/generated/model_pb2.py /app/app/model_pb2.py
COPY --from=builder /build/generated/model_pb2_grpc.py /app/app/model_pb2_grpc.py

# ---- Переменные окружения ----
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/app/.venv/bin:$PATH" \
    LOG_DIR=/app/logs \
    AUTOMATION_TEMP_DIR=/app/temp/automation \
    ALEMBIC_CONFIG=/app/alembic.ini \
    TZ=Europe/Minsk

WORKDIR /app

# ---- Создание директорий и пользователя ДО COPY кода ----
RUN mkdir -p /app/logs /app/temp/automation && \
    groupadd --gid 1000 botuser && \
    useradd --uid 1000 --gid botuser --create-home --shell /bin/bash botuser && \
    chown -R botuser:botuser /app

# ---- Копирование кода приложения ----
# ARG CACHEBUST инвалидирует только COPY-слои ниже (app/, run.py и т.д.),
# не трогая apt-get / venv / COPY --from=builder. Собирать с:
#   docker build --build-arg CACHEBUST=$(Get-Date -Format "yyyyMMddHHmmss") -t team-bot:latest .
# Значение по умолчанию 1 — чтобы `docker build .` без аргумента не падал.
ARG CACHEBUST=1
# Docker инвалидирует кеш только если ARG реально используется в RUN/COPY.
# Этот RUN «пустой», но он заставляет BuildKit сбросить кеш для всех слоёв ниже.
RUN echo "CACHEBUST=$CACHEBUST" > /dev/null

COPY --chown=botuser:botuser app/ ./app/
COPY --chown=botuser:botuser run.py ./
COPY --chown=botuser:botuser run.sh ./
COPY --chown=botuser:botuser alembic.ini ./
COPY --chown=botuser:botuser migrations/ ./migrations/

# ---- Точка входа с поддержкой миграций ----
COPY --chmod=0755 docker-entrypoint.sh /docker-entrypoint.sh

# ---- Healthcheck ----
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# ---- Запуск от непривилегированного пользователя ----
USER botuser

# tini — корректная обработка SIGTERM/SIGINT, важно для graceful shutdown
ENTRYPOINT ["/usr/bin/tini", "--", "/docker-entrypoint.sh"]
CMD ["--mode", "full"]
