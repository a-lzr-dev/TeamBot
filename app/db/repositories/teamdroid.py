"""
Репозиторий вызова хранимых процедур SQL Server Teamdroid.

Все процедуры ходят через ЕДИНОЕ singleton-соединение
(get_teamdroid_sql_conn из app.db.manager) и строку подключения
TEAMDROID_SQL_*:

    TEAMDROID_SQL_PROC_AUTH_START               ext.PA_mbl_AuthStart_Exec
    TEAMDROID_SQL_PROC_AUTH_FINISH              ext.PA_mbl_AuthFinish_Exec
    TEAMDROID_SQL_PROC_TOKEN_VERIFY             ext.PA_mbl_TokenVerify_Exec
    TEAMDROID_SQL_PROC_TOKEN_FINISH             ext.PA_mbl_TokenFinish_Exec
    TEAMDROID_SQL_PROC_EDIT_MSG_STATUS_DELIVERY ext.PA_mbl_MsgsDeliveryStatus_Edit

Контракт всех процедур:
    EXEC <proc> @Params = N'<json>'
    Выход: одна JSON-строка в одной колонке одной строки,
    либо (Success BIT) для VerifyToken / TokenFinish.

Все методы синхронные (pyodbc блокирующий). Из async-кода вызывать так:

    import asyncio
    result = await asyncio.to_thread(TDProc.auth_start, params)
"""

from __future__ import annotations

import json
import re
from typing import Any

import pyodbc

from ...config import settings
from ...logger import db_logger
from ...utils.datetime import get_timestamp
from ..manager import teamdroid_sql_cursor

# Разрешённые символы в имени хранимой процедуры (защита от инъекции).
_PROC_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")

