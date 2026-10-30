"""Проверка токена мобильного клиента для WS-подключения.

Поддерживаемые режимы (``settings.WS_NOTIFY_TOKEN_VERIFY_MODE``):
- ``trust``     — доверять переданному user_id (только development);
- ``grpc``      — проверять через Tinode gRPC (production);
- ``avanpost``  — проверять через Teamdroid SQL Server (production).

CHANGED: режим ``avanpost`` теперь вызывает
``TeamdroidProcedureRepository.verify_token`` (см.
``app/db/repositories/teamdroid.py``), а не Avanpost (``DB_AVANPOST_*``).
Процедура ``ext.PA_mbl_TokenVerify_Exec`` — это Teamdroid-процедура
(``TEAMDROID_SQL_*``), так же как ``ext.PA_mbl_MsgsDeliveryStatus_Edit``
и ``ext.PA_mbl_AuthStart_Exec``/``ext.PA_mbl_AuthFinish_Exec``.

Используется простой in-memory кеш с TTL, чтобы не дёргать SQL Server
на каждое подключение.

Для проверки токенов через gRPC используется ОТДЕЛЬНЫЙ TeamdroidClient,
а не singleton ``get_teamdroid_client()``, потому что повторный LOGIN
в той же gRPC-сессии перезапишет root-аутентификацию и сломает
send-text/send-files.

Расшифровка токена делегируется ``token_crypto.decrypt_ws_token`` —
единый формат plaintext, все обязательные поля (usi, ver, code)
проверяются на уровне ``decrypt_ws_token``. Токен без обязательных
полей отвергается до обращения к Teamdroid SQL Server.

Безопасность режима ``avanpost``
--------------------------------
Проверка токена через
``TeamdroidProcedureRepository.verify_token`` — процедура требует
непустые usi/api/dvc/tkn/cip; отсутствие usi обрабатывается как
отказ (fail-closed).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Any

from ..config import settings
from ..db.repositories import TeamdroidProcedureRepository  # CHANGED
from ..logger import api_logger
from .token_crypto import decrypt_ws_token

# ============================================================
# Результат проверки
# ============================================================


@dataclass(frozen=True)
class VerifiedToken:
    """Результат проверки WS-токена.

    Attributes:
        user_id: Tinode user ID (``usrXXX``) или ``None``, если проверка
            не удалась.
        fcm_id: Firebase Installation ID, извлечённый из токена.
    """

    user_id: str | None
    fcm_id: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.user_id and self.user_id.startswith("usr"))


# ============================================================
# Кеш и auth-клиент
# ============================================================


@dataclass
class _CacheEntry:
    """Запись кеша: результат проверки + абсолютное время истечения."""

    verified: VerifiedToken
    expires_at: float
    token_hash: str


# In-memory кеш: token -> _CacheEntry
_cache: dict[str, _CacheEntry] = {}
_cache_lock = asyncio.Lock()

# Отдельный клиент для проверки токенов через Tinode gRPC (лениво).
_auth_client: Any = None
_auth_client_lock = asyncio.Lock()


# ============================================================
# Хелперы
# ============================================================


def _hash_token_for_log(token: str) -> str:
    """Короткий хеш токена для логов (без утечки самого токена)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def _as_str_or_none(value: Any) -> str | None:
    """Приводит значение к ``str | None`` без вызова ``str()`` от ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _safe_int(value: Any) -> int | None:
    """Безопасно приводит к int (None, если нельзя)."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ============================================================
# Проверка через Teamdroid SQL Server (CHANGED)
# ============================================================


