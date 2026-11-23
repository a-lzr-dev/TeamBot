"""Расшифровка WS-токенов мобильного клиента (AES-256-GCM).

ЕДИНСТВЕННЫЙ поддерживаемый формат токена (7 полей):

    fid|sch|prm1|prm2|yyMMdd|appVer|appCode

где:
    fid     — Firebase Installation ID, [A-Za-z0-9_\\-]{20,255}
    sch     — "1" | "2" | "3":
                "1" — login + password           (POST /login)
                "2" — request_id + код           (POST /login)
                "3" — post-login WS-токен        (все остальные эндпоинты)
                      prm1 = usi (usrXXX), prm2 = ""
    prm1    — логин (sch=1) | request_id (sch=2) | usi (sch=3)
    prm2    — пароль (sch=1) | код (sch=2)      | "" (sch=3)
    yyMMdd  — 6 цифр, дата токена ([-31; +1] дней от «сегодня» UTC)
    appVer  — versionName, [A-Za-z0-9._\\-+ ]{1,32}
    appCode — versionCode, десятичное число > 0

Общая часть:
    Токен — это base64(iv(12) || ciphertext || tag(16)), где plaintext
    зашифрован AES-256-GCM с ключом WS_TOKEN_KEY_B64 (base64(32 байта)).
    Ключ ДОЛЖЕН совпадать с BuildConfig.WS_TOKEN_KEY в Android-клиенте.

    При любой ошибке (неверный base64, неверный ключ, InvalidTag,
    неверное число полей, невалидная дата, невалидный sch/appCode)
    функция возвращает ``None``.

CHANGED (v3):
  * ПОЛНОСТЬЮ УДАЛЕНА поддержка legacy 5-полевого формата
    (fid|usrXXXX|yyMMdd|ver|code) и функции ``decrypt_ws_token_legacy`` /
    ``WsTokenDataLegacy`` / ``decrypt_ws_token_any`` / ``WsTokenDataAny``.
  * Единственный декриптор — ``decrypt_ws_token`` (7 полей).
  * Для sch=3 в поле ``user_id`` возвращается usi из prm1; для sch=1|2
    поле пустое (usi резолвится через /login).

Безопасность:
    * Для sch=1|2 user_id в plaintext отсутствует.
    * Дата токена: [-31; +1] дней от «сегодня» (UTC).
    * Ключ и plaintext НЕ логируются.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import os
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

# Ограничения для prm1/prm2.
_MAX_PRM_LEN = 256

# Ограничения для appCode.
_MAX_APP_CODE_DIGITS = 10

# 7 полей в plaintext.
_EXPECTED_PARTS = 7


# ============================================================
# DATACLASS
# ============================================================


@dataclass(frozen=True)
class WsTokenData:
    """Результат расшифровки WS-токена (7 полей).

    Attributes:
        fcm_id: полный Firebase Installation ID (FID).
        user_id: usi (usrXXX) — только для sch=3; для sch=1|2 пустая строка
                 (usi резолвится отдельно через /login).
        sch: схема токена ("1" | "2" | "3").
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

    @property
    def has_usi(self) -> bool:
        """True, если в токене есть валидный usi (только sch=3)."""
        return self.sch == "3" and self.user_id.startswith("usr")


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
    """Проверить sch: "1", "2" или "3"."""
    if value not in ("1", "2", "3"):
        api_logger.warning("ws_token: invalid sch %r (expected '1', '2' or '3')", value[:16])
        return None
    return value


def _parse_prm(value: str, name: str) -> str | None:
    """Проверить prm1/prm2: без '|', длина <= 256.

    Пустая строка допустима для prm2 (sch=3 и часть sch=2).
    """
    if "|" in value:
        api_logger.warning("ws_token: %s contains '|'", name)
        return None
    if len(value) > _MAX_PRM_LEN:
        api_logger.warning("ws_token: %s too long %d", name, len(value))
        return None
    return value


# ============================================================
# ДЕКРИПТОР
# ============================================================


