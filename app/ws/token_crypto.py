"""Расшифровка WS-токенов мобильного клиента (AES-256-GCM).

Поддерживаются ДВА формата токена:

1. LEGACY (5 полей) — для /register, DELETE /register, /update-check,
   /sync-load, /sync-edit:

       fid|usrXXXX|yyMMdd|ver|code

   Пример plaintext: ``dX4f..._fid|usrABCdef123|260115|2.5.1|251``

2. NEW (7 полей) — для POST /login:

       fid|sch|prm1|prm2|yyMMdd|appVer|appCode

   где:
       fid     — UUID Firebase, [A-Za-z0-9_\\-]{20,}
       sch     — "1" (логин+пароль) | "2" (request_id + код)
       prm1    — логин (sch=1) | request_id (sch=2)
       prm2    — пароль (sch=1) | код (sch=2)
       yyMMdd  — 6 цифр, дата токена
       appVer  — versionName, клиент заменяет '|' → '_'
       appCode — versionCode, десятичное число

   В plaintext НЕТ usi. usi резолвится через
   ext.PA_mbl_Login_Exec (см. TeamdroidProcedureRepository.login,
   mid=1|2).

Общая часть (для обоих форматов):
    Токен — это base64(iv(12) || ciphertext || tag(16)), где plaintext
    зашифрован AES-256-GCM с ключом WS_TOKEN_KEY_B64 (base64(32 байта)).
    Ключ ДОЛЖЕН совпадать с BuildConfig.WS_TOKEN_KEY в Android-клиенте.

    При любой ошибке (неверный base64, неверный ключ, InvalidTag,
    неверное число полей, невалидная дата, невалидный sch/appCode)
    функция возвращает ``None``.

Безопасность:
    * user_id в NEW-токене отсутствует — резолвится отдельно.
    * Дата токена: [-31; +1] дней от «сегодня» (UTC).
    * Ключ и plaintext НЕ логируются.
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

# Общие ограничения длины (защита от мусора / DoS).
_MAX_FCM_ID_LEN = 255
_MAX_APP_VERSION_LEN = 32
_MAX_TOKEN_DATE_LEN = 16

# Ограничения для prm1/prm2 нового формата.
_MAX_PRM_LEN = 256

# Ограничения для appCode.
_MAX_APP_CODE_DIGITS = 10

# ---- legacy: 5 полей ----
_LEGACY_EXPECTED_PARTS = 5

# ---- new: 7 полей ----
_NEW_EXPECTED_PARTS = 7


# ============================================================
# DATACLASSES
# ============================================================


@dataclass(frozen=True)
class WsTokenDataLegacy:
    """Результат расшифровки LEGACY-токена (5 полей).

    Используется в /register, DELETE /register, /update-check,
    /sync-load, /sync-edit.

    Attributes:
        fcm_id: полный Firebase Installation ID (FID).
        user_id: Tinode user id, начинается с "usr".
        date: дата токена в формате yyMMdd.
        app_version: versionName мобильного приложения.
        app_version_code: versionCode мобильного приложения.
    """

    fcm_id: str
    user_id: str
    date: str
    app_version: str
    app_version_code: int


@dataclass(frozen=True)
class WsTokenData:
    """Результат расшифровки NEW-токена (7 полей).

    Используется в POST /login.

    Поле ``user_id`` в plaintext отсутствует и здесь всегда пустое.
    Вызывающий код (/login) обязан получить usi через
    ``TeamdroidProcedureRepository.login(mid=1|2, ...)``.

    Attributes:
        fcm_id: полный Firebase Installation ID (FID).
        user_id: ВСЕГДА "" (резолвится отдельно).
        sch: схема токена ("1" | "2").
        prm1: первый параметр (клиент заменил '|' → '_').
        prm2: второй параметр (клиент заменил '|' → '_').
        date: дата токена в формате yyMMdd.
        app_version: versionName мобильного приложения.
        app_version_code: versionCode мобильного приложения.
    """

    fcm_id: str
    user_id: str
    sch: str
    prm1: str
    prm2: str
    date: str
    app_version: str
    app_version_code: int


# ============================================================
# НИЗКОУРОВНЕВЫЕ ХЕЛПЕРЫ
# ============================================================


def _normalize_b64(value: str) -> bytes:
    """URL-safe -> стандартный base64, восстановить padding."""
    s = (value or "").strip().replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return base64.b64decode(s, validate=False)


def _load_key() -> bytes:
    """Загрузить ключ AES-256-GCM из WS_TOKEN_KEY_B64 (base64(32 байта))."""
    raw = (getattr(settings, "WS_TOKEN_KEY_B64", "") or "").strip()
    if not raw:
        raise RuntimeError("WS_TOKEN_KEY_B64 is not configured")
    key = _normalize_b64(raw)
    if len(key) != 32:
        raise RuntimeError(f"WS_TOKEN_KEY_B64 must decode to 32 bytes, got {len(key)}")
    return key


def _decrypt_to_plaintext(token_b64: str) -> tuple[str | None, int]:
    """Расшифровать токен и вернуть (plaintext_utf8 | None, blob_len).

    Выполняет: base64 decode → AES-GCM decrypt → utf-8 decode.
    Возвращает ``(None, blob_len)`` при любой ошибке.
    """
    if not token_b64:
        api_logger.warning("ws_token: empty token")
        return None, 0

    try:
        blob = _normalize_b64(token_b64)
    except (binascii.Error, ValueError) as e:
        api_logger.warning("ws_token: base64 decode failed: %r", e)
        return None, 0

    blob_len = len(blob)

    if blob_len < _MIN_LEN:
        api_logger.warning(
            "ws_token: too short (%d < %d) — wrong key or truncated token",
            blob_len,
            _MIN_LEN,
        )
        return None, blob_len

    iv = blob[:_IV_LEN]
    ct = blob[_IV_LEN:]

    try:
        key = _load_key()
    except Exception as key_err:
        api_logger.error("ws_token: _load_key FAILED: %r", key_err, exc_info=True)
        return None, blob_len

    try:
        plaintext = AESGCM(key).decrypt(iv, ct, associated_data=None)
    except Exception as e:
        api_logger.warning(
            "ws_token: AES-GCM decrypt failed (InvalidTag?) err=%r "
            "— вероятно, WS_TOKEN_KEY_B64 не совпадает с ключом клиента",
            e,
        )
        return None, blob_len

    try:
        text = plaintext.decode("utf-8")
    except UnicodeDecodeError as e:
        api_logger.warning("ws_token: not utf-8: %r", e)
        return None, blob_len

    return text, blob_len


def _parse_date(yymmdd: str) -> bool:
    """Проверить yyMMdd: 6 цифр, парсится, в пределах [-31; +1] дней."""
    if not yymmdd or len(yymmdd) != 6 or not yymmdd.isdigit():
        api_logger.warning("ws_token: invalid date %r (expected 6 digits yyMMdd)", yymmdd)
        return False

    if len(yymmdd) > _MAX_TOKEN_DATE_LEN:
        api_logger.warning("ws_token: date too long %d", len(yymmdd))
        return False

    try:
        token_date = dt.datetime.strptime(yymmdd, "%y%m%d").date()
    except ValueError:
        api_logger.warning("ws_token: invalid date format %r (expected yyMMdd)", yymmdd)
        return False

    today = dt.date.today()
    delta_days = (today - token_date).days

    if token_date > today + dt.timedelta(days=1):
        api_logger.warning("ws_token: date in future %s", yymmdd)
        return False

    if delta_days > 31:
        api_logger.warning(
            "ws_token: date too old %s (delta=%d days)",
            yymmdd,
            delta_days,
        )
        return False

    return True


def _parse_fcm_id(value: str) -> str | None:
    """Проверить FID: непустой, [A-Za-z0-9_\\-]{20,}, длина <= 255."""
    if not value:
        api_logger.warning("ws_token: empty fcm_id")
        return None
    if len(value) > _MAX_FCM_ID_LEN:
        api_logger.warning("ws_token: fcm_id too long %d", len(value))
        return None
    if not re.fullmatch(r"[A-Za-z0-9_\-]{20,}", value):
        api_logger.warning(
            "ws_token: invalid fcm_id %r (regex [A-Za-z0-9_\\-]{20,})",
            value[:24],
        )
        return None
    return value


def _parse_user_id(value: str) -> str | None:
    """Проверить usi: usr[A-Za-z0-9_\\-]{4,}."""
    if not _USER_ID_RE.match(value):
        api_logger.warning(
            "ws_token: invalid user_id %r (regex %s)",
            value,
            _USER_ID_RE.pattern,
        )
        return None
    return value


def _parse_app_version(value: str) -> str | None:
    """Проверить appVer: непустой, [A-Za-z0-9._\\-+ ]{1,32}."""
    if not value:
        api_logger.warning("ws_token: empty app_version")
        return None
    if len(value) > _MAX_APP_VERSION_LEN:
        api_logger.warning("ws_token: app_version too long %d", len(value))
        return None
    if not re.fullmatch(r"[A-Za-z0-9._\-+ ]{1,32}", value):
        api_logger.warning("ws_token: invalid app_version %r", value[:32])
        return None
    return value


def _parse_app_code(value: str) -> int | None:
    """Проверить appCode: десятичное число > 0, <= 10 цифр."""
    if not value:
        api_logger.warning("ws_token: empty app_code")
        return None
    if len(value) > _MAX_APP_CODE_DIGITS:
        api_logger.warning("ws_token: app_code too long %d", len(value))
        return None
    if not value.isdigit():
        api_logger.warning("ws_token: invalid app_code %r (not digits)", value[:16])
        return None
    try:
        code = int(value)
    except ValueError:
        api_logger.warning("ws_token: invalid app_code %r", value[:16])
        return None
    if code <= 0:
        api_logger.warning("ws_token: app_code must be > 0, got %d", code)
        return None
    return code


def _parse_sch(value: str) -> str | None:
    """Проверить sch: ровно "1" или "2"."""
    if value not in ("1", "2"):
        api_logger.warning("ws_token: invalid sch %r (expected '1' or '2')", value[:16])
        return None
    return value


def _parse_prm(value: str, name: str) -> str | None:
    """Проверить prm1/prm2: непустой, без '|', длина <= 256."""
    if not value:
        api_logger.warning("ws_token: empty %s", name)
        return None
    if "|" in value:
        api_logger.warning("ws_token: %s contains '|'", name)
        return None
    if len(value) > _MAX_PRM_LEN:
        api_logger.warning("ws_token: %s too long %d", name, len(value))
        return None
    return value


# ============================================================
# LEGACY: 5 ПОЛЕЙ — fid|usrXXXX|yyMMdd|ver|code
# ============================================================


def decrypt_ws_token_legacy(token_b64: str) -> WsTokenDataLegacy | None:
    """Расшифровать и провалидировать LEGACY WS-токен (5 полей).

    Формат plaintext:
        fid|usrXXXX|yyMMdd|ver|code

    Возвращает ``None`` при любой ошибке.
    """
    text, _blob_len = _decrypt_to_plaintext(token_b64)
    if text is None:
        return None

    parts = text.split("|")
    if len(parts) != _LEGACY_EXPECTED_PARTS:
        api_logger.warning(
            "ws_token[legacy]: unexpected parts count %d (expected %d)",
            len(parts),
            _LEGACY_EXPECTED_PARTS,
        )
        return None

    fcm_id_raw, user_id_raw, date_raw, ver_raw, code_raw = parts

    fcm_id = _parse_fcm_id(fcm_id_raw.strip())
    if fcm_id is None:
        return None

    user_id = _parse_user_id(user_id_raw.strip())
    if user_id is None:
        return None

    date_str = date_raw.strip()
    if not _parse_date(date_str):
        return None

    app_version = _parse_app_version(ver_raw.strip())
    if app_version is None:
        return None

    app_version_code = _parse_app_code(code_raw.strip())
    if app_version_code is None:
        return None

    api_logger.info(
        "ws_token[legacy]: OK fcm=%s... user=%s ver=%s code=%d date=%s",
        fcm_id[-6:],
        user_id,
        app_version,
        app_version_code,
        date_str,
    )

    return WsTokenDataLegacy(
        fcm_id=fcm_id,
        user_id=user_id,
        date=date_str,
        app_version=app_version,
        app_version_code=app_version_code,
    )


# ============================================================
# NEW: 7 ПОЛЕЙ — fid|sch|prm1|prm2|yyMMdd|appVer|appCode
# ============================================================


def decrypt_ws_token(token_b64: str) -> WsTokenData | None:
    """Расшифровать и провалидировать NEW WS-токен (7 полей).

    Формат plaintext:
        fid|sch|prm1|prm2|yyMMdd|appVer|appCode

    Возвращает ``None`` при любой ошибке.

    Поле ``user_id`` не заполняется — usi резолвится через
    ``TeamdroidProcedureRepository.login(mid=1|2, ...)``.
    """
    text, _blob_len = _decrypt_to_plaintext(token_b64)
    if text is None:
        return None

    parts = text.split("|")
    if len(parts) != _NEW_EXPECTED_PARTS:
        api_logger.warning(
            "ws_token[new]: unexpected parts count %d (expected %d)",
            len(parts),
            _NEW_EXPECTED_PARTS,
        )
        return None

    fid_raw, sch_raw, prm1_raw, prm2_raw, date_raw, ver_raw, code_raw = parts

    fcm_id = _parse_fcm_id(fid_raw.strip())
    if fcm_id is None:
        return None

    sch = _parse_sch(sch_raw.strip())
    if sch is None:
        return None

    prm1 = _parse_prm(prm1_raw.strip(), "prm1")
    if prm1 is None:
        return None

    prm2 = _parse_prm(prm2_raw.strip(), "prm2")
    if prm2 is None:
        return None

    date_str = date_raw.strip()
    if not _parse_date(date_str):
        return None

    app_version = _parse_app_version(ver_raw.strip())
    if app_version is None:
        return None

    app_version_code = _parse_app_code(code_raw.strip())
    if app_version_code is None:
        return None

    api_logger.info(
        "ws_token[new]: OK fcm=%s... sch=%s prm1_len=%d prm2_len=%d ver=%s code=%d date=%s",
        fcm_id[-6:],
        sch,
        len(prm1),
        len(prm2),
        app_version,
        app_version_code,
        date_str,
    )

    return WsTokenData(
        fcm_id=fcm_id,
        user_id="",
        sch=sch,
        prm1=prm1,
        prm2=prm2,
        date=date_str,
        app_version=app_version,
        app_version_code=app_version_code,
    )


__all__ = [
    "WsTokenData",
    "WsTokenDataLegacy",
    "decrypt_ws_token",
    "decrypt_ws_token_legacy",
]
