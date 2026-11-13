"""Репозиторий вызова хранимых процедур SQL Server Teamdroid.

Все процедуры ходят через ЕДИНОЕ singleton-соединение
(get_teamdroid_sql_conn из app.db.manager) и строку подключения
TEAMDROID_SQL_*:

    TEAMDROID_SQL_PROC_AUTH_START               ext.PA_mbl_AuthStart_Exec
    TEAMDROID_SQL_PROC_AUTH_LOGIN               ext.PA_mbl_AuthLogin_Exec
    TEAMDROID_SQL_PROC_TOKEN_VERIFY             ext.PA_mbl_TokenVerify_Exec
    TEAMDROID_SQL_PROC_TOKEN_FINISH             ext.PA_mbl_TokenFinish_Exec
    TEAMDROID_SQL_PROC_TOKEN_DEVICES_LOAD       ext.PA_mbl_TokenDevices_Load
    TEAMDROID_SQL_PROC_EDIT_MSG_STATUS_DELIVERY ext.PA_mbl_MsgsDeliveryStatus_Edit
    TEAMDROID_SQL_PROC_APP_UPDATE_CHECK         ext.PA_mbl_AppUpdateCheck_Exec
    TEAMDROID_SQL_PROC_APP_UPDATE_OFFERED       ext.PA_mbl_AppUpdateOffered_Exec
    TEAMDROID_SQL_PROC_APP_UPDATE_CHECK_ALL     ext.PA_mbl_AppUpdateCheckAll_Exec
    TEAMDROID_SQL_PROC_SYNC_BASE_LOAD           ext.PA_mbl_SyncBaseData_Load
    TEAMDROID_SQL_PROC_SYNC_BASE_EDIT           ext.PA_mbl_SyncBaseData_Edit

Контракт ext.PA_mbl_TokenVerify_Exec:

    EXEC <proc> @Params = N'<json>'

    Выход: одна строка (Success BIT, prm NVARCHAR(MAX),
                        sid VARCHAR(36), snc DATETIME, dtp NVARCHAR(MAX))

    Колонка prm — JSON-массив из двух возможных элементов:
      * {"fup":1,"prm":{frc,ver,vcd,fph,fsz,fhs}} — обновление приложения;
      * {"sid":...,"snc":...,"dtp":[...],"prm":[...]} — sync-пакет.

    Колонки sid/snc/dtp в контракте оставлены как legacy и
    методом verify_token НЕ читаются: sync-пакет приходит внутри prm.

    Python-парсер verify_token возвращает 3-tuple:
      (ok, err, prm_raw)
        ok       — True при Success=1.
        err      — текст ошибки (None при ok=True).
        prm_raw  — СЫРАЯ строка из колонки prm (без парсинга).
                   None, если колонка NULL.

Контракт ext.PA_mbl_AuthLogin_Exec (mid=1: логин+пароль, mid=2: request_id+код):

    EXEC <proc> @Params = N'<json>'

    Выход: одна строка
        (Success BIT, usi NVARCHAR(64), prm NVARCHAR(MAX),
         sid VARCHAR(36), snc DATETIME, dtp NVARCHAR(MAX))

    Колонка prm — тот же JSON-массив, что и у TokenVerify.

    Колонки sid/snc/dtp в контракте оставлены как legacy и
    методом login НЕ читаются: sync-пакет приходит внутри prm.

    Python-парсер login возвращает 4-tuple:
      (ok, err, usi, prm_raw)
        ok       — True при Success=1.
        err      — текст ошибки (None при ok=True).
        usi      — usrXXX из колонки usi (может быть заполнен и при
                   Success=0, если SQL успел резолвнуть пользователя
                   до force-update).
        prm_raw  — СЫРАЯ строка из колонки prm (без парсинга).
                   None, если колонка NULL.

    Ошибки (THROW):
      PRC_mbl_AuthLogin_BadAuth — неверные учётные данные;
      PRC_mbl_AuthLogin_NoData  — сессия устройства не найдена.

Все методы синхронные (pyodbc блокирующий). Из async-кода вызывать так:

    import asyncio
    result = await asyncio.to_thread(TDProc.auth_start, params)
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

import pyodbc

from ...config import settings
from ...logger import db_logger
from ...utils.datetime import get_timestamp
from ..manager import teamdroid_sql_cursor

_PROC_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")

_WHAT_TO_WHT: dict[str, int] = {"recv": 1, "read": 2}


# ============================================================
# НОРМАЛИЗАЦИЯ TIMESTAMP ДЛЯ MSSQL
# ============================================================


def _normalize_ts_for_sql(ts: str) -> str:
    """ISO 8601 → MSSQL-совместимый DATETIME (UTC, без 'Z')."""
    if not ts:
        return ts
    try:
        parsed = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _as_str(v: Any) -> str | None:
    """Приводит значение к ``str | None`` без вызова ``str()`` от ``None``."""
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace") or None
    if isinstance(v, str):
        return v or None
    return str(v)


# ============================================================
# Статистика SyncBaseData (in-memory, для /api/v1/client/sync-stats)
# ============================================================


class _SyncBaseStats:
    """Счётчики вызовов SyncBaseData (для диагностики)."""

    __slots__ = (
        "load_calls",
        "load_rows",
        "load_empty",
        "load_errors",
        "load_oversized",
        "load_missing",
        "edit_calls",
        "edit_items",
        "edit_types",
        "edit_errors",
        "edit_invalid",
        "edit_timeout",
        "edit_partial",
        "edit_bad_ts",
    )

    def __init__(self) -> None:
        self.load_calls = 0
        self.load_rows = 0
        self.load_empty = 0
        self.load_errors = 0
        self.load_oversized = 0
        self.load_missing = 0
        self.edit_calls = 0
        self.edit_items = 0
        self.edit_types = 0
        self.edit_errors = 0
        self.edit_invalid = 0
        self.edit_timeout = 0
        self.edit_partial = 0
        self.edit_bad_ts = 0

    def snapshot(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__slots__}


_sync_base_stats = _SyncBaseStats()


class TeamdroidProcedureRepository:
    """Вызовы хранимых процедур SQL Server Teamdroid.

    Все методы статические и синхронные — вызывать через
    asyncio.to_thread() из async-кода.
    """

    # ============================================================
    # AUTH
    # ============================================================

    @staticmethod
    def auth_start(params: dict[str, Any]) -> dict[str, Any]:
        return TeamdroidProcedureRepository._run_json_proc(
            settings.TEAMDROID_SQL_PROC_AUTH_START,
            params,
        )

    @staticmethod
    def auth_login(params: dict[str, Any]) -> dict[str, Any]:
        return TeamdroidProcedureRepository._run_json_proc(
            settings.TEAMDROID_SQL_PROC_AUTH_LOGIN,
            params,
        )

    # ============================================================
    # VERIFY TOKEN
    # ============================================================

    @staticmethod
    def verify_token(
        *,
        user_id: str,
        fcm_id: str,
        app_id: int,
        token_date: str | None,
        client_ip: str | None,
        app_version: str | None = None,
        app_version_code: int | None = None,
    ) -> tuple[bool, str | None, str | None]:
        """EXEC settings.TEAMDROID_SQL_PROC_TOKEN_VERIFY @Params = N'<json>'.

        Вызывает ext.PA_mbl_TokenVerify_Exec с @Params = N'<json>', где:

            {
              "usi": "usrXXXX",    -- Teamdroid user hash
              "api": 1,            -- AppID (TEAMDROID_APP_ID)
              "dvc": "...",        -- FID устройства
              "tkn": "yyMMdd",     -- дата токена
              "cip": "...",        -- IP клиента
              "ver": "2.5.1",      -- versionName (опционально)
              "vcd": 251           -- versionCode (опционально)
            }

        Процедура возвращает одну строку:

            Success BIT,           -- 1 = OK, 0 = отказ (force-update)
            prm NVARCHAR(MAX),     -- JSON-массив (см. docstring модуля)
            sid VARCHAR(36),       -- legacy, не читается
            snc DATETIME,          -- legacy, не читается
            dtp NVARCHAR(MAX)      -- legacy, не читается

        Возвращает:
            (ok, err, prm_raw)
              ok       — True при Success=1.
              err      — текст ошибки (None при ok=True).
              prm_raw  — СЫРАЯ строка из колонки prm (без парсинга).
                         None, если колонка NULL.

        Ошибки (THROW):
          PRC_mbl_TokenVerify_NoData — устройство/сессия не найдены.

        При любой pyodbc/unexpected-ошибке возвращает
        (False, "<описание>", None) — не бросает исключение.
        """
        if not fcm_id:
            return False, "empty_fcm_id", None
        if not user_id or not user_id.startswith("usr"):
            return False, "invalid_user_id", None
        if not app_id or int(app_id) <= 0:
            return False, "invalid_app_id", None

        params: dict[str, Any] = {
            "usi": user_id[:64],
            "api": int(app_id),
            "dvc": fcm_id[:255],
            "tkn": (token_date or "")[:16],
            "cip": (client_ip or "")[:64],
        }
        if app_version:
            params["ver"] = str(app_version)[:32]
        if app_version_code is not None:
            try:
                params["vcd"] = int(app_version_code)
            except (ValueError, TypeError):
                db_logger.warning("[verify_token] invalid vcd: %r", app_version_code)

        proc_name = settings.TEAMDROID_SQL_PROC_TOKEN_VERIFY
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        db_logger.debug(
            "🔐 [verify_token] proc=%s user=%s fcm=%s api=%d tkn=%s ip=%s ver=%s vcd=%s",
            proc_name,
            user_id,
            fcm_id[-6:] if len(fcm_id) >= 6 else "***",
            int(app_id),
            params["tkn"],
            params["cip"],
            params.get("ver"),
            params.get("vcd"),
        )

        params_json = json.dumps(params, ensure_ascii=False)

        row: pyodbc.Row | None = None
        try:
            with teamdroid_sql_cursor() as cur:
                try:
                    cur.execute(f"EXEC {proc_name} @Params = ?", params_json)
                    row = cur.fetchone() if cur.description is not None else None
                    while cur.nextset():
                        pass
                    cur.connection.commit()
                except Exception:
                    try:
                        cur.connection.rollback()
                    except pyodbc.Error as rb_exc:
                        db_logger.error("[verify_token] rollback failed: %r", rb_exc, exc_info=True)
                    raise
        except pyodbc.Error as e:
            err_text = str(e)
            if "PRC_mbl_TokenVerify_NoData" in err_text or "50000" in err_text:
                db_logger.warning(
                    "⚠️ [verify_token] THROW NoData user=%s fcm=%s...: %s",
                    user_id,
                    fcm_id[-6:] if len(fcm_id) >= 6 else "***",
                    err_text,
                )
                return False, "PRC_mbl_TokenVerify_NoData", None

            db_logger.error(
                "❌ [verify_token] pyodbc error user=%s: %s",
                user_id,
                err_text,
                exc_info=True,
            )
            return False, f"pyodbc: {err_text}", None

        except Exception as e:  # noqa: BLE001
            db_logger.error(
                "❌ [verify_token] unexpected error user=%s: %r",
                user_id,
                e,
                exc_info=True,
            )
            return False, repr(e), None

        if row is None:
            db_logger.warning("⚠️ [verify_token] procedure returned no rows for user=%s", user_id)
            return False, "no_rows", None

        raw_success: Any = row[0]
        raw_prm: Any = row[1] if len(row) > 1 else None

        ok = bool(raw_success == 1 or raw_success is True)

        prm_raw = _as_str(raw_prm)

        if not ok:
            db_logger.warning(
                "⚠️ [verify_token] force update user=%s prm=%s",
                user_id,
                (prm_raw or "")[:200],
            )
            return False, "force_update", prm_raw

        db_logger.info(
            "✅ [verify_token] OK user=%s prm_len=%d",
            user_id,
            len(prm_raw) if prm_raw else 0,
        )
        return True, None, prm_raw

    # ============================================================
    # LOGIN (mid=1: логин+пароль, mid=2: request_id+код)
    # ============================================================

    @staticmethod
    def login(
        *,
        mid: int,
        pr1: str,
        pr2: str,
        fcm_id: str,
        token_date: str | None,
        client_ip: str | None,
        app_version: str | None,
        app_version_code: int | None,
        app_id: int,
    ) -> tuple[bool, str | None, str | None, str | None]:
        """mid=1|2: проверка учётных данных + TokenVerify внутри SQL.

        Вызывает TEAMDROID_SQL_PROC_AUTH_LOGIN (ext.PA_mbl_AuthLogin_Exec)
        с @Params = N'<json>', где:

            {
              "mid": 1 | 2,        -- 1=логин+пароль, 2=request_id+код
              "pr1": "..." ,       -- логин | request_id
              "pr2": "..." ,       -- пароль | код
              "dvc": "..." ,       -- FID устройства
              "tkn": "yyMMdd",     -- дата токена
              "cip": "..." ,       -- IP клиента
              "ver": "2.5.1",      -- versionName (опционально)
              "vcd": 251,          -- versionCode (опционально)
              "api": 1             -- AppID (TEAMDROID_APP_ID)
            }

        Процедура возвращает одну строку:

            Success BIT,           -- 1 = OK, 0 = отказ (force-update)
            Usi VARCHAR(64),       -- usrXXXX
            prm NVARCHAR(MAX),     -- JSON-массив (см. docstring модуля)
            sid VARCHAR(36),       -- legacy, не читается
            snc DATETIME,          -- legacy, не читается
            dtp NVARCHAR(MAX)      -- legacy, не читается

        Возвращает:
            (ok, err, usi, prm_raw)
              ok       — True при Success=1.
              err      — текст ошибки (None при ok=True).
              usi      — usrXXX из колонки usi (может быть заполнен и при
                         Success=0, если SQL успел резолвнуть пользователя
                         до force-update).
              prm_raw  — СЫРАЯ строка из колонки prm (без парсинга).
                         None, если колонка NULL.

        Ошибки (THROW):
          PRC_mbl_AuthLogin_BadAuth — неверные учётные данные;
          PRC_mbl_AuthLogin_NoData  — сессия устройства не найдена.

        При любой pyodbc/unexpected-ошибке возвращает
        (False, "<описание>", None, None) — не бросает исключение.
        """
        if mid not in (1, 2):
            return False, f"invalid_mid:{mid!r}", None, None
        if not fcm_id:
            return False, "empty_dvc", None, None
        if not pr1 or not pr2:
            return False, "empty_pr1_or_pr2", None, None
        if not app_id or int(app_id) <= 0:
            return False, "invalid_app_id", None, None

        params: dict[str, Any] = {
            "mid": int(mid),
            "pr1": pr1[:256],
            "pr2": pr2[:256],
            "dvc": fcm_id[:255],
            "tkn": (token_date or "")[:16],
            "cip": (client_ip or "")[:64],
            "api": int(app_id),
        }
        if app_version:
            params["ver"] = str(app_version)[:32]
        if app_version_code is not None:
            try:
                params["vcd"] = int(app_version_code)
            except (ValueError, TypeError):
                pass

        proc_name = settings.TEAMDROID_SQL_PROC_AUTH_LOGIN
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        db_logger.debug(
            "🔑 [login] proc=%s mid=%s pr1_len=%d pr2_len=%d dvc=%s api=%d ip=%r",
            proc_name,
            mid,
            len(pr1),
            len(pr2),
            fcm_id[-6:] if len(fcm_id) >= 6 else "***",
            int(app_id),
            client_ip,
        )

        params_json = json.dumps(params, ensure_ascii=False)

        row: pyodbc.Row | None = None
        try:
            with teamdroid_sql_cursor() as cur:
                try:
                    cur.execute(f"EXEC {proc_name} @Params = ?", params_json)
                    row = cur.fetchone() if cur.description is not None else None
                    while cur.nextset():
                        pass
                    cur.connection.commit()
                except Exception:
                    try:
                        cur.connection.rollback()
                    except pyodbc.Error as rb_exc:
                        db_logger.error("[login] rollback failed: %r", rb_exc, exc_info=True)
                    raise
        except pyodbc.Error as e:
            err_text = str(e)

            if "PRC_mbl_AuthLogin_BadAuth" in err_text:
                db_logger.warning("⚠️ [login] BadAuth mid=%s: %s", mid, err_text)
                return False, "invalid_credentials", None, None

            if "PRC_mbl_AuthLogin_NoData" in err_text or "50000" in err_text:
                db_logger.warning("⚠️ [login] NoData mid=%s: %s", mid, err_text)
                return False, "PRC_mbl_AuthLogin_NoData", None, None

            db_logger.error("❌ [login] pyodbc error: %s", err_text, exc_info=True)
            return False, f"pyodbc: {err_text}", None, None
        except Exception as e:
            db_logger.error("❌ [login] unexpected error: %r", e, exc_info=True)
            return False, repr(e), None, None

        if row is None:
            return False, "no_rows", None, None

        raw_success: Any = row[0]
        raw_usi: Any = row[1] if len(row) > 1 else None
        raw_prm: Any = row[2] if len(row) > 2 else None

        ok = bool(raw_success == 1 or raw_success is True)

        result_usi = _as_str(raw_usi)
        if result_usi is not None and not result_usi.startswith("usr"):
            db_logger.warning("⚠️ [login] invalid usi in result: %r", raw_usi)
            result_usi = None

        prm_raw = _as_str(raw_prm)

        if not ok:
            db_logger.warning(
                "⚠️ [login] force-update mid=%s has_prm=%s usi=%r",
                mid,
                prm_raw is not None,
                result_usi,
            )
            return False, "force_update", result_usi, prm_raw

        if not result_usi:
            db_logger.warning("⚠️ [login] Success=1, но usi=NULL")
            return False, "no_usi_in_result", None, None

        db_logger.info(
            "✅ [login] OK mid=%s usi=%s prm_len=%d",
            mid,
            result_usi,
            len(prm_raw) if prm_raw else 0,
        )
        return True, None, result_usi, prm_raw

    # ============================================================
    # LOGOUT (TokenFinish)
    # ============================================================

    @staticmethod
    def logout(
        *,
        usi: str,
        fcm_id: str,
        app_id: int,
    ) -> tuple[bool, str | None]:
        """mid=0: завершение сессии устройства (TokenFinish).

        Вызывает ext.PA_mbl_TokenFinish_Exec с @Params = N'<json>', где:

            {
              "usi": "usr...",   -- Teamdroid user hash
              "api": 1,          -- AppID (TEAMDROID_APP_ID)
              "dvc": "..."       -- FID устройства
            }

        Процедура возвращает одну строку: Success BIT.

        При отсутствии активной сессии процедура делает RETURN -1
        (без THROW). pyodbc увидит либо пустой resultset, либо
        строку с Success=0 — трактуем как "logout не выполнен".

        Возвращает:
            (ok, err)
        """
        if not fcm_id:
            return False, "empty_dvc"
        if not usi or not usi.startswith("usr"):
            return False, "invalid_usi"
        if not app_id or int(app_id) <= 0:
            return False, "invalid_app_id"

        params: dict[str, Any] = {
            "usi": usi[:64],
            "api": int(app_id),
            "dvc": fcm_id[:255],
        }

        proc_name = settings.TEAMDROID_SQL_PROC_TOKEN_FINISH
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        db_logger.debug(
            "🔚 [logout] proc=%s usi=%s dvc=%s api=%d",
            proc_name,
            usi,
            fcm_id[-6:] if len(fcm_id) >= 6 else "***",
            int(app_id),
        )

        params_json = json.dumps(params, ensure_ascii=False)

        row: pyodbc.Row | None = None
        try:
            with teamdroid_sql_cursor() as cur:
                try:
                    cur.execute(f"EXEC {proc_name} @Params = ?", params_json)
                    row = cur.fetchone() if cur.description is not None else None
                    while cur.nextset():
                        pass
                    cur.connection.commit()
                except Exception:
                    try:
                        cur.connection.rollback()
                    except pyodbc.Error as rb_exc:
                        db_logger.error("[logout] rollback failed: %r", rb_exc, exc_info=True)
                    raise
        except pyodbc.Error as e:
            err_text = str(e)
            if "PRC_mbl_TokenFinish_NoData" in err_text or "50000" in err_text:
                db_logger.warning("⚠️ [logout] NoData usi=%s: %s", usi, err_text)
                return False, "PRC_mbl_TokenFinish_NoData"
            db_logger.error("❌ [logout] pyodbc error: %s", err_text, exc_info=True)
            return False, f"pyodbc: {err_text}"
        except Exception as e:
            db_logger.error("❌ [logout] unexpected error: %r", e, exc_info=True)
            return False, repr(e)

        if row is None:
            db_logger.warning("⚠️ [logout] no rows (RETURN -1?) usi=%s", usi)
            return False, "no_rows"

        raw_success: Any = row[0]
        ok = bool(raw_success == 1 or raw_success is True)
        if ok:
            db_logger.info("✅ [logout] OK usi=%s", usi)
            return True, None

        db_logger.warning("⚠️ [logout] Success=0 usi=%s raw=%r", usi, raw_success)
        return False, f"rejected_value={raw_success!r}"

    # ============================================================
    # TOKEN DEVICES (FID registry, read-only)
    # ============================================================

    @staticmethod
    def load_token_devices() -> dict[str, set[str]]:
        proc_name = settings.TEAMDROID_SQL_PROC_TOKEN_DEVICES_LOAD
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
        if not app_id:
            db_logger.warning("[load_token_devices] TEAMDROID_APP_ID=0 — процедура вернёт 0 строк")
            return {}

        params_json = json.dumps({"api": app_id}, ensure_ascii=False)
        result_map: dict[str, set[str]] = {}

        db_logger.debug("[load_token_devices] EXEC %s api=%d", proc_name, app_id)

        try:
            with teamdroid_sql_cursor() as cur:
                try:
                    cur.execute(f"EXEC {proc_name} @Params = ?", params_json)
                    rows = cur.fetchall()
                    while cur.nextset():
                        pass
                    cur.connection.commit()
                except Exception:
                    try:
                        cur.connection.rollback()
                    except pyodbc.Error as rb_exc:
                        db_logger.error(
                            "[load_token_devices] rollback failed: %r",
                            rb_exc,
                            exc_info=True,
                        )
                    raise

            for row in rows:
                usi = str(row[0] or "").strip()
                dvc = str(row[1] or "").strip()
                if usi.startswith("usr") and dvc:
                    result_map.setdefault(usi, set()).add(dvc)

            db_logger.info(
                "[load_token_devices] loaded %d users, %d total FIDs",
                len(result_map),
                sum(len(s) for s in result_map.values()),
            )
            return result_map

        except pyodbc.Error as e:
            db_logger.warning("[load_token_devices] SQL error: %r", e, exc_info=True)
            return {}
        except Exception as e:  # noqa: BLE001
            db_logger.error("[load_token_devices] unexpected error: %r", e, exc_info=True)
            return {}

    # ============================================================
    # MSG DELIVERY STATUS
    # ============================================================

    @staticmethod
    def edit_msg_status_delivery(
        *,
        topic: str,
        what: str,
        seq: int,
        user_id: str,
        client_ip: str | None,
    ) -> bool:
        if what not in _WHAT_TO_WHT:
            return True

        results = TeamdroidProcedureRepository.edit_msg_status_delivery_batch(
            topic=topic,
            seq=seq,
            user_id=user_id,
            client_ip=client_ip,
            recv=(what == "recv"),
            read=(what == "read"),
        )
        return results.get(what, False)

    @staticmethod
    def edit_msg_status_delivery_batch(
        *,
        topic: str,
        seq: int,
        user_id: str,
        client_ip: str | None,
        recv: bool = False,
        read: bool = False,
    ) -> dict[str, bool]:
        requested: list[tuple[str, int]] = []
        if recv:
            requested.append(("recv", _WHAT_TO_WHT["recv"]))
        if read:
            requested.append(("read", _WHAT_TO_WHT["read"]))
        if not requested:
            return {}

        app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
        proc_name = settings.TEAMDROID_SQL_PROC_EDIT_MSG_STATUS_DELIVERY
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        base = {
            "tpc": topic[:100],
            "seq": int(seq),
            "usi": user_id[:64],
            "api": app_id,
            "cip": (client_ip or "")[:64],
        }
        payload = [dict(base, wht=wht) for _, wht in requested]
        params_json = json.dumps(payload, ensure_ascii=False)

        results: dict[str, bool] = {}

        with teamdroid_sql_cursor() as cur:
            try:
                cur.execute(f"EXEC {proc_name} @Params = ?", params_json)

                success = True
                if cur.description is not None:
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        success = bool(row[0])
                while cur.nextset():
                    pass

                cur.connection.commit()

                for key, _ in requested:
                    results[key] = success

                db_logger.debug(
                    "[edit_msg_status_delivery_batch] saved: topic=%r seq=%s "
                    "user=%r api=%d cip=%r statuses=%s success=%s",
                    topic,
                    seq,
                    user_id,
                    app_id,
                    base["cip"],
                    [k for k, _ in requested],
                    success,
                )
                return results

            except pyodbc.Error as av_exc:
                err_text = str(av_exc)
                try:
                    cur.connection.rollback()
                except pyodbc.Error as rb_exc:
                    db_logger.error(
                        "[edit_msg_status_delivery_batch] rollback failed: %r (original: %r)",
                        rb_exc,
                        av_exc,
                        exc_info=True,
                    )

                if "PRC_mbl_MsgsDeliveryStatus_NoData" in err_text or "50000" in err_text:
                    db_logger.warning(
                        "[edit_msg_status_delivery_batch] NoData: topic=%r seq=%s user=%r api=%d cip=%r statuses=%s",
                        topic,
                        seq,
                        user_id,
                        app_id,
                        base["cip"],
                        [k for k, _ in requested],
                    )
                elif "PRC_mbl_MsgsDeliveryStatus_BadParams" in err_text:
                    db_logger.error(
                        "[edit_msg_status_delivery_batch] BadParams: "
                        "процедура ожидает JSON-массив, получен объект. "
                        "payload=%r",
                        params_json[:300],
                    )
                else:
                    db_logger.warning(
                        "[edit_msg_status_delivery_batch] failed: topic=%r seq=%s user=%r statuses=%s err=%r",
                        topic,
                        seq,
                        user_id,
                        [k for k, _ in requested],
                        av_exc,
                    )

                for key, _ in requested:
                    results[key] = False
                return results

            except Exception:
                try:
                    cur.connection.rollback()
                except pyodbc.Error as rb_exc:
                    db_logger.error(
                        "[edit_msg_status_delivery_batch] rollback failed: %r",
                        rb_exc,
                        exc_info=True,
                    )
                raise

    # ============================================================
    # APP UPDATE CHECK
    # ============================================================

    @staticmethod
    def app_update_check(
        *,
        user_id: str,
        fcm_id: str,
        app_id: int,
    ) -> str | None:
        if not fcm_id:
            return None
        if not user_id or not user_id.startswith("usr"):
            return None
        if not app_id or int(app_id) <= 0:
            return None

        proc_name = settings.TEAMDROID_SQL_PROC_APP_UPDATE_CHECK
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        params: dict[str, Any] = {
            "usi": user_id[:64],
            "api": int(app_id),
            "dvc": fcm_id[:255],
        }
        params_json = json.dumps(params, ensure_ascii=False)

        db_logger.debug(
            "📲 [app_update_check] user=%s fcm=%s api=%d",
            user_id,
            fcm_id[-6:] if len(fcm_id) >= 6 else "***",
            int(app_id),
        )

        row: pyodbc.Row | None = None
        has_result_set = False

        try:
            with teamdroid_sql_cursor() as cur:
                try:
                    cur.execute(f"EXEC {proc_name} @Params = ?", params_json)

                    has_result_set = cur.description is not None
                    if has_result_set:
                        row = cur.fetchone()

                    while cur.nextset():
                        pass
                    cur.connection.commit()
                except Exception:
                    try:
                        cur.connection.rollback()
                    except pyodbc.Error as rb_exc:
                        db_logger.error(
                            "[app_update_check] rollback failed: %r",
                            rb_exc,
                            exc_info=True,
                        )
                    raise

        except pyodbc.Error as e:
            err_text = str(e)
            if "PRC_mbl_AppUpdateCheck_NoData" in err_text or "50000" in err_text:
                db_logger.warning(
                    "⚠️ [app_update_check] NoData user=%s fcm=%s...: %s",
                    user_id,
                    fcm_id[-6:] if len(fcm_id) >= 6 else "***",
                    err_text,
                )
                return None

            db_logger.error(
                "❌ [app_update_check] pyodbc error user=%s: %s",
                user_id,
                err_text,
                exc_info=True,
            )
            raise

        except Exception as e:  # noqa: BLE001
            db_logger.error(
                "❌ [app_update_check] unexpected error user=%s: %r",
                user_id,
                e,
                exc_info=True,
            )
            raise

        if not has_result_set:
            db_logger.warning(
                "⚠️ [app_update_check] no result set user=%s",
                user_id,
            )
            return None

        if row is None:
            db_logger.warning(
                "⚠️ [app_update_check] empty result user=%s",
                user_id,
            )
            return None

        raw: Any = row[0]
        result: str | None
        if isinstance(raw, bytes):
            result = raw.decode("utf-8", errors="replace") or None
        elif isinstance(raw, str):
            result = raw or None
        else:
            result = None

        db_logger.info(
            "✅ [app_update_check] user=%s result_len=%s",
            user_id,
            len(result) if result else 0,
        )

        return result

    @staticmethod
    def app_update_offered_batch(
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not records:
            return {"success": True, "rows": 0, "error": None}

        proc_name = settings.TEAMDROID_SQL_PROC_APP_UPDATE_OFFERED
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        params_json = json.dumps(records, ensure_ascii=False)

        db_logger.debug("📝 [app_update_offered_batch] rows=%d", len(records))

        try:
            with teamdroid_sql_cursor() as cur:
                try:
                    cur.execute(f"EXEC {proc_name} @Params = ?", params_json)
                    if cur.description is not None:
                        cur.fetchall()
                    while cur.nextset():
                        pass
                    cur.connection.commit()
                except Exception:
                    try:
                        cur.connection.rollback()
                    except pyodbc.Error as rb_exc:
                        db_logger.error(
                            "[app_update_offered_batch] rollback failed: %r",
                            rb_exc,
                            exc_info=True,
                        )
                    raise

            db_logger.info("✅ [app_update_offered_batch] recorded %d rows", len(records))
            return {"success": True, "rows": len(records), "error": None}

        except pyodbc.Error as e:
            err_text = str(e)
            if (
                "PRC_mbl_AppUpdateOffered_NoData" in err_text
                or "PRC_mbl_AppUpdateOffered_BadParams" in err_text
                or "50000" in err_text
            ):
                db_logger.warning(
                    "⚠️ [app_update_offered_batch] %s: %s",
                    proc_name,
                    err_text,
                )
                return {"success": False, "rows": 0, "error": err_text}

            db_logger.error(
                "❌ [app_update_offered_batch] pyodbc error: %s",
                err_text,
                exc_info=True,
            )
            return {"success": False, "rows": 0, "error": f"pyodbc: {err_text}"}

        except Exception as e:  # noqa: BLE001
            db_logger.error(
                "❌ [app_update_offered_batch] unexpected error: %r",
                e,
                exc_info=True,
            )
            return {"success": False, "rows": 0, "error": repr(e)}

    @staticmethod
    def list_outdated_sessions() -> list[dict[str, Any]]:
        proc_name = settings.TEAMDROID_SQL_PROC_APP_UPDATE_CHECK_ALL
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        result: list[dict[str, Any]] = []
        try:
            with teamdroid_sql_cursor() as cur:
                try:
                    cur.execute(f"EXEC {proc_name}")
                    rows = cur.fetchall()
                    while cur.nextset():
                        pass
                    cur.connection.commit()
                except Exception:
                    try:
                        cur.connection.rollback()
                    except pyodbc.Error as rb_exc:
                        db_logger.error(
                            "[list_outdated_sessions] rollback failed: %r",
                            rb_exc,
                            exc_info=True,
                        )
                    raise

            for row in rows:
                result.append(
                    {
                        "usi": str(row[0] or "").strip(),
                        "api": int(row[1]) if row[1] is not None else 0,
                        "dvc": str(row[2] or "").strip(),
                        "frc": row[3],
                        "ver": row[4],
                        "vcd": int(row[5]) if row[5] is not None else 0,
                        "fph": row[6],
                        "fsz": row[7],
                        "fhs": row[8],
                    }
                )

            db_logger.info("[list_outdated_sessions] found %d rows to offer update", len(result))
            return result

        except pyodbc.Error as e:
            db_logger.warning("[list_outdated_sessions] SQL error: %r", e, exc_info=True)
            return []
        except Exception as e:  # noqa: BLE001
            db_logger.error("[list_outdated_sessions] unexpected error: %r", e, exc_info=True)
            return []

    # ============================================================
    # SYNC BASE DATA
    # ============================================================

    @staticmethod
    def load_base_data(
        *,
        user_id: str,
        fcm_id: str,
        app_id: int,
        data_types: list[int] | None = None,
        limit: int | None = None,
        force: bool = False,
        client_ip: str | None = None,
        debug: bool = False,
    ) -> dict[str, Any]:
        if not user_id or not user_id.startswith("usr"):
            raise ValueError("invalid usi")
        if not fcm_id:
            raise ValueError("empty dvc")
        if not app_id or int(app_id) <= 0:
            raise ValueError("invalid api")

        proc_name = settings.TEAMDROID_SQL_PROC_SYNC_BASE_LOAD
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        if limit is None:
            limit = int(getattr(settings, "APP_CLIENT_SYNC_BASE_DEFAULT_LIMIT", 1000) or 1000)
        if limit < 1:
            limit = 1

        params: dict[str, Any] = {
            "usi": user_id[:64],
            "api": int(app_id),
            "dvc": fcm_id[:255],
            "lmt": int(limit),
            "frc": 1 if force else 0,
        }
        if data_types:
            params["dtp"] = [int(t) for t in data_types]

        params_json = json.dumps(params, ensure_ascii=False)
        db_logger.debug(
            "[sync_base.load] proc=%s usi=%s dvc=%s api=%d lmt=%d frc=%d dtp=%r ip=%r debug=%s",
            proc_name,
            user_id,
            fcm_id[-6:] if len(fcm_id) >= 6 else "***",
            int(app_id),
            int(limit),
            1 if force else 0,
            params.get("dtp"),
            client_ip,
            debug,
        )

        _sync_base_stats.load_calls += 1

        row: pyodbc.Row | None = None

        try:
            with teamdroid_sql_cursor() as cur:
                try:
                    if debug:
                        cur.execute(f"EXEC {proc_name} @Params = ?, @Debug = 1", params_json)
                    else:
                        cur.execute(f"EXEC {proc_name} @Params = ?", params_json)

                    while True:
                        if cur.description is not None:
                            row = cur.fetchone()
                        if not cur.nextset():
                            break

                    cur.connection.commit()

                except Exception:
                    try:
                        cur.connection.rollback()
                    except pyodbc.Error as rb_exc:
                        db_logger.error(
                            "[sync_base.load] rollback failed: %r",
                            rb_exc,
                            exc_info=True,
                        )
                    raise

        except pyodbc.Error as e:
            err_text = str(e)
            if "PRC_mbl_SyncBaseData_NoData" in err_text or "50000" in err_text:
                _sync_base_stats.load_errors += 1
                db_logger.warning(
                    "[sync_base.load] NoData proc=%s usi=%s dvc=%s...: %s",
                    proc_name,
                    user_id,
                    fcm_id[-6:] if len(fcm_id) >= 6 else "***",
                    err_text,
                )
                raise RuntimeError(f"PRC_mbl_SyncBaseData_NoData: {err_text}") from e

            _sync_base_stats.load_errors += 1
            db_logger.error(
                "[sync_base.load] pyodbc error proc=%s: %s",
                proc_name,
                err_text,
                exc_info=True,
            )
            raise

        except Exception:
            _sync_base_stats.load_errors += 1
            raise

        if row is None:
            db_logger.warning(
                "[sync_base.load] no result set proc=%s usi=%s",
                proc_name,
                user_id,
            )
            _sync_base_stats.load_empty += 1
            return {"sid": "", "snc": None, "dtp": [], "prm": []}

        raw_sid: Any = row[0]
        raw_snc: Any = row[1]
        raw_dtp: Any = row[2] if len(row) > 2 else None
        raw_result: Any = row[3] if len(row) > 3 else None

        sid: str
        if isinstance(raw_sid, str):
            sid = raw_sid
        elif raw_sid is not None:
            sid = str(raw_sid)
        else:
            sid = ""

        snc: str | None
        if isinstance(raw_snc, dt.datetime):
            snc = raw_snc.strftime("%Y-%m-%dT%H:%M:%S")
        elif isinstance(raw_snc, dt.date):
            snc = raw_snc.strftime("%Y-%m-%dT00:00:00")
        elif isinstance(raw_snc, str) and raw_snc:
            snc = raw_snc
        else:
            snc = None

        def _json_load(value: Any) -> Any:
            if value is None:
                return None
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            if isinstance(value, str):
                v = value.strip()
                if not v:
                    return None
                try:
                    return json.loads(v)
                except (ValueError, TypeError):
                    return None
            return value

        dtp_raw = _json_load(raw_dtp)
        dtp: list[int] = []
        if isinstance(dtp_raw, list):
            for t in dtp_raw:
                try:
                    dtp.append(int(t))
                except (ValueError, TypeError):
                    continue

        result_raw = _json_load(raw_result)
        prm: list[dict[str, Any]] = []
        if isinstance(result_raw, list):
            for item in result_raw:
                if not isinstance(item, dict):
                    continue

                dt_val = item.get("dt")
                if dt_val is None:
                    continue
                if not isinstance(dt_val, int | str):
                    continue
                try:
                    dt_int = int(dt_val)
                except (ValueError, TypeError):
                    continue

                exp_val = item.get("exp")
                exp_int: int | None = None
                if isinstance(exp_val, int | str):
                    try:
                        exp_int = int(exp_val)
                    except (ValueError, TypeError):
                        exp_int = None

                val = item.get("val")
                if isinstance(val, str):
                    try:
                        parsed = json.loads(val)
                        val_clean: Any = parsed if isinstance(parsed, list) else []
                    except (ValueError, TypeError):
                        val_clean = []
                elif isinstance(val, list):
                    val_clean = val
                else:
                    val_clean = []

                prm.append({"dt": dt_int, "exp": exp_int, "val": val_clean})

        _sync_base_stats.load_rows += len(prm)
        if not prm:
            _sync_base_stats.load_empty += 1

        db_logger.info(
            "[sync_base.load] proc=%s usi=%s sid=%s snc=%r dtp=%s prm_rows=%d",
            proc_name,
            user_id,
            sid,
            snc,
            dtp,
            len(prm),
        )

        return {"sid": sid, "snc": snc, "dtp": dtp, "prm": prm}

    @staticmethod
    def edit_base_data(items: list[dict[str, Any]]) -> None:
        if not items:
            return

        proc_name = settings.TEAMDROID_SQL_PROC_SYNC_BASE_EDIT
        TeamdroidProcedureRepository._validate_proc_name(proc_name)

        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            usi = str(item.get("usi") or "").strip()
            dvc = str(item.get("dvc") or "").strip()
            api = item.get("api")
            dtp = item.get("dtp") or []
            ts = item.get("ts")

            if not usi.startswith("usr"):
                raise ValueError(f"items[{idx}]: invalid usi {usi!r}")
            if not dvc:
                raise ValueError(f"items[{idx}]: empty dvc")
            if not isinstance(api, int) or api <= 0:
                if api is None:
                    raise ValueError(f"items[{idx}]: invalid api (got None)")
                raise ValueError(f"items[{idx}]: invalid api {api!s}")
            if not isinstance(dtp, list) or not dtp:
                raise ValueError(f"items[{idx}]: dtp must be non-empty list")
            if not isinstance(ts, str) or not ts:
                raise ValueError(f"items[{idx}]: ts must be non-empty ISO string")

            api_int: int = int(api)
            usi_str: str = str(usi)
            dvc_str: str = str(dvc)

            normalized.append(
                {
                    "usi": usi_str[:64],
                    "api": api_int,
                    "dvc": dvc_str[:255],
                    "dtp": [int(t) for t in dtp],
                    "ts": _normalize_ts_for_sql(ts),
                }
            )

        params_json = json.dumps(normalized, ensure_ascii=False)
        db_logger.debug(
            "[sync_base.edit] proc=%s items=%d types=%s ts=%r",
            proc_name,
            len(normalized),
            [len(n["dtp"]) for n in normalized],
            normalized[0]["ts"] if normalized else None,
        )

        _sync_base_stats.edit_calls += 1

        try:
            with teamdroid_sql_cursor() as cur:
                try:
                    cur.execute(f"EXEC {proc_name} @Params = ?", params_json)
                    while cur.nextset():
                        pass
                    cur.connection.commit()
                except Exception:
                    try:
                        cur.connection.rollback()
                    except pyodbc.Error as rb_exc:
                        db_logger.error(
                            "[sync_base.edit] rollback failed: %r",
                            rb_exc,
                            exc_info=True,
                        )
                    raise
        except pyodbc.Error as e:
            err_text = str(e)
            if "PRC_mbl_SyncBaseDataEdit_BadTs" in err_text:
                _sync_base_stats.edit_bad_ts += 1
                db_logger.warning("[sync_base.edit] BadTs proc=%s: %s", proc_name, err_text)
                raise RuntimeError(f"PRC_mbl_SyncBaseDataEdit_BadTs: {err_text}") from e

            if "PRC_mbl_SyncBaseDataEdit_NoData" in err_text or "50000" in err_text:
                _sync_base_stats.edit_errors += 1
                db_logger.warning("[sync_base.edit] NoData proc=%s: %s", proc_name, err_text)
                raise RuntimeError(f"PRC_mbl_SyncBaseDataEdit_NoData: {err_text}") from e

            _sync_base_stats.edit_errors += 1
            db_logger.error("[sync_base.edit] pyodbc error proc=%s: %s", proc_name, err_text, exc_info=True)
            raise
        except Exception:
            _sync_base_stats.edit_errors += 1
            raise

        _sync_base_stats.edit_items += len(normalized)
        _sync_base_stats.edit_types += sum(len(n["dtp"]) for n in normalized)

        db_logger.info(
            "[sync_base.edit] proc=%s committed items=%d types=%d",
            proc_name,
            len(normalized),
            sum(len(n["dtp"]) for n in normalized),
        )

    # ============================================================
    # DIAGNOSTICS
    # ============================================================

    @staticmethod
    def sync_base_stats_snapshot() -> dict[str, int]:
        return _sync_base_stats.snapshot()

    @staticmethod
    def bump_sync_stat(name: str, delta: int = 1) -> None:
        if not hasattr(_sync_base_stats, name):
            db_logger.warning("[bump_sync_stat] unknown counter: %r", name)
            return
        try:
            current = getattr(_sync_base_stats, name)
            setattr(_sync_base_stats, name, current + int(delta))
        except (TypeError, ValueError):
            db_logger.warning("[bump_sync_stat] invalid delta for %r: %r", name, delta)

    # ============================================================
    # LOW-LEVEL
    # ============================================================

    @staticmethod
    def _validate_proc_name(proc_name: str) -> None:
        if not _PROC_NAME_RE.match(proc_name):
            raise ValueError(f"Invalid procedure name: {proc_name!r}")

    @staticmethod
    def _run_json_proc(proc_name: str, params: dict[str, Any]) -> dict[str, Any]:
        TeamdroidProcedureRepository._validate_proc_name(proc_name)
        params_json = json.dumps(params, ensure_ascii=False)

        with teamdroid_sql_cursor() as cur:
            try:
                cur.execute(f"EXEC {proc_name} @Params = ?", params_json)

                result_obj: Any = None
                raw_cell: Any = None

                try:
                    if cur.description is not None:
                        row = cur.fetchone()
                        if row is not None:
                            raw_cell = row[0]
                            if isinstance(raw_cell, str | bytes):
                                text = (
                                    raw_cell.decode("utf-8", errors="replace")
                                    if isinstance(raw_cell, bytes)
                                    else raw_cell
                                )
                                try:
                                    result_obj = json.loads(text)
                                except (ValueError, TypeError):
                                    result_obj = None
                            else:
                                result_obj = raw_cell
                except pyodbc.Error:
                    raw_cell = None
                    result_obj = None

                cur.connection.commit()

                return {
                    "success": True,
                    "proc": proc_name,
                    "result": result_obj,
                    "raw": raw_cell,
                    "rows_affected": cur.rowcount if cur.rowcount is not None else -1,
                    "timestamp": get_timestamp(),
                }
            except Exception:
                try:
                    cur.connection.rollback()
                except pyodbc.Error as rb_exc:
                    db_logger.error(
                        "[_run_json_proc] rollback failed: %r",
                        rb_exc,
                        exc_info=True,
                    )
                raise


__all__ = ["TeamdroidProcedureRepository"]