def decrypt_ws_token(token_b64: str) -> WsTokenData | None:
    """Расшифровать и провалидировать WS-токен (7 полей).

    Формат plaintext:
        fid|sch|prm1|prm2|yyMMdd|appVer|appCode

    Для sch=3: prm1 = usi (usrXXX), prm2 = ''.
    В этом случае WsTokenData.user_id заполняется из prm1.

    Возвращает ``None`` при любой ошибке.
    """
    text, _blob_len = _decrypt_to_plaintext(token_b64)
    if text is None:
        return None

    parts = text.split("|")
    if len(parts) != _EXPECTED_PARTS:
        api_logger.warning(
            "ws_token: unexpected parts count %d (expected %d)",
            len(parts),
            _EXPECTED_PARTS,
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

    # sch=3 — post-login WS-токен: prm1=usi, prm2=''.
    user_id = ""
    if sch == "3":
        parsed_usi = _parse_user_id(prm1)
        if not parsed_usi:
            api_logger.warning("ws_token: sch=3 but prm1 is not a valid usi: %r", prm1)
            return None
        user_id = parsed_usi

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
        "ws_token: OK fcm=%s... sch=%s prm1_len=%d prm2_len=%d ver=%s code=%d date=%s user=%r",
        fcm_id[-6:],
        sch,
        len(prm1),
        len(prm2),
        app_version,
        app_version_code,
        date_str,
        user_id or None,
    )

    return WsTokenData(
        fcm_id=fcm_id,
        user_id=user_id,
        sch=sch,
        prm1=prm1,
        prm2=prm2,
        date=date_str,
        app_version=app_version,
        app_version_code=app_version_code,
    )


def encrypt_ws_token(data: WsTokenData) -> str:
    """Собрать 7-полевой WS-токен и зашифровать (обратное decrypt_ws_token).

    Формат plaintext:  fid|sch|prm1|prm2|yyMMdd|appVer|appCode
    Результат — та же строка, что decrypt_ws_token примет обратно.

    Шифрование: AES-256-GCM, key = WS_TOKEN_KEY_B64 (base64(32 байта)),
    blob = iv(12) || ciphertext || tag(16), token = base64url(blob).

    IV генерируется случайно на каждый вызов (как требует AES-GCM).
    Поэтому encrypt_ws_token(d) != encrypt_ws_token(d) побайтово —
    это НОРМАЛЬНО. Вызывать функцию нужно ОДИН раз на токен и
    использовать результат и для TApps.FKey, и для ответа клиенту.
    """
    # --- 1. Валидация входных полей (те же правила, что в decrypt) ---
    if not _parse_fcm_id((data.fcm_id or "").strip()):
        raise ValueError("encrypt_ws_token: invalid fcm_id")

    sch = _parse_sch((data.sch or "").strip())
    if sch is None:
        raise ValueError("encrypt_ws_token: invalid sch")

    prm1 = _parse_prm((data.prm1 or "").strip(), "prm1")
    if prm1 is None:
        raise ValueError("encrypt_ws_token: invalid prm1")

    prm2 = _parse_prm((data.prm2 or "").strip(), "prm2")
    if prm2 is None:
        raise ValueError("encrypt_ws_token: invalid prm2")

    if sch == "3":
        # Для sch=3 prm1 ОБЯЗАН быть валидным usi, prm2 = "".
        if _parse_user_id(prm1) is None:
            raise ValueError("encrypt_ws_token: sch=3 requires usi in prm1")
        if prm2 != "":
            raise ValueError("encrypt_ws_token: sch=3 requires prm2=''")

    if not _parse_date((data.date or "").strip()):
        raise ValueError("encrypt_ws_token: invalid date (yyMMdd)")

    app_version = _parse_app_version((data.app_version or "").strip())
    if app_version is None:
        raise ValueError("encrypt_ws_token: invalid app_version")

    app_code = _parse_app_code(str(data.app_version_code))
    if app_code is None:
        raise ValueError("encrypt_ws_token: invalid app_version_code")

    # --- 2. Собрать plaintext ---
    plaintext = "|".join(
        [
            data.fcm_id.strip(),
            sch,
            prm1,
            prm2,
            data.date.strip(),
            app_version,
            str(app_code),
        ]
    ).encode("utf-8")

    # --- 3. Зашифровать AES-256-GCM ---
    key = _load_key()  # 32 байта, тот же, что в decrypt
    iv = os.urandom(_IV_LEN)  # 12 байт, случайный на каждый вызов
    blob = AESGCM(key).encrypt(iv, plaintext, associated_data=None)

    # --- 4. base64url (без padding, как у клиента) ---
    token = base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")

    api_logger.info(
        "ws_token: encrypt OK fcm=%s... sch=%s prm1_len=%d prm2_len=%d ver=%s code=%d date=%s",
        data.fcm_id[-6:],
        sch,
        len(prm1),
        len(prm2),
        app_version,
        app_code,
        data.date.strip(),
    )
    return token


__all__ = [
    "WsTokenData",
    "decrypt_ws_token",
    "encrypt_ws_token",
]
