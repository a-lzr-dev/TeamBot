import ast
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ============ ОСНОВНАЯ БД ============

    # Основная БД (для работы текущего приложения)
    DB_MAIN_NAME: str = "team_bot"
    DB_MAIN_USER: str = "user"
    DB_MAIN_PASSWORD: str = "password"
    DB_MAIN_HOST: str = "localhost"
    DB_MAIN_PORT: str = "5432"
    DB_MAIN_URL: str = (
        f"postgresql+asyncpg://{DB_MAIN_USER}:{DB_MAIN_PASSWORD}@{DB_MAIN_HOST}:{DB_MAIN_PORT}/{DB_MAIN_NAME}"
    )
    DB_MAIN_ECHO: bool = False
    DB_MAIN_POOL_SIZE: int = 10
    DB_MAIN_MAX_OVERFLOW: int = 20

    # Вторичная БД (для коммуникации с внешней системой)
    DB_AVANPOST_NAME: str = "avanpost"
    DB_AVANPOST_USER: str = "user"
    DB_AVANPOST_PASSWORD: str = "password"
    DB_AVANPOST_HOST: str = "localhost"
    DB_AVANPOST_PORT: str = "5432"
    DB_AVANPOST_URL: str = f"mssql+aioodbc://{DB_AVANPOST_USER}:{DB_AVANPOST_PASSWORD}@{DB_AVANPOST_HOST}:{DB_AVANPOST_PORT}/{DB_AVANPOST_NAME}?driver=ODBC+Driver+17+for+SQL+Server"
    DB_AVANPOST_ECHO: bool = False
    DB_AVANPOST_POOL_SIZE: int = 5
    DB_AVANPOST_MAX_OVERFLOW: int = 10

    # ============ AVANPOST SYNC ============

    # Автоматические действия при старте приложения
    AVANPOST_AUTO_ADD_USERS_ON_START: list[int] = Field(default_factory=lambda: [])
    AVANPOST_AUTO_SYNC_ON_START: bool = True

    # Принудительная полная синхронизация (игнорировать кеш)
    AVANPOST_SYNC_FORCE: bool = False

    # Режим синхронизации (True - фоновая, False - синхронная)
    AVANPOST_SYNC_ASYNC: bool = True

    # Синхронизация пользовательских данных
    AVANPOST_SYNC_USERS: bool = False

    # Требовать успешную синхронизацию для старта приложения
    AVANPOST_SYNC_REQUIRED: bool = False

    # Таймаут синхронизации в секундах (0 - без ограничения)
    AVANPOST_SYNC_TIMEOUT: int = 300

    # Размер чанка для синхронизации (количество типов данных за один запрос)
    AVANPOST_SYNC_CHUNK_SIZE: int = 10

    # ============ TELEGRAM ============

    # Telegram Bot
    BOT_TOKEN: str = ""
    BOT_ID: int = 0
    BOT_HASH: str = ""
    BOT_SESSION_NAME: str = "bot_session"
    BOT_USERNAME: str = ""

    # Тип аккаунта: "bot" или "user"
    TELEGRAM_ACCOUNT_TYPE: str = "bot"

    # Для user-аккаунта (если TELEGRAM_ACCOUNT_TYPE = "user")
    USER_PHONE: str = "+375336391519"
    USER_SESSION_NAME: str = "user_session"

    # ============ API ============

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Режим работы
    APP_ENV: str = "production"
    APP_DEBUG: bool = False
    API_RELOAD: bool = False
    API_WORKERS: int = 1

    # ============ ЛОГИРОВАНИЕ ============

    # Логирование
    LOG_LEVEL: str = "DEBUG"
    LOG_DIR: str = "../logs"
    LOG_MAX_BYTES: int = 10_000_000
    LOG_BACKUP_COUNT: int = 5

    # ============ НАСТРОЙКИ БОТА ============

    # Настройки бота
    ADMIN_IDS: list[int] = Field(default_factory=lambda: [1039799368])
    SYNC_INTERVAL: int = 300
    MAX_MESSAGE_LENGTH: int = 4096

    # ============ НАСТРОЙКИ TELETHON ============

    # Настройки Telethon
    TELEGRAM_API_RETRY: int = 3
    TELEGRAM_RECONNECT_DELAY: int = 5
    TELEGRAM_CATCH_UP_ON_START: bool = True
    TELEGRAM_SYNC_CHATS_ON_START: bool = True

    # ============ RATE LIMITING ============

    # Rate Limiting
    API_RATE_LIMIT: int = 100
    API_RATE_PERIOD: int = 60
    BOT_RATE_LIMIT: int = 10
    BOT_COMMAND_LIMIT: int = 5
    BOT_RATE_PERIOD: int = 60
    BOT_COMMAND_PERIOD: int = 10

    # ============ ШИФРОВАНИЕ ============

    # Шифрование
    ENCRYPTION_SECRET: str = Field(default=secrets.token_urlsafe(32), description="Секретный ключ для шифрования")

    # ============ НАСТРОЙКИ УВЕДОМЛЕНИЙ ============

    # Настройки уведомлений по умолчанию
    DEFAULT_NOTIFICATION_LEVEL: str = "error"
    DEFAULT_GROUPING_WINDOW: int = 60
    DEFAULT_AUTO_REPORT_INTERVAL: int = 60
    DEFAULT_WORK_HOURS_START: int = 9
    DEFAULT_WORK_HOURS_END: int = 18

    # Настройки ошибок
    ERROR_GROUPING_ENABLED: bool = True
    ERROR_GROUPING_WINDOW_MINUTES: int = 60
    ERROR_MAX_OCCURRENCES_BEFORE_SILENCE: int = 10

    # ============ НАСТРОЙКИ НАПОМИНАНИЙ ============

    # Настройки напоминаний
    REMINDER_MAX_PER_USER: int = 100
    REMINDER_DEFAULT_INTERVAL: int = 0
    REMINDER_MAX_REMIND_COUNT: int = 10
    REMINDER_CHECK_INTERVAL: int = 60
    REMINDER_BATCH_SIZE: int = 100

    # ============ НАСТРОЙКИ ЛОГОВ ОШИБОК ============

    # ID чата, в котором находятся топики
    SUPPORT_CHAT_ID: int = Field(default=0, description="ID чата для отправки уведомлений об ошибках")

    # Список топиков для разных источников ошибок
    SUPPORT_CHAT_TOPIC_IDS: dict[str, int] = Field(
        default_factory=dict, description="Маппинг источников ошибок на ID топиков в Telegram"
    )

    # Минимальный интервал между уведомлениями об одинаковых ошибках
    LOG_ERROR_NOTIFICATION_INTERVAL: int = 60

    # Включить/выключить автоматическое логирование ошибок из логов
    LOG_ERROR_AUTO_CAPTURE: bool = True

    # Максимальная длина сохраняемого сообщения об ошибке
    LOG_ERROR_MAX_MESSAGE_LENGTH: int = 500

    # Максимальная длина сохраняемого traceback
    LOG_ERROR_MAX_TRACEBACK_LENGTH: int = 1000

    # Группировать ли ошибки по хешу
    LOG_ERROR_GROUPING_ENABLED: bool = True

    # Очищать ли кеш ошибок при старте
    LOG_ERROR_CLEAR_CACHE_ON_START: bool = True

    # Время жизни сообщений об ошибках в секундах
    LOG_ERROR_MESSAGE_LIFETIME_SECONDS: int = 604800  # 7 дней в секундах

    # ============ НАСТРОЙКИ АВТОМАТИЗАЦИИ ============

    # Метод конвертации DOC в PDF: pywin32, comtypes, libreoffice, auto
    AUTOMATION_CONVERSION_METHOD: str = "auto"

    # Максимальный размер файла для конвертации (в байтах)
    AUTOMATION_MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50 MB

    # Директория для временных файлов
    AUTOMATION_TEMP_DIR: str = "./temp/automation"

    # Количество попыток при конвертации
    AUTOMATION_RETRY_COUNT: int = 3

    # Задержка между попытками (в секундах)
    AUTOMATION_RETRY_DELAY: int = 2

    # Время жизни временных файлов (в секундах)
    AUTOMATION_CLEANUP_AFTER: int = 3600  # 1 час

    # Разрешенные форматы файлов для конвертации
    AUTOMATION_ALLOWED_EXTENSIONS: list[str] = Field(default_factory=lambda: [".doc", ".docx"])

    # Максимальное количество заявок на пользователя
    AUTOMATION_MAX_REQUESTS_PER_USER: int = 50

    # Требуется ли подтверждение администратора для заявок
    AUTOMATION_REQUIRE_ADMIN_APPROVAL: bool = True

    # Каналы для уведомлений о заявках (переопределяет SUPPORT_CHAT_ID)
    AUTOMATION_NOTIFICATION_CHAT_IDS: list[int] = Field(default_factory=list)

    # Включить/выключить автоматическую очистку временных файлов
    AUTOMATION_AUTO_CLEANUP: bool = True

    # Время ожидания конвертации (в секундах)
    AUTOMATION_CONVERSION_TIMEOUT: int = 60

    # ============ НАСТРОЙКИ ВРЕМЕНИ ЖИЗНИ СООБЩЕНИЙ ============

    # --- Настройки времени жизни сообщений ---

    MESSAGE_LIFETIME_CHECK_INTERVAL: int = 60  # Интервал проверки истекших сообщений (сек) = 1 мин
    MESSAGE_LIFETIME_BATCH_SIZE: int = 1000  # Максимум сообщений за одну проверку
    MESSAGE_LIFETIME_DEFAULT_SECONDS: int = 300  # Время жизни сообщений по умолчанию (сек) = 5 мин

    # --- Настройки синхронизации ---

    SYNC_CACHE_TTL_SECONDS: int = 60  # Время жизни кеша участников чата (сек)

    # --- Настройки ошибок ---

    ERROR_GROUP_CACHE_TTL_SECONDS: int = 300  # Время жизни кеша группировки ошибок (сек)

    # --- Настройки логирования ---

    LOG_QUEUE_MAX_SIZE: int = 1000  # Максимальный размер очереди логов
    LOG_WORKER_TIMEOUT: float = 0.3  # Таймаут ожидания записи в очереди

    # --- Настройки сообщений бота ---

    BOT_MESSAGE_LIFETIME_SECONDS: int = 300  # Время жизни сообщений меню бота (сек)

    # --- Настройки клавиатур ---

    KEYBOARD_BUTTONS_PER_ROW: int = 3  # Количество кнопок в ряду

    # --- Настройки аутентификации ---

    AUTH_CACHE_TTL_SECONDS: int = 3600  # Время жизни кеша авторизации (сек)

    # --- Настройки автоматизации (дополнительные) ---

    AUTOMATION_STATS_ENABLED: bool = True  # Включить сбор статистики конвертаций
    AUTOMATION_STATS_MAX_ENTRIES: int = 1000  # Максимум записей в статистике

    # --- Настройки сети ---

    HTTP_TIMEOUT_KEEP_ALIVE: int = 30  # Таймаут keep-alive для HTTP
    TELEGRAM_POLLING_TIMEOUT: int = 30  # Таймаут polling Telegram
    TELEGRAM_RETRY_DELAY: int = 5  # Задержка перед повторным подключением (сек)
    TELEGRAM_MAX_RETRIES: int = 5  # Максимум попыток подключения

    # --- Настройки API ---

    API_DEFAULT_PAGE_SIZE: int = 50  # Размер страницы по умолчанию
    API_STATS_DAYS: int = 7  # Период статистики в днях

    # ============ ВАЛИДАТОРЫ ============

    @field_validator("ADMIN_IDS", "AUTOMATION_NOTIFICATION_CHAT_IDS", mode="before")
    @classmethod
    def parse_list_field(cls, v: str | list[int] | None) -> list[int]:
        """Парсинг списков из строки в список"""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                # Пробуем распарсить как JSON список
                if v.startswith("[") and v.endswith("]"):
                    result = ast.literal_eval(v)
                    if isinstance(result, list):
                        parsed_result: list[int] = [int(x) for x in result]
                        return parsed_result
                # Если через запятую
                elif "," in v:
                    parts = v.split(",")
                    result_list: list[int] = []
                    for part in parts:
                        part = part.strip()
                        if part:
                            try:
                                result_list.append(int(part))
                            except ValueError:
                                continue
                    return result_list
                # Если просто число
                try:
                    return [int(v)]
                except ValueError:
                    return []
            except (ValueError, SyntaxError):
                return []
        return []

    @field_validator("AVANPOST_AUTO_ADD_USERS_ON_START", mode="before")
    @classmethod
    def parse_avanpost_users_list(cls, v: str | list[int] | None) -> list[int]:
        """Парсинг списка пользователей Avanpost из строки в список"""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                if v.startswith("[") and v.endswith("]"):
                    result: Any = ast.literal_eval(v)
                    if isinstance(result, list):
                        return [int(x) for x in result if isinstance(x, int | str)]
                elif "," in v:
                    parts = v.split(",")
                    result = []
                    for part in parts:
                        part = part.strip()
                        if part:
                            try:
                                result.append(int(part))
                            except ValueError:
                                continue
                    return result  # type: ignore[no-any-return]
            except (ValueError, SyntaxError):
                return []
        return []

    @field_validator("SUPPORT_CHAT_TOPIC_IDS", mode="before")
    @classmethod
    def parse_support_chat_topic_ids(cls, v: str | dict | None) -> dict[str, int]:
        """Парсинг SUPPORT_CHAT_TOPIC_IDS из строки в словарь"""
        if v is None:
            return {}
        if isinstance(v, dict):
            return {str(k): int(v) for k, v in v.items()}
        if isinstance(v, str):
            try:
                # Если словарь
                if v.startswith("{") and v.endswith("}"):
                    result = ast.literal_eval(v)
                    if isinstance(result, dict):
                        return {str(k): int(v) for k, v in result.items()}
                # Если через запятую (ключ:значение, ключ:значение)
                elif "," in v and ":" in v:
                    parts = v.split(",")
                    parsed_dict: dict[str, int] = {}
                    for part in parts:
                        if ":" in part:
                            key, value = part.split(":", 1)
                            key = key.strip().strip('"').strip("'")
                            value = value.strip()
                            try:
                                parsed_dict[key] = int(value)
                            except ValueError:
                                continue
                    return parsed_dict
            except (ValueError, SyntaxError) as e:
                raise ValueError(f"Неверный формат SUPPORT_CHAT_TOPIC_IDS: {e}") from e
        return {}

    @field_validator("AUTOMATION_ALLOWED_EXTENSIONS", mode="before")
    @classmethod
    def parse_extensions_list(cls, v: str | list[str] | None) -> list[str]:
        """Парсинг списка расширений"""
        if v is None:
            return [".doc", ".docx"]
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                if v.startswith("[") and v.endswith("]"):
                    result = ast.literal_eval(v)
                    if isinstance(result, list):
                        return [str(x).strip().lower() for x in result]
                elif "," in v:
                    return [x.strip().lower() for x in v.split(",") if x.strip()]
                else:
                    return [v.strip().lower()]
            except (ValueError, SyntaxError):
                return [".doc", ".docx"]
        # Эта ветка никогда не должна достигаться, но mypy требует возврата
        return [".doc", ".docx"]  # pragma: no cover

    @field_validator("AUTOMATION_CONVERSION_METHOD")
    @classmethod
    def validate_conversion_method(cls, v: str) -> str:
        """Валидация метода конвертации"""
        valid_methods = ["pywin32", "comtypes", "libreoffice", "auto"]
        if v.lower() not in valid_methods:
            raise ValueError(f"Invalid conversion method: {v}. Must be one of: {', '.join(valid_methods)}")
        return v.lower()

    @field_validator("AUTOMATION_MAX_FILE_SIZE")
    @classmethod
    def validate_max_file_size(cls, v: int) -> int:
        """Валидация максимального размера файла"""
        if v < 1024 * 1024:  # Меньше 1 MB
            raise ValueError("AUTOMATION_MAX_FILE_SIZE must be at least 1 MB")
        if v > 500 * 1024 * 1024:  # Больше 500 MB
            raise ValueError("AUTOMATION_MAX_FILE_SIZE must not exceed 500 MB")
        return v

    @field_validator("AUTOMATION_CONVERSION_TIMEOUT")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Валидация таймаута конвертации"""
        if v < 5:
            raise ValueError("AUTOMATION_CONVERSION_TIMEOUT must be at least 5 seconds")
        if v > 300:
            raise ValueError("AUTOMATION_CONVERSION_TIMEOUT must not exceed 300 seconds")
        return v

    @field_validator("MESSAGE_LIFETIME_DEFAULT_SECONDS")
    @classmethod
    def validate_message_lifetime(cls, v: int) -> int:
        """Валидация времени жизни сообщений"""
        if v < 10:
            raise ValueError("MESSAGE_LIFETIME_DEFAULT_SECONDS must be at least 10 seconds")
        if v > 86400:  # 24 часа
            raise ValueError("MESSAGE_LIFETIME_DEFAULT_SECONDS must not exceed 24 hours (86400 seconds)")
        return v

    @field_validator("LOG_QUEUE_MAX_SIZE")
    @classmethod
    def validate_queue_size(cls, v: int) -> int:
        """Валидация размера очереди логов"""
        if v < 10:
            raise ValueError("LOG_QUEUE_MAX_SIZE must be at least 10")
        if v > 10000:
            raise ValueError("LOG_QUEUE_MAX_SIZE must not exceed 10000")
        return v

    @field_validator("API_DEFAULT_PAGE_SIZE")
    @classmethod
    def validate_page_size(cls, v: int) -> int:
        """Валидация размера страницы API"""
        if v < 1:
            raise ValueError("API_DEFAULT_PAGE_SIZE must be at least 1")
        if v > 1000:
            raise ValueError("API_DEFAULT_PAGE_SIZE must not exceed 1000")
        return v

    @field_validator("TELEGRAM_MAX_RETRIES")
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        """Валидация максимального количества попыток"""
        if v < 1:
            raise ValueError("TELEGRAM_MAX_RETRIES must be at least 1")
        if v > 20:
            raise ValueError("TELEGRAM_MAX_RETRIES must not exceed 20")
        return v

    @field_validator("AVANPOST_SYNC_CHUNK_SIZE")
    @classmethod
    def validate_sync_chunk_size(cls, v: int) -> int:
        """Валидация размера чанка синхронизации"""
        if v < 1:
            raise ValueError("AVANPOST_SYNC_CHUNK_SIZE must be at least 1")
        if v > 50:
            raise ValueError("AVANPOST_SYNC_CHUNK_SIZE must not exceed 50")
        return v

    @field_validator("AVANPOST_SYNC_TIMEOUT")
    @classmethod
    def validate_sync_timeout(cls, v: int) -> int:
        """Валидация таймаута синхронизации"""
        if v < 0:
            raise ValueError("AVANPOST_SYNC_TIMEOUT must be >= 0")
        return v

    # ============ СВОЙСТВА ============

    @property
    def is_development(self) -> bool:
        return self.LOG_LEVEL.lower() == "debug"

    @property
    def is_bot_account(self) -> bool:
        return self.TELEGRAM_ACCOUNT_TYPE.lower() == "bot"

    @property
    def is_user_account(self) -> bool:
        return self.TELEGRAM_ACCOUNT_TYPE.lower() == "user"

    @property
    def is_windows(self) -> bool:
        """Проверка, работаем ли мы на Windows"""
        return sys.platform == "win32"

    @property
    def is_linux(self) -> bool:
        """Проверка, работаем ли мы на Linux"""
        return sys.platform.startswith("linux")

    @property
    def is_macos(self) -> bool:
        """Проверка, работаем ли мы на macOS"""
        return sys.platform == "darwin"

    @property
    def automation_supported_methods(self) -> list[str]:
        """Список доступных методов конвертации на текущей платформе"""
        methods: list[str] = []

        if self.is_windows:
            try:
                methods.append("pywin32")
                methods.append("comtypes")
            except ImportError:
                pass

        # LibreOffice доступен на всех платформах
        try:
            libreoffice_cmds = ["soffice", "libreoffice"]
            for cmd in libreoffice_cmds:
                if shutil.which(cmd) is not None:
                    methods.append("libreoffice")
                    break
        except Exception:
            pass

        return methods

    @property
    def automation_is_available(self) -> bool:
        """Проверка, доступна ли конвертация на текущей платформе"""
        return len(self.automation_supported_methods) > 0

    @property
    def automation_best_method(self) -> str | None:
        """
        Определение лучшего метода для текущей платформы.
        Возвращает Optional[str], так как метод может быть не найден.
        """
        # Если пользователь указал конкретный метод
        if (
            self.AUTOMATION_CONVERSION_METHOD != "auto"
            and self.AUTOMATION_CONVERSION_METHOD in self.automation_supported_methods
        ):
            return self.AUTOMATION_CONVERSION_METHOD

        # Автовыбор на Windows
        if self.is_windows:
            if "pywin32" in self.automation_supported_methods:
                return "pywin32"
            elif "comtypes" in self.automation_supported_methods:
                return "comtypes"

        # LibreOffice (кроссплатформенный)
        if "libreoffice" in self.automation_supported_methods:
            return "libreoffice"

        # Если ничего не найдено
        return None

    @property
    def automation_get_notification_chats(self) -> list[int]:
        """
        Получение списка чатов для уведомлений о заявках.
        Возвращает список с одним чатом (SUPPORT_CHAT_ID) или пустой список.
        """
        if self.AUTOMATION_NOTIFICATION_CHAT_IDS:
            return self.AUTOMATION_NOTIFICATION_CHAT_IDS
        # Возвращение списка с одним чатом, если он настроен
        if self.SUPPORT_CHAT_ID:
            return [self.SUPPORT_CHAT_ID]
        return []

    @property
    def automation_get_notification_topic(self) -> int | None:
        """
        Получение ID топика для уведомлений о заявках.
        Возвращает ID топика для "Jobs" или None, если не настроен.
        """
        # Заявки на автоматизацию отправляем в топик Jobs
        return self.SUPPORT_CHAT_TOPIC_IDS.get("Jobs")

    @property
    def avanpost_sync_enabled(self) -> bool:
        """Проверка, включена ли синхронизация Avanpost"""
        return self.AVANPOST_AUTO_SYNC_ON_START

    @property
    def avanpost_sync_mode(self) -> str:
        """Режим синхронизации: 'async' или 'sync'"""
        return "async" if self.AVANPOST_SYNC_ASYNC else "sync"

    @property
    def avanpost_sync_is_required(self) -> bool:
        """Является ли синхронизация обязательной"""
        return self.AVANPOST_SYNC_REQUIRED

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


settings = Settings()
