"""
Модуль роутера для интеграции с Teamdroid.

Эндпоинты:
    * POST /send-code   — запуск хранимой процедуры SQL Server (отправка кода).
    * POST /verify-code — запуск хранимой процедуры SQL Server (проверка кода).
    * POST /note        — пересылка {note} (recv/read/kp) в Tinode через gRPC
                          и сохранение recv/read в Teamdroid SQL Server.
    * POST /send-files  — отправка файлов из SQL Server в Teamdroid.
    * POST /send-text   — отправка текстового сообщения в Teamdroid.
    * POST /delete-messages — удаление сообщений в топике Teamdroid.
    * POST /grant-user  — выдача прав пользователю в топике.
    * GET  /acs/{topic} — получение ACS топика.
    * GET  /user-id/{id_val} — генерация Teamdroid user id (usrXXXX).
    * GET  /health      — проверка доступности Teamdroid.

SQL Server (CHANGED):
    Все четыре хранимые процедуры (AuthStart, AuthFinish, VerifyToken,
    MsgsDeliveryStatus) ходят через ЕДИНОЕ singleton-соединение,
    которое теперь живёт в app.db.manager (get_teamdroid_sql_conn /
    teamdroid_sql_cursor) и конфигурируется переменными TEAMDROID_SQL_*.

    Вызовы процедур инкапсулированы в
    app.db.repositories.TeamdroidProcedureRepository — роутер
    больше не работает с pyodbc напрямую (кроме _load_files, которому
    нужно отдельное соединение для длительного чтения файлов).

Метаданные клиента:
    Сервер САМ извлекает IP клиента из стандартных заголовков,
    проставленных nginx (X-Forwarded-For / X-Real-IP). Клиент НЕ
    передаёт X-App-*, X-Device-*, X-OS-*, User-Agent — сервер
    их не принимает и в хранимые процедуры не передаёт.

    ВАЖНО: из X-Forwarded-For берётся ПОСЛЕДНИЙ адрес (добавленный
    доверенным прокси nginx), а не первый — первый может быть подделан
    клиентом.

Идентичность пользователя:
    В /note идентификатор пользователя передаётся в ТЕЛЕ запроса
    (поле user_id) и является ОБЯЗАТЕЛЬНЫМ. Сервер не принимает
    клиентскую идентичность из заголовков.
"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import queue
import re
import struct
import threading
from collections.abc import Iterator, Mapping
from typing import Any, cast

import grpc
import pyodbc
import requests
from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from google.protobuf.json_format import MessageToDict
    from google.protobuf.message import Message
except ImportError:  # pragma: no cover
    MessageToDict = None  # type: ignore[assignment]
    Message = None  # type: ignore[assignment]

from ...config import settings
from ...db.manager import build_teamdroid_sql_conn_str, close_teamdroid_sql
from ...db.repositories import TeamdroidProcedureRepository  # NEW
from ...logger import api_logger
from ...utils.datetime import get_timestamp
from ...utils.decorators import log_exceptions

# Импорт сгенерированных protobuf-модулей Teamdroid.
try:
    from app import model_pb2, model_pb2_grpc

    TEAMDROID_PB_AVAILABLE = True
except ImportError as exc:  # pragma: no cover
    model_pb2 = None  # type: ignore[assignment]
    model_pb2_grpc = None  # type: ignore[assignment]
    TEAMDROID_PB_AVAILABLE = False
    api_logger.warning(f"⚠️ Teamdroid protobuf modules not available: {exc}")


# ============================================================
# РОУТЕР
# ============================================================

router = APIRouter(prefix="/teamdroid", tags=["Teamdroid"])

CHUNK_SIZE = 64 * 1024

# Допустимые символы прав доступа Teamdroid (ACS)
_ACS_VALID_CHARS = frozenset("JRWPSACDO")
# Допустимые префиксы топиков Teamdroid
_TOPIC_PREFIXES = ("usr", "grp", "p2p", "fnd", "me")
# Допустимые префиксы sender (только пользовательские)
_USER_PREFIX = "usr"

_USER_ID_RE = re.compile(r"^usr[A-Za-z0-9_\-]{10,}$")

# Допустимые значения what для /note.
_NOTE_WHAT_ALLOWED = frozenset({"recv", "read", "kp"})

# MIME-типы для офисных форматов.
_EXTRA_MIME: dict[str, str] = {
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".zip": "application/zip",
    ".7z": "application/x-7z-compressed",
    ".rar": "application/vnd.rar",
    ".heic": "image/heic",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".rtf": "application/rtf",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}

# Префиксы схем для HTTPAdapter.mount().
_HTTP_SCHEME = "http://"
_HTTPS_SCHEME = "https://"

_RETRY_POLICY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[],
    allowed_methods=frozenset(["GET", "POST"]),
)

_http_session = requests.Session()
_http_session.mount(_HTTP_SCHEME, HTTPAdapter(max_retries=_RETRY_POLICY))
_http_session.mount(_HTTPS_SCHEME, HTTPAdapter(max_retries=_RETRY_POLICY))


def close_http_session() -> None:
    """Закрытие глобальной HTTP-сессии при shutdown приложения."""
    try:
        _http_session.close()
    except Exception as close_exc:
        api_logger.warning(f"[teamdroid] failed to close http session: {close_exc!r}")


# ============================================================
# PYDANTIC-МОДЕЛИ
# ============================================================


class SendFilesRequest(BaseModel):
    """Модель запроса для отправки файлов из SQL Server в Teamdroid."""

    file_ids: list[int] = Field(
        ...,
        description="Список FID файлов в SQL Server",
        min_length=1,
        max_length=100,
    )
    topic: str = Field(..., description="Teamdroid топик", min_length=1, max_length=64)
    text: str = Field("", description="Текст сообщения", max_length=4000)
    sender: str = Field(
        "",
        description="ID пользователя (только для root-аккаунта), например usrXXXXXX",
        max_length=32,
    )

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        v = v.strip()
        if not any(v.startswith(p) for p in _TOPIC_PREFIXES):
            raise ValueError(f"Topic must start with one of: {', '.join(_TOPIC_PREFIXES)} (got '{v}')")
        if not re.fullmatch(r"[A-Za-z0-9_\-:.]+", v):
            raise ValueError("Topic contains invalid characters")
        return v

    @field_validator("sender")
    @classmethod
    def validate_sender(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return v
        if not _USER_ID_RE.match(v):
            raise ValueError(f"sender must match usr[A-Za-z0-9_-]+, got {v!r}")
        return v


class SendTextRequest(BaseModel):
    """Модель запроса для отправки текстового сообщения."""

    topic: str = Field(..., description="Teamdroid топик", min_length=1, max_length=64)
    text: str = Field("TEST PUB", description="Текст сообщения", max_length=4000)
    sender: str = Field(
        "",
        description="ID пользователя (только для root-аккаунта), например usrXXXXXX",
        max_length=32,
    )

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        v = v.strip()
        if not any(v.startswith(p) for p in _TOPIC_PREFIXES):
            raise ValueError(f"Topic must start with one of: {', '.join(_TOPIC_PREFIXES)}")
        return v

    @field_validator("sender")
    @classmethod
    def validate_sender(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return v
        if not _USER_ID_RE.match(v):
            raise ValueError(f"sender must match usr[A-Za-z0-9_-]+, got {v!r}")
        return v


class DelRange(BaseModel):
    """Диапазон ID сообщений для удаления."""

    low: int = Field(..., ge=0, description="Нижняя граница диапазона (включительно)")
    hi: int = Field(0, ge=0, description="Верхняя граница (включительно). 0 — только low.")


class DeleteMessagesRequest(BaseModel):
    """Модель запроса для удаления сообщений топика Teamdroid."""

    topic: str = Field(..., description="Teamdroid топик", min_length=1, max_length=64)
    del_seq: list[DelRange] = Field(
        ...,
        description=(
            "Список диапазонов ID сообщений для удаления. "
            'Если "hi" отсутствует или 0 — удаляется только сообщение с ID "low".'
        ),
        min_length=1,
        max_length=1000,
    )
    hard: bool = Field(
        False,
        description=(
            "Если True — удалить сообщения для всех пользователей (требует права 'D'). "
            "Если False — удаление только для текущего пользователя."
        ),
    )

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        v = v.strip()
        if not any(v.startswith(p) for p in _TOPIC_PREFIXES):
            raise ValueError(f"Topic must start with one of: {', '.join(_TOPIC_PREFIXES)}")
        return v


class GrantUserRequest(BaseModel):
    """Модель запроса для выдачи прав пользователю в топике."""

    topic: str = Field(..., description="Teamdroid топик", min_length=1, max_length=64)
    user_id: str = Field(
        ...,
        description="ID пользователя, например usrXXXXXX",
        min_length=1,
        max_length=32,
    )
    given: str = Field("JRWPS", description="Права, которые выдаёт текущий пользователь", max_length=10)
    want: str = Field("JRWPS", description="Права, которые запрашиваются", max_length=10)

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        v = v.strip()
        if not any(v.startswith(p) for p in _TOPIC_PREFIXES):
            raise ValueError(f"Topic must start with one of: {', '.join(_TOPIC_PREFIXES)}")
        return v

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        v = v.strip()
        if not _USER_ID_RE.match(v):
            raise ValueError(f"user_id must match usr[A-Za-z0-9_-]+, got {v!r}")
        return v

    @field_validator("given", "want")
    @classmethod
    def validate_acs(cls, v: str) -> str:
        invalid = set(v) - _ACS_VALID_CHARS
        if invalid:
            raise ValueError(f"ACS contains invalid characters: {invalid}")
        return v


class SendFilesResponse(BaseModel):
    """Модель ответа при успешной отправке файлов."""

    success: bool = Field(True, description="Успешность операции")
    topic: str = Field(..., description="Teamdroid топик")
    files_count: int = Field(..., description="Количество отправленных файлов")
    files: list[dict[str, Any]] = Field(default_factory=list, description="Информация об отправленных файлах")
    message: str = Field(..., description="Сообщение о результате")
    timestamp: str = Field(..., description="Время выполнения операции")


class MakeUserIdResponse(BaseModel):
    """Ответ с сгенерированным Teamdroid user id."""

    success: bool = Field(True, description="Успешность операции")
    id_val: int = Field(..., description="Исходный числовой ID")
    user_id: str = Field(..., description="Teamdroid user id, например usrXXXXXX")
    timestamp: str = Field(..., description="Время операции")


class ErrorResponse(BaseModel):
    """Стандартная модель ответа при ошибке."""

    success: bool = Field(False, description="Успешность операции (всегда False)")
    status_code: int = Field(..., description="HTTP status code")
    error: str = Field(..., description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время ошибки")


# ------------------------------------------------------------------
# Модели для /note (recv/read/kp)
# ------------------------------------------------------------------


class NoteRelayRequest(BaseModel):
    """Запрос от мобильного клиента: {note} для пересылки в Tinode.

    Поле ``user_id`` (Tinode user ID ``usrXXX``) — это одновременно и
    ``usi`` (хэш пользователя Teamdroid). Они совпадают: ``usrXXX``
    формируется XTEA-шифрованием числового ID пользователя (см.
    ``make_teamdroid_user_id``), и это же значение хранится в
    ``TRSAppUsersValues.FValue`` (FK_Link=4) как хэш пользователя.

    Хранимая процедура ``ext.PA_mbl_MsgsDeliveryStatus_Edit`` ищет
    пользователя по ``uv.FValue = jsn.UserHash`` (FK_Link=4), поэтому
    в ``usi`` передаётся тот же ``usrXXX``, что и в ``user_id``.

    Поддержка старых клиентов (без ``user_id``) удалена: запрос без
    ``user_id`` отклоняется на этапе валидации Pydantic (HTTP 422).
    """

    topic: str = Field(
        ...,
        description="Tinode topic (usrXXX/grpXXX/p2pXXX)",
        min_length=1,
        max_length=64,
    )
    what: str = Field(..., description="Тип note: recv | read | kp", min_length=1, max_length=8)
    seq: int = Field(..., description="Seq ID сообщения", ge=0)
    user_id: str = Field(
        ...,
        description=(
            "Tinode user ID (usrXXX). Одновременно является usi — "
            "хэшем пользователя Teamdroid (FValue из TRSAppUsersValues, "
            "FK_Link=4)."
        ),
        max_length=32,
    )
    tinode_server: str | None = Field(
        None,
        description="Origin Tinode-сервера (для совместимости с мобильным клиентом; игнорируется)",
        max_length=255,
    )

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        v = v.strip()
        if not any(v.startswith(p) for p in _TOPIC_PREFIXES):
            raise ValueError(f"Topic must start with one of: {', '.join(_TOPIC_PREFIXES)}")
        if not re.fullmatch(r"[A-Za-z0-9_\-:.]+", v):
            raise ValueError("Topic contains invalid characters")
        return v

    @field_validator("what")
    @classmethod
    def validate_what(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _NOTE_WHAT_ALLOWED:
            raise ValueError(f"what must be one of: {', '.join(sorted(_NOTE_WHAT_ALLOWED))}, got {v!r}")
        return v

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        v = v.strip()
        if not _USER_ID_RE.match(v):
            raise ValueError(f"user_id must match usr[A-Za-z0-9_-]+, got {v!r}")
        return v


class NoteRelayResponse(BaseModel):
    """Ответ на /note: подтверждение пересылки в Tinode."""

    success: bool = Field(True, description="Успешность операции")
    topic: str = Field(..., description="Tinode topic")
    what: str = Field(..., description="Тип note (recv/read/kp)")
    seq: int = Field(..., description="Seq ID сообщения")
    user_id: str = Field(..., description="ID пользователя, от имени которого отправлен note")
    ctrl_code: int | None = Field(None, description="Код CTRL-ответа Tinode (200 = OK)")
    ctrl_text: str | None = Field(None, description="Текст CTRL-ответа Tinode")
    teamdroid_saved: bool = Field(False, description="Факт recv/read сохранён в Teamdroid SQL Server")
    timestamp: str = Field(..., description="Время операции")


# ============================================================
# SQL SERVER — FILE LOADING (отдельное соединение)
# ============================================================
#
# CHANGED: singleton-соединение и _run_json_proc переехали в
# app.db.manager и app.db.repositories.teamdroid. Роутер больше
# не держит SQL-connection для процедур.
#
# Единственное, что осталось здесь — _load_files: чтение больших
# файлов может занимать секунды/минуты, поэтому использует
# ОТДЕЛЬНОЕ соединение (build_teamdroid_sql_conn_str), чтобы не
# блокировать singleton на время загрузки.


def _guess_mime(file_name: str, extension: str) -> str:
    """Определяет MIME-тип файла с учётом офисных форматов."""
    ext = extension.lower()
    if not ext.startswith("."):
        ext = "." + ext
    if ext in _EXTRA_MIME:
        return _EXTRA_MIME[ext]
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or "application/octet-stream"


def get_file(conn: pyodbc.Connection, fid: int) -> dict[str, Any]:
    """Извлекает файл из SQL Server по FID."""
    sql = """
        SELECT
            f.FID,
            f.FFileName,
            f.FName,
            f.FExtention,
            d.FData
        FROM TRSAppFiles f
        INNER JOIN TRSAppFilesData d
            ON d.FK_Parent = f.FID
        WHERE f.FID = ?
    """

    cur = conn.cursor()
    cur.execute(sql, fid)
    row = cur.fetchone()

    if not row:
        raise RuntimeError(f"FID={fid} not found")

    file_id = int(row.FID)
    file_name = row.FFileName or row.FName or str(file_id)
    extension = row.FExtention or ""

    if extension and not extension.startswith("."):
        extension = "." + extension

    if not os.path.splitext(file_name)[1] and extension:
        file_name += extension

    data = bytes(row.FData or b"")
    mime_type = _guess_mime(file_name, extension)

    return {
        "fid": file_id,
        "name": file_name,
        "mime": mime_type,
        "size": len(data),
        "data": data,
    }


def _load_files(fids: list[int]) -> list[dict[str, Any]]:
    """Синхронно загружает файлы из SQL Server по списку FID.

    Использует ОТДЕЛЬНОЕ соединение, а не singleton: чтение файлов
    может занимать секунды/минуты, и держать на это время
    блокировку singleton-соединения (которое нужно AuthStart/
    VerifyToken) недопустимо.
    """
    conn = pyodbc.connect(
        build_teamdroid_sql_conn_str(),
        timeout=getattr(settings, "TEAMDROID_SQL_TIMEOUT", 10),
    )
    try:
        return [get_file(conn, fid) for fid in fids]
    finally:
        try:
            conn.close()
        except Exception as close_exc:
            api_logger.warning(f"[teamdroid] failed to close file-load connection: {close_exc!r}")


# ============================================================
# ПАРСИНГ ТЕКСТА В DRAFTY (порт Drafty.parse из Android-клиента)
# ============================================================

_DRAFTY_INLINE_STYLES: list[tuple[str, re.Pattern[str]]] = [
    ("ST", re.compile(r"(^|[\W_])\*([^*]+[^\s*])\*(?=$|[\W_])")),
    ("EM", re.compile(r"(^|\W)_([^_]+[^\s_])_(?=$|\W)")),
    ("DL", re.compile(r"(^|[\W_])~([^~]+[^\s~])~(?=$|[\W_])")),
    ("CO", re.compile(r"(^|\W)`([^`]+)`(?=$|\W)")),
]

_DRAFTY_ENTITIES: list[tuple[str, re.Pattern[str], Any]] = [
    (
        "LN",
        re.compile(
            r"(^|[\W_])((https?://)?(?:www\.)?(?:[a-z0-9][-a-z0-9]*[a-z0-9]\.){1,5}"
            r"[a-z]{2,6}(?:[/?#:][-a-z0-9@:%_+.~#?&/=]*)?)",
            re.IGNORECASE,
        ),
        lambda m: {
            "url": m.group(2) if m.group(3) else "http://" + m.group(2),
        },
    ),
    (
        "MN",
        re.compile(
            r"(^|[\W_])@([^\W\d_][._\w]*[^\W\d_])",
            re.UNICODE,
        ),
        lambda m: {"val": "@" + m.group(2)},
    ),
    (
        "HT",
        re.compile(
            r"(^|[\W_])#([^\W\d_][._\w]*[^\W\d_])",
            re.UNICODE,
        ),
        lambda m: {"val": "#" + m.group(2)},
    ),
]


def _spannify(text: str, pattern: re.Pattern[str], style: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for m in pattern.finditer(text):
        spans.append(
            {
                "start": m.start(2),
                "end": m.end(2),
                "text": m.group(2),
                "type": style,
                "children": None,
            }
        )
    return spans


def _chunkify(line: str, start: int, end: int, spans: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not spans:
        return None

    chunks: list[dict[str, Any]] = []
    for span in spans:
        if span["start"] > start:
            chunks.append({"text": line[start : span["start"]]})

        chunk: dict[str, Any] = {"type": span["type"]}
        children = _chunkify(line, span["start"] + 1, span["end"], span.get("children"))
        if children:
            chunk["children"] = children
        else:
            chunk["text"] = span["text"]
        chunks.append(chunk)
        start = span["end"] + 1

    if start < end:
        chunks.append({"text": line[start:end]})

    return chunks


def _to_span_tree(spans: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not spans:
        return None

    tree: list[dict[str, Any]] = []
    last = spans[0]
    tree.append(last)
    for curr in spans[1:]:
        if curr["start"] > last["end"]:
            tree.append(curr)
            last = curr
        elif curr["end"] < last["end"]:
            last.setdefault("children", []).append(curr)

    for s in tree:
        s["children"] = _to_span_tree(s.get("children") or [])
    return tree


def _draftify(chunks: list[dict[str, Any]] | None, start_at: int) -> dict[str, Any] | None:
    if not chunks:
        return None

    txt = ""
    fmt: list[dict[str, Any]] = []
    for chunk in chunks:
        if chunk.get("text") is None:
            drafty = _draftify(chunk.get("children") or [], len(txt) + start_at)
            if drafty:
                chunk["text"] = drafty["txt"]
                if drafty.get("fmt"):
                    fmt.extend(drafty["fmt"])

        if chunk.get("type"):
            fmt.append(
                {
                    "at": len(txt) + start_at,
                    "len": len(chunk.get("text") or ""),
                    "tp": chunk["type"],
                }
            )

        if chunk.get("text") is not None:
            txt += chunk["text"]

    return {"txt": txt, "fmt": fmt or None}


def _extract_entities(line: str) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    for tp, pattern, pack in _DRAFTY_ENTITIES:
        for m in pattern.finditer(line):
            extracted.append(
                {
                    "at": m.start(2),
                    "len": len(m.group(2)),
                    "tp": tp,
                    "data": pack(m),
                }
            )
    return extracted


def drafty_parse(text: str) -> dict[str, Any]:
    """Порт Drafty.parse(): plain-text -> Drafty dict."""
    if text is None:
        text = ""

    text = text.replace("\u2421", "")

    lines = re.split(r"\r?\n", text)
    blocks: list[dict[str, Any]] = []
    entity_map: dict[str, int] = {}
    refs: list[dict[str, Any]] = []

    for line in lines:
        spans: list[dict[str, Any]] = []
        for style, pattern in _DRAFTY_INLINE_STYLES:
            spans.extend(_spannify(line, pattern, style))

        if spans:
            spans.sort(key=lambda s: s["start"])
            spans = _to_span_tree(spans) or []
            spans = _chunkify(line, 0, len(line), spans) or []
            block = _draftify(spans, 0) or {"txt": line, "fmt": None}
        else:
            block = {"txt": line, "fmt": None}

        for ent in _extract_entities(block.get("txt") or ""):
            key = ent["data"]["url"] if ent["tp"] == "LN" else ent["data"]["val"]
            idx = entity_map.get(key)
            if idx is None:
                idx = len(refs)
                entity_map[key] = idx
                refs.append({"tp": ent["tp"], "data": ent["data"]})

            fmt_list = block.get("fmt")
            if fmt_list is None:
                fmt_list = []
                block["fmt"] = fmt_list
            fmt_list.append({"at": ent["at"], "len": ent["len"], "key": idx})

        blocks.append(block)

    txt = ""
    fmt: list[dict[str, Any]] = []
    if blocks:
        first = blocks[0]
        txt = first.get("txt") or ""
        for s in first.get("fmt") or []:
            fmt.append(dict(s))

        for block in blocks[1:]:
            offset = len(txt) + 1
            fmt.append({"at": offset - 1, "len": 1, "tp": "BR"})
            txt += " "
            if block.get("txt") is not None:
                txt += block["txt"]
            for s in block.get("fmt") or []:
                s2 = dict(s)
                s2["at"] = int(s2["at"]) + offset
                fmt.append(s2)

    result: dict[str, Any] = {"txt": txt}
    if fmt:
        result["fmt"] = fmt
    if refs:
        result["ent"] = refs
    return result


# ============================================================
# TEAMDROID CLIENT
# ============================================================


def _require_pb() -> tuple[Any, Any]:
    """Возвращает (model_pb2, model_pb2_grpc), гарантируя что они не None."""
    if model_pb2 is None or model_pb2_grpc is None:
        raise RuntimeError("Teamdroid protobuf modules (model_pb2, model_pb2_grpc) are not available")
    return model_pb2, model_pb2_grpc


class TeamdroidClient:
    """Клиент для работы с Teamdroid через gRPC.

    Singleton-клиент: один gRPC-канал на всё приложение.
    Клиент не закрывается после каждого запроса — это устраняет ошибки
    `context canceled` на стороне сервера Teamdroid.

    Реализует базовый протокол Teamdroid: HI, LOGIN, SUB, GET, SET, PUB, DEL, NOTE.
    Поддерживает загрузку файлов через HTTP-эндпоинт Teamdroid.
    """

    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password

        self.channel: grpc.Channel | None = None
        self.stub: Any = None
        self.stream: Any = None

        self.tx_queue: queue.Queue[Any] = queue.Queue()

        self.running = False
        self.stream_thread: threading.Thread | None = None

        self._id = 0
        self._lock = threading.Lock()

        self._ctrl_waiters: dict[str, queue.Queue[Any]] = {}
        self._ctrl_waiters_lock = threading.Lock()

        self._subscribed: set[str] = set()
        self._subscribed_lock = threading.Lock()

    def next_id(self) -> str:
        with self._lock:
            self._id += 1
            return str(self._id)

    def connect(self) -> None:
        pb_mod, pb_grpc_mod = _require_pb()

        self.channel = grpc.insecure_channel(
            self.host,
            options=[
                ("grpc.max_send_message_length", settings.TEAMDROID_GRPC_MAX_MESSAGE),
                (
                    "grpc.max_receive_message_length",
                    settings.TEAMDROID_GRPC_MAX_MESSAGE,
                ),
            ],
        )
        self.stub = pb_grpc_mod.NodeStub(self.channel)

        self.running = True
        self.stream = self.stub.MessageLoop(self._outgoing())

        thread = threading.Thread(target=self._consume_stream, daemon=True)
        self.stream_thread = thread
        thread.start()

    def _outgoing(self) -> Iterator[Any]:
        while self.running:
            try:
                msg = self.tx_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg is None:
                break
            yield msg

    def _consume_stream(self) -> None:
        stream = self.stream
        if stream is None:
            return
        try:
            for msg in stream:
                self._handle_server_message(msg)
        except grpc.RpcError as rpc_exc:
            if self.running:
                api_logger.error(f"[teamdroid] gRPC stream error: {rpc_exc}", exc_info=True)
                self.running = False
        except Exception as stream_exc:
            if self.running:
                api_logger.error(f"[teamdroid] stream error: {stream_exc!r}", exc_info=True)
                self.running = False

    def _handle_server_message(self, msg: Any) -> None:
        if msg.HasField("ctrl"):
            ctrl = msg.ctrl
            request_id = str(getattr(ctrl, "id", "") or "")
            with self._ctrl_waiters_lock:
                waiter = self._ctrl_waiters.get(request_id)
            if waiter is not None:
                waiter.put(ctrl)
            else:
                ctrl_code = getattr(ctrl, "code", None)
                ctrl_text = getattr(ctrl, "text", None)
                api_logger.warning(
                    "[teamdroid] unsolicited ctrl id=%r code=%r text=%r pending_waiters=%s (race?)",
                    request_id,
                    ctrl_code,
                    ctrl_text,
                    len(self._ctrl_waiters),
                )
            return
        return

    def _send(self, msg: Any) -> None:
        if not self.running:
            raise RuntimeError("Teamdroid client is not running")
        self.tx_queue.put(msg)

    @staticmethod
    def _ctrl_error(ctrl: Any) -> str | None:
        code = getattr(ctrl, "code", 0)
        if not code or code < 400:
            return None
        text = getattr(ctrl, "text", "") or ""
        return f"code={code} text={text!r}"

    @staticmethod
    def _ctrl_summary(ctrl: Any) -> str:
        code = getattr(ctrl, "code", None)
        text = getattr(ctrl, "text", None)
        try:
            params = _params_to_dict(getattr(ctrl, "params", None))
            keys = sorted(params.keys())
        except Exception:  # noqa: BLE001
            keys = "<params parse error>"
        return f"code={code!r} text={text!r} params_keys={keys}"

    def _wait_ctrl(self, request_id: str, timeout: int | None = None) -> Any:
        if timeout is None:
            timeout = settings.TEAMDROID_CTRL_TIMEOUT
        waiter: queue.Queue[Any] = queue.Queue(maxsize=1)

        with self._ctrl_waiters_lock:
            self._ctrl_waiters[request_id] = waiter

        try:
            ctrl = waiter.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(
                f"Timeout waiting for CTRL id={request_id} "
                f"(timeout={timeout}s, running={self.running}, "
                f"stream_alive="
                f"{self.stream_thread.is_alive() if self.stream_thread else None})"
            ) from None
        finally:
            with self._ctrl_waiters_lock:
                self._ctrl_waiters.pop(request_id, None)

        return ctrl

    def hi(self) -> None:
        pb_mod, _ = _require_pb()
        msg_id = self.next_id()
        hi = pb_mod.ClientHi(
            id=msg_id,
            user_agent="teambot-teamdroid-grpc",
            ver="0.25",
            lang="ru",
            device_id="\u2421",
            platform="",
            background=False,
        )
        self._send(pb_mod.ClientMsg(hi=hi))
        ctrl = self._wait_ctrl(msg_id)
        err = self._ctrl_error(ctrl)
        if err:
            api_logger.warning("[teamdroid] HI failed: %s", err)
            raise RuntimeError(f"HI failed: {err}")

    def login(self) -> None:
        pb_mod, _ = _require_pb()
        msg_id = self.next_id()
        credentials = f"{self.username}:{self.password}"
        login = pb_mod.ClientLogin(
            id=msg_id,
            scheme="basic",
            secret=credentials.encode("utf-8"),
        )
        self._send(pb_mod.ClientMsg(login=login))
        ctrl = self._wait_ctrl(msg_id)
        err = self._ctrl_error(ctrl)
        if err:
            api_logger.warning("[teamdroid] LOGIN failed: %s", err)
            raise RuntimeError(f"LOGIN failed: {err}")

    def login_with_token(self, token: str) -> dict[str, Any] | None:
        """Выполняет вход по токену и возвращает распарсенный CTRL."""
        pb_mod, _ = _require_pb()
        msg_id = self.next_id()

        login = pb_mod.ClientLogin(
            id=msg_id,
            scheme="token",
            secret=token.encode("utf-8"),
        )

        api_logger.info(
            "[teamdroid] login_with_token SEND: msg_id=%s running=%s "
            "stream_alive=%s timeout=%s token_len=%d pending_waiters=%d",
            msg_id,
            self.running,
            self.stream_thread.is_alive() if self.stream_thread else None,
            settings.TEAMDROID_CTRL_TIMEOUT,
            len(token),
            len(self._ctrl_waiters),
        )

        self._send(pb_mod.ClientMsg(login=login))

        try:
            ctrl = self._wait_ctrl(msg_id, timeout=settings.TEAMDROID_CTRL_TIMEOUT)
        except (TimeoutError, RuntimeError) as exc:
            api_logger.warning(
                "[teamdroid] login_with_token _wait_ctrl failed: %r running=%s timeout=%s pending_waiters=%d",
                exc,
                self.running,
                settings.TEAMDROID_CTRL_TIMEOUT,
                len(self._ctrl_waiters),
            )
            return None

        code = getattr(ctrl, "code", None)
        text = getattr(ctrl, "text", None)
        params = _params_to_dict(getattr(ctrl, "params", None))
        api_logger.info(
            "[teamdroid] login_with_token CTRL: %s",
            self._ctrl_summary(ctrl),
        )

        err = self._ctrl_error(ctrl)
        if err:
            api_logger.warning(
                "[teamdroid] login_with_token non-200: %s params=%r",
                err,
                params,
            )
            return None

        if not params.get("user"):
            api_logger.warning(
                "[teamdroid] login_with_token code=200 but no 'user' in params: %r",
                params,
            )

        result: dict[str, Any] = {
            "id": getattr(ctrl, "id", None),
            "code": code,
            "text": text,
            "params": params,
        }
        api_logger.info("[teamdroid] login_with_token OK: user=%r", params.get("user"))
        return result

    def subscribe(self, topic: str) -> None:
        pb_mod, _ = _require_pb()
        msg_id = self.next_id()
        sub = pb_mod.ClientSub(id=msg_id, topic=topic)
        self._send(pb_mod.ClientMsg(sub=sub))
        ctrl = self._wait_ctrl(msg_id)
        err = self._ctrl_error(ctrl)
        if err:
            api_logger.warning("[teamdroid] SUBSCRIBE %r failed: %s", topic, err)
            raise RuntimeError(f"SUBSCRIBE {topic!r} failed: {err}")
        with self._subscribed_lock:
            self._subscribed.add(topic)

    def ensure_subscribed(self, topic: str) -> None:
        with self._subscribed_lock:
            if topic in self._subscribed:
                return
        self.subscribe(topic)

    def get_topic_acs(self, topic: str) -> Any:
        pb_mod, _ = _require_pb()
        msg_id = self.next_id()
        get = pb_mod.ClientGet(
            id=msg_id,
            topic=topic,
            query=pb_mod.GetQuery(what="sub"),
        )
        self._send(pb_mod.ClientMsg(get=get))
        ctrl = self._wait_ctrl(msg_id)
        api_logger.debug(
            "[teamdroid] GET ACS topic=%r -> %s",
            topic,
            self._ctrl_summary(ctrl),
        )
        return ctrl

    def set_user_acs(
        self,
        topic: str,
        user_id: str,
        given: str = "JRWPS",
        want: str = "JRWPS",
    ) -> Any:
        pb_mod, _ = _require_pb()
        msg_id = self.next_id()
        sub = pb_mod.Subscription(
            user_id=user_id,
            mode=pb_mod.AccessMode(want=want, given=given),
        )
        set_query = pb_mod.SetQuery(
            desc=pb_mod.TopicDesc(acs=pb_mod.AccessMode(want=want, given=given)),
            sub=sub,
        )
        set_msg = pb_mod.ClientSet(id=msg_id, topic=topic, query=set_query)
        self._send(pb_mod.ClientMsg(set=set_msg))
        ctrl = self._wait_ctrl(msg_id)
        api_logger.debug(
            "[teamdroid] SET ACS topic=%r user=%r -> %s",
            topic,
            user_id,
            self._ctrl_summary(ctrl),
        )
        return ctrl

    def send_text(self, topic: str, text: str, on_behalf_of: str = "") -> Any:
        """Публикует текстовое сообщение в топик Teamdroid."""
        pb_mod, _ = _require_pb()
        msg_id = self.next_id()

        drafty = drafty_parse(text)

        content = json.dumps(
            drafty,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        pub = pb_mod.ClientPub(
            id=msg_id,
            topic=topic,
            no_echo=False,
            content=content,
        )
        _set_pub_mime(pub, "text/x-drafty")

        msg = pb_mod.ClientMsg(pub=pub)
        if on_behalf_of:
            msg.extra.on_behalf_of = on_behalf_of
        self._send(msg)
        ctrl = self._wait_ctrl(msg_id)
        api_logger.debug(
            "[teamdroid] PUB topic=%r (text) -> %s",
            topic,
            self._ctrl_summary(ctrl),
        )
        return ctrl

    def note(
        self,
        topic: str,
        what: str,
        seq: int,
        on_behalf_of: str = "",
    ) -> Any:
        """Отправляет {note} (recv/read/kp) в Tinode.

        ВАЖНО: в protobuf `ClientNote` НЕТ поля `id` (см. model_pb2.py:
        ClientNote = topic, what, seq_id, unread, event, payload). Поэтому
        сервер Tinode возвращает CTRL с пустым `id`, который не коррелируется
        с запросом через `_wait_ctrl(msg_id)`. Раньше это приводило к таймауту
        и 500 при каждом recv/read.

        Решение:
          - Отправляем note как fire-and-forget (не ждём CTRL по id).
          - Возвращаем None (caller отдаст 200 без ctrl_code).
          - Гарантируем, что клиент подписан на топик: Tinode обрабатывает
            {note} только для активных подписок. Без подписки сервер
            вернёт 403, и recvseqid/readseqid не обновятся.

        Returns:
            None (fire-and-forget).
        """
        pb_mod, _ = _require_pb()

        what_lc = (what or "").strip().lower()
        if what_lc not in _NOTE_WHAT_ALLOWED:
            raise ValueError(f"what must be one of: {', '.join(sorted(_NOTE_WHAT_ALLOWED))}, got {what!r}")

        self.ensure_subscribed(topic)

        if what_lc == "read":
            info_note = pb_mod.InfoNote.READ
        elif what_lc == "recv":
            info_note = pb_mod.InfoNote.RECV
        else:  # kp
            info_note = pb_mod.InfoNote.KP

        seq_id = int(seq) if what_lc != "kp" else 0

        note = pb_mod.ClientNote(
            topic=topic,
            what=info_note,
            seq_id=seq_id,
        )

        msg = pb_mod.ClientMsg(note=note)
        if on_behalf_of:
            msg.extra.on_behalf_of = on_behalf_of

        api_logger.info(
            "[teamdroid] NOTE SEND (fire-and-forget): topic=%r what=%s seq=%s on_behalf_of=%r",
            topic,
            what_lc,
            seq_id,
            on_behalf_of or "",
        )

        self._send(msg)
        return None

    def delete_messages(
        self,
        topic: str,
        del_seq: list[dict[str, int]],
        hard: bool = False,
    ) -> Any:
        """Удаляет сообщения в топике Teamdroid."""
        pb_mod, _ = _require_pb()
        msg_id = self.next_id()

        seq_ranges = []
        for r in del_seq:
            low = int(r["low"])
            hi = int(r.get("hi", 0) or 0)
            seq_ranges.append(pb_mod.SeqRange(low=low, hi=hi))

        del_msg = pb_mod.ClientDel(
            id=msg_id,
            topic=topic,
            what=pb_mod.ClientDel.MSG,
            del_seq=seq_ranges,
            hard=hard,
        )

        client_msg = pb_mod.ClientMsg()
        del_field = getattr(client_msg, "del", None)
        if del_field is None:
            del_field = getattr(client_msg, "delete", None)
        if del_field is None:
            raise RuntimeError("ClientMsg has neither 'del' nor 'delete' field — check model_pb2")
        del_field.CopyFrom(del_msg)
        self._send(client_msg)
        ctrl = self._wait_ctrl(msg_id, timeout=settings.TEAMDROID_CTRL_TIMEOUT)
        api_logger.debug(
            "[teamdroid] DEL topic=%r del_seq=%r hard=%s -> %s",
            topic,
            del_seq,
            hard,
            self._ctrl_summary(ctrl),
        )
        return ctrl

    def upload_file(self, file: dict[str, Any], topic: str) -> str:
        """Загружает файл в Teamdroid через HTTP и возвращает ref."""
        try:
            response = _http_session.post(
                settings.TEAMDROID_HTTP_UPLOAD_URL,
                headers={"X-Tinode-APIKey": settings.TEAMDROID_API_KEY},
                auth=(self.username, self.password),
                files={"file": (file["name"], file["data"], file["mime"])},
                data={"topic": topic},
                timeout=120,
            )
        except requests.RequestException as req_exc:
            raise RuntimeError(f"Teamdroid HTTP file upload request failed: {req_exc}") from req_exc

        if response.status_code >= 400:
            raise RuntimeError(f"File upload failed: HTTP {response.status_code} {response.text!r}")

        try:
            payload = response.json()
        except ValueError as json_exc:
            raise RuntimeError(f"File upload: server returned non-JSON response: {response.text!r}") from json_exc

        ctrl: dict[str, Any] = payload.get("ctrl") or {}
        params: dict[str, Any] = ctrl.get("params") or {}

        raw_code = ctrl.get("code")
        ctrl_code: int | None = raw_code if isinstance(raw_code, int) else None

        if ctrl_code is not None and ctrl_code >= 400:
            ctrl_text = ctrl.get("text")
            raise RuntimeError(f"File upload failed: {ctrl_code} {ctrl_text or ''}")

        file_ref = params.get("url") or payload.get("url") or payload.get("id")
        if not file_ref:
            raise RuntimeError(f"File upload succeeded, but Teamdroid returned empty file reference: {payload!r}")

        if not (file_ref.startswith("/") or file_ref.startswith("http://") or file_ref.startswith("https://")):
            file_ref = f"/v0/file/s/{file_ref}"

        return file_ref

    def publish_files(
        self,
        topic: str,
        files: list[dict[str, Any]],
        text: str,
        on_behalf_of: str = "",
    ) -> Any:
        """Публикует сообщение с несколькими файлами в Teamdroid."""
        pb_mod, _ = _require_pb()
        pub_id = self.next_id()

        text_drafty = drafty_parse(text) if text else {"txt": "", "fmt": None, "ent": None}

        txt: str = text_drafty.get("txt") or ""
        fmt: list[dict[str, Any]] = list(text_drafty.get("fmt") or [])
        ent: list[dict[str, Any]] = list(text_drafty.get("ent") or [])

        if txt:
            fmt.append({"at": len(txt), "len": 1, "tp": "BR"})
            txt += " "

        for file in files:
            ent.append(
                {
                    "tp": "EX",
                    "data": {
                        "mime": file["mime"],
                        "name": file["name"],
                        "ref": file["ref"],
                        "size": file["size"],
                    },
                }
            )
            fmt.append({"at": -1, "key": len(ent) - 1, "len": 1})

        drafty: dict[str, Any] = {"txt": txt, "fmt": fmt}
        if ent:
            drafty["ent"] = ent

        content = json.dumps(
            drafty,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        pub = pb_mod.ClientPub(
            id=pub_id,
            topic=topic,
            no_echo=False,
            content=content,
        )
        _set_pub_mime(pub, "text/x-drafty")

        msg = pb_mod.ClientMsg(pub=pub)

        msg.extra.attachments.extend([file["ref"] for file in files])

        if on_behalf_of:
            msg.extra.on_behalf_of = on_behalf_of

        self._send(msg)
        ctrl = self._wait_ctrl(pub_id, timeout=settings.TEAMDROID_CTRL_TIMEOUT)
        api_logger.debug(
            "[teamdroid] PUB topic=%r (files=%d) -> %s",
            topic,
            len(files),
            self._ctrl_summary(ctrl),
        )
        return ctrl

    def close(self) -> None:
        """Закрывает gRPC-канал и останавливает поток чтения."""
        self.running = False

        try:
            self.tx_queue.put_nowait(None)
        except queue.Full:
            pass

        channel = self.channel
        if channel is not None:
            try:
                channel.close()
            except grpc.RpcError:
                pass

        thread = self.stream_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

        with self._subscribed_lock:
            self._subscribed.clear()


def _set_pub_mime(pub: Any, mime: str) -> None:
    """Безопасно устанавливает mime в pub.head."""
    head = cast("Any", getattr(pub, "head", None))
    if head is None:
        return

    mime_bytes = f'"{mime}"'.encode()

    try:
        head["mime"] = mime_bytes
    except TypeError:
        try:
            head.SetInParent()
            head["mime"] = mime_bytes
        except Exception as pub_mime_exc:
            api_logger.warning(f"[teamdroid] failed to set pub mime: {pub_mime_exc!r}")


# ============================================================
# SINGLETON-КЛИЕНТ (gRPC)
# ============================================================

_teamdroid_client: TeamdroidClient | None = None
_teamdroid_client_lock = threading.RLock()


def get_teamdroid_client() -> TeamdroidClient:
    """Возвращает singleton-клиент Teamdroid (gRPC)."""
    global _teamdroid_client

    with _teamdroid_client_lock:
        if _teamdroid_client is None or not _teamdroid_client.running:
            if _teamdroid_client is not None:
                api_logger.warning("[teamdroid] client not running, recreating...")
                try:
                    _teamdroid_client.close()
                except Exception as close_exc:
                    api_logger.warning(f"[teamdroid] failed to close dead client: {close_exc!r}")
                _teamdroid_client = None

            client = TeamdroidClient(
                host=settings.TEAMDROID_HOST,
                username=settings.TEAMDROID_USERNAME,
                password=settings.TEAMDROID_PASSWORD,
            )
            try:
                client.connect()
                client.hi()
                client.login()
            except Exception:
                client.close()
                raise

            _teamdroid_client = client
            api_logger.info("[teamdroid] singleton client connected")

        return _teamdroid_client


def shutdown_teamdroid_client() -> None:
    """Закрывает singleton-клиент Teamdroid и SQL-соединение.

    CHANGED: SQL-соединение теперь singleton в app.db.manager,
    закрываем его через close_teamdroid_sql(). Это гарантирует, что
    при shutdown приложения закрыты и gRPC-канал, и pyodbc-соединение.
    """
    global _teamdroid_client

    with _teamdroid_client_lock:
        if _teamdroid_client is not None:
            try:
                _teamdroid_client.close()
            except Exception as close_exc:
                api_logger.warning(f"[teamdroid] failed to close singleton client: {close_exc!r}")
            _teamdroid_client = None
            api_logger.info("[teamdroid] singleton client closed")

    # CHANGED: SQL-соединение живёт в db_manager.
    close_teamdroid_sql()


# ============================================================
# TEAMDROID USER ID (XTEA)
# ============================================================

try:
    _TEAMDROID_UID_KEY = base64.b64decode("la6YsO+bNX/+XIkOqc5Svw==")
except Exception as key_exc:  # pragma: no cover
    raise RuntimeError(f"Invalid TEAMDROID_UID_KEY: {key_exc}") from key_exc


def _init_xtea_table(key_bytes: bytes) -> list[int]:
    """Инициализирует таблицу раундовых ключей XTEA."""
    k = [0, 0, 0, 0]
    for i in range(4):
        j = i * 4
        k[i] = (key_bytes[j] << 24) | (key_bytes[j + 1] << 16) | (key_bytes[j + 2] << 8) | key_bytes[j + 3]

    delta = 0x9E3779B9
    sum_val = 0
    table: list[int] = []
    for _ in range(32):
        table.append((sum_val + k[sum_val & 3]) & 0xFFFFFFFF)
        sum_val = (sum_val + delta) & 0xFFFFFFFF
        table.append((sum_val + k[(sum_val >> 11) & 3]) & 0xFFFFFFFF)
    return table


def _xtea_encrypt_block(v0: int, v1: int, table: list[int]) -> tuple[int, int]:
    """Шифрует один 64-битный блок XTEA."""
    for i in range(0, 64, 2):
        v0 = (v0 + ((((v1 << 4) ^ (v1 >> 5)) + v1) ^ table[i])) & 0xFFFFFFFF
        v1 = (v1 + ((((v0 << 4) ^ (v0 >> 5)) + v0) ^ table[i + 1])) & 0xFFFFFFFF
    return v0, v1


_TEAMDROID_UID_TABLE = _init_xtea_table(_TEAMDROID_UID_KEY)


def make_teamdroid_user_id(id_val: int) -> str:
    """Формирует Teamdroid user id (usrXXXX) из числового идентификатора."""
    import numbers

    if isinstance(id_val, bool) or not isinstance(id_val, numbers.Integral):
        raise ValueError(f"id_val must be int, got {type(id_val).__name__}")
    id_val = int(id_val)
    if id_val < 0 or id_val > 0xFFFFFFFFFFFFFFFF:
        raise ValueError(f"id_val must fit into uint64, got {id_val}")

    data = struct.pack("<Q", id_val)
    v0, v1 = struct.unpack(">II", data)
    enc_v0, enc_v1 = _xtea_encrypt_block(v0, v1, _TEAMDROID_UID_TABLE)
    enc_bytes = struct.pack(">II", enc_v0, enc_v1)
    result = base64.urlsafe_b64encode(enc_bytes).decode().rstrip("=")
    return f"usr{result}"


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def _ensure_pb_available() -> None:
    """Проверяет, что protobuf-модули Teamdroid доступны."""
    if not TEAMDROID_PB_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=(
                "Teamdroid protobuf modules (model_pb2, model_pb2_grpc) not available. "
                "Сгенерируйте их из .proto и положите в app/."
            ),
        )


# ============================================================
# КЛИЕНТСКИЕ МЕТАДАННЫЕ (только IP)
# ============================================================

_CLIENT_FIELD_MAX_LEN = 200


def _truncate(value: str | None, max_len: int = _CLIENT_FIELD_MAX_LEN) -> str:
    """Обрезает строку до max_len символов (безопасно для None)."""
    if value is None:
        return ""
    s = str(value)
    return s if len(s) <= max_len else s[:max_len]


def _get_client_ip(request: Request) -> str:
    """Возвращает реальный IP клиента с учётом прокси.

    Берём ПОСЛЕДНИЙ адрес из X-Forwarded-For (первый может быть
    подделан клиентом, последний добавлен нашим доверенным прокси).
    Если заголовка нет — X-Real-IP, затем request.client.host.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return _truncate(parts[-1], 64)

    xri = request.headers.get("x-real-ip")
    if xri:
        return _truncate(xri.strip(), 64)

    if request.client is not None:
        return _truncate(request.client.host, 64)

    return ""


