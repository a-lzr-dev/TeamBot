"""
Middleware для аутентификации запросов к API.

Назначение:
    Обеспечивает аутентификацию входящих HTTP запросов через API ключи.
    Защищает эндпоинты API от несанкционированного доступа.

Основные функции:
    1. Проверка наличия API ключа в заголовке settings.API_KEY_HEADER
    2. Валидация API ключа по списку из настроек
    3. Пропуск публичных путей (health, docs, relay-ingest, WS,
       публичная раздача APK)
    4. Пропуск запросов с доверенных хостов (API_TRUSTED_HOSTS)
    5. Пропуск CORS preflight (OPTIONS) и WebSocket upgrade запросов
    6. Добавление информации о пользователе в request.state

Отдельные наборы ключей (НЕ пересекаются):
    - API_KEYS — основной набор (admin, бизнес-API).
    - APP_CLIENT_SUPPORT_INGEST_API_KEYS — приём диагностических логов
      мобильных клиентов:
          POST /api/v1/logs/batch
          POST /api/v1/logs/request/{id}/decline
    - APP_CLIENT_SYNC_INGEST_API_KEYS — регистрация/логин/прочее мобильного клиента:
          POST /api/v1/client/register (выдаёт TApps.FKey)
          POST api/v1/client/login
          DELETE /api/v1/client/register
          GET /api/v1/client/sync-stats
          GET /api/v1/client/health
          POST api/v1/client/note (deprecated)
          GET /api/v1/update/apk/{filename}
     - TApps.FKey — операции по устройству (X-API-Key == TApps.FKey).
          Если ключ не найден/неактивен — 401/403/404 с
          {"scs":0,"err":"device_not_registered","rtr":"register"},
          клиент обязан вызвать POST /api/v1/client/register.
          POST /api/v1/client/send-code
          POST /api/v1/client/sync-load
          POST /api/v1/client/sync-edit
          POST /api/v1/client/uploads, PATCH/HEAD/DELETE /uploads/{uid},
          POST /uploads/{uid}/complete
          GET /api/v1/client/files/{fid}
          POST /api/v1/client/msgs
    - APP_CLIENT_SUPPORT_INGEST_API_KEYS — обновление версии клиента:
          POST /api/v1/client/update-check
    - APP_SERVER_SYNC_INGEST_API_KEYS — синхронизация основного сервера
      (Teamdroid):
          POST /api/v1/teamdroid/send-files
          POST /api/v1/teamdroid/send-text
          POST /api/v1/teamdroid/delete-messages
          POST /api/v1/teamdroid/grant-user
          GET /api/v1/teamdroid/user-id/{id_val}
          GET /api/v1/teamdroid/acs/{topic}
          GET /api/v1/teamdroid/health

Публичные пути (без ключа):
    - /health, /version, /api/docs, /api/redoc, /api/openapi.json
    - /api/v1/health, /api/v1/ping, /api/v1/ready
    - WS_NOTIFY_PATH и WS_RELAY_INGEST_PATH (если WS_NOTIFY_ENABLED)
    - /api/v1/update/public/* (публичная раздача APK/version.json)

Технические особенности:
    - Интеграция с FastAPI/Starlette через BaseHTTPMiddleware
    - Динамический список публичных путей: учитывает WS_NOTIFY_PATH
      и WS_RELAY_INGEST_PATH из настроек
    - Поддержка CIDR-нотации (например, 192.168.12.0/24)
    - Поддержка X-Forwarded-For / X-Real-IP для работы за прокси
    - Constant-time сравнение API-ключа (hmac.compare_digest)
    - В production тело ошибки не содержит client_ip

Безопасность:
    - В production необходимо настроить API_KEYS в конфигурации
    - /internal/push защищён отдельным Bearer-токеном (WS_RELAY_AUTH_TOKEN)
      внутри relay_handler, а не API-ключом
    - /ws/notify проверяет токен в query при accept в ws_notify_handler
    - Каждый ingest-канал защищён СВОИМ набором ключей, чтобы ключ
      одного канала можно было отозвать независимо от остальных
    - Логирование предупреждений при неавторизованных попытках

Архитектура:
    - Реализует интерфейс BaseHTTPMiddleware от Starlette
    - Поддерживает асинхронную обработку запросов
    - Интегрируется с настройками приложения через settings
"""

import asyncio
import hmac
import ipaddress
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.websockets import WebSocket

from ...config import settings
from ...logger import api_logger
from ...models import datetime_now


def _is_dev_env() -> bool:
    """Проверка, что мы в development-окружении."""
    return (getattr(settings, "APP_ENV", "") or "").lower() in ("development", "dev")