_WHAT_TO_WHT: dict[str, int] = {"recv": 1, "read": 2}


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
        """EXEC settings.TEAMDROID_SQL_PROC_AUTH_START @Params = N'<json>'.

        params обычно содержит: phone, client_ip (добавляется вызывающим).

        Returns:
            dict: {"success": True, "result": parsed_json|None,
                   "raw": <cell>, "rows_affected": int, "timestamp": str}
        """
        return TeamdroidProcedureRepository._run_json_proc(
            settings.TEAMDROID_SQL_PROC_AUTH_START,
            params,
        )

    @staticmethod
    def auth_finish(params: dict[str, Any]) -> dict[str, Any]:
        """EXEC settings.TEAMDROID_SQL_PROC_AUTH_FINISH @Params = N'<json>'.

        params обычно содержит: request_id, code, client_ip.

        Returns:
            dict: см. auth_start.
        """
        return TeamdroidProcedureRepository._run_json_proc(
            settings.TEAMDROID_SQL_PROC_AUTH_FINISH,
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
    ) -> tuple[bool, str | None]:
        """EXEC settings.TEAMDROID_SQL_PROC_TOKEN_VERIFY @Params = N'<json>'.

        Контракт процедуры:
            JSON: {"usi":"<hash>","api":<int>,"dvc":"<fid>",
                   "tkn":"yyMMdd","cip":"<ip>","ver":"<...>","vcd":<int>}
            Выход: (Success BIT). При отсутствии пользователя —
            THROW 50000 ('PRC_mbl_TokenVerify_NoData').

        Args:
            user_id: Tinode user ID (usrXXXX), он же usi.
            fcm_id: Firebase Installation ID.
            app_id: AppID приложения (dir.TRSDirSysApps.FID) — обязателен.
            token_date: Дата токена yyMMdd.
            client_ip: IP клиента ($.cip).
            app_version: Версия приложения (опционально).
            app_version_code: Кодовый номер версии (опционально).

        Returns:
            tuple[bool, str | None]: (успех, текст ошибки или None).
        """
        if not fcm_id:
            return False, "empty_fcm_id"
        if not user_id or not user_id.startswith("usr"):
            return False, "invalid_user_id"
        if not app_id or int(app_id) <= 0:
            return False, "invalid_app_id"

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

        db_logger.debug(
            "🔐 [verify_token] user=%s fcm=%s api=%d tkn=%s ip=%s",
            user_id,
            fcm_id[-6:] if len(fcm_id) >= 6 else "***",
            int(app_id),
            params["tkn"],
            params["cip"],
        )

        try:
            result = TeamdroidProcedureRepository._run_json_proc(proc_name, params)
            raw = result.get("raw")

            if raw is None:
                db_logger.warning(
                    "⚠️ [verify_token] procedure returned no rows for user=%s",
                    user_id,
                )
                return False, "no_rows"

            ok = raw == 1 or raw is True

            if ok:
                db_logger.info(
                    "✅ [verify_token] OK user=%s fcm=%s...",
                    user_id,
                    fcm_id[-6:] if len(fcm_id) >= 6 else "***",
                )
                return True, None

            db_logger.warning(
                "⚠️ [verify_token] rejected user=%s value=%r",
                user_id,
                raw,
            )
            return False, f"rejected_value={raw!r}"

        except pyodbc.Error as e:
            err_text = str(e)
            if "PRC_mbl_VerifyToken_NoData" in err_text or "50000" in err_text:
                db_logger.warning(
                    "⚠️ [verify_token] THROW NoData user=%s fcm=%s...: %s",
                    user_id,
                    fcm_id[-6:] if len(fcm_id) >= 6 else "***",
                    err_text,
                )
                return False, "PRC_mbl_VerifyToken_NoData"

            db_logger.error(
                "❌ [verify_token] pyodbc error user=%s: %s",
                user_id,
                err_text,
                exc_info=True,
            )
            return False, f"pyodbc: {err_text}"

        except Exception as e:
            db_logger.error(
                "❌ [verify_token] unexpected error user=%s: %r",
                user_id,
                e,
                exc_info=True,
            )
            return False, repr(e)

    # ============================================================
    # TOKEN FINISH (logout / WS disconnect)
    # ============================================================

    @staticmethod
    def token_finish(
        *,
        user_id: str,
        fcm_id: str,
        app_id: int,
    ) -> tuple[bool, str | None]:
        """EXEC settings.TEAMDROID_SQL_PROC_TOKEN_FINISH @Params = N'<json>'.

        Контракт процедуры:
            JSON: {"usi":"<hash>","api":<int>,"dvc":"<fid>"}
            Выход: (Success BIT). При отсутствии пользователя —
            THROW 50000 ('PRC_mbl_TokenFinish_NoData').

        Вызывается при разъединении WebSocket-соединения,
        чтобы завершить сессию токена в Teamdroid SQL Server.

        Args:
            user_id: Tinode user ID (usrXXXX), он же usi.
            fcm_id: Firebase Installation ID.
            app_id: AppID приложения (dir.TRSDirSysApps.FID) — обязателен.

        Returns:
            tuple[bool, str | None]: (успех, текст ошибки или None).
        """
        if not fcm_id:
            return False, "empty_fcm_id"
        if not user_id or not user_id.startswith("usr"):
            return False, "invalid_user_id"
        if not app_id or int(app_id) <= 0:
            return False, "invalid_app_id"

        params: dict[str, Any] = {
            "usi": user_id[:64],
            "api": int(app_id),
            "dvc": fcm_id[:255],
        }

        proc_name = settings.TEAMDROID_SQL_PROC_TOKEN_FINISH

        db_logger.debug(
            "🔚 [token_finish] user=%s fcm=%s api=%d",
            user_id,
            fcm_id[-6:] if len(fcm_id) >= 6 else "***",
            int(app_id),
        )

        try:
            result = TeamdroidProcedureRepository._run_json_proc(proc_name, params)
            raw = result.get("raw")

            if raw is None:
                db_logger.warning(
                    "⚠️ [token_finish] procedure returned no rows for user=%s",
                    user_id,
                )
                return False, "no_rows"

            ok = raw == 1 or raw is True

            if ok:
                db_logger.info(
                    "✅ [token_finish] OK user=%s fcm=%s...",
                    user_id,
                    fcm_id[-6:] if len(fcm_id) >= 6 else "***",
                )
                return True, None

            db_logger.warning(
                "⚠️ [token_finish] rejected user=%s value=%r",
                user_id,
                raw,
            )
            return False, f"rejected_value={raw!r}"

        except pyodbc.Error as e:
            err_text = str(e)
            if "PRC_mbl_TokenFinish_NoData" in err_text or "50000" in err_text:
                db_logger.warning(
                    "⚠️ [token_finish] THROW NoData user=%s fcm=%s...: %s",
                    user_id,
                    fcm_id[-6:] if len(fcm_id) >= 6 else "***",
                    err_text,
                )
                return False, "PRC_mbl_TokenFinish_NoData"

            db_logger.error(
                "❌ [token_finish] pyodbc error user=%s: %s",
                user_id,
                err_text,
                exc_info=True,
            )
            return False, f"pyodbc: {err_text}"

        except Exception as e:
            db_logger.error(
                "❌ [token_finish] unexpected error user=%s: %r",
                user_id,
                e,
                exc_info=True,
            )
            return False, repr(e)

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
        """Один статус. Формирует массив из одного элемента.

        Процедура принимает ТОЛЬКО массив, поэтому даже для одного статуса
        отправляем `[{...}]`.
        """
        if what not in _WHAT_TO_WHT:
            # kp и прочее в SQL не сохраняем.
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
        """Сохранить recv и/или read ОДНИМ EXEC-ом с JSON-массивом.

        @Params всегда массив, даже если запрошен только один статус:
            [{"tpc":...,"wht":1,...}]                      # только recv
            [{"tpc":...,"wht":2,...}]                      # только read
            [{"tpc":...,"wht":1,...},{"tpc":...,"wht":2,...}]  # recv+read

        Процедура обрабатывает все статусы в одной транзакции.
        """
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
                except Exception:  # noqa: BLE001
                    pass

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
                    # Кто-то вызвал процедуру в обход репозитория — объектом.
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
                except Exception:  # noqa: BLE001
                    pass
                raise

    # ============================================================
    # LOW-LEVEL
    # ============================================================

    @staticmethod
    def _validate_proc_name(proc_name: str) -> None:
        """Проверяет имя хранимой процедуры на допустимые символы."""
        if not _PROC_NAME_RE.match(proc_name):
            raise ValueError(f"Invalid procedure name: {proc_name!r}")

    @staticmethod
    def _run_json_proc(proc_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """EXEC <proc> @Params = N'<json>' на singleton-соединении.

        Args:
            proc_name: полное имя процедуры (schema.name).
            params: JSON-совместимый словарь.

        Returns:
            dict: {"success": True, "proc": ..., "result": parsed_json|None,
                   "raw": <first_cell>, "rows_affected": int,
                   "timestamp": str}

        Raises:
            ValueError: невалидное имя процедуры.
            pyodbc.Error: ошибка SQL Server (включая THROW).
        """
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
                            if isinstance(raw_cell, (str, bytes)):
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

                # commit для DML-процедур, иначе транзакция висит
                # в singleton-соединении.
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
                # Откат при ошибке, чтобы не «зависла» транзакция
                # в singleton-соединении.
                try:
                    cur.connection.rollback()
                except Exception:  # noqa: BLE001
                    pass
                raise


__all__ = ["TeamdroidProcedureRepository"]