async def _verify_token_in_teamdroid(
    fcm_id: str | None,
    user_id: str | None,
    app_version: str | None,
    app_version_code: int | str | None,
    app_id: int | None,
    token_date: str | None,
    client_ip: str | None,
) -> bool:
    """Проверяет токен в Teamdroid SQL Server (ext.PA_mbl_TokenVerify_Exec).

    Вызывается через TeamdroidProcedureRepository.verify_token,
    который использует singleton-соединение из app.db.manager
    (TEAMDROID_SQL_*).

    Поведение:
    - Если ``fcm_id``/``user_id`` пустые или ``user_id``
      не начинается с ``usr`` — отказ (быстрая проверка формы).
    - В **development/dev** принимаем токен «по форме» (для отладки).
    - В **production** вызываем TeamdroidProcedureRepository.verify_token.

    Args:
        fcm_id: Firebase Installation ID.
        user_id: Tinode user ID.
        app_version: Версия приложения.
        app_version_code: Числовой код версии приложения.
        app_id: AppID приложения (dir.TRSDirSysApps.FID).
        token_date: Дата токена yyMMdd ($.tkn).
        client_ip: IP клиента ($.cip).

    Returns:
        ``True`` — токен действителен, ``False`` — отказ.
    """
    # ---------- 1. Быстрая проверка формы ----------
    if not fcm_id or not user_id:
        return False
    if not user_id.startswith("usr"):
        return False

    env = (settings.APP_ENV or "").lower()
    is_dev = env in ("development", "dev")
    api_logger.debug(
        "auth(teamdroid): _verify_token_in_teamdroid ENTER env=%s is_dev=%s app_version_code=%r user=%s",
        env,
        is_dev,
        app_version_code,
        user_id,
    )

    # ---------- 2. Dev-режим: принимаем «по форме» ----------
    if is_dev:
        api_logger.info(
            "auth(teamdroid): dev mode, accepting token by shape (fcm=%s..., usi=%s...)",
            (fcm_id or "")[-6:],
            user_id,
        )
        return True

    # ---------- 3. Production: реальная проверка через Teamdroid SQL ----------
    effective_app_id = app_id
    if effective_app_id is None:
        effective_app_id = getattr(settings, "TEAMDROID_APP_ID", 0)

    if not effective_app_id:
        api_logger.error(
            "auth(teamdroid): TEAMDROID_APP_ID is 0 — процедура вернёт THROW (AppID обязателен для поиска устройства)."
        )
        return False

    try:
        ok, err = await asyncio.to_thread(
            TeamdroidProcedureRepository.verify_token,
            user_id=user_id,
            fcm_id=fcm_id,
            app_id=int(effective_app_id),
            token_date=token_date,
            client_ip=client_ip,
            app_version=app_version,
            app_version_code=_safe_int(app_version_code),
        )
    except Exception as exc:  # noqa: BLE001
        api_logger.error("auth(teamdroid): verify_token raised: %r", exc, exc_info=True)
        return False

    if not ok:
        api_logger.warning(
            "auth(teamdroid): rejected user=%s fcm=%s... err=%s",
            user_id,
            (fcm_id or "")[-6:],
            err,
        )
    return bool(ok)


# ============================================================
# Проверка через Tinode gRPC
# ============================================================


async def _get_auth_client() -> Any:
    """Лениво создаёт отдельный TeamdroidClient для проверки токенов."""
    global _auth_client
    async with _auth_client_lock:
        if _auth_client is not None:
            return _auth_client

        from ..api.routers.teamdroid import TeamdroidClient

        client = TeamdroidClient(
            host=settings.TEAMDROID_HOST,
            username=settings.TEAMDROID_USERNAME,
            password=settings.TEAMDROID_PASSWORD,
        )
        await asyncio.to_thread(client.connect)
        await asyncio.to_thread(client.hi)

        _auth_client = client
        return client


async def _reset_auth_client() -> None:
    """Сбрасывает кэшированный auth-клиент (например, после ошибки)."""
    global _auth_client
    async with _auth_client_lock:
        if _auth_client is not None:
            try:
                await asyncio.to_thread(_auth_client.close)
            except Exception as exc:  # noqa: BLE001
                api_logger.warning(f"auth: failed to close auth client: {exc!r}")
            _auth_client = None


async def _verify_via_tinode(token: str) -> VerifiedToken:
    """Проверка токена через Tinode gRPC (отдельный клиент, не singleton)."""

    def _do_verify() -> tuple[VerifiedToken, dict[str, Any] | None]:
        client = _auth_client
        if client is None:
            return (
                VerifiedToken(user_id=None),
                {"error": "auth_client_not_created"},
            )
        try:
            rec = client.login_with_token(token)
        except Exception as login_err:  # noqa: BLE001
            api_logger.exception("auth: Tinode gRPC verification raised")
            return VerifiedToken(user_id=None), {"error": repr(login_err)}

        api_logger.info("auth: login_with_token raw result: %r", rec)
        if not rec:
            return (
                VerifiedToken(user_id=None),
                {"error": "login_with_token_returned_none"},
            )

        raw_user_id = rec.get("user")
        if not raw_user_id:
            return (
                VerifiedToken(user_id=None),
                {"error": "no_user_in_ctrl", "ctrl": rec},
            )

        raw_fcm_id = rec.get("fcm_id") or (rec.get("params") or {}).get("fcm_id")

        return (
            VerifiedToken(
                user_id=_as_str_or_none(raw_user_id),
                fcm_id=_as_str_or_none(raw_fcm_id),
            ),
            None,
        )

    try:
        auth_client = await _get_auth_client()
    except Exception as exc:  # noqa: BLE001
        api_logger.error(f"auth: failed to create auth client: {exc!r}", exc_info=True)
        return VerifiedToken(user_id=None)

    verified, diag = await asyncio.to_thread(_do_verify)

    if not getattr(auth_client, "running", False):
        api_logger.warning("auth: auth client not running (diag=%r), resetting", diag)
        await _reset_auth_client()

    if diag:
        api_logger.warning("auth: verify failed diag=%r", diag)

    return verified


# ============================================================
# Проверка через Teamdroid SQL Server (публичная обёртка)
# ============================================================


