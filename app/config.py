import ast
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ============ ОСНОВНАЯ БД ============

    DB_MAIN_NAME: str = "team_bot"
    DB_MAIN_USER: str = "user"
    DB_MAIN_PASSWORD: str = "password"
    DB_MAIN_HOST: str = "localhost"
    DB_MAIN_PORT: str = "5432"
    DB_MAIN_ECHO: bool = False
    DB_MAIN_POOL_SIZE: int = 10
    DB_MAIN_MAX_OVERFLOW: int = 20

    DB_AVANPOST_NAME: str = "avanpost"
    DB_AVANPOST_USER: str = "user"
    DB_AVANPOST_PASSWORD: str = "password"
    DB_AVANPOST_HOST: str = "localhost"
    DB_AVANPOST_PORT: str = "5432"
    DB_AVANPOST_DRIVER: str = "ODBC Driver 17 for SQL Server"
    DB_AVANPOST_ECHO: bool = False
    DB_AVANPOST_POOL_SIZE: int = 5
    DB_AVANPOST_MAX_OVERFLOW: int = 10

    # ============ AVANPOST SYNC ============

    AVANPOST_AUTO_ADD_USERS_ALL_ON_START: bool = True
    AVANPOST_AUTO_ADD_USERS_IDS_ON_START: list[int] = Field(default_factory=lambda: [])
    AVANPOST_AUTO_SYNC_ON_START: bool = True
    AVANPOST_AUTO_ADD_VEHICLES_ON_START: bool = False

    AVANPOST_SYNC_FORCE: bool = False
    AVANPOST_SYNC_ASYNC: bool = True
    AVANPOST_SYNC_USERS_BASE: bool = True
    AVANPOST_SYNC_USERS_DETAILS: bool = True
    AVANPOST_SYNC_USERS_DETAILS_IDS: list[int] | None = Field(default_factory=lambda: [])
    AVANPOST_SYNC_USER_IDS: list[int] = Field(default_factory=lambda: [])
    AVANPOST_SYNC_REQUIRED: bool = False
    AVANPOST_SYNC_TIMEOUT: int = 300
    AVANPOST_SYNC_CHUNK_SIZE: int = 10

    # ============ TELEGRAM ============

    BOT_TOKEN: str = ""
    BOT_ID: int = 0
    BOT_HASH: str = ""
    BOT_SESSION_NAME: str = "bot_session"
    BOT_USERNAME: str = ""
    TELEGRAM_ACCOUNT_TYPE: str = "bot"
    USER_PHONE: str = "+375336391519"
    USER_SESSION_NAME: str = "user_session"

    # ============ TEAMDROID ============

    TEAMDROID_HOST: str = "localhost:16060"
    TEAMDROID_HTTP_UPLOAD_URL: str = "http://localhost:6060/v0/file/u"
    TEAMDROID_API_KEY: str = "apikey"
    TEAMDROID_USERNAME: str = "user"
    TEAMDROID_PASSWORD: str = "password"
    TEAMDROID_APP_ID: int = 0
    TEAMDROID_GRPC_MAX_MESSAGE: int = 16 * 1024 * 1024
    TEAMDROID_CTRL_TIMEOUT: int = 10

    # ============ SQL SERVER (Teamdroid / Avanpost procedures) ============
    TEAMDROID_SQL_SERVER: str = ""
    TEAMDROID_SQL_DATABASE: str = ""
    TEAMDROID_SQL_USERNAME: str = ""
    TEAMDROID_SQL_PASSWORD: str = ""
    TEAMDROID_SQL_TIMEOUT: int = 10

    TEAMDROID_SQL_PROC_AUTH_START: str = "ext.PA_mbl_AuthStart_Exec"
    TEAMDROID_SQL_PROC_AUTH_FINISH: str = "ext.PA_mbl_AuthFinish_Exec"
    TEAMDROID_SQL_PROC_TOKEN_VERIFY: str = "ext.PA_mbl_TokenVerify_Exec"
    TEAMDROID_SQL_PROC_TOKEN_FINISH: str = "ext.PA_mbl_TokenFinish_Exec"
    TEAMDROID_SQL_PROC_TOKEN_DEVICES_LOAD: str = "ext.PA_mbl_TokenDevices_Load"
    TEAMDROID_SQL_PROC_EDIT_MSG_STATUS_DELIVERY: str = "ext.PA_mbl_MsgsDeliveryStatus_Edit"

    # ============ PUSH NOTIFICATIONS (WebSocket + FCM) ============

    WS_NOTIFY_ENABLED: bool = True
    WS_NOTIFY_PATH: str = "/ws/notify"
    WS_NOTIFY_TOKEN_VERIFY_MODE: str = "avanpost"
    WS_NOTIFY_TOKEN_CACHE_TTL: int = 300
    WS_NOTIFY_MAX_CONNECTIONS_PER_USER: int = 10
    WS_NOTIFY_HEARTBEAT_INTERVAL: int = 30
    WS_NOTIFY_SEND_TIMEOUT: float = 5.0

    WS_RELAY_AUTH_TOKEN: str = ""
    WS_RELAY_INGEST_PATH: str = "/internal/push"
    WS_TOKEN_KEY_B64: str = ""

    # FCM (Firebase Cloud Messaging) — доставка, когда WS-клиента нет онлайн,
    # или всегда (в зависимости от FCM_SEND_MODE).
    FCM_ENABLED: bool = True
    FCM_LOAD_FIDS_ON_START: bool = True
    FCM_CREDENTIALS_PATH: str = ""

    # Режим отправки FCM:
    #   "always" — всегда (WS + FCM одновременно)
    #   "fallback" — только если WS не доставил (для msg) / всегда (для sub)
    #   "never" — только WS
    FCM_SEND_MODE: str = "fallback"
    FCM_FID_TTL_SECONDS: int = 7 * 24 * 3600

    # ============ API ============

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_KEYS: list[str] = Field(default_factory=lambda: [], description="Список API ключей для аутентификации запросов")
    APP_ENV: str = "production"
    APP_DEBUG: bool = False
    API_RELOAD: bool = False
    API_WORKERS: int = 1
    API_TRUSTED_HOSTS: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "::1", "172.17.0.1", "192.168.12.1"],
        description="Список доверенных IP/подсетей",
    )

    # ============ ЛОГИРОВАНИЕ ============

    LOG_LEVEL: str = "DEBUG"
    LOG_DIR: str = "../logs"
    LOG_MAX_BYTES: int = 10_000_000
    LOG_BACKUP_COUNT: int = 5

    # ============ НАСТРОЙКИ БОТА ============

    ADMIN_IDS: list[int] = Field(default_factory=lambda: [1039799368])
    SYNC_INTERVAL: int = 300
    MAX_MESSAGE_LENGTH: int = 4096

    # ============ НАСТРОЙКИ TELETHON ============

    TELEGRAM_API_RETRY: int = 3
    TELEGRAM_RECONNECT_DELAY: int = 5
    TELEGRAM_CATCH_UP_ON_START: bool = True
    TELEGRAM_SYNC_CHATS_ON_START: bool = True

    # ============ RATE LIMITING ============

    API_RATE_LIMIT: int = 100
    API_RATE_PERIOD: int = 60
    BOT_RATE_LIMIT: int = 10
    BOT_COMMAND_LIMIT: int = 5
    BOT_RATE_PERIOD: int = 60
    BOT_COMMAND_PERIOD: int = 10

    # ============ ШИФРОВАНИЕ ============

    ENCRYPTION_SECRET: str = Field(default=secrets.token_urlsafe(32), description="Секретный ключ для шифрования")

    # ============ НАСТРОЙКИ УВЕДОМЛЕНИЙ ============

    DEFAULT_NOTIFICATION_LEVEL: str = "error"
    DEFAULT_GROUPING_WINDOW: int = 60
    DEFAULT_AUTO_REPORT_INTERVAL: int = 60
    DEFAULT_WORK_HOURS_START: int = 9
    DEFAULT_WORK_HOURS_END: int = 18

    ERROR_GROUPING_ENABLED: bool = True
    ERROR_GROUPING_WINDOW_MINUTES: int = 60
    ERROR_MAX_OCCURRENCES_BEFORE_SILENCE: int = 10

    # ============ НАСТРОЙКИ НАПОМИНАНИЙ ============

    REMINDER_MAX_PER_USER: int = 100
    REMINDER_DEFAULT_INTERVAL: int = 0
    REMINDER_MAX_REMIND_COUNT: int = 10
    REMINDER_CHECK_INTERVAL: int = 60
    REMINDER_BATCH_SIZE: int = 100

    # ============ НАСТРОЙКИ ЛОГОВ ОШИБОК ============

    SUPPORT_CHAT_ID: int = Field(default=0, description="ID чата для отправки уведомлений об ошибках")
    SUPPORT_CHAT_TOPIC_IDS: dict[str, int] = Field(
        default_factory=dict, description="Маппинг источников ошибок на ID топиков в Telegram"
    )
    LOG_ERROR_NOTIFICATION_INTERVAL: int = 60
    LOG_ERROR_AUTO_CAPTURE: bool = True
    LOG_ERROR_MAX_MESSAGE_LENGTH: int = 500
    LOG_ERROR_MAX_TRACEBACK_LENGTH: int = 1000
    LOG_ERROR_GROUPING_ENABLED: bool = True
    LOG_ERROR_CLEAR_CACHE_ON_START: bool = True
    LOG_ERROR_MESSAGE_LIFETIME_SECONDS: int = 604800

    # ============ НАСТРОЙКИ АВТОМАТИЗАЦИИ ============

    AUTOMATION_CONVERSION_METHOD: str = "auto"
    AUTOMATION_MAX_FILE_SIZE: int = 50 * 1024 * 1024
    AUTOMATION_TEMP_DIR: str = "./temp/automation"
    AUTOMATION_RETRY_COUNT: int = 3
    AUTOMATION_RETRY_DELAY: int = 2
    AUTOMATION_CLEANUP_AFTER: int = 3600
    AUTOMATION_ALLOWED_EXTENSIONS: list[str] = Field(default_factory=lambda: [".doc", ".docx"])
    AUTOMATION_MAX_REQUESTS_PER_USER: int = 50
    AUTOMATION_REQUIRE_ADMIN_APPROVAL: bool = True
    AUTOMATION_NOTIFICATION_CHAT_IDS: list[int] = Field(default_factory=list)
    AUTOMATION_AUTO_CLEANUP: bool = True
    AUTOMATION_CONVERSION_TIMEOUT: int = 60

    # ============ НАСТРОЙКИ ВРЕМЕНИ ЖИЗНИ СООБЩЕНИЙ ============

    MESSAGE_LIFETIME_CHECK_INTERVAL: int = 60
    MESSAGE_LIFETIME_BATCH_SIZE: int = 1000
    MESSAGE_LIFETIME_DEFAULT_SECONDS: int = 300
    SYNC_CACHE_TTL_SECONDS: int = 60
    ERROR_GROUP_CACHE_TTL_SECONDS: int = 300
    LOG_QUEUE_MAX_SIZE: int = 1000
    LOG_WORKER_TIMEOUT: float = 0.3
    BOT_MESSAGE_LIFETIME_SECONDS: int = 300
    KEYBOARD_BUTTONS_PER_ROW: int = 3
    AUTH_CACHE_TTL_SECONDS: int = 3600
    AUTOMATION_STATS_ENABLED: bool = True
    AUTOMATION_STATS_MAX_ENTRIES: int = 1000
    HTTP_TIMEOUT_KEEP_ALIVE: int = 30
    TELEGRAM_POLLING_TIMEOUT: int = 30
    TELEGRAM_RETRY_DELAY: int = 5
    TELEGRAM_MAX_RETRIES: int = 5
    API_DEFAULT_PAGE_SIZE: int = 50
    API_STATS_DAYS: int = 7

    # ============ СВОЙСТВА ДЛЯ URL БАЗ ДАННЫХ ============

    @property
    def db_main_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DB_MAIN_USER}:"
            f"{quote_plus(self.DB_MAIN_PASSWORD)}@"
            f"{self.DB_MAIN_HOST}:{self.DB_MAIN_PORT}/{self.DB_MAIN_NAME}"
        )

    @property
    def db_avanpost_url(self) -> str:
        return (
            f"mssql+aioodbc://{self.DB_AVANPOST_USER}:"
            f"{quote_plus(self.DB_AVANPOST_PASSWORD)}@"
            f"{self.DB_AVANPOST_HOST}:{self.DB_AVANPOST_PORT}/"
            f"{self.DB_AVANPOST_NAME}?driver={quote_plus(self.DB_AVANPOST_DRIVER)}"
            f"&TrustServerCertificate=yes"
        )

    # ============ ВАЛИДАТОРЫ ============

    @field_validator("ADMIN_IDS", "AUTOMATION_NOTIFICATION_CHAT_IDS", mode="before")
    @classmethod
    def parse_list_field(cls, v: str | list[int] | None) -> list[int]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                if v.startswith("[") and v.endswith("]"):
                    result = ast.literal_eval(v)
                    if isinstance(result, list):
                        return [int(x) for x in result]
                elif "," in v:
                    return [int(p.strip()) for p in v.split(",") if p.strip()]
                return [int(v)]
            except (ValueError, SyntaxError):
                return []
        return []

    @field_validator("AVANPOST_AUTO_ADD_USERS_IDS_ON_START", mode="before")
    @classmethod
    def parse_avanpost_users_list(cls, v: str | list[int] | None) -> list[int]:
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
                    return [int(p.strip()) for p in v.split(",") if p.strip()]
            except (ValueError, SyntaxError):
                return []
        return []

    @field_validator("AVANPOST_SYNC_USER_IDS", mode="before")
    @classmethod
    def parse_avanpost_sync_user_ids(cls, v: str | list[int] | None) -> list[int]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                if v.startswith("[") and v.endswith("]"):
                    parsed = ast.literal_eval(v)
                    if isinstance(parsed, list):
                        return [int(x) if isinstance(x, int) else int(x) for x in parsed if isinstance(x, (int, str))]
                elif "," in v:
                    return [int(p.strip()) for p in v.split(",") if p.strip()]
            except (ValueError, SyntaxError):
                return []
        return []

    @field_validator("AVANPOST_AUTO_ADD_VEHICLES_ON_START", mode="before")
    @classmethod
    def validate_auto_add_vehicles(cls, v: bool | str | None) -> bool:
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return False

    @field_validator("SUPPORT_CHAT_TOPIC_IDS", mode="before")
    @classmethod
    def parse_support_chat_topic_ids(cls, v: str | dict | None) -> dict[str, int]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return {str(k): int(val) for k, val in v.items()}
        if isinstance(v, str):
            try:
                if v.startswith("{") and v.endswith("}"):
                    result = ast.literal_eval(v)
                    if isinstance(result, dict):
                        return {str(k): int(val) for k, val in result.items()}
                elif "," in v and ":" in v:
                    parsed: dict[str, int] = {}
                    for part in v.split(","):
                        if ":" in part:
                            key, value = part.split(":", 1)
                            parsed[key.strip().strip('"').strip("'")] = int(value.strip())
                    return parsed
            except (ValueError, SyntaxError) as e:
                raise ValueError(f"Неверный формат SUPPORT_CHAT_TOPIC_IDS: {e}") from e
        return {}

    @field_validator("AUTOMATION_ALLOWED_EXTENSIONS", mode="before")
    @classmethod
    def parse_extensions_list(cls, v: str | list[str] | None) -> list[str]:
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
                return [v.strip().lower()]
            except (ValueError, SyntaxError):
                return [".doc", ".docx"]
        return [".doc", ".docx"]

    @field_validator("AUTOMATION_CONVERSION_METHOD")
    @classmethod
    def validate_conversion_method(cls, v: str) -> str:
        valid = ["pywin32", "comtypes", "libreoffice", "auto"]
        if v.lower() not in valid:
            raise ValueError(f"Invalid conversion method: {v}. Must be one of: {', '.join(valid)}")
        return v.lower()

    @field_validator("AUTOMATION_MAX_FILE_SIZE")
    @classmethod
    def validate_max_file_size(cls, v: int) -> int:
        if v < 1024 * 1024:
            raise ValueError("AUTOMATION_MAX_FILE_SIZE must be at least 1 MB")
        if v > 500 * 1024 * 1024:
            raise ValueError("AUTOMATION_MAX_FILE_SIZE must not exceed 500 MB")
        return v

    @field_validator("AUTOMATION_CONVERSION_TIMEOUT")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v < 5:
            raise ValueError("AUTOMATION_CONVERSION_TIMEOUT must be at least 5 seconds")
        if v > 300:
            raise ValueError("AUTOMATION_CONVERSION_TIMEOUT must not exceed 300 seconds")
        return v

    @field_validator("MESSAGE_LIFETIME_DEFAULT_SECONDS")
    @classmethod
    def validate_message_lifetime(cls, v: int) -> int:
        if v < 10:
            raise ValueError("MESSAGE_LIFETIME_DEFAULT_SECONDS must be at least 10 seconds")
        if v > 86400:
            raise ValueError("MESSAGE_LIFETIME_DEFAULT_SECONDS must not exceed 24 hours (86400 seconds)")
        return v

    @field_validator("LOG_QUEUE_MAX_SIZE")
    @classmethod
    def validate_queue_size(cls, v: int) -> int:
        if v < 10:
            raise ValueError("LOG_QUEUE_MAX_SIZE must be at least 10")
        if v > 10000:
            raise ValueError("LOG_QUEUE_MAX_SIZE must not exceed 10000")
        return v

    @field_validator("API_DEFAULT_PAGE_SIZE")
    @classmethod
    def validate_page_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("API_DEFAULT_PAGE_SIZE must be at least 1")
        if v > 1000:
            raise ValueError("API_DEFAULT_PAGE_SIZE must not exceed 1000")
        return v

    @field_validator("API_TRUSTED_HOSTS", mode="before")
    @classmethod
    def parse_trusted_hosts(cls, v: str | list[str] | None) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                try:
                    result = ast.literal_eval(v)
                    if isinstance(result, list):
                        return [str(x).strip() for x in result if str(x).strip()]
                except (ValueError, SyntaxError):
                    pass
            return [x.strip() for x in v.split(",") if x.strip()]
        return []

    @field_validator("TELEGRAM_MAX_RETRIES")
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        if v < 1:
            raise ValueError("TELEGRAM_MAX_RETRIES must be at least 1")
        if v > 20:
            raise ValueError("TELEGRAM_MAX_RETRIES must not exceed 20")
        return v

    @field_validator("AVANPOST_SYNC_CHUNK_SIZE")
    @classmethod
    def validate_sync_chunk_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("AVANPOST_SYNC_CHUNK_SIZE must be at least 1")
        if v > 50:
            raise ValueError("AVANPOST_SYNC_CHUNK_SIZE must not exceed 50")
        return v

    @field_validator("AVANPOST_SYNC_TIMEOUT")
    @classmethod
    def validate_sync_timeout(cls, v: int) -> int:
        if v < 0:
            raise ValueError("AVANPOST_SYNC_TIMEOUT must be >= 0")
        return v

    @field_validator("TEAMDROID_APP_ID")
    @classmethod
    def validate_teamdroid_app_id(cls, v: int) -> int:
        if v < 0:
            raise ValueError("TEAMDROID_APP_ID must be >= 0")
        if v > 255:
            raise ValueError("TEAMDROID_APP_ID must fit TINYINT (0..255)")
        return v

    @field_validator("FCM_SEND_MODE")
    @classmethod
    def validate_fcm_send_mode(cls, v: str) -> str:
        mode = (v or "fallback").lower()
        if mode not in ("always", "fallback", "never"):
            raise ValueError(f"FCM_SEND_MODE must be one of: always, fallback, never; got {v!r}")
        return mode

    # ============ КРОСС-ВАЛИДАЦИЯ ============

    @model_validator(mode="after")
    def validate_fcm_credentials(self) -> "Settings":
        """
        Проверяет, что при FCM_ENABLED=True и FCM_SEND_MODE != 'never'
        указан путь к service account JSON и файл существует.

        Не бросает исключение, но оставляет FCM_CREDENTIALS_PATH пустым
        при отсутствии файла — это позволяет приложению стартовать,
        а сервис push_notification_service зафиксирует
        fcm_available=False в /api/v1/ws/stats.
        """
        if not self.FCM_ENABLED or self.FCM_SEND_MODE == "never":
            return self

        path_str = (self.FCM_CREDENTIALS_PATH or "").strip()
        if not path_str:
            return self

        path = Path(path_str)
        if not path.exists():
            # Не падаем — просто предупреждаем. Реальную проверку
            # делает _FcmClient._ensure_initialized при первом использовании.
            import logging

            logging.getLogger("app.config").warning(
                "FCM_CREDENTIALS_PATH=%r does not exist; FCM will be unavailable",
                path_str,
            )
        return self

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
        return sys.platform == "win32"

    @property
    def is_linux(self) -> bool:
        return sys.platform.startswith("linux")

    @property
    def is_macos(self) -> bool:
        return sys.platform == "darwin"

    @property
    def automation_supported_methods(self) -> list[str]:
        methods: list[str] = []
        if self.is_windows:
            try:
                methods.append("pywin32")
                methods.append("comtypes")
            except ImportError:
                pass
        try:
            for cmd in ["soffice", "libreoffice"]:
                if shutil.which(cmd) is not None:
                    methods.append("libreoffice")
                    break
        except (OSError, TypeError, ValueError):
            pass
        return methods

    @property
    def automation_is_available(self) -> bool:
        return len(self.automation_supported_methods) > 0

    @property
    def automation_best_method(self) -> str | None:
        if (
            self.AUTOMATION_CONVERSION_METHOD != "auto"
            and self.AUTOMATION_CONVERSION_METHOD in self.automation_supported_methods
        ):
            return self.AUTOMATION_CONVERSION_METHOD
        if self.is_windows:
            if "pywin32" in self.automation_supported_methods:
                return "pywin32"
            if "comtypes" in self.automation_supported_methods:
                return "comtypes"
        if "libreoffice" in self.automation_supported_methods:
            return "libreoffice"
        return None

    @property
    def automation_get_notification_chats(self) -> list[int]:
        if self.AUTOMATION_NOTIFICATION_CHAT_IDS:
            return self.AUTOMATION_NOTIFICATION_CHAT_IDS
        if self.SUPPORT_CHAT_ID:
            return [self.SUPPORT_CHAT_ID]
        return []

    @property
    def automation_get_notification_topic(self) -> int | None:
        return self.SUPPORT_CHAT_TOPIC_IDS.get("Jobs")

    @property
    def avanpost_sync_enabled(self) -> bool:
        return self.AVANPOST_AUTO_SYNC_ON_START

    @property
    def avanpost_sync_mode(self) -> str:
        return "async" if self.AVANPOST_SYNC_ASYNC else "sync"

    @property
    def avanpost_sync_is_required(self) -> bool:
        return self.AVANPOST_SYNC_REQUIRED

    @property
    def avanpost_sync_user_ids(self) -> list[int]:
        return self.AVANPOST_SYNC_USER_IDS

    @property
    def ws_notify_enabled(self) -> bool:
        return self.WS_NOTIFY_ENABLED

    @property
    def ws_notify_verify_mode(self) -> str:
        mode = (self.WS_NOTIFY_TOKEN_VERIFY_MODE or "trust").lower()
        if mode not in ("trust", "grpc", "avanpost"):
            return "trust"
        return mode

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
