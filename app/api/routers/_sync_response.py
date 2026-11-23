"""Единая обработка ответа SQL Server для всех каналов синхронизации.

Используется из:
    POST /api/v1/client/register    (TokenVerify)
    POST /api/v1/client/login       (AuthLogin mid=1|2)
    POST /api/v1/client/sync-load   (SyncBaseData_Load)
    POST /api/v1/client/sync-edit   (SyncBaseData_Edit — возвращает новый пакет)

Все 4 процедуры возвращают ОДИН И ТОТ ЖЕ формат:
    sid   VARCHAR(36)     UUID пакета (пустой/NULL → «изменений нет»)
    snc   DATETIME        метка синхронизации
    dtp   NVARCHAR(MAX)   JSON-массив [DataTypeId, ...]
    prm   NVARCHAR(MAX)   JSON-массив [{dt, exp, val}, ...]

`record_and_build_response` парсит этот ответ, регистрирует sid в
in-memory реестре (для валидации последующего sync-edit) и возвращает
тело HTTP-ответа для клиента.
"""

from __future__ import annotations

import json
from typing import Any

from ...logger import api_logger
from ...services.sync_session_registry import sync_session_registry


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


def _parse_dtp(raw: Any) -> list[int]:
    parsed = _json_load(raw)
    if not isinstance(parsed, list):
        return []
    result: list[int] = []
    for t in parsed:
        try:
            result.append(int(t))
        except (ValueError, TypeError):
            continue
    return result


def _parse_prm(raw: Any) -> list[dict[str, Any]]:
    """Парсит `prm` из SQL в формат, который ждёт клиент.

    Возвращает массив элементов:
      * {"i": 1, "prm": {"frc":..., "ver":..., "vcd":...,
                        "fph":..., "fsz":..., "fhs":...}}  — update;
      * {"i": 2, "prm": [{"dt":..., "exp":..., "val": [...]}, ...]} — sync.

    Принимает как «сырой» формат SQL (элементы с `fup`/`sid`), так и
    уже нормализованный (элементы с `i`).
    """
    parsed = _json_load(raw)
    if not isinstance(parsed, list):
        return []

    out: list[dict[str, Any]] = []
    sync_items: list[dict[str, Any]] = []
    update_item: dict[str, Any] | None = None

    for item in parsed:
        if not isinstance(item, dict):
            continue

        # --- Уже нормализованный формат клиента: есть "i" ---
        i_val = item.get("i")
        if i_val in (1, 2):
            if i_val == 1 and update_item is None:
                update_item = item
            elif i_val == 2:
                sync_items.append(item)
            continue

        # --- Update-элемент из SQL: {"fup": 1, "prm": {...}} ---
        if "fup" in item:
            raw_inner = item.get("prm")
            inner = raw_inner
            if isinstance(raw_inner, str):
                try:
                    inner = json.loads(raw_inner)
                except (ValueError, TypeError):
                    inner = None
            if isinstance(inner, dict) and update_item is None:
                update_item = {"i": 1, "prm": inner}
            continue

        # --- Sync-элемент из SQL: {"sid":..., "dtp":..., "prm": [...]} ---
        raw_sync = item.get("prm")
        sync_parsed = raw_sync
        if isinstance(raw_sync, str):
            try:
                sync_parsed = json.loads(raw_sync)
            except (ValueError, TypeError):
                sync_parsed = None

        if isinstance(sync_parsed, list):
            for sub in sync_parsed:
                if not isinstance(sub, dict):
                    continue
                dt_val: Any = sub.get("dt")
                if dt_val is None or isinstance(dt_val, bool):
                    continue
                try:
                    dt_int = int(dt_val)
                except (ValueError, TypeError):
                    continue

                exp_int: int | None = None
                exp_val = sub.get("exp")
                if isinstance(exp_val, int | str):
                    try:
                        exp_int = int(exp_val)
                    except (ValueError, TypeError):
                        exp_int = None

                val = sub.get("val")
                if isinstance(val, str):
                    try:
                        parsed_val = json.loads(val)
                        val_clean: Any = parsed_val if isinstance(parsed_val, list) else []
                    except (ValueError, TypeError):
                        val_clean = []
                elif isinstance(val, list):
                    val_clean = val
                else:
                    val_clean = []

                sync_items.append({"dt": dt_int, "exp": exp_int, "val": val_clean})
            continue

        # --- Плоский sync-элемент: {"dt":..., "exp":..., "val":...} ---
        if "dt" in item:
            dt_val: Any = item.get("dt")
            if dt_val is None or isinstance(dt_val, bool):
                continue
            try:
                dt_int = int(dt_val)
            except (ValueError, TypeError):
                continue

            exp_int: int | None = None
            exp_val = item.get("exp")
            if isinstance(exp_val, int | str):
                try:
                    exp_int = int(exp_val)
                except (ValueError, TypeError):
                    exp_int = None

            val = item.get("val")
            if isinstance(val, str):
                try:
                    parsed_val = json.loads(val)
                    val_clean: Any = parsed_val if isinstance(parsed_val, list) else []
                except (ValueError, TypeError):
                    val_clean = []
            elif isinstance(val, list):
                val_clean = val
            else:
                val_clean = []

            sync_items.append({"dt": dt_int, "exp": exp_int, "val": val_clean})

    if update_item is not None:
        out.append(update_item)
    if sync_items:
        out.append({"i": 2, "prm": sync_items})
    return out


