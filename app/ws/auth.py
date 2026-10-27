"""Проверка токена мобильного клиента для WS-подключения.

Два режима (WS_NOTIFY_TOKEN_VERIFY_MODE):
- "trust": доверять переданному user_id (только development);
- "grpc": проверять через Tinode gRPC (production).

Используется простой in-memory кеш с TTL, чтобы не дёргать Tinode на каждое подключение.

ВАЖНО: для проверки токенов используется ОТДЕЛЬНЫЙ TeamdroidClient,
а не singleton get_teamdroid_client(), потому что повторный LOGIN в той же
gRPC-сессии перезапишет root-аутентификацию и сломает send-text/send-files.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..config import settings
from ..logger import api_logger

# In-memory кеш: token -> (user_id | None, expiry_timestamp)
_cache: dict[str, tuple[str | None, float]] = {}
_cache_lock = asyncio.Lock()

# Отдельный клиент для проверки токенов (лениво создаётся).
_auth_client: Any = None
_auth_client_lock = asyncio.Lock()


async def _get_auth_client() -> Any:
    """Лениво создаёт отдельный TeamdroidClient для проверки токенов.

    Не использует singleton get_teamdroid_client(), чтобы не затирать
    root-сессию, которая нужна для send-text/send-files/grant-user.
    """
    global _auth_client
    async with _auth_client_lock:
        if _auth_client is not None:
            return _auth_client

        # Импорт здесь, чтобы избежать циклических зависимостей.
        from ..api.routers.teamdroid import TeamdroidClient

        client = TeamdroidClient(
            host=settings.TEAMDROID_HOST,
            username=settings.TEAMDROID_USERNAME,
            password=settings.TEAMDROID_PASSWORD,
        )
        # connect() + hi() — блокирующие, выполняем в потоке.
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
            except Exception as e:  # noqa: BLE001
                api_logger.warning(f"auth: failed to close auth client: {e!r}")
            _auth_client = None


async def _verify_via_tinode(token: str) -> str | None:
    """Проверка токена через Tinode gRPC.

    Использует ОТДЕЛЬНЫЙ TeamdroidClient (не singleton), чтобы не затирать
    root-сессию. Вызов блокирующий, выполняется в отдельном потоке.
    """

    def _do_verify() -> tuple[str | None, dict | None]:
        try:
            client = _auth_client
            if client is None:
                return None, {"error": "auth_client_not_created"}
            rec = client.login_with_token(token)
            api_logger.info("auth: login_with_token raw result: %r", rec)
            if not rec:
                return None, {"error": "login_with_token_returned_none"}
            if not rec.get("user"):
                return None, {"error": "no_user_in_ctrl", "ctrl": rec}
            return str(rec["user"]), None
        except Exception as e:
            api_logger.exception("auth: Tinode gRPC verification raised")
            return None, {"error": repr(e)}

    try:
        client = await _get_auth_client()
    except Exception as e:
        api_logger.error(f"auth: failed to create auth client: {e!r}", exc_info=True)
        return None

    user_id, diag = await asyncio.to_thread(_do_verify)

    # Если клиент «сломался» (running=False), сбрасываем его, чтобы следующий
    # вызов пересоздал.
    if not getattr(client, "running", False):
        api_logger.warning("auth: auth client not running (diag=%r), resetting", diag)
        await _reset_auth_client()

    if diag:
        api_logger.warning("auth: verify failed diag=%r", diag)

    return user_id


async def verify_ws_token(token: str | None) -> str | None:
    """Проверяет токен в соответствии с режимом из настроек."""
    if not token:
        api_logger.warning("auth: empty token")
        return None

    mode = settings.ws_notify_verify_mode
    env = (settings.APP_ENV or "").lower()
    api_logger.info(
        "auth: verify_ws_token mode=%s env=%s token_prefix=%r len=%d",
        mode,
        env,
        token[:12],
        len(token),
    )

    if mode == "trust":
        if env not in ("development", "dev"):
            api_logger.error("auth: 'trust' mode is forbidden in production. Denying connection.")
            return None
        if not (token.startswith("usr") and len(token) > 5):
            api_logger.warning(f"auth: invalid token format in trust mode: {token}")
            return None
        return token

    # mode == "grpc"
    now = time.time()
    async with _cache_lock:
        cached = _cache.get(token)
        if cached and cached[1] > now:
            api_logger.debug("auth: cache hit for token")
            return cached[0]
        if cached:
            api_logger.info("auth: cache expired user=%r", cached[0])

    user_id = await _verify_via_tinode(token)

    ttl = max(1, settings.WS_NOTIFY_TOKEN_CACHE_TTL)
    async with _cache_lock:
        _cache[token] = (user_id, now + ttl)

    if user_id:
        api_logger.info(f"auth: token verified for user {user_id}")
    else:
        api_logger.warning("auth: token verification failed (will be cached as None for %ds)", ttl)

    return user_id