async def _verify_via_avanpost(
    token: str,
    client_ip: str | None = None,
) -> VerifiedToken:
    """Проверка токена через Teamdroid SQL Server.

    CHANGED: раньше ходили в Avanpost (DB_AVANPOST_*) — теперь в
    Teamdroid SQL Server (TEAMDROID_SQL_*), потому что
    ext.PA_mbl_TokenVerify_Exec — Teamdroid-процедура.

    Расшифровывает токен (FID|usrXXXX|yyMMdd|ver|code), извлекает
    FID/usrXXXX/дату/версию и вызывает _verify_token_in_teamdroid.

    Args:
        token: base64-строка токена.
        client_ip: IP клиента (передаётся в процедуру как $.cip).
    """
    api_logger.debug("auth(teamdroid): decrypt start client_ip=%r", client_ip)

    payload = decrypt_ws_token(token)
    if payload is None:
        api_logger.warning("auth(teamdroid): decrypt_ws_token returned None -> REJECT")
        return VerifiedToken(user_id=None)

    api_logger.info(
        "auth(teamdroid): payload user=%s fcm=%s... ver=%s code=%s date=%s",
        payload.user_id,
        (payload.fcm_id[-6:] if len(payload.fcm_id) >= 6 else "***"),
        payload.app_version,
        payload.app_version_code,
        payload.date,
    )

    app_id = getattr(settings, "TEAMDROID_APP_ID", 0)
    api_logger.info("auth(teamdroid): app_id=%s", app_id)

    ok = await _verify_token_in_teamdroid(
        fcm_id=payload.fcm_id,
        user_id=payload.user_id,
        app_version=payload.app_version,
        app_version_code=payload.app_version_code,
        app_id=app_id,
        token_date=payload.date,
        client_ip=client_ip,
    )

    api_logger.info("auth(teamdroid): verify_token ok=%s user=%s", ok, payload.user_id)

    if not ok:
        return VerifiedToken(user_id=None, fcm_id=payload.fcm_id)
    return VerifiedToken(user_id=payload.user_id, fcm_id=payload.fcm_id)


# ============================================================
# Публичный API
# ============================================================


async def verify_ws_token(
    token: str | None,
    client_ip: str | None = None,
) -> VerifiedToken:
    """Проверяет токен в соответствии с режимом из настроек.

    Возвращает ``VerifiedToken``; ``.ok is False`` означает отказ.

    Args:
        token: base64-строка токена из query/header.
        client_ip: IP клиента (для режима avanpost — передаётся в процедуру
            как $.cip; для режима grpc игнорируется).
    """
    if not token:
        api_logger.warning("auth: empty token")
        return VerifiedToken(user_id=None)

    mode = settings.ws_notify_verify_mode
    env = (settings.APP_ENV or "").lower()
    token_hash = _hash_token_for_log(token)

    api_logger.info(
        "auth: verify_ws_token mode=%s env=%s token_hash=%s len=%d ip=%r",
        mode,
        env,
        token_hash,
        len(token),
        client_ip,
    )

    # ---------- trust ----------
    if mode == "trust":
        if env not in ("development", "dev"):
            api_logger.error("auth: 'trust' mode is forbidden in production. Denying connection.")
            return VerifiedToken(user_id=None)
        if not (token.startswith("usr") and len(token) > 5):
            api_logger.warning(
                "auth: invalid token format in trust mode (hash=%s)",
                token_hash,
            )
            return VerifiedToken(user_id=None)
        return VerifiedToken(user_id=token)

    # ---------- кеш ----------
    now = time.time()
    async with _cache_lock:
        cached = _cache.get(token)
        if cached is not None:
            if cached.expires_at > now:
                api_logger.debug("auth: cache hit for token")
                return cached.verified
            api_logger.info(
                "auth: cache expired user=%r (hash=%s)",
                cached.verified.user_id,
                cached.token_hash,
            )

    # ---------- проверка ----------
    if mode == "avanpost":
        verified = await _verify_via_avanpost(token, client_ip=client_ip)
    else:
        verified = await _verify_via_tinode(token)

    ttl = max(1, settings.WS_NOTIFY_TOKEN_CACHE_TTL)
    async with _cache_lock:
        _cache[token] = _CacheEntry(
            verified=verified,
            expires_at=now + ttl,
            token_hash=token_hash,
        )

    if verified.ok:
        api_logger.info(
            "auth: token verified for user %s (fcm=%s, hash=%s)",
            verified.user_id,
            (verified.fcm_id or "-")[-6:] if verified.fcm_id else "-",
            token_hash,
        )
    else:
        api_logger.warning(
            "auth: token verification failed (cached as None for %ds, hash=%s)",
            ttl,
            token_hash,
        )

    return verified


def clear_token_cache() -> None:
    """Очищает кеш проверки токенов (для тестов / при logout)."""
    _cache.clear()


__all__ = [
    "VerifiedToken",
    "verify_ws_token",
    "clear_token_cache",
]