# Регулярка для /api/v1/logs/request/<uuid>/decline
_LOGS_DECLINE_RE = re.compile(r"^/api/v1/logs/request/[^/]+/decline$")

# Точный путь приёма батча диагностических логов
_LOGS_BATCH_PATH = "/api/v1/logs/batch"

# --- Группа 3: auth по TApps.FKey ---
_CLIENT_TAPPS_EXACT: frozenset[str] = frozenset(
    {
        "/api/v1/client/send-code",
        "/api/v1/client/sync-load",
        "/api/v1/client/sync-edit",
        "/api/v1/client/msgs",
    }
)
_CLIENT_TAPPS_PREFIXES: tuple[str, ...] = (
    "/api/v1/client/uploads",  # uploads, uploads/{uid}, uploads/{uid}/complete
    "/api/v1/client/files",  # files/{fid}
)

# --- Группы 1, 2, 5, 6: статический APP_CLIENT_SYNC_INGEST_API_KEYS ---
_CLIENT_SYNC_INGEST_EXACT: frozenset[str] = frozenset(
    {
        "/api/v1/client/register",  # группа 1 (POST) и группа 2 (DELETE)
        "/api/v1/client/login",  # группа 1
        "/api/v1/client/sync-stats",  # группа 5
        "/api/v1/client/health",  # группа 5
        "/api/v1/client/note",  # группа 6 (deprecated)
    }
)

# --- Группа 4: APP_CLIENT_SUPPORT_INGEST_API_KEYS ---
_CLIENT_SUPPORT_EXACT: frozenset[str] = frozenset(
    {
        "/api/v1/client/update-check",
    }
)

# Префиксы путей с параметризованным хвостом (остаются для /update/apk).
_CLIENT_SYNC_INGEST_PREFIXES: tuple[str, ...] = (
    "/api/v1/update",  # /api/v1/update/apk/{filename}, ...
)

# Канал server-sync (APP_SERVER_SYNC_INGEST_API_KEYS):
#   POST /api/v1/teamdroid/send-files
#   POST /api/v1/teamdroid/send-text
#   POST /api/v1/teamdroid/delete-messages
#   POST /api/v1/teamdroid/grant-user
#   GET  /api/v1/teamdroid/user-id/{id_val}
#   GET  /api/v1/teamdroid/acs/{topic}
#   GET  /api/v1/teamdroid/health
#
# Матчим по префиксу (startswith path + "/" или точное совпадение),
# потому что user-id/acs имеют параметризованные хвосты.
_SERVER_SYNC_INGEST_PATHS: tuple[str, ...] = (
    "/api/v1/teamdroid/send-files",
    "/api/v1/teamdroid/send-text",
    "/api/v1/teamdroid/delete-messages",
    "/api/v1/teamdroid/grant-user",
    "/api/v1/teamdroid/user-id",
    "/api/v1/teamdroid/acs",
    "/api/v1/teamdroid/health",
    "/api/v1/utils",
)


def _is_server_sync_ingest_path(path: str) -> bool:
    """Пути sync-каналов основного сервера (teamdroid/*)."""
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _SERVER_SYNC_INGEST_PATHS)


def _is_client_sync_ingest_path(path: str) -> bool:
    """Пути sync-каналов мобильного клиента.

    - точные пути;
    - префиксы с параметризованным хвостом.
    """
    if path in _CLIENT_SYNC_INGEST_EXACT:
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _CLIENT_SYNC_INGEST_PREFIXES)


def _is_client_tapps_path(path: str) -> bool:
    """Группа 3: операции с авторизацией по TApps.FKey."""
    if path in _CLIENT_TAPPS_EXACT:
        return True
    return any(path == p or path.startswith(p + "/") for p in _CLIENT_TAPPS_PREFIXES)


def _is_client_support_path(path: str) -> bool:
    """Группа 4: APP_CLIENT_SUPPORT_INGEST_API_KEYS (update-check)."""
    return path in _CLIENT_SUPPORT_EXACT


def _is_logs_ingest_path(path: str) -> bool:
    """Пути приёма диагностических логов мобильного клиента."""
    if path == _LOGS_BATCH_PATH:
        return True
    if _LOGS_DECLINE_RE.match(path):
        return True
    return False


