"""Репозиторий Service Broker для приёма сигналов и отправки ответов."""

from __future__ import annotations

import json
import re
from typing import Any

from ...config import settings
from ..manager import teamdroid_sql_cursor

# Разрешённые символы в имени хранимой процедуры (защита от инъекции).
_PROC_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


class TeamdroidServiceBrokerRepository:
    """Синхронные методы (вызывать через asyncio.to_thread)."""

    @staticmethod
    def _validate_proc_name(proc_name: str) -> None:
        """Проверяет имя хранимой процедуры на допустимые символы."""
        if not _PROC_NAME_RE.match(proc_name):
            raise ValueError(f"Invalid procedure name: {proc_name!r}")

    @staticmethod
    def receive_signals() -> list[dict[str, Any]]:
        """Блокирующий RECEIVE через ext.PA_mbl_Notifies_Load.

        Возвращает список {handle, payload}.

        ВАЖНО: процедура делает `RETURN 0` после WAITFOR/RECEIVE.
        pyodbc может выдать это как дополнительный result set —
        поэтому читаем ТОЛЬКО первый набор (`cur.fetchall()` сразу
        после `execute`), а `while cur.nextset()` здесь НЕ выполняем:
        нам нужен именно первый набор RECEIVE.
        """
        proc_name = settings.TEAMDROID_SQL_PROC_NOTIFIES_LOAD
        TeamdroidServiceBrokerRepository._validate_proc_name(proc_name)

        result: list[dict[str, Any]] = []
        with teamdroid_sql_cursor() as cur:
            try:
                cur.execute(f"EXEC {proc_name};")
                rows = cur.fetchall()
                for row in rows:
                    handle = row[0]
                    payload = row[1]
                    try:
                        parsed = json.loads(payload) if payload else {}
                    except (ValueError, TypeError):
                        parsed = {}
                    result.append({"handle": handle, "payload": parsed})
                cur.connection.commit()
            except Exception:
                cur.connection.rollback()
                raise
        return result

    @staticmethod
    def send_result(handle: Any, payload: dict[str, Any]) -> None:
        """SEND ON CONVERSATION + END CONVERSATION через ext.PA_mbl_Notifies_Send."""
        proc_name = settings.TEAMDROID_SQL_PROC_NOTIFIES_SEND
        TeamdroidServiceBrokerRepository._validate_proc_name(proc_name)

        payload_json = json.dumps(payload, ensure_ascii=False)

        with teamdroid_sql_cursor() as cur:
            try:
                cur.execute(
                    f"EXEC {proc_name} @handle = ?, @payload = ?;",
                    handle,
                    payload_json,
                )
                cur.connection.commit()
            except Exception:
                cur.connection.rollback()
                raise

    @staticmethod
    def mark_sent(user_id: str, topic: str, msg_type: str, channel: str) -> None:
        """Вызов PA_mbl_Notify_MarkSent."""
        with teamdroid_sql_cursor() as cur:
            try:
                cur.execute(
                    "EXEC ext.PA_mbl_Notify_MarkSent @UserId=?, @Topic=?, @Type=?, @Channel=?",
                    user_id,
                    topic,
                    msg_type,
                    channel,
                )
                cur.connection.commit()
            except Exception:
                cur.connection.rollback()
                raise


__all__ = ["TeamdroidServiceBrokerRepository"]
