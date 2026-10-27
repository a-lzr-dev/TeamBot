"""Standalone-скрипт: только send-files (SQL Server → Teamdroid).

Без FastAPI. Только:
    - pyodbc (SQL Server)
    - requests (HTTP upload)
    - grpc + сгенерированные model_pb2 / model_pb2_grpc
    - стандартная библиотека

Логика 1:1 как в _do_send_files из роутера (включая Drafty-парсинг текста).

Запуск:
    python send_files_standalone.py

Параметры через env (или правьте константы ниже):
    TEAMDROID_TOPIC     - топик (по умолчанию grpgx9hUy-VnMi)
    TEAMDROID_SENDER    - sender usrXXXX (по умолчанию usrfXVemq3nSIw)
    TEAMDROID_TEXT      - текст (по умолчанию "тест файла")
    TEAMDROID_FILE_IDS  - FID через запятую (по умолчанию 16985428)
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import queue
import re
import sys
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, cast

import grpc
import pyodbc
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# protobuf-модули Teamdroid (должны лежать в sys.path, например в app/)
# ---------------------------------------------------------------------------
try:
    from app import model_pb2, model_pb2_grpc  # type: ignore[import]
except ImportError as exc:
    print(f"ERROR: cannot import app.model_pb2 / model_pb2_grpc: {exc}", file=sys.stderr)
    print("Убедитесь, что сгенерированные protobuf-модули лежат в пакете app/", file=sys.stderr)
    sys.exit(1)

try:
    from google.protobuf.message import Message
except ImportError:  # pragma: no cover
    Message = None  # type: ignore[assignment]


# ============================================================
# ЛОГГЕР
# ============================================================

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("send_files.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("send_files")


# ============================================================
# НАСТРОЙКИ (env или правка)
# ============================================================

# --- Teamdroid gRPC ---
TEAMDROID_HOST = os.getenv("TEAMDROID_HOST", "192.168.12.156:16060")
TEAMDROID_USERNAME = os.getenv("TEAMDROID_USERNAME", "root")
TEAMDROID_PASSWORD = os.getenv("TEAMDROID_PASSWORD", "IYo1Jq!j%lCp")
TEAMDROID_GRPC_MAX_MESSAGE = 16777216
TEAMDROID_CTRL_TIMEOUT = 10

# --- Teamdroid HTTP upload ---
TEAMDROID_HTTP_UPLOAD_URL = os.getenv("TEAMDROID_HTTP_UPLOAD_URL", "http://192.168.12.156:6060/v0/file/u")
TEAMDROID_API_KEY = os.getenv("TEAMDROID_API_KEY", "AQEAAAABAAD_rAp4DJh05a1HAwFT3A6K")

# --- SQL Server ---
SQL_SERVER = os.getenv("SQL_SERVER", "192.168.12.1")
SQL_DATABASE = os.getenv("SQL_DATABASE", "SrvService")
SQL_USERNAME = os.getenv("SQL_USERNAME", "APSTeamdroid")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "K!7mPq2$Zv9!Lx4@Nc")
SQL_TIMEOUT = 10

# --- Параметры запроса ---
TOPIC = "grp5jtXWid5AcB"
SENDER = "usrW-aanadgH1o"
TEXT = "16.10.2026 14:21:06 H 911 AP790 Отправлено вложение: 200 кб Ваше полное задание на завтра рано утром во вложении. Изучите и отпишитесь, приняли задание? Файл можно скачать по ссылке: https://clck.ru/3WXhWM"
FILE_IDS_RAW = None


# ============================================================
# MIME
# ============================================================

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


def _guess_mime(file_name: str, extension: str) -> str:
    ext = extension.lower()
    if not ext.startswith("."):
        ext = "." + ext
    if ext in _EXTRA_MIME:
        return _EXTRA_MIME[ext]
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or "application/octet-stream"


# ============================================================
# SQL SERVER
# ============================================================


@contextmanager
def _sql_conn() -> Iterator[pyodbc.Connection]:
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"UID={SQL_USERNAME};"
        f"PWD={SQL_PASSWORD};"
        "TrustServerCertificate=yes;"
    )
    log.debug("SQL connect: server=%s db=%s user=%s", SQL_SERVER, SQL_DATABASE, SQL_USERNAME)
    conn = pyodbc.connect(conn_str, timeout=SQL_TIMEOUT)
    try:
        yield conn
    finally:
        try:
            conn.close()
            log.debug("SQL connection closed")
        except Exception as exc:
            log.warning("SQL close failed: %s", exc)


def get_file(conn: pyodbc.Connection, fid: int) -> dict[str, Any]:
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
    log.debug("SQL get_file: FID=%s", fid)
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
    mime = _guess_mime(file_name, extension)
    log.debug(
        "SQL get_file OK: FID=%s name=%r ext=%r mime=%s size=%d",
        file_id,
        file_name,
        extension,
        mime,
        len(data),
    )
    return {
        "fid": file_id,
        "name": file_name,
        "mime": mime,
        "size": len(data),
        "data": data,
    }


def _load_files(fids: list[int]) -> list[dict[str, Any]]:
    with _sql_conn() as conn:
        return [get_file(conn, fid) for fid in fids]


# ============================================================
# HTTP SESSION
# ============================================================

_RETRY_POLICY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[],
    allowed_methods=frozenset(["GET", "POST"]),
)
_http_session = requests.Session()
_http_session.mount("http://", HTTPAdapter(max_retries=_RETRY_POLICY))
_http_session.mount("https://", HTTPAdapter(max_retries=_RETRY_POLICY))


def close_http_session() -> None:
    """Закрытие глобальной HTTP-сессии."""
    try:
        _http_session.close()
    except Exception as close_exc:
        log.warning("[send-files] failed to close http session: %r", close_exc)


# ============================================================
# ПАРСИНГ ТЕКСТА В DRAFTY (порт Drafty.parse из Android-клиента)
# ============================================================
#
# См. подробные комментарии в роутере. Кратко:
#   - inline-стили: *bold*, _italic_, ~strike~, `code`
#   - сущности: LN (ссылки), MN (@mentions), HT (#hashtags)
#   - переносы строк как BR
#
# Регулярки используют захватывающую группу для префиксного разделителя,
# поэтому содержимое — группа 2, позиции считаются по group(2).

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
    """Порт Drafty.parse(): plain-text -> Drafty dict.

    Поддерживает inline-стили, LN/MN/HT-сущности и переносы строк (BR).
    """
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
# JSON-SAFE КОНВЕРТАЦИЯ PROTobuf
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
    if params is None:
        return {}
    try:
        return {str(k): _to_jsonable(params[k]) for k in params}
    except (AttributeError, TypeError) as params_exc:
        log.debug("_params_to_dict failed: %r", params_exc)
        return {}


def _ctrl_to_dict(ctrl: Any) -> dict[str, Any]:
    """Преобразует protobuf CTRL в JSON-совместимый dict (рекурсивно)."""
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
        log.debug("extra ctrl fields skipped: %r", ctrl_fields_exc)

    return result


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
            log.warning("failed to set pub mime: %r", pub_mime_exc)


# ============================================================
# TEAMDROID CLIENT (упрощённая копия)
# ============================================================


class TeamdroidClient:
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
        log.info("gRPC connect: host=%s", self.host)
        self.channel = grpc.insecure_channel(
            self.host,
            options=[
                ("grpc.max_send_message_length", TEAMDROID_GRPC_MAX_MESSAGE),
                ("grpc.max_receive_message_length", TEAMDROID_GRPC_MAX_MESSAGE),
            ],
        )
        try:
            grpc.channel_ready_future(self.channel).result(timeout=5)
            log.info("gRPC channel ready")
        except grpc.FutureTimeoutError as exc:
            raise RuntimeError(
                f"Cannot connect to Teamdroid gRPC at {self.host} — проверьте, что сервер запущен и порт доступен"
            ) from exc

        self.stub = model_pb2_grpc.NodeStub(self.channel)
        self.running = True
        self.stream = self.stub.MessageLoop(self._outgoing())
        t = threading.Thread(target=self._consume_stream, daemon=True)
        self.stream_thread = t
        t.start()
        log.debug("gRPC MessageLoop started")

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
                log.error("gRPC stream error: %s", rpc_exc)
                self.running = False
        except Exception as stream_exc:
            if self.running:
                log.exception("gRPC stream error: %r", stream_exc)
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
                log.debug(
                    "unsolicited CTRL id=%r code=%r text=%r",
                    request_id,
                    getattr(ctrl, "code", None),
                    getattr(ctrl, "text", None),
                )

    def _send(self, msg: Any) -> None:
        if not self.running:
            raise RuntimeError("Teamdroid client is not running")
        self.tx_queue.put(msg)

    def _wait_ctrl(self, request_id: str, timeout: int | None = None) -> Any:
        if timeout is None:
            timeout = TEAMDROID_CTRL_TIMEOUT
        waiter: queue.Queue[Any] = queue.Queue(maxsize=1)
        with self._ctrl_waiters_lock:
            self._ctrl_waiters[request_id] = waiter
        log.debug("waiting CTRL id=%s timeout=%ss", request_id, timeout)
        try:
            ctrl = waiter.get(timeout=timeout)
        except queue.Empty:
            log.error("timeout waiting CTRL id=%s", request_id)
            raise TimeoutError(f"Timeout waiting for CTRL id={request_id}") from None
        finally:
            with self._ctrl_waiters_lock:
                self._ctrl_waiters.pop(request_id, None)
        log.debug("got CTRL id=%s code=%r text=%r", request_id, ctrl.code, ctrl.text)
        if ctrl.code >= 400:
            raise RuntimeError(f"Teamdroid error {ctrl.code}: {ctrl.text}")
        return ctrl

    def hi(self) -> None:
        msg_id = self.next_id()
        log.debug("→ HI id=%s", msg_id)
        hi = model_pb2.ClientHi(
            id=msg_id,
            user_agent="teambot-teamdroid-grpc",
            ver="0.25",
            lang="ru",
            device_id="\u2421",
            platform="",
            background=False,
        )
        self._send(model_pb2.ClientMsg(hi=hi))
        self._wait_ctrl(msg_id)
        log.info("HI OK")

    def login(self) -> None:
        msg_id = self.next_id()
        log.debug("→ LOGIN id=%s user=%r", msg_id, self.username)
        creds = f"{self.username}:{self.password}"
        login = model_pb2.ClientLogin(id=msg_id, scheme="basic", secret=creds.encode("utf-8"))
        self._send(model_pb2.ClientMsg(login=login))
        self._wait_ctrl(msg_id)
        log.info("LOGIN OK as %r", self.username)

    def subscribe(self, topic: str) -> None:
        msg_id = self.next_id()
        log.debug("→ SUB id=%s topic=%r", msg_id, topic)
        sub = model_pb2.ClientSub(id=msg_id, topic=topic)
        self._send(model_pb2.ClientMsg(sub=sub))
        self._wait_ctrl(msg_id)
        with self._subscribed_lock:
            self._subscribed.add(topic)
        log.info("SUB OK topic=%r", topic)

    def ensure_subscribed(self, topic: str) -> None:
        with self._subscribed_lock:
            if topic in self._subscribed:
                log.debug("already subscribed to %r", topic)
                return
        self.subscribe(topic)

    def get_topic_acs(self, topic: str) -> Any:
        msg_id = self.next_id()
        log.debug("→ GET sub id=%s topic=%r", msg_id, topic)
        get = model_pb2.ClientGet(
            id=msg_id,
            topic=topic,
            query=model_pb2.GetQuery(what="sub"),
        )
        self._send(model_pb2.ClientMsg(get=get))
        return self._wait_ctrl(msg_id)

    def upload_file(self, file: dict[str, Any], topic: str) -> str:
        log.debug(
            "HTTP upload: url=%s topic=%r name=%r mime=%s size=%d",
            TEAMDROID_HTTP_UPLOAD_URL,
            topic,
            file["name"],
            file["mime"],
            file["size"],
        )
        headers: dict[str, str] = {}
        if TEAMDROID_API_KEY:
            headers["X-Tinode-APIKey"] = TEAMDROID_API_KEY
        try:
            response = _http_session.post(
                TEAMDROID_HTTP_UPLOAD_URL,
                headers=headers,
                auth=(self.username, self.password),
                files={"file": (file["name"], file["data"], file["mime"])},
                data={"topic": topic},
                timeout=120,
            )
        except requests.RequestException as req_exc:
            log.exception("HTTP upload request failed")
            raise RuntimeError(f"HTTP upload failed: {req_exc}") from req_exc

        log.debug("HTTP upload response: status=%s", response.status_code)
        if response.status_code >= 400:
            log.error("HTTP upload failed: status=%s body=%r", response.status_code, response.text[:500])
            raise RuntimeError(f"File upload failed: HTTP {response.status_code} {response.text!r}")

        try:
            payload = response.json()
        except ValueError as json_exc:
            log.error("HTTP upload non-JSON: %r", response.text[:500])
            raise RuntimeError(f"File upload: non-JSON response: {response.text!r}") from json_exc

        ctrl = payload.get("ctrl") or {}
        params = ctrl.get("params") or {}
        raw_code = ctrl.get("code")
        if isinstance(raw_code, int) and raw_code >= 400:
            log.error("HTTP upload CTRL error: code=%s text=%r", raw_code, ctrl.get("text"))
            raise RuntimeError(f"File upload failed: {raw_code} {ctrl.get('text', '')}")

        file_ref = params.get("url") or payload.get("url") or payload.get("id")
        if not file_ref:
            log.error("HTTP upload empty ref: payload=%r", payload)
            raise RuntimeError(f"File upload succeeded but empty ref: {payload!r}")
        if not (file_ref.startswith("/") or file_ref.startswith("http://") or file_ref.startswith("https://")):
            file_ref = f"/v0/file/s/{file_ref}"
        log.info("HTTP upload OK: ref=%r", file_ref)
        return file_ref

    def publish_files(
        self,
        topic: str,
        files: list[dict[str, Any]],
        text: str,
        on_behalf_of: str = "",
    ) -> Any:
        """Публикует сообщение с файлами.

        Текст парсится в Drafty (``drafty_parse``), вложения (EX) добавляются
        на новой строке после текста (через BR), чтобы не накладываться.
        Ключи EX-сущностей нумеруются после текстовых сущностей (LN/MN/HT).
        """
        pub_id = self.next_id()
        log.info(
            "→ PUB id=%s topic=%r files=%d on_behalf_of=%r",
            pub_id,
            topic,
            len(files),
            on_behalf_of,
        )

        # 1. Парсим текст в Drafty.
        text_drafty = drafty_parse(text) if text else {"txt": "", "fmt": None, "ent": None}

        txt: str = text_drafty.get("txt") or ""
        fmt: list[dict[str, Any]] = list(text_drafty.get("fmt") or [])
        ent: list[dict[str, Any]] = list(text_drafty.get("ent") or [])

        # 2. BR между текстом и вложениями, если текст непустой.
        if txt:
            fmt.append({"at": len(txt), "len": 1, "tp": "BR"})
            txt += " "

        # 3. EX-сущности для вложений.
        #    key должен указывать на правильный индекс в общем ent:
        #    текстовые сущности занимают 0..N-1, вложения продолжают с len(ent).
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

        drafty_json = json.dumps(drafty, ensure_ascii=False, separators=(",", ":"))
        log.debug("PUB drafty (first 500 chars): %s", drafty_json[:500])

        content = drafty_json.encode("utf-8")
        pub = model_pb2.ClientPub(id=pub_id, topic=topic, no_echo=False, content=content)
        _set_pub_mime(pub, "text/x-drafty")

        msg = model_pb2.ClientMsg(pub=pub)
        msg.extra.attachments.extend([file["ref"] for file in files])
        if on_behalf_of:
            msg.extra.on_behalf_of = on_behalf_of

        log.debug("PUB attachments=%s", [f["ref"] for f in files])

        self._send(msg)
        log.debug("PUB sent, waiting CTRL id=%s", pub_id)

        try:
            ctrl = self._wait_ctrl(pub_id)
        except RuntimeError as exc:
            log.error(
                "PUB CTRL error: %s | topic=%r on_behalf_of=%r",
                exc,
                topic,
                on_behalf_of,
            )
            raise

        ctrl_dict = _ctrl_to_dict(ctrl)
        seq = (ctrl_dict.get("params") or {}).get("seq")
        log.info("PUB OK: seq=%r", seq)
        return ctrl

    def send_text(self, topic: str, text: str, on_behalf_of: str = "") -> Any:
        """Публикует текстовое сообщение (Drafty) в топик."""
        msg_id = self.next_id()

        drafty = drafty_parse(text)

        content = json.dumps(
            drafty,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        pub = model_pb2.ClientPub(
            id=msg_id,
            topic=topic,
            no_echo=False,
            content=content,
        )
        _set_pub_mime(pub, "text/x-drafty")

        msg = model_pb2.ClientMsg(pub=pub)
        if on_behalf_of:
            msg.extra.on_behalf_of = on_behalf_of
        self._send(msg)
        return self._wait_ctrl(msg_id)

    def close(self) -> None:
        log.debug("closing Teamdroid client")
        self.running = False
        try:
            self.tx_queue.put_nowait(None)
        except queue.Full:
            pass
        if self.channel is not None:
            try:
                self.channel.close()
            except grpc.RpcError:
                pass
        if self.stream_thread is not None and self.stream_thread.is_alive():
            self.stream_thread.join(timeout=2.0)
        with self._subscribed_lock:
            self._subscribed.clear()
        log.debug("Teamdroid client closed")


# ============================================================
# ЛОГИКА send-files (копия _do_send_files)
# ============================================================


def do_send_files(
    client: TeamdroidClient,
    file_ids: list[int],
    topic: str,
    text: str,
    sender: str,
) -> dict[str, Any]:
    log.info("=" * 60)
    log.info("do_send_files START")
    log.info("  topic    = %r", topic)
    log.info("  sender   = %r", sender)
    log.info("  text     = %r", text)
    log.info("  file_ids = %s", file_ids)

    # --- 1. Подписка ---
    log.info("[1/5] ensure_subscribed(topic=%r)", topic)
    try:
        client.ensure_subscribed(topic)
        log.info("[1/5] OK: subscribed")
    except Exception as exc:
        log.exception("[1/5] FAILED: ensure_subscribed: %s", exc)
        raise

    # --- 2. Диагностика прав (ACS) ---
    log.info("[2/5] fetching current ACS for topic=%r", topic)
    try:
        acs = client.get_topic_acs(topic)
        acs_dict = _ctrl_to_dict(acs)
        log.info("[2/5] current ACS: %s", json.dumps(acs_dict, ensure_ascii=False)[:1000])
    except Exception as exc:
        log.warning("[2/5] could not fetch ACS (continuing): %s", exc)

    # --- 3. Загрузка файлов из SQL ---
    log.info("[3/5] loading files from SQL Server: %s", file_ids)
    try:
        files = _load_files(file_ids)
    except Exception as exc:
        log.exception("[3/5] FAILED: _load_files: %s", exc)
        raise
    log.info("[3/5] OK: loaded %d file(s)", len(files))
    for f in files:
        log.debug(
            "[3/5]   fid=%s name=%r mime=%s size=%d bytes",
            f["fid"],
            f["name"],
            f["mime"],
            f["size"],
        )

    if not files:
        log.error("[3/5] FAILED: no files loaded")
        raise RuntimeError("No files to send")

    # --- 4. Upload в Teamdroid (HTTP) ---
    log.info("[4/5] uploading %d file(s) to %s", len(files), TEAMDROID_HTTP_UPLOAD_URL)
    for i, f in enumerate(files, 1):
        log.info(
            "[4/5]   (%d/%d) uploading fid=%s name=%r size=%d ...",
            i,
            len(files),
            f["fid"],
            f["name"],
            f["size"],
        )
        try:
            ref = client.upload_file(file=f, topic=topic)
            f["ref"] = ref
            log.info("[4/5]   (%d/%d) OK: ref=%r", i, len(files), ref)
        except Exception as exc:
            log.exception(
                "[4/5]   (%d/%d) FAILED: upload fid=%s: %s",
                i,
                len(files),
                f["fid"],
                exc,
            )
            raise

    # --- 5. Publish Drafty ---
    log.info("[5/5] publishing drafty message to topic=%r", topic)
    log.debug(
        "[5/5]   on_behalf_of=%r attachments=%s",
        sender,
        [f["ref"] for f in files],
    )
    try:
        ctrl = client.publish_files(topic=topic, files=files, text=text, on_behalf_of=sender)
    except Exception as exc:
        log.exception("[5/5] FAILED: publish_files: %s", exc)
        raise

    ctrl_dict = _ctrl_to_dict(ctrl)
    log.info(
        "[5/5] OK: ctrl.id=%r ctrl.code=%r ctrl.text=%r",
        ctrl_dict.get("id"),
        ctrl_dict.get("code"),
        ctrl_dict.get("text"),
    )
    log.debug("[5/5]   ctrl.params=%s", ctrl_dict.get("params"))

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

    log.info("do_send_files DONE: %d file(s) published", len(files))
    log.info("=" * 60)

    return {"files_count": len(files), "files": files_info, "ctrl": ctrl_dict}


# ============================================================
# MAIN
# ============================================================


def _parse_file_ids(raw: str) -> list[int]:
    return [int(p.strip()) for p in raw.split(",") if p.strip()]


def main() -> int:
    try:
        file_ids = _parse_file_ids(FILE_IDS_RAW)
    except ValueError as exc:
        log.error("invalid FILE_IDS_RAW: %s", exc)
        return 2

    log.info("=" * 70)
    log.info("send-files standalone")
    log.info("=" * 70)
    log.info("host      : %s", TEAMDROID_HOST)
    log.info("upload_url: %s", TEAMDROID_HTTP_UPLOAD_URL)
    log.info("sql_server: %s / %s", SQL_SERVER, SQL_DATABASE)
    log.info("topic     : %s", TOPIC)
    log.info("sender    : %r", SENDER)
    log.info("text      : %r", TEXT)
    log.info("file_ids  : %s", file_ids)
    log.info("-" * 70)

    client = TeamdroidClient(TEAMDROID_HOST, TEAMDROID_USERNAME, TEAMDROID_PASSWORD)
    try:
        client.connect()
        client.hi()
        client.login()
        result = do_send_files(client, file_ids, TOPIC, TEXT, SENDER)
    except Exception as exc:
        log.exception("FAILED: %s: %s", type(exc).__name__, exc)
        return 1
    finally:
        client.close()
        close_http_session()

    ctrl = result.get("ctrl") or {}
    output = {
        "success": True,
        "topic": TOPIC,
        "files_count": result.get("files_count"),
        "files": result.get("files"),
        "ctrl": ctrl,
        "seq": (ctrl.get("params") or {}).get("seq"),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