def _enrich_params_with_client(
    params: dict[str, Any],
    request: Request,
) -> None:
    """Добавляет в params поле client_ip (in-place)."""
    params["client_ip"] = _get_client_ip(request)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПАРСИНГА PROTOBUF → JSON
# ============================================================


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float, str)):
        return value

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, bytearray):
        return bytes(value).decode("utf-8", errors="replace")

    if Message is not None and isinstance(value, Message):
        result: dict[str, Any] = {}
        for field, field_value in value.ListFields():
            result[field.name] = _to_jsonable(field_value)
        return result

    enum_name = getattr(value, "name", None)
    if isinstance(enum_name, str) and hasattr(value, "value"):
        return enum_name

    if isinstance(value, Mapping):
        return {str(k): _to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]

    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return [_to_jsonable(v) for v in value]
        except TypeError:
            pass

    return str(value)


def _params_to_dict(params: Any) -> dict[str, Any]:
    """Рекурсивная конвертация MapField params в dict."""
    if params is None:
        return {}
    try:
        return {str(k): _to_jsonable(params[k]) for k in params}
    except (AttributeError, TypeError) as params_exc:
        api_logger.debug(f"[teamdroid] _params_to_dict failed: {params_exc!r}")
        return {}


def _ctrl_to_dict(ctrl: Any) -> dict[str, Any]:
    """Преобразует protobuf CTRL в JSON-совместимый dict."""
    if ctrl is None:
        return {}

    result: dict[str, Any] = {}

    for field_name in ("id", "code", "text"):
        result[field_name] = getattr(ctrl, field_name, None)

    params = getattr(ctrl, "params", None)
    if params is not None:
        result["params"] = _params_to_dict(params)

    try:
        descriptor = cast("Any", getattr(ctrl, "DESCRIPTOR", None))
        if descriptor is not None:
            for field in descriptor.fields:
                if field.name in result:
                    continue
                result[field.name] = _to_jsonable(getattr(ctrl, field.name, None))
    except Exception as ctrl_fields_exc:
        api_logger.debug(f"[teamdroid] extra ctrl fields skipped: {ctrl_fields_exc!r}")

    return result


