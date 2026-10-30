"""Расшифровка WS-токена мобильного клиента (AES-256-GCM).

Формат токена (см. NotificationsWsService.buildWsToken):
    base64(iv(12) || ciphertext || tag(16))

plaintext (обязательный, строго позиционный формат):
    "FID|usrXXXX|yyMMdd|ver|code"

    где:
        FID — Firebase Installation ID (dvc в процедуре Avanpost)
        usrXXXX — Tinode user id (он же usi для Avanpost)
        yyMMdd — дата токена (tkn)
        ver — versionName мобильного приложения
        code — versionCode мобильного приложения

Ровно 5 компонентов через '|'. Любое отклонение — невалидный токен:
  * неверное количество компонентов (не 5);
  * пустой компонент;
  * компонент содержит '=' (старый kv-формат не поддерживается);
  * невалидный user_id (не начинается с 'usr');
  * невалидная/просроченная/будущая дата;
  * невалидный versionCode (не число).

Хранимая процедура ext.PA_mbl_TokenVerify_Exec требует непустые
usi/api/dvc/tkn/cip. usi ОБЯЗАТЕЛЕН и ВСЕГДА равен user_id (usrXXXX).
Никакой подмены usi через отдельное поле "usi=" не допускается —
это исключает подделку идентичности клиентом.

Ключ AES-256 берётся из настроек (WS_TOKEN_KEY_B64) — base64(32 байта).
Ключ ДОЛЖЕН совпадать с BuildConfig.WS_TOKEN_KEY в Android-клиенте.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import re
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings
from ..logger import api_logger

_IV_LEN = 12
_TAG_LEN = 16
_MIN_LEN = _IV_LEN + _TAG_LEN + 1

_USER_ID_RE = re.compile(r"^usr[A-Za-z0-9_\-]{4,}$")

# Ограничения (защита от мусора/DoS).
_MAX_FCM_ID_LEN = 255
_MAX_APP_VERSION_LEN = 32
_MAX_APP_VERSION_CODE_LEN = 10
_MAX_USER_HASH_LEN = 64
_MAX_TOKEN_DATE_LEN = 16

# Обязательные компоненты plaintext.
# Позиции: FID, usrXXXX, yyMMdd, ver, code — ровно 5.
_EXPECTED_PARTS = 5

# Порядок extra-компонентов (позиции 3 и 4).
_EXTRA_POSITIONAL_ORDER = ("ver", "code")

# Обязательные extra-компоненты.
# usi НЕ входит в этот набор: он всегда равен user_id и не передаётся
# отдельным полем.
_REQUIRED_EXTRA_KEYS = frozenset({"ver", "code"})


@dataclass(frozen=True)
class WsTokenData:
    """Результат расшифровки WS-токена.

    Все поля обязательны. Токен без какого-либо поля считается
    невалидным, и ``decrypt_ws_token`` возвращает ``None``.

    Attributes:
        fcm_id: полный Firebase Installation ID (FID), как пришёл в plaintext.
        user_id: Tinode user id, начинается с "usr".
        date: дата токена в формате yyMMdd.
        app_version: versionName мобильного приложения — обязателен.
        app_version_code: versionCode мобильного приложения — обязателен.
    """

    fcm_id: str
    user_id: str
    date: str
    app_version: str
    app_version_code: int


def _normalize_b64(value: str) -> bytes:
    """URL-safe -> стандартный base64, восстановить padding."""
    s = (value or "").strip().replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return base64.b64decode(s, validate=False)


def _load_key() -> bytes:
    raw = (getattr(settings, "WS_TOKEN_KEY_B64", "") or "").strip()
    if not raw:
        raise RuntimeError("WS_TOKEN_KEY_B64 is not configured")
    key = _normalize_b64(raw)
    if len(key) != 32:
        raise RuntimeError(f"WS_TOKEN_KEY_B64 must decode to 32 bytes, got {len(key)}")
    return key


def _parse_extra_parts(parts: list[str]) -> dict[str, str] | None:
    """Строго позиционный разбор extra-компонентов plaintext.

    Поддерживается только формат:
        "FID|usrXXXX|yyMMdd|ver|code"

    Returns:
        dict {"ver": ..., "code": ...} при успехе, ``None`` при любой
        ошибке формата:
          - неверное количество компонентов;
          - пустой компонент;
          - компонент содержит "=" (старый kv-формат НЕ поддерживается).
    """
    if len(parts) != len(_EXTRA_POSITIONAL_ORDER):
        return None

    result: dict[str, str] = {}
    for idx, part in enumerate(parts):
        part = part.strip()
        if not part or "=" in part:
            return None
        result[_EXTRA_POSITIONAL_ORDER[idx]] = part
    return result


def decrypt_ws_token(token_b64: str) -> WsTokenData | None:
    """Расшифровать и провалидировать WS-токен.

    Возвращает ``None`` при любой ошибке (не логируя сам plaintext).

    Обязательный формат plaintext (позиционный, ровно 5 компонентов):
        "FID|usrXXXX|yyMMdd|ver|code"

    Старый формат с префиксами usi=/ver=/code= НЕ поддерживается.
    Отсутствие любого обязательного поля — невалидный токен.
    """
    if not token_b64:
        api_logger.warning("ws_token: empty token")
        return None

    api_logger.info("ws_token: decrypt START token_len=%d prefix=%r", len(token_b64), token_b64[:12])

    try:
        blob = _normalize_b64(token_b64)
    except (binascii.Error, ValueError) as e:
        api_logger.warning("ws_token: base64 decode failed: %r", e)
        return None

    api_logger.info("ws_token: decoded %d bytes (min=%d)", len(blob), _MIN_LEN)

    if len(blob) < _MIN_LEN:
        api_logger.warning(
            "ws_token: too short (%d < %d) — wrong key or truncated token",
            len(blob),
            _MIN_LEN,
        )
        return None

    iv = blob[:_IV_LEN]
    ct = blob[_IV_LEN:]

    try:
        key = _load_key()
        api_logger.info("ws_token: key loaded len=%d", len(key))
    except Exception as key_err:
        api_logger.error("ws_token: _load_key FAILED: %r", key_err, exc_info=True)
        return None

    try:
        plaintext = AESGCM(key).decrypt(iv, ct, associated_data=None)
        api_logger.info("ws_token: AES-GCM decrypt OK, plaintext_len=%d", len(plaintext))
    except Exception as e:
        api_logger.warning(
            "ws_token: AES-GCM decrypt failed (InvalidTag?) err=%r "
            "— вероятно, WS_TOKEN_KEY_B64 не совпадает с ключом клиента",
            e,
        )
        return None

    try:
        text = plaintext.decode("utf-8")
        api_logger.info("ws_token: plaintext=%r", text[:120])
    except UnicodeDecodeError as e:
        api_logger.warning("ws_token: not utf-8: %r", e)
        return None

    parts = text.split("|")
    api_logger.info("ws_token: parts count=%d parts=%r", len(parts), parts)

    if len(parts) != _EXPECTED_PARTS:
        api_logger.warning(
            "ws_token: unexpected parts count %d (expected %d) — клиент использует старый формат с usi=/ver=/code=?",
            len(parts),
            _EXPECTED_PARTS,
        )
        return None

    fcm_id = parts[0].strip()
    user_id = parts[1].strip()
    date_str = parts[2].strip()
    extra_parts = parts[3:]

    if not fcm_id:
        api_logger.warning("ws_token: empty fcm_id")
        return None
    if len(fcm_id) > _MAX_FCM_ID_LEN:
        api_logger.warning("ws_token: fcm_id too long %d", len(fcm_id))
        return None

    if not _USER_ID_RE.match(user_id):
        api_logger.warning("ws_token: invalid user_id %r (regex %s)", user_id, _USER_ID_RE.pattern)
        return None

    if not date_str or len(date_str) > _MAX_TOKEN_DATE_LEN:
        api_logger.warning("ws_token: invalid date length %r", date_str)
        return None
    try:
        token_date = dt.datetime.strptime(date_str, "%y%m%d").date()
        today = dt.date.today()
        api_logger.info(
            "ws_token: date=%s today=%s delta_days=%d",
            token_date,
            today,
            (today - token_date).days,
        )
        if token_date > today + dt.timedelta(days=1):
            api_logger.warning("ws_token: date in future %s", date_str)
            return None
        if (today - token_date).days > 31:
            api_logger.warning("ws_token: date too old %s (delta=%d days)", date_str, (today - token_date).days)
            return None
    except ValueError:
        api_logger.warning("ws_token: invalid date format %r (expected yyMMdd)", date_str)
        return None

    extra = _parse_extra_parts(extra_parts)
    if extra is None:
        api_logger.warning(
            "ws_token: invalid extra parts %r — ожидается [ver, code] без префиксов и без '='",
            extra_parts,
        )
        return None

    missing = _REQUIRED_EXTRA_KEYS - extra.keys()
    if missing:
        api_logger.warning("ws_token: missing extra keys %s (got %s)", sorted(missing), sorted(extra.keys()))
        return None

    app_version = extra["ver"]
    try:
        app_version_code = int(extra["code"])
    except ValueError:
        api_logger.warning("ws_token: invalid versionCode %r", extra["code"])
        return None

    api_logger.info(
        "ws_token: OK fcm=%s... user=%s ver=%s code=%d date=%s",
        fcm_id[-6:],
        user_id,
        app_version,
        app_version_code,
        date_str,
    )

    return WsTokenData(
        fcm_id=fcm_id,
        user_id=user_id,
        date=date_str,
        app_version=app_version,
        app_version_code=app_version_code,
    )


__all__ = ["WsTokenData", "decrypt_ws_token"]