def extract_request_client_ip(request: Request) -> str:
    """IP клиента с учётом прокси."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1][:64]
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()[:64]
    client = request.client
    if client is not None:
        return (client.host or "")[:64]
    return ""


def extract_websocket_client_ip(websocket: WebSocket) -> str | None:
    """Определяет реальный IP клиента с учётом прокси.

    Берём ПОСЛЕДНИЙ адрес из X-Forwarded-For (первый может быть
    подделан клиентом, последний добавлен нашим доверенным прокси).
    Если заголовка нет — X-Real-IP, затем websocket.client.host.
    """
    xff = websocket.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1][:64]

    xri = websocket.headers.get("x-real-ip")
    if xri:
        return xri.strip()[:64]

    client = websocket.client
    if client is not None:
        host = client.host or ""
        return host[:64] or None
    return None


# ============================================================
# ЕДИНАЯ ПРОВЕРКА WS-ТОКЕНА (register / ws-notify)
# ============================================================


@dataclass(frozen=True)
class VerifiedToken:
    """Результат ``verify_token()`` — единый контракт для
    ``POST /api/v1/client/register`` и ``GET /ws/notify``.

    Attributes:
        user_id: ``usrXXX`` из ``prm1`` расшифрованного токена.
        fcm_id: Firebase Installation ID из поля ``fid`` токена.
        err: Код/текст ошибки (``None`` при успехе).
        app_id: ``TEAMDROID_APP_ID``, с которым шёл запрос.
        bundle: Сырой пакет SQL-процедуры ``{"sid","snc","dtp","prm"}``.
        tapps_ok: True, если запись ``TApps`` создана/обновлена.
        tapps_reason: ``key_already_bound`` / ``tapps_sync_failed``.
    """

    user_id: str | None
    fcm_id: str | None = None
    err: str | None = None
    app_id: int = 0
    bundle: dict[str, Any] = field(default_factory=dict)
    tapps_ok: bool = True
    tapps_reason: str | None = None

    @property
    def fid(self) -> str | None:
        """Alias для ``fcm_id`` (для ``register_fid``)."""
        return self.fcm_id

    @property
    def ok(self) -> bool:
        return self.err is None and bool(self.user_id and self.user_id.startswith("usr"))

    def __post_init__(self) -> None:
        """Нормализация после ``__init__``.

        При ``ok=True`` гарантирует ``user_id: str`` и ``fcm_id: str``
        (а не ``str | None``). Это убирает касты в вызывающем коде
        ``register_fid`` / ``_verify_via_avanpost``.
        """
        if self.err is None:
            uid = getattr(self, "user_id", None)
            fid = getattr(self, "fcm_id", None)
            if isinstance(uid, str) and uid.startswith("usr") and isinstance(fid, str):
                object.__setattr__(self, "user_id", uid)
                object.__setattr__(self, "fcm_id", fid)

    @property
    def prm_raw(self) -> str | None:
        """Сырая строка ``prm`` из SQL-процедуры."""
        return self.bundle.get("prm")

    @property
    def force_update(self) -> bool:
        """True, если SQL вернул отказ вместе с ``prm``."""
        return not self.ok and bool(self.prm_raw)


async def upsert_tapps(*, fid: str, user_id: str, key: str, app_version_code: int | None) -> tuple[bool, str | None]:
    """Создать/обновить ``TApps`` после успешного ``verify_token``.

    ``FKey`` = полный 7-полевой токен (обрезка до 512 символов).

    fail-closed: любая ошибка БД → ``(False, reason)``.

    Returns:
        ``(True, None)`` либо ``(False, "key_already_bound"|"tapps_sync_failed")``.
    """
    from sqlalchemy.exc import IntegrityError

    from ...db import db_manager
    from ...db.repositories import AppRepository

    try:
        async with db_manager.get_session() as session:
            await AppRepository.register_app(
                session,
                fid=fid,
                user_id=user_id,
                key=key[:512],
                app_version_code=app_version_code,
            )
            await session.commit()
        return True, None
    except IntegrityError:
        return False, "key_already_bound"
    except Exception as exc:  # noqa: BLE001
        api_logger.error(
            "TApps upsert failed user=%s fid=%s: %r",
            user_id,
            fid[-8:] if len(fid) >= 8 else "***",
            exc,
            exc_info=True,
        )
        return False, "tapps_sync_failed"


async def verify_token(
    raw_token: str | None,
    *,
    client_ip: str | None = None,
    ensure_tapps: bool = True,
) -> VerifiedToken:
    """Расшифровать WS-токен, проверить в SQL Server, записать ``TApps``.

    Единая точка проверки для ``POST /api/v1/client/register`` и
    ``GET /ws/notify``. Принимает СЫРУЮ строку токена (7 полей,
    разделитель ``|``), расшифровывает её ``decrypt_ws_token`` и вызывает
    ``TeamdroidProcedureRepository.verify_token``
    (``settings.TEAMDROID_SQL_PROC_TOKEN_VERIFY``).

    При успехе (и ``ensure_tapps=True``) создаёт/обновляет запись
    ``TApps`` с ``FKey = raw_token[:512]``.

    Args:
        raw_token: Зашифрованный токен ``fid|3|usrXXX||yyMMdd|appVer|appCode``.
        client_ip: IP клиента для поля ``$.cip``.
        ensure_tapps: Выполнять ли upsert ``TApps`` после успешного verify.

    Returns:
        ``VerifiedToken``; ``.ok is False`` означает отказ.
    """
    from ...ws.token_crypto import decrypt_ws_token

    if not raw_token:
        return VerifiedToken(user_id=None, err="empty_token")

    payload = decrypt_ws_token(raw_token)
    if payload is None:
        api_logger.warning("auth: decrypt_ws_token returned None -> REJECT")
        return VerifiedToken(user_id=None, err="invalid_token")

    if payload.sch != "3" or not payload.user_id:
        api_logger.warning(
            "auth: token sch=%r user_id=%r — not usable (expected sch=3)",
            payload.sch,
            payload.user_id,
        )
        return VerifiedToken(
            user_id=payload.user_id,
            fcm_id=payload.fcm_id,
            err="sch_not_3",
        )

    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
    if app_id <= 0:
        api_logger.error("auth: TEAMDROID_APP_ID=0 — verify невозможен")
        return VerifiedToken(
            user_id=payload.user_id,
            fcm_id=payload.fcm_id,
            app_id=0,
            err="server_misconfigured",
        )

    from ...db.repositories import TeamdroidProcedureRepository

    try:
        ok, err, bundle = await asyncio.to_thread(
            TeamdroidProcedureRepository.verify_token,
            user_id=payload.user_id,
            app_id=app_id,
            fcm_id=payload.fcm_id,
            token_date=payload.date,
            client_ip=client_ip,
            app_version=payload.app_version,
            app_version_code=payload.app_version_code,
        )
    except Exception as exc:
        api_logger.error("auth: verify_token raised: %r", exc, exc_info=True)
        return VerifiedToken(
            user_id=payload.user_id,
            fcm_id=payload.fcm_id,
            app_id=app_id,
            err="db_error",
        )

    bundle = bundle or {}

    if not ok:
        api_logger.warning(
            "auth: verify_token rejected user=%s fid=%s... err=%s has_prm=%s",
            payload.user_id,
            payload.fcm_id[-6:] if len(payload.fcm_id) >= 6 else "***",
            err,
            bool(bundle.get("prm")),
        )
        return VerifiedToken(
            user_id=payload.user_id,
            fcm_id=payload.fcm_id,
            app_id=app_id,
            bundle=bundle,
            err=err or "token_rejected",
        )

    tapps_ok, tapps_reason = (True, None)
    if ensure_tapps:
        tapps_ok, tapps_reason = await upsert_tapps(
            fid=payload.fcm_id,
            user_id=payload.user_id,
            key=raw_token,
            app_version_code=payload.app_version_code,
        )
        if not tapps_ok:
            api_logger.warning(
                "auth: TApps upsert failed user=%s reason=%s",
                payload.user_id,
                tapps_reason,
            )

    api_logger.info(
        "auth: verify_token OK user=%s fid=%s... has_prm=%s tapps_ok=%s",
        payload.user_id,
        payload.fcm_id[-6:] if len(payload.fcm_id) >= 6 else "***",
        bool(bundle.get("prm")),
        tapps_ok,
    )

    return VerifiedToken(
        user_id=payload.user_id,
        fcm_id=payload.fcm_id,
        app_id=app_id,
        bundle=bundle,
        tapps_ok=tapps_ok,
        tapps_reason=tapps_reason,
    )


# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ АУТЕНТИФИКАЦИИ
# ============================================================


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware для аутентификации запросов к API.

    Проверяет наличие и валидность API ключа в заголовке settings.API_KEY_HEADER.
    Публичные пути, доверенные хосты, CORS preflight и WebSocket upgrade
    пропускаются без проверки.

    Attributes:
        PUBLIC_PATHS (list[str]): Базовый список путей, не требующих аутентификации

    Пример использования в FastAPI:
        app.add_middleware(AuthMiddleware)
    """

    # Базовые пути, которые не требуют аутентификации.
    # Пути relay-ingest и WS добавляются динамически из настроек
    # (см. _get_public_paths), чтобы учитывать WS_NOTIFY_PATH
    # и WS_RELAY_INGEST_PATH из .env.
    #
    # ВАЖНО: _is_public_path() вызывается в dispatch() РАНЬШЕ всех
    # проверок ingest-каналов и settings.API_KEY_HEADER. Поэтому добавление сюда
    # префикса делает все вложенные пути публичными.
    PUBLIC_PATHS = [
        "/api/v1/health",
        "/api/v1/ping",
        "/api/v1/ready",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/health",
        "/version",
        # Публичная раздача APK/version.json — БЕЗ settings.API_KEY_HEADER.
        # См. app/api/routers/update.py::download_public_file.
        # ВАЖНО: должен идти до _CLIENT_SYNC_INGEST_PREFIXES в dispatch(),
        # но так как _is_public_path() вызывается раньше — порядок в
        # списке не важен. /api/v1/update/apk/* при этом остаётся
        # закрытым, т.к. он матчится по ДРУГОМУ префиксу.
        "/api/v1/update/public",
    ]

    # Доверенные IP-адреса и подсети (CIDR), которым не нужен API-ключ.
    # Значения по умолчанию можно переопределить через settings.API_TRUSTED_HOSTS.
    DEFAULT_TRUSTED_HOSTS = [
        "127.0.0.1",  # localhost (IPv4)
        "::1",  # localhost (IPv6)
        "172.17.0.1",  # Docker bridge (по умолчанию)
        "192.168.12.1",  # ваш доверенный хост
    ]

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ ЗАПРОСА
    # ============================================================

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        Основной метод обработки запроса.

        Args:
            request: Объект запроса FastAPI/Starlette
            call_next: Функция для передачи запроса дальше по цепочке

        Returns:
            Response: Ответ от приложения или ошибка аутентификации
        """
        # Пропускаем WebSocket — его аутентификация в ws_notify_handler
        if request.scope["type"] == "websocket":
            return await call_next(request)

        path = request.url.path
        method = request.method

        # 0. WebSocket upgrade: пропускаем всегда.
        #    Аутентификация WS-клиента выполняется в ws_notify_handler
        #    через query-параметр token.
        if self._is_websocket_upgrade(request):
            api_logger.debug(f"🔓 WebSocket upgrade: {path}")
            return await call_next(request)

        # 0.1. CORS preflight (OPTIONS): пропускаем, чтобы браузер
        #      получил корректные CORS-заголовки от CORSMiddleware.
        if method == "OPTIONS":
            api_logger.debug(f"🔓 CORS preflight: {path}")
            return await call_next(request)

        # 1. Проверка, является ли путь публичным.
        #    ВАЖНО: эта проверка идёт ДО всех ingest-веток и проверки
        #    settings.API_KEY_HEADER, поэтому префикс из PUBLIC_PATHS делает
        #    вложенные пути публичными, не затрагивая соседние ветки.
        if self._is_public_path(path):
            api_logger.debug(f"🔓 Public path: {path}")
            return await call_next(request)

        client_ip = self._get_client_ip(request)

        # 2. Ingest-логи мобильного клиента: APP_CLIENT_SUPPORT_INGEST_API_KEYS.
        if _is_logs_ingest_path(path):
            if not getattr(settings, "APP_CLIENT_SUPPORT_LOGS_INGEST_ENABLED", True):
                api_logger.warning(f"⚠️ Logs ingest disabled, path={path}")
                return JSONResponse(
                    status_code=404,
                    content={
                        "error": "NotFound",
                        "message": "Logs ingest is disabled",
                        "path": path,
                    },
                )

            api_key = request.headers.get(settings.API_KEY_HEADER)
            if not api_key:
                api_logger.warning(f"⚠️ Missing ingest API key for {path} (client={client_ip})")
                return self._unauthorized_response(
                    path=path,
                    client_ip=client_ip,
                    status_code=401,
                    error="Unauthorized",
                    message="Missing ingest API key. Please provide key header.",
                )

            valid_keys = list(getattr(settings, "APP_CLIENT_SUPPORT_INGEST_API_KEYS", []) or [])
            if not valid_keys:
                api_logger.warning("⚠️ APP_CLIENT_SUPPORT_INGEST_API_KEYS пуст — /api/v1/logs/* отклоняется")
                return self._unauthorized_response(
                    path=path,
                    client_ip=client_ip,
                    status_code=503,
                    error="ServiceUnavailable",
                    message="Ingest keys not configured.",
                )

            if not self.is_valid_key_for(api_key, valid_keys):
                api_logger.warning(f"⚠️ Invalid client-support ingest key for {path} (client={client_ip})")
                return self._unauthorized_response(
                    path=path,
                    client_ip=client_ip,
                    status_code=403,
                    error="Forbidden",
                    message="Invalid ingest API key.",
                )

            request.state.user = {
                "api_key": api_key,
                "role": "logs_ingest_client",
                "client_ip": client_ip,
            }
            return await call_next(request)

        # 2.1. Client: auth by TApps.FKey (группа 3)
        if _is_client_tapps_path(path):
            api_key = request.headers.get(settings.API_KEY_HEADER)
            if not api_key:
                api_logger.warning(f"⚠️ Missing device API key for {path} (client={client_ip})")
                return JSONResponse(
                    status_code=401,
                    content={
                        "scs": 0,
                        "err": settings.APP_CLIENT_ERROR_DEVICE_NOT_REGISTERED,
                        "msg": f"Missing API key. Provide {settings.API_KEY_HEADER} header.",
                        "rtr": "register",
                        "reason": "missing_key",
                    },
                )

            ok, reason = await self._check_tapps_key(api_key)
            if not ok:
                api_logger.warning(
                    "⚠️ Device key rejected for %s (client=%s, reason=%s)",
                    path,
                    client_ip,
                    reason,
                )
                return self._tapps_error_response(reason)

            request.state.user = {
                "api_key": api_key,
                "role": "client_tapps",
                "client_ip": client_ip,
            }
            return await call_next(request)

        # 2.2. Client: register/login/stats/health/note (группы 1,2,5,6)
        if _is_client_sync_ingest_path(path):
            api_key = request.headers.get(settings.API_KEY_HEADER)
            if not api_key:
                api_logger.warning(f"⚠️ Missing client-sync API key for {path} (client={client_ip})")
                return self._unauthorized_response(
                    path=path,
                    client_ip=client_ip,
                    status_code=401,
                    error="Unauthorized",
                    message=f"Missing API key. Please provide {settings.API_KEY_HEADER} header.",
                )

            valid_keys = list(getattr(settings, "APP_CLIENT_SYNC_INGEST_API_KEYS", []) or [])
            if not valid_keys:
                api_logger.warning("⚠️ APP_CLIENT_SYNC_INGEST_API_KEYS пуст — client-sync отклоняется")
                return self._unauthorized_response(
                    path=path,
                    client_ip=client_ip,
                    status_code=503,
                    error="ServiceUnavailable",
                    message="Client-sync keys not configured.",
                )

            if not self.is_valid_key_for(api_key, valid_keys):
                api_logger.warning(f"⚠️ Invalid client-sync key for {path} (client={client_ip})")
                return self._unauthorized_response(
                    path=path,
                    client_ip=client_ip,
                    status_code=403,
                    error="Forbidden",
                    message="Invalid client-sync API key.",
                )

            request.state.user = {
                "api_key": api_key,
                "role": "client_sync",
                "client_ip": client_ip,
            }
            return await call_next(request)

        # 2.3. Client: update-check (группа 4) — APP_CLIENT_SUPPORT_INGEST_API_KEYS
        if _is_client_support_path(path):
            api_key = request.headers.get(settings.API_KEY_HEADER)
            if not api_key:
                api_logger.warning(f"⚠️ Missing support API key for {path} (client={client_ip})")
                return self._unauthorized_response(
                    path=path,
                    client_ip=client_ip,
                    status_code=401,
                    error="Unauthorized",
                    message=f"Missing API key. Please provide {settings.API_KEY_HEADER} header.",
                )

            valid_keys = list(getattr(settings, "APP_CLIENT_SUPPORT_INGEST_API_KEYS", []) or [])
            if not valid_keys:
                api_logger.warning("⚠️ APP_CLIENT_SUPPORT_INGEST_API_KEYS пуст — update-check отклоняется")
                return self._unauthorized_response(
                    path=path,
                    client_ip=client_ip,
                    status_code=503,
                    error="ServiceUnavailable",
                    message="Support keys not configured.",
                )

            if not self.is_valid_key_for(api_key, valid_keys):
                api_logger.warning(f"⚠️ Invalid support key for {path} (client={client_ip})")
                return self._unauthorized_response(
                    path=path,
                    client_ip=client_ip,
                    status_code=403,
                    error="Forbidden",
                    message="Invalid support API key.",
                )

            request.state.user = {
                "api_key": api_key,
                "role": "client_support",
                "client_ip": client_ip,
            }
            return await call_next(request)

        # 3. Доверенные хосты — без ключа
        if self._is_trusted_host(client_ip):
            api_logger.info(f"🔓 Trusted host {client_ip} -> {path} (no API key required)")
            request.state.user = {
                "api_key": None,
                "role": "trusted_host",
                "client_ip": client_ip,
            }
            return await call_next(request)

        # 4. Основной API-ключ (API_KEYS)
        api_key = request.headers.get(settings.API_KEY_HEADER)
        if not api_key:
            api_logger.warning(f"⚠️ Missing API key for {path} (client={client_ip})")
            return self._unauthorized_response(
                path=path,
                client_ip=client_ip,
                status_code=401,
                error="Unauthorized",
                message=f"Missing API key. Please provide {settings.API_KEY_HEADER} header.",
            )

        if not self._is_valid_api_key(api_key):
            api_logger.warning(f"⚠️ Invalid API key for {path} (client={client_ip})")
            return self._unauthorized_response(
                path=path,
                client_ip=client_ip,
                status_code=403,
                error="Forbidden",
                message="Invalid API key.",
            )

        request.state.user = {
            "api_key": api_key,
            "role": "admin",
            "client_ip": client_ip,
        }
        return await call_next(request)

    # ============================================================
    # 1.2. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================

    @staticmethod
    def _is_websocket_upgrade(request: Request) -> bool:
        """Проверка, что запрос — WebSocket upgrade."""
        upgrade = request.headers.get("upgrade", "").lower()
        connection = request.headers.get("connection", "").lower()
        return upgrade == "websocket" and "upgrade" in connection

    @classmethod
    def _get_public_paths(cls) -> list[str]:
        """
        Возвращает список публичных путей, включая динамические:
        relay-ingest и WS-эндпоинт (если WS_NOTIFY_ENABLED=true).

        Returns:
            list[str]: Полный список публичных путей
        """
        paths = list(cls.PUBLIC_PATHS)

        if getattr(settings, "WS_NOTIFY_ENABLED", False):
            # Relay ingest: путь из настроек, по умолчанию /internal/push
            ingest_path = getattr(settings, "WS_RELAY_INGEST_PATH", None) or "/internal/push"
            paths.append(ingest_path)

            # WebSocket endpoint: путь из настроек, по умолчанию /ws/notify
            ws_path = getattr(settings, "WS_NOTIFY_PATH", None) or "/ws/notify"
            paths.append(ws_path)

        return paths

    @classmethod
    def _is_public_path(cls, path: str) -> bool:
        """
        Проверка, является ли путь публичным.

        Использует точное совпадение или префикс с "/":
        - "/api/docs" совпадёт с "/api/docs" и "/api/docs/..."
        - "/api/v1/health" НЕ совпадёт с "/api/v1/health-check"
        - "/internal/push" — точное совпадение (не префикс)
        - "/api/v1/update/public" совпадёт с "/api/v1/update/public/<file>"

        Args:
            path: Путь запроса

        Returns:
            bool: True если путь публичный (не требует аутентификации)
        """
        # Точное совпадение для корня
        if path == "/":
            return False

        for public_path in cls._get_public_paths():
            # Точное совпадение
            if path == public_path:
                return True
            # Префикс с "/" (для подресурсов вроде /api/docs/swagger-ui.css)
            if path.startswith(public_path + "/"):
                return True

        return False

    def _is_trusted_host(self, client_ip: str) -> bool:
        """
        Проверка, является ли IP-адрес доверенным.

        Поддерживает:
        - Точные IPv4/IPv6 адреса: "192.168.12.1", "::1"
        - CIDR-подсети: "192.168.12.0/24", "10.0.0.0/8"

        Args:
            client_ip: IP-адрес клиента

        Returns:
            bool: True если хост доверенный
        """
        if not client_ip or client_ip == "unknown":
            return False

        try:
            ip = ipaddress.ip_address(client_ip)
        except ValueError:
            api_logger.warning(f"⚠️ Invalid client IP: {client_ip!r}")
            return False

        for trusted in self._get_trusted_hosts():
            try:
                if "/" in trusted:
                    network = ipaddress.ip_network(trusted, strict=False)
                    if ip in network:
                        return True
                else:
                    if ip == ipaddress.ip_address(trusted):
                        return True
            except ValueError:
                api_logger.warning(f"⚠️ Invalid trusted host entry: {trusted!r}")
                continue

        return False

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """
        Получение IP-адреса клиента с учётом X-Forwarded-For / X-Real-IP.

        Args:
            request: Объект запроса

        Returns:
            str: IP-адрес клиента или "unknown"
        """
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
            if client_ip:
                return client_ip

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        client = request.client
        if client is not None and client.host is not None:
            return client.host

        return "unknown"

    @classmethod
    def _get_trusted_hosts(cls) -> list[str]:
        """
        Получение списка доверенных хостов.

        Приоритет:
        1. settings.API_TRUSTED_HOSTS (если задан и не пустой)
        2. cls.DEFAULT_TRUSTED_HOSTS (значения по умолчанию)

        Returns:
            list[str]: Список доверенных IP/подсетей
        """
        from_settings = getattr(settings, "API_TRUSTED_HOSTS", None)
        if from_settings:
            if isinstance(from_settings, list):
                return [str(h) for h in from_settings]
            if isinstance(from_settings, str):
                return [h.strip() for h in from_settings.split(",") if h.strip()]
        return cls.DEFAULT_TRUSTED_HOSTS

    @classmethod
    def _is_valid_api_key(cls, api_key: str) -> bool:
        """
        Проверка валидности основного API ключа (API_KEYS).

        Использует hmac.compare_digest для защиты от timing-атак.

        Args:
            api_key: API ключ из заголовка запроса

        Returns:
            bool: True если ключ валидный
        """
        valid_keys = getattr(settings, "API_KEYS", []) or []
        if not valid_keys:
            api_logger.critical("🚨 API_KEYS is not configured! API is not protected.")
            return False
        return cls.is_valid_key_for(api_key, [str(k) for k in valid_keys])

    @staticmethod
    async def _check_tapps_key(api_key: str) -> tuple[bool, str | None]:
        """Проверить ``tkn``-заголовок по расшифрованным ``fid`` + ``prm1``.

        ``TApps.FKey`` хранит полный 7-полевой токен, но ``buildToken()``
        шифрует его заново при каждом вызове (случайный nonce), поэтому
        побайтовое сравнение невозможно. Аутентификация идёт по паре
        ``fid`` + ``prm1 (usi)`` из расшифрованного токена.

        fail-closed: пустой ключ, ошибка расшифровки, сбой БД,
        отсутствие/неактивная запись → (False, reason).
        """
        if not api_key:
            return False, "invalid_key"

        from ...ws.token_crypto import decrypt_ws_token

        payload = decrypt_ws_token(api_key)
        if payload is None or not payload.has_usi:
            return False, "invalid_key"

        from ...db import db_manager
        from ...db.repositories import AppRepository

        try:
            async with db_manager.get_session() as session:
                app = await AppRepository.get_app_by_fid(session, payload.fcm_id)
                if app is None or app.FUserID != payload.user_id:
                    return False, "device_not_found"
                if not bool(app.FIsActive):
                    return False, "device_inactive"
                # complete: edit TApps.FLastSeenAt
                app.FLastSeenAt = datetime_now()
                await session.commit()
                return True, None
        except Exception as exc:
            api_logger.error(f"❌ TApps key check failed: {exc!r}", exc_info=True)
            return False, "db_error"

    @staticmethod
    def _tapps_error_response(reason: str | None) -> JSONResponse:
        """Единый ответ клиенту: требуется /client/register."""
        status = {
            "invalid_key": 401,
            "device_not_found": 404,
            "device_inactive": 403,
        }.get(reason or "", 401)
        return JSONResponse(
            status_code=status,
            content={
                "scs": 0,
                "err": settings.APP_CLIENT_ERROR_DEVICE_NOT_REGISTERED,
                "msg": "Device not registered; call POST /api/v1/client/register",
                "rtr": "register",
                "reason": reason,
            },
        )

    @staticmethod
    def is_valid_key_for(api_key: str, valid_keys: list[str]) -> bool:
        """Constant-time проверка ключа против набора valid_keys.

        fail-closed: пустой набор → всегда False.
        Все элементы набора приводятся к str (защита от случайных
        int/bytes в конфиге).
        """
        if not valid_keys:
            return False
        provided: bytes = api_key.encode("utf-8")
        result = False
        for valid in valid_keys:
            candidate: bytes = str(valid).encode("utf-8")
            # Сравниваем ВСЕ элементы, чтобы время не зависело от позиции совпадения
            if hmac.compare_digest(provided, candidate):
                result = True
        return result

    @staticmethod
    def _unauthorized_response(
        path: str,
        client_ip: str,
        status_code: int,
        error: str,
        message: str,
    ) -> JSONResponse:
        """
        Формирует JSON-ответ об ошибке аутентификации.

        В production не раскрывает client_ip в теле ответа.
        """
        content: dict[str, object] = {
            "error": error,
            "message": message,
            "path": path,
        }
        if _is_dev_env():
            content["client_ip"] = client_ip
        return JSONResponse(status_code=status_code, content=content)


__all__ = [
    "AuthMiddleware",
    "VerifiedToken",
    "verify_token",
    "extract_request_client_ip",
    "extract_websocket_client_ip",
    "upsert_tapps",
]