def _error_response(
    status_code: int,
    error: str,
) -> JSONResponse:
    """Формирует стандартный JSON-ответ об ошибке."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            status_code=status_code,
            error=error,
            timestamp=get_timestamp(),
        ).model_dump(),
    )


# ============================================================
# ЭНДПОИНТЫ
# ============================================================


def _do_send_files(request: SendFilesRequest) -> dict[str, Any]:
    """Синхронная реализация send_files — выполняется в отдельном потоке."""
    client = get_teamdroid_client()
    client.ensure_subscribed(request.topic)

    files = _load_files(request.file_ids)

    if not files:
        raise RuntimeError("No files to send (all FIDs resolved to empty)")

    for file in files:
        file["ref"] = client.upload_file(file=file, topic=request.topic)

    ctrl = client.publish_files(
        topic=request.topic,
        files=files,
        text=request.text,
        on_behalf_of=request.sender,
    )
    ctrl_dict = _ctrl_to_dict(ctrl)

    files_info = [
        {
            "fid": f["fid"],
            "name": f["name"],
            "mime": f["mime"],
            "size": f["size"],
            "ref": f["ref"],
        }
        for f in files
    ]

    return {
        "files_count": len(files),
        "files": files_info,
        "ctrl": ctrl_dict,
    }


@router.post(
    "/send-files",
    summary="Отправить файлы из SQL Server в Teamdroid",
    description=(
        "Загружает указанные файлы из SQL Server, загружает их в Teamdroid "
        "через HTTP и публикует одно Drafty-сообщение с вложениями. "
        "Ссылки в поле text парсятся в Drafty и становятся кликабельными."
    ),
)
@log_exceptions(api_logger)
async def send_files(request: SendFilesRequest) -> JSONResponse:
    """Отправка файлов из SQL Server в Teamdroid."""
    _ensure_pb_available()

    api_logger.info(f"📤 [teamdroid] Sending {len(request.file_ids)} files to topic {request.topic}")

    try:
        result = await asyncio.to_thread(_do_send_files, request)
    except HTTPException:
        raise
    except Exception as send_exc:
        return _error_response(500, f"{type(send_exc).__name__}: {send_exc}")

    api_logger.info(f"✅ [teamdroid] Sent {result['files_count']} files to topic {request.topic}")

    ctrl_dict = result["ctrl"]
    return JSONResponse(
        status_code=200,
        content={
            **SendFilesResponse(
                success=True,
                topic=request.topic,
                files_count=result["files_count"],
                files=result["files"],
                message=(f"Successfully sent {result['files_count']} file(s) to Teamdroid"),
                timestamp=get_timestamp(),
            ).model_dump(),
            "ctrl": ctrl_dict,
            "seq": ctrl_dict.get("params", {}).get("seq"),
        },
    )


def _do_send_text(request: SendTextRequest) -> dict[str, Any]:
    """Синхронная реализация send_text."""
    client = get_teamdroid_client()
    client.ensure_subscribed(request.topic)

    ctrl = client.send_text(
        topic=request.topic,
        text=request.text,
        on_behalf_of=request.sender,
    )
    return _ctrl_to_dict(ctrl)


@router.post(
    "/send-text",
    summary="Отправить текстовое сообщение в Teamdroid",
    description=(
        "Публикует текстовое сообщение (Drafty) в указанный топик (без файлов). "
        "Ссылки/@mentions/#hashtags парсятся и становятся кликабельными."
    ),
)
@log_exceptions(api_logger)
async def send_text(request: SendTextRequest) -> JSONResponse:
    """Отправка текстового сообщения."""
    _ensure_pb_available()

    api_logger.info(f"📤 [teamdroid] Sending text message to {request.topic}")

    try:
        ctrl_dict = await asyncio.to_thread(_do_send_text, request)
    except HTTPException:
        raise
    except Exception as text_exc:
        return _error_response(500, f"{type(text_exc).__name__}: {text_exc}")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "topic": request.topic,
            "ctrl": ctrl_dict,
            "seq": ctrl_dict.get("params", {}).get("seq"),
            "timestamp": get_timestamp(),
        },
    )


def _do_delete_messages(request: DeleteMessagesRequest) -> dict[str, Any]:
    """Синхронная реализация delete_messages."""
    del_seq = [r.model_dump() for r in request.del_seq]
    client = get_teamdroid_client()
    client.ensure_subscribed(request.topic)

    ctrl = client.delete_messages(
        topic=request.topic,
        del_seq=del_seq,
        hard=request.hard,
    )
    return _ctrl_to_dict(ctrl)


@router.post(
    "/delete-messages",
    summary="Удалить сообщения в топике Teamdroid",
    description=(
        "Удаляет сообщения по диапазонам ID. Если hard=False — удаление только "
        "для текущего пользователя, иначе — для всех (требует права 'D')."
    ),
)
@log_exceptions(api_logger)
async def delete_messages(request: DeleteMessagesRequest) -> JSONResponse:
    """Удаление сообщений в топике Teamdroid."""
    _ensure_pb_available()

    api_logger.info(
        f"🗑️ [teamdroid] Deleting messages in topic {request.topic}: del_seq={request.del_seq}, hard={request.hard}"
    )

    try:
        ctrl_dict = await asyncio.to_thread(_do_delete_messages, request)
    except HTTPException:
        raise
    except Exception as del_exc:
        return _error_response(500, f"{type(del_exc).__name__}: {del_exc}")

    api_logger.info(f"✅ [teamdroid] Deleted messages in topic {request.topic}")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "topic": request.topic,
            "hard": request.hard,
            "del_seq": [r.model_dump() for r in request.del_seq],
            "ctrl": ctrl_dict,
            "timestamp": get_timestamp(),
        },
    )


def _do_grant_user(request: GrantUserRequest) -> dict[str, Any]:
    """Синхронная реализация grant_user."""
    client = get_teamdroid_client()
    client.ensure_subscribed(request.topic)

    ctrl = client.set_user_acs(
        topic=request.topic,
        user_id=request.user_id,
        given=request.given,
        want=request.want,
    )
    return _ctrl_to_dict(ctrl)


@router.post(
    "/grant-user",
    summary="Выдать права пользователю в топике Teamdroid",
    description="Устанавливает права доступа (ACS) для пользователя в указанном топике.",
)
@log_exceptions(api_logger)
async def grant_user(request: GrantUserRequest) -> JSONResponse:
    """Выдача прав пользователю в топике."""
    _ensure_pb_available()

    api_logger.info(f"🔐 [teamdroid] Granting {request.given} to {request.user_id} in {request.topic}")

    try:
        ctrl_dict = await asyncio.to_thread(_do_grant_user, request)
    except HTTPException:
        raise
    except Exception as grant_exc:
        return _error_response(500, f"{type(grant_exc).__name__}: {grant_exc}")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": (f"Granted {request.given} to {request.user_id} in {request.topic}"),
            "ctrl": ctrl_dict,
            "timestamp": get_timestamp(),
        },
    )


def _do_get_acs(topic: str) -> dict[str, Any]:
    """Синхронная реализация get_acs."""
    client = get_teamdroid_client()
    ctrl = client.get_topic_acs(topic)
    return _ctrl_to_dict(ctrl)


@router.get(
    "/acs/{topic}",
    summary="Получить ACS топика Teamdroid",
    description="Запрашивает метаданные (ACS) топика Teamdroid.",
)
@log_exceptions(api_logger)
async def get_acs(topic: str) -> JSONResponse:
    """Получение ACS топика."""
    _ensure_pb_available()

    api_logger.info(f"🔍 [teamdroid] Getting ACS for topic {topic}")

    try:
        ctrl_dict = await asyncio.to_thread(_do_get_acs, topic)
    except HTTPException:
        raise
    except Exception as acs_exc:
        return _error_response(500, f"{type(acs_exc).__name__}: {acs_exc}")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "topic": topic,
            "ctrl": ctrl_dict,
            "timestamp": get_timestamp(),
        },
    )


@router.get(
    "/user-id/{id_val}",
    summary="Сгенерировать Teamdroid user id (usrXXXX) из числового ID",
    description=(
        "Выполняет XTEA-шифрование числового идентификатора так же, как это делает "
        "сервер Teamdroid (Go). Возвращает строку вида usrXXXXXXXXXXXXXXXXXXXXXX."
    ),
)
@log_exceptions(api_logger)
async def make_user_id(
    id_val: int = Path(..., ge=0, description="Числовой ID (uint64)"),
) -> JSONResponse:
    """Генерация Teamdroid user id из числового ID."""
    _ensure_pb_available()

    try:
        user_id = make_teamdroid_user_id(id_val)
    except ValueError as val_exc:
        raise HTTPException(status_code=400, detail=str(val_exc)) from val_exc

    api_logger.info(f"🆔 [teamdroid] Generated user_id={user_id} for id_val={id_val}")

    return JSONResponse(
        status_code=200,
        content=MakeUserIdResponse(
            success=True,
            id_val=id_val,
            user_id=user_id,
            timestamp=get_timestamp(),
        ).model_dump(),
    )


def _do_health() -> dict[str, Any]:
    """Синхронная проверка подключения к Teamdroid + диагностика состояния."""
    client = get_teamdroid_client()
    return {
        "running": client.running,
        "stream_alive": (client.stream_thread.is_alive() if client.stream_thread else None),
        "subscribed_count": len(client._subscribed),
        "host": client.host,
    }


@router.get(
    "/health",
    summary="Проверка доступности Teamdroid",
    description="Проверяет подключение к Teamdroid gRPC и выполнение LOGIN.",
)
@log_exceptions(api_logger)
async def teamdroid_health() -> JSONResponse:
    """Проверка доступности Teamdroid."""
    _ensure_pb_available()

    try:
        details = await asyncio.to_thread(_do_health)
    except HTTPException:
        raise
    except Exception as health_exc:
        api_logger.error(f"❌ [teamdroid] health check failed: {health_exc}", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "status": "unhealthy",
                "host": settings.TEAMDROID_HOST,
                "error": f"{type(health_exc).__name__}: {health_exc}",
                "timestamp": get_timestamp(),
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "status": "healthy",
            "host": settings.TEAMDROID_HOST,
            "details": details,
            "timestamp": get_timestamp(),
        },
    )


# ============================================================
# SEND-CODE / VERIFY-CODE (через TeamdroidProcedureRepository)
# ============================================================


@router.post(
    "/send-code",
    summary="Запустить хранимую процедуру SQL Server для отправки кода",
    description=(
        "Принимает произвольный JSON, минимально валидирует поле phone (если оно есть) "
        "и запускает хранимую процедуру SQL Server, передавая ей весь входной JSON "
        "в качестве параметра @Params. Дополнительно в @Params добавляется client_ip "
        "(из стандартных заголовков X-Forwarded-For / X-Real-IP, проставленных nginx). "
        "Имя процедуры задаётся в settings.TEAMDROID_SQL_PROC_AUTH_START "
        "(по умолчанию ext.PA_mbl_AuthStart_Exec). "
        "Процедура должна возвращать JSON-строку (одна колонка, одна строка)."
    ),
)
@log_exceptions(api_logger)
async def send_code(params: dict[str, Any], request: Request) -> JSONResponse:
    """Запуск хранимой процедуры SQL Server с JSON-параметром (отправка кода).

    CHANGED: вызов инкапсулирован в TeamdroidProcedureRepository.auth_start.
    """
    phone = params.get("phone")
    if isinstance(phone, str):
        phone_str = str(phone).strip()
        digits = "".join(ch for ch in phone_str if ch.isdigit())
        if len(digits) < 8 or not phone_str.startswith("+"):
            return _error_response(400, "invalid_phone_format")
        params["phone"] = phone_str

    _enrich_params_with_client(params, request)

    try:
        result = await asyncio.to_thread(TeamdroidProcedureRepository.auth_start, params)
    except Exception as proc_exc:
        api_logger.error(
            f"❌ [teamdroid] send_code procedure failed: {proc_exc}",
            exc_info=True,
        )
        return _error_response(
            500,
            f"send_code_proc_failed: {type(proc_exc).__name__}: {proc_exc}",
        )

    api_logger.debug(f"✅ [teamdroid] send_code procedure executed: ip={params.get('client_ip')!r}")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "result": result.get("result"),
            "timestamp": result.get("timestamp"),
        },
    )


@router.post(
    "/verify-code",
    summary="Запустить хранимую процедуру SQL Server для проверки кода",
    description=(
        "Принимает произвольный JSON, минимально валидирует поля request_id и code "
        "(если они есть) и запускает хранимую процедуру SQL Server, передавая ей весь "
        "входной JSON в качестве параметра @Params. Дополнительно в @Params добавляется "
        "client_ip (из стандартных заголовков X-Forwarded-For / X-Real-IP, проставленных "
        "nginx). Имя процедуры задаётся в settings.TEAMDROID_SQL_PROC_AUTH_FINISH "
        "(по умолчанию ext.PA_mbl_AuthFinish_Exec). "
        "Процедура должна возвращать JSON-строку (одна колонка, одна строка), "
        "которая парсится и возвращается клиенту в поле result."
    ),
)
@log_exceptions(api_logger)
async def verify_code(params: dict[str, Any], request: Request) -> JSONResponse:
    """Запуск хранимой процедуры SQL Server с JSON-параметром (проверка кода).

    CHANGED: вызов инкапсулирован в TeamdroidProcedureRepository.auth_finish.
    """
    request_id = params.get("request_id")
    code = params.get("code")

    if request_id is not None and not str(request_id or "").strip():
        return _error_response(400, "invalid_request_id")

    if code is not None:
        code_str = str(code or "").strip()
        if len(code_str) < 4:
            return _error_response(400, "invalid_code")
        params["code"] = code_str

    _enrich_params_with_client(params, request)

    try:
        result = await asyncio.to_thread(TeamdroidProcedureRepository.auth_finish, params)
    except Exception as proc_exc:
        api_logger.error(
            f"❌ [teamdroid] verify_code procedure failed: {proc_exc}",
            exc_info=True,
        )
        return _error_response(
            500,
            f"verify_code_proc_failed: {type(proc_exc).__name__}: {proc_exc}",
        )

    api_logger.debug(
        f"✅ [teamdroid] verify_code executed: proc={result.get('proc')} "
        f"rows={result.get('rows_affected')} raw={result.get('raw')!r}"
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "result": result.get("result"),
            "timestamp": result.get("timestamp"),
        },
    )


# ============================================================
# NOTE RELAY (recv / read / kp)
# ============================================================


def _do_note(
    topic: str,
    what: str,
    seq: int,
    on_behalf_of: str,
    client_ip: str,
) -> tuple[dict[str, Any], bool]:
    """Синхронная отправка {note} в Tinode и сохранение в Teamdroid SQL Server.

    Args:
        topic: имя топика Tinode.
        what: "recv" | "read" | "kp".
        seq: seq ID сообщения.
        on_behalf_of: Tinode user ID (usrXXX) — от имени кого отправить
            note. Он же используется как ``usi`` для Teamdroid SQL.
        client_ip: IP клиента ($.cip).

    Returns:
        tuple[dict, bool]: (ctrl_dict, teamdroid_saved)

    CHANGED: сохранение recv/read выполняется через
    TeamdroidProcedureRepository.edit_msg_status_delivery.
    """
    client = get_teamdroid_client()

    ctrl = client.note(
        topic=topic,
        what=what,
        seq=seq,
        on_behalf_of=on_behalf_of,
    )
    ctrl_dict = _ctrl_to_dict(ctrl) if ctrl is not None else {}

    # Сохраняем факт recv/read в Teamdroid SQL Server.
    # kp (key press) не сохраняем — эфемерное событие.
    teamdroid_saved = False
    if what in ("recv", "read"):
        teamdroid_saved = TeamdroidProcedureRepository.edit_msg_status_delivery(
            topic=topic,
            what=what,
            seq=seq,
            user_id=on_behalf_of,  # usrXXX == usi
            client_ip=client_ip,
        )

    return ctrl_dict, teamdroid_saved


@router.post(
    "/note",
    summary="Переслать {note} (recv/read/kp) в Tinode",
    description=(
        "Принимает {note} от мобильного клиента (Teamdroid/TeamBot Android) "
        "и пересылает его в Tinode через gRPC-клиент. "
        "Дополнительно факт recv/read сохраняется в Teamdroid SQL Server "
        "через хранимую процедуру settings.TEAMDROID_SQL_PROC_EDIT_MSG_STATUS_DELIVERY. "
        "Используется вместо прямой отправки {note} с мобильного клиента в Tinode, "
        "чтобы обойти блокировку note-канала на сервере/клиенте. "
        "Аутентификация — через X-API-Key (стандартный AuthMiddleware). "
        "Идентификатор пользователя ОБЯЗАТЕЛЕН и берётся из поля user_id "
        "в теле запроса (не из заголовков — клиент не передаёт свою "
        "идентичность в headers)."
    ),
)
@log_exceptions(api_logger)
async def relay_note(
    request: Request,
    payload: NoteRelayRequest,
) -> JSONResponse:
    """Приём {note} от мобильного клиента и пересылка в Tinode."""
    _ensure_pb_available()

    user_id = payload.user_id
    client_ip = _get_client_ip(request)

    api_logger.info(
        "📨 [teamdroid] note relay: topic=%r what=%s seq=%s user=%r ip=%r",
        payload.topic,
        payload.what,
        payload.seq,
        user_id,
        client_ip,
    )

    try:
        ctrl_dict, teamdroid_saved = await asyncio.to_thread(
            _do_note,
            payload.topic,
            payload.what,
            payload.seq,
            user_id,
            client_ip,
        )
    except HTTPException:
        raise
    except ValueError as val_exc:
        api_logger.warning("[teamdroid] note relay validation error: %s", val_exc)
        return _error_response(400, f"validation_error: {val_exc}")
    except Exception as note_exc:
        api_logger.error("❌ [teamdroid] note relay failed: %s", note_exc, exc_info=True)
        return _error_response(500, f"{type(note_exc).__name__}: {note_exc}")

    ctrl_code = ctrl_dict.get("code")
    ctrl_text = ctrl_dict.get("text")

    response = NoteRelayResponse(
        success=True,
        topic=payload.topic,
        what=payload.what,
        seq=payload.seq,
        user_id=user_id,
        ctrl_code=ctrl_code if isinstance(ctrl_code, int) else None,
        ctrl_text=ctrl_text if isinstance(ctrl_text, str) else None,
        teamdroid_saved=teamdroid_saved,
        timestamp=get_timestamp(),
    )

    if isinstance(ctrl_code, int) and ctrl_code >= 400:
        api_logger.warning(
            "⚠️ [teamdroid] note relay: Tinode returned CTRL code=%s text=%r",
            ctrl_code,
            ctrl_text,
        )
        return JSONResponse(
            status_code=502,
            content={
                **response.model_dump(),
                "success": False,
                "error": f"tinode_ctrl_error: code={ctrl_code} text={ctrl_text!r}",
            },
        )

    return JSONResponse(status_code=200, content=response.model_dump())


__all__ = [
    "router",
    "get_teamdroid_client",
    "shutdown_teamdroid_client",
    "TeamdroidClient",
]
