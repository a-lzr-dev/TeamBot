# 🤖 TeamBot

**TeamBot** — это корпоративный Telegram-бот для автоматизации бизнес-процессов и интеграции с системой Avanpost. Бот предоставляет сотрудникам единый интерфейс для работы с данными Avanpost, управления задачами, отправки уведомлений и автоматизации рутинных операций прямо из Telegram.

---

## 📋 Оглавление

1. [Основные возможности](#-основные-возможности)
2. [Архитектура проекта](#-архитектура-проекта)
3. [Технологический стек](#-технологический-стек)
4. [Структура проекта](#-структура-проекта)
5. [Установка и запуск](#-установка-и-запуск)
6. [Команды бота](#-команды-бота)
7. [API Эндпоинты](#-api-эндпоинты)
8. [Управление проектом](#-управление-проектом)
9. [Тестирование](#-тестирование)
10. [База данных и миграции](#-база-данных-и-миграции)
11. [Устранение неполадок](#-устранение-неполадок)
12. [Лицензия](#-лицензия)

---

## 🚀 Основные возможности

### 🤖 Интеграция с Avanpost
- Полноценная синхронизация данных (справочники, пользователи, заказы, чаты, транспорт) через хранимые процедуры
- Поддержка MSSQL для работы с внешней системой
- Гибкая настройка синхронизации (базовые данные, пользовательские данные, принудительная синхронизация)

### 🔐 Авторизация и безопасность
- Безопасная аутентификация по номеру телефона через отправку контакта в Telegram
- Проверка пользователя через хранимую процедуру Avanpost
- Поддержка шифрования конфиденциальных данных (напоминания, заявки)
- Ролевая модель: обычные пользователи и администраторы

### 📋 Динамическое меню действий
- Иерархическое меню, строящееся на основе прав пользователя из Avanpost
- Поддержка вложенных меню и конечных действий
- Локализация названий пунктов меню (поддержка языков)
- Гибкая навигация: возврат на предыдущий уровень, переход в главное меню

### ⏰ Управление задачами и напоминаниями
- Создание личных и групповых дел
- Гибкая настройка напоминаний: интервал повторения, максимальное количество, дата окончания
- Поддержка кодовых слов для быстрого доступа к делам
- Шифрование конфиденциальных данных дел
- Автоматическая отправка уведомлений в указанное время

### 📄 Автоматизация документооборота
- Конвертация документов DOC/DOCX в PDF с использованием нескольких движков:
  - `pywin32` (Windows, через Microsoft Word)
  - `comtypes` (Windows, альтернативный метод)
  - `LibreOffice` (кроссплатформенный, Linux/macOS)
- Создание и отслеживание заявок на автоматизацию
- Статистика конвертаций
- Автоматическая очистка временных файлов

### 📢 Массовые рассылки
- Отправка сообщений во все активные чаты с подтверждением
- Фильтрация по типам чатов и исключение указанных чатов
- Полная история рассылок с сохранением связей с отправленными сообщениями
- Отмена рассылки с удалением всех связанных сообщений из Telegram и БД

### 🚨 Централизованное логирование ошибок
- Автоматический перехват и логирование ошибок из всех компонентов
- Группировка схожих ошибок для уменьшения количества уведомлений
- Отправка уведомлений об ошибках в выделенный чат поддержки (с поддержкой топиков)
- Статусная модель ошибок: новые, в работе, решенные, переоткрытые, отклоненные
- Автоматическое решение ошибок с проверкой через хранимые процедуры Avanpost

### 🌐 REST API
- Полный набор эндпоинтов для управления ботом и интеграции с внешними системами
- Отправка сообщений (одиночных, массовых, во все чаты)
- Управление напоминаниями и заявками на автоматизацию
- Получение статистики по всем компонентам системы
- Аутентификация через API-ключ

### ⚡ Высокая производительность
- Полностью асинхронная архитектура на базе `asyncio`
- Оптимизированные запросы к базе данных через SQLAlchemy
- Кеширование данных синхронизации и результатов API-запросов
- Rate limiting для защиты от перегрузок

### 🐳 Контейнеризация
- Готовые Dockerfile для production и development
- Docker Compose для простого развертывания всех сервисов
- Поддержка внешней PostgreSQL и MSSQL

---

## 🏗️ Архитектура проекта

Проект построен на модульной архитектуре с четким разделением ответственности:

```text
┌─────────────────────────────────────────────────────────────┐
│                    ApplicationManager                       │
│         (Управление жизненным циклом приложения)            │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   DBManager   │    │   APIManager  │    │   BotManager  │
│  (База данных)│    │  (REST API)   │    │(Telegram Bot) │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  Repositories │    │   Routers     │    │   Handlers    │
│  (CRUD/БД)    │    │  (Эндпоинты)  │    │  (Команды)    │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
                ┌───────────────────────┐
                │   Services (Бизнес-   │
                │      логика)          │
                └───────────────────────┘
```

### Ключевые компоненты

| Компонент | Описание |
|-----------|----------|
| **`app/core`** | Ядро приложения. Содержит менеджер жизненного цикла (`ApplicationManager`), конвертеры данных, rate limiter и базовые сервисы. |
| **`app/api`** | Слой REST API на FastAPI. Обрабатывает HTTP-запросы, используя роутеры для разных сущностей. |
| **`app/bot`** | Слой Telegram бота на Aiogram и Telethon. Включает клиенты, обработчики, клавиатуры и менеджер. |
| **`app/db`** | Слой работы с базой данных. Содержит менеджер подключений (`DBManager`), репозитории и модели SQLAlchemy. |
| **`app/services`** | Бизнес-логика приложения. Отвечает за синхронизацию с Avanpost, обработку ошибок, напоминания и другие ключевые функции. |
| **`app/models`** | Определения SQLAlchemy моделей данных для основной БД и Avanpost. |
| **`app/middlewares`** | Промежуточные слои для обработки запросов (логирование, аутентификация, rate limiting). |
| **`app/utils`** | Вспомогательные утилиты (криптография, декораторы, работа с датой/временем). |
| **`scripts`** | Набор вспомогательных скриптов для управления проектом, инициализации БД, очистки кеша и т.д. |

---

## 🛠️ Технологический стек

| Компонент | Технология | Версия |
|-----------|------------|--------|
| **Язык** | Python | 3.14+ |
| **Telegram Bot API** | aiogram | 3.30+ |
| **Telegram User API** | telethon | 1.44+ |
| **Веб-фреймворк** | FastAPI | 0.141+ |
| **Основная БД** | PostgreSQL | 15+ |
| **Внешняя БД (Avanpost)** | MSSQL | 2019+ |
| **ORM** | SQLAlchemy | 2.0+ (асинхронный) |
| **Миграции** | Alembic | 1.19+ |
| **Контейнеризация** | Docker, Docker Compose | latest |
| **Логирование** | Python logging (с ротацией) | — |
| **Качество кода** | Ruff, Mypy, Pre-commit | — |
| **Управление проектом** | UV (опционально), make.py | — |
| **Шифрование** | cryptography | 50+ |
| **Тестирование** | pytest, pytest-asyncio, pytest-cov | — |

---

## 📁 Структура проекта

```
├── .dockerignore
├── .env.example                 # Пример конфигурации
├── .pre-commit-config.yaml      # Pre-commit хуки
├── docker-compose.yaml          # Основной файл для Docker
├── Dockerfile                   # Production-образ
├── Dockerfile.dev               # Development-образ
├── pyproject.toml               # Зависимости и настройки Ruff/Mypy
├── run.py                       # Точка входа в приложение
│
├── app/                         # Основной код приложения
│   ├── __init__.py
│   ├── config.py                # Конфигурация (Pydantic Settings)
│   ├── exceptions.py            # Кастомные исключения
│   ├── logger.py                # Настройка логирования
│   │
│   ├── api/                     # REST API
│   │   ├── manager.py           # APIManager
│   │   └── routers/             # Роутеры
│   │
│   ├── bot/                     # Telegram бот
│   │   ├── manager.py           # BotManager
│   │   ├── callbacks/           # Обработчики колбэков
│   │   ├── clients/             # Клиенты Telegram API
│   │   ├── handlers/            # Обработчики событий
│   │   ├── keyboards/           # Клавиатуры
│   │   └── services/            # Сервисы бота
│   │
│   ├── core/                    # Ядро приложения
│   │   ├── application.py       # ApplicationManager
│   │   ├── converters.py        # Конвертеры данных
│   │   └── rate_limiter.py      # Rate limiting
│   │
│   ├── db/                      # База данных
│   │   ├── manager.py           # DBManager
│   │   └── repositories/        # Репозитории
│   │
│   ├── dtos/                    # Data Transfer Objects
│   ├── locales/                 # Локализация
│   │   └── data/                # Файлы переводов (JSON)
│   ├── middlewares/             # Промежуточные слои
│   ├── models/                  # SQLAlchemy модели
│   ├── services/                # Бизнес-логика
│   └── utils/                   # Утилиты
│
├── docker/                      # Конфиги для Docker
│   └── nginx/
│
├── migrations/                  # Alembic миграции
│
└── scripts/                     # Вспомогательные скрипты
    ├── backup.py                # Резервное копирование БД
    ├── db_clean.py              # Очистка БД
    ├── init_project.py          # Полная инициализация проекта
    ├── make.py                  # Управление проектом
    ├── seed_data.py             # Генерация тестовых данных
    ├── setup_precommit.py       # Настройка pre-commit хуков
    └── ...
```

---

## 🚀 Установка и запуск

### Предварительные требования

- **Python**: 3.14 или выше
- **PostgreSQL**: 15 или выше
- **MSSQL**: 2019 или выше (для Avanpost)
- **Docker** и **Docker Compose** (рекомендуется)
- **Git**

### Настройка окружения

1.  **Клонируйте репозиторий:**
    ```bash
    git clone https://github.com/your-username/teambot.git
    cd teambot
    ```

2.  **Создайте файл `.env` из шаблона:**
    ```bash
    cp .env.example .env
    ```

3.  **Заполните `.env` необходимыми данными:**
    ```env
    # PostgreSQL (основная БД)
    DB_MAIN_NAME=team_bot
    DB_MAIN_USER=your_user
    DB_MAIN_PASSWORD=your_password
    DB_MAIN_HOST=localhost
    DB_MAIN_PORT=5432

    # MSSQL (Avanpost)
    DB_AVANPOST_NAME=avanpost
    DB_AVANPOST_USER=avanpost_user
    DB_AVANPOST_PASSWORD=avanpost_password
    DB_AVANPOST_HOST=localhost
    DB_AVANPOST_PORT=1433

    # Telegram
    BOT_TOKEN=your_bot_token_here
    BOT_ID=your_api_id_here
    BOT_HASH=your_api_hash_here
    BOT_USERNAME=your_bot_username

    # Администрирование
    ADMIN_IDS=[123456789, 987654321]

    # Поддержка
    SUPPORT_CHAT_ID=-1001234567890
    SUPPORT_CHAT_TOPIC_IDS={"TeamBot": 1, "Globus": 2, "Avanpost": 3}

    # Безопасность
    ENCRYPTION_SECRET=your_strong_encryption_secret_here

    # API
    API_HOST=0.0.0.0
    API_PORT=8000
    APP_ENV=production
    APP_DEBUG=false
    ```

### Запуск через Docker (рекомендуемый способ)

1.  **Соберите и запустите контейнеры:**
    ```bash
    docker-compose up -d
    ```

2.  **Выполните миграции базы данных:**
    ```bash
    docker-compose run --rm app-migrate
    ```
    > **Для интерактивной работы с миграциями** (например, создание новой миграции внутри контейнера):
    > ```bash
    > docker-compose --profile migration run --rm app-migrate-interactive revision --autogenerate -m "description"
    > ```

3.  **Инициализируйте проект (создание системных данных):**
    ```bash
    docker-compose run --rm app python scripts/init_project.py --force
    ```

4.  **Проверьте, что все работает:**
    ```bash
    curl http://localhost:8000/health
    ```

### Запуск в режиме разработки

1.  **Установите зависимости:**
    ```bash
    pip install -r requirements.txt
    # или с использованием UV
    uv pip install -r requirements.txt
    ```

2.  **Настройте Pre-commit хуки:**
    ```bash
    python scripts/setup_precommit.py
    ```

3.  **Инициализируйте базу данных:**
    ```bash
    python scripts/init_project.py --force
    ```

4.  **Запустите приложение:**
    ```bash
    python run.py --mode dev
    ```

Приложение будет доступно по адресу `http://localhost:8000`. Документация API: `http://localhost:8000/api/docs`.

---

## 🤖 Команды бота

### Основные команды (доступны всем)

| Команда | Описание |
|---------|----------|
| `/start` | Начать работу / Авторизация |
| `/help` | Помощь и список команд |
| `/id` | Показать свой ID и информацию о пользователе |

### Команды для авторизованных пользователей

| Команда | Описание |
|---------|----------|
| `/actions` | Меню действий (доступно после авторизации) |
| `/automation` | Меню автоматизации (конвертация, заявки) |
| `/stats` | Меню статистики |
| `/msg <id>` | Контекстное меню сообщения |
| `/logout` | Выйти из системы |

### Команды для администраторов

| Команда | Описание |
|---------|----------|
| `/admins` | Список администраторов |
| `/add_admin <id>` | Добавить администратора |
| `/remove_admin <id>` | Удалить администратора |
| `/users` | Список пользователей |
| `/bc` | Меню рассылки |
| `/sync` | Меню синхронизации |
| `/sync_base` | Синхронизация справочников |
| `/sync_user <id>` | Синхронизация пользователя |

---

## 🌐 API Эндпоинты

Документация API доступна после запуска приложения:
- **Swagger UI**: `http://localhost:8000/api/docs`
- **ReDoc**: `http://localhost:8000/api/redoc`

### Основные группы эндпоинтов

| Префикс | Описание |
|---------|----------|
| `/api/v1/admin/*` | Администрирование (пользователи, статистика) |
| `/api/v1/bot/msgs/*` | Управление сообщениями (отправка, удаление, время жизни) |
| `/api/v1/bot/sync/*` | Синхронизация чатов и участников |
| `/api/v1/avanpost/*` | Интеграция с Avanpost (проверка пользователей, меню) |
| `/api/v1/automation/*` | Заявки на автоматизацию |
| `/api/v1/broadcast/*` | Управление рассылками |
| `/api/v1/errors/*` | Управление ошибками |
| `/api/v1/reminders/*` | Управление напоминаниями |
| `/api/v1/stats/*` | Статистика системы |
| `/api/v1/sync/*` | Синхронизация данных с Avanpost |

### Примеры запросов

```bash
# Отправка сообщения
curl -X POST http://localhost:8000/api/v1/bot/msgs/send \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"chat_id": 123456789, "text": "Hello from API"}'

# Получение статистики
curl -X GET http://localhost:8000/api/v1/stats/full \
  -H "X-API-Key: your_api_key"

# Создание напоминания
curl -X POST http://localhost:8000/api/v1/reminders/ \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 123456789,
    "title": "Meeting at 3 PM",
    "remind_at": "2026-08-25T15:00:00",
    "category": "work"
  }'

# Проверка пользователя в Avanpost
curl -X POST http://localhost:8000/api/v1/avanpost/users/check \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+375291234567"}'

# Регистрация внешней ошибки
curl -X POST http://localhost:8000/api/v1/errors/external \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "error_code": "ERR_001",
    "error_message": "Database connection lost",
    "source_system": "Avanpost",
    "severity": "critical"
  }'
```

---

## 🛠️ Управление проектом

Для удобства управления проектом реализован скрипт `scripts/make.py`. Он группирует часто используемые команды.

```bash
# Показать все доступные команды
python scripts/make.py help

# ---------- Очистка ----------
python scripts/make.py clean          # Очистка кешей

# ---------- База данных ----------
python scripts/make.py init           # Инициализация БД с seed
python scripts/make.py sync           # Синхронизация Avanpost
python scripts/make.py seed           # Заполнение системных данных
python scripts/make.py reset          # Полный сброс БД

python scripts/make.py db-clean       # Очистка БД (интерактивно)
python scripts/make.py db-clean-show  # Показать статистику таблиц
python scripts/make.py db-clean-dry   # Показать что будет удалено (dry-run)

# ---------- Запуск ----------
python scripts/make.py dev            # Запуск в режиме разработки
python scripts/make.py full           # Полный запуск приложения

# ---------- Качество кода ----------
python scripts/make.py lint           # Запуск линтеров
python scripts/make.py format         # Форматирование кода
python scripts/make.py precommit      # Запуск pre-commit хуков
python scripts/make.py test           # Запуск тестов

# ---------- Другое ----------
python scripts/make.py setup          # Полная настройка проекта
```

---

## 🧪 Тестирование

Проект покрыт модульными, интеграционными и сквозными (E2E) тестами с использованием **pytest**. Тесты обеспечивают стабильность кода и позволяют быстро выявлять регрессии при внесении изменений.

### Структура тестов

```
tests/
├── conftest.py                    # Общие фикстуры для всех тестов
├── unit/                          # Модульные тесты (быстрые, изолированные)
│   ├── test_api/                  # Тесты API роутеров и эндпоинтов
│   ├── test_bot/                  # Тесты бота (клавиатуры, менеджер, обработчики)
│   ├── test_core/                 # Тесты ядра (конвертеры, rate limiter)
│   ├── test_db/                   # Тесты репозиториев БД
│   ├── test_integration/          # Интеграционные тесты (с БД)
│   ├── test_locales/              # Тесты локализации
│   ├── test_middleware/           # Тесты middleware
│   ├── test_models/               # Тесты моделей данных
│   ├── test_routers/              # Тесты API роутеров
│   ├── test_services/             # Тесты сервисов бизнес-логики
│   └── test_utils/                # Тесты утилит
```

### Команды для запуска тестов

```bash
# Запуск всех тестов
pytest

# Запуск только модульных тестов
pytest tests/unit/

# Запуск интеграционных тестов
pytest tests/unit/test_integration/

# Запуск с отчетом о покрытии
pytest --cov=app

# Запуск с подробным выводом
pytest -v

# Запуск конкретного файла с тестами
pytest tests/unit/test_bot/test_manager.py

# Запуск тестов по маркерам
pytest -m "unit"          # Только unit-тесты
pytest -m "integration"   # Только интеграционные
pytest -m "slow"          # Только медленные тесты
pytest -m "db"            # Только тесты с БД

# Запуск с максимальным количеством ошибок
pytest --maxfail=5

# Запуск в параллельном режиме (требуется pytest-xdist)
pytest -n auto
```

### Маркеры тестов

| Маркер | Описание |
|--------|----------|
| `@pytest.mark.unit` | Быстрые, изолированные unit-тесты |
| `@pytest.mark.integration` | Интеграционные тесты (требуют БД) |
| `@pytest.mark.e2e` | Сквозные тесты (полная система) |
| `@pytest.mark.slow` | Медленные тесты |
| `@pytest.mark.db` | Тесты, требующие подключения к БД |
| `@pytest.mark.api` | Тесты API эндпоинтов |
| `@pytest.mark.bot` | Тесты Telegram бота |
| `@pytest.mark.service` | Тесты сервисов |

### Покрытие кода

```bash
# Запуск с отчетом о покрытии в консоли
pytest --cov=app

# Запуск с HTML отчетом
pytest --cov=app --cov-report=html

# Открыть отчет в браузере
open htmlcov/index.html

# Запуск с XML отчетом (для CI/CD)
pytest --cov=app --cov-report=xml
```

### Настройки тестов

Конфигурация тестов находится в `pyproject.toml`:

```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
addopts = "-v --strict-markers --tb=short --maxfail=5"
asyncio_mode = "auto"

[tool.coverage.run]
source = ["app"]
branch = true
parallel = true
concurrency = ["thread", "gevent"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "pass",
    "if __name__ == .__main__.:",
]
show_missing = true
precision = 2
```

### Примеры тестов

**Тест репозитория пользователей:**

```python
@pytest.mark.asyncio
async def test_save_user_create(self, db_session: AsyncSession):
    user = await UserRepository.save_user(
        session=db_session,
        user_id=123456789,
        first_name="Test",
        last_name="User",
        username="test_user",
        is_bot=False,
        phone="+1234567890",
    )
    assert user.FID == 123456789
    assert user.FFirstName == "Test"
```

**Тест API эндпоинта:**

```python
def test_health_endpoint(self, api_client: TestClient):
    response = api_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
```

**Тест сервиса автоматизации:**

```python
@pytest.mark.asyncio
async def test_convert_doc_to_pdf_unsupported_format(self, service):
    result = await service.convert_doc_to_pdf(
        doc_content=b"test",
        filename="test.txt",
    )
    assert result["success"] is False
    assert "Неподдерживаемый формат" in result["error"]
```

### Фикстуры для тестов

В `tests/conftest.py` определены общие фикстуры:

| Фикстура | Описание |
|----------|----------|
| `db_session` | Асинхронная сессия БД для тестов |
| `api_client` | Тестовый клиент FastAPI |
| `temp_dir` | Временная директория для файлов |
| `sample_user_data` | Образец данных пользователя |
| `sample_chat_data` | Образец данных чата |
| `sample_message_data` | Образец данных сообщения |
| `sample_error_data` | Образец данных ошибки |

---

## 🗄️ База данных и миграции

### Управление миграциями через Alembic

```bash
# Создать новую миграцию
alembic revision --autogenerate -m "description"

# Применить все миграции
alembic upgrade head

# Откатить последнюю миграцию
alembic downgrade -1

# Показать статус миграций
alembic current
```

### Управление через скрипты

```bash
# Создать таблицы
python scripts/db_migrate.py --create

# Удалить все таблицы (осторожно!)
python scripts/db_migrate.py --drop

# Пересоздать таблицы
python scripts/db_migrate.py --reset

# Показать все таблицы
python scripts/db_migrate.py --show

# Инициализировать все БД
python scripts/db_migrate.py --init

# Заполнить системные данные Avanpost
python scripts/db_migrate.py --seed
```

### Очистка базы данных

```bash
# Интерактивная очистка
python scripts/db_clean.py

# Очистка только данных пользователей
python scripts/db_clean.py --users

# Полная очистка всех данных (структура сохраняется)
python scripts/db_clean.py --all-data --force

# Удаление всех таблиц (структура + данные)
python scripts/db_clean.py --drop-all --force

# Показать статистику таблиц
python scripts/db_clean.py --show

# Dry-run (показать что будет удалено)
python scripts/db_clean.py --all-data --dry-run
```

---

## 🐛 Устранение неполадок

### Частые проблемы и решения

| Проблема | Решение |
|----------|---------|
| **Бот не отвечает** | Проверьте `BOT_TOKEN` в `.env`. Убедитесь, что бот запущен: `docker-compose logs app` |
| **Ошибка подключения к БД** | Проверьте настройки `DB_MAIN_*` и `DB_AVANPOST_*` в `.env`. Убедитесь, что БД запущена. |
| **Ошибка миграций** | Выполните `docker-compose run --rm app-migrate` или `alembic upgrade head` |
| **Синхронизация Avanpost не работает** | Проверьте доступность MSSQL. Включите `AVANPOST_SYNC_REQUIRED=false` для тестирования. |
| **Не конвертируются DOC в PDF** | Проверьте наличие LibreOffice: `which soffice`. Для Windows убедитесь, что установлен Microsoft Word. |
| **Rate limit превышен** | Увеличьте `API_RATE_LIMIT` и `BOT_RATE_LIMIT` в `.env` или настройте `whitelist` для администраторов. |
| **Ошибки в логах не отправляются** | Проверьте `SUPPORT_CHAT_ID` и `SUPPORT_CHAT_TOPIC_IDS` в `.env`. Убедитесь, что бот добавлен в чат. |

### Логи

Логи хранятся в директории `logs/`:
- `app.log` — основные логи приложения
- `api.log` — логи API запросов
- `bot.log` — логи Telegram бота
- `db.log` — логи базы данных
- `admin.log` — административные логи
- `stat.log` — статистика синхронизации

### Отладка

```bash
# Просмотр логов в реальном времени (Docker)
docker-compose logs -f app

# Проверка статуса всех сервисов
docker-compose ps

# Проверка здоровья API
curl http://localhost:8000/health

# Проверка статуса бота
curl http://localhost:8000/api/v1/bot/msgs/status
```

---

## 📄 Лицензия

Этот проект является проприетарным и предназначен для внутреннего использования в компании. Все права защищены.

---

**TeamBot** — ваш надежный помощник в автоматизации бизнес-процессов через Telegram. 🚀