async def record_and_build_response(
    *,
    user_id: str,
    raw_sid: Any,
    raw_snc: Any,
    raw_dtp: Any,
    raw_prm: Any,
    source: str,
) -> dict[str, Any]:
    """Парсит ответ SQL, регистрирует sid и возвращает тело HTTP-ответа.

    Args:
        user_id: Tinode user id (usrXXX).
        raw_sid: сырое значение sid из SQL.
        raw_snc: сырое значение snc из SQL.
        raw_dtp: сырое значение dtp из SQL (JSON-строка или list).
        raw_prm: сырое значение prm/Result из SQL.
        source: имя источника для логов (register|login|sync-load|sync-edit).

    Returns:
        Тело ответа клиенту:
          {"scs": 1, "sid": ..., "prm": [...]}  — есть реальный пакет;
          {"scs": 1}                            — изменений нет.
    """
    sid = (
        raw_sid.decode("utf-8", errors="replace").strip()
        if isinstance(raw_sid, bytes)
        else (str(raw_sid).strip() if raw_sid is not None else "")
    )
    snc_str: str | None
    if isinstance(raw_snc, str):
        snc_str = raw_snc or None
    elif raw_snc is not None:
        snc_str = str(raw_snc)
    else:
        snc_str = None

    dtp = _parse_dtp(raw_dtp)
    prm = _parse_prm(raw_prm)

    # «Изменений нет» — только если sid пуст И prm пуст.
    # Если есть prm (update или sync), но нет sid — отдаём prm,
    # это валидный ответ клиенту (например, только update).
    if not sid and not prm:
        api_logger.info(
            "sync[%s]: no changes user=%s",
            source,
            user_id,
        )
        return {"scs": 1}

    if sid:
        try:
            await sync_session_registry.record_sid(
                user_id=user_id,
                sid=sid,
                snc=snc_str,
                dtp=dtp,
            )
            # legacy-совместимость: список dtp/ts для диагностики
            if snc_str and dtp:
                await sync_session_registry.record_load(
                    user_id=user_id,
                    sync_time=snc_str,
                    data_types=set(dtp),
                )
        except Exception as exc:
            api_logger.warning(
                "sync[%s]: failed to record sid user=%s sid=%s: %r",
                source,
                user_id,
                sid,
                exc,
            )

    api_logger.info(
        "sync[%s]: packet user=%s sid=%r snc=%r dtp=%s prm_rows=%d",
        source,
        user_id,
        sid or None,
        snc_str,
        dtp,
        len(prm),
    )
    body: dict[str, Any] = {"scs": 1}
    if sid:
        body["sid"] = sid
    if prm:
        body["prm"] = prm
    return body
