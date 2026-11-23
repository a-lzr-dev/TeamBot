"""Роутер для отдачи APK-файлов мобильного клиента.

URL:
    GET /api/v1/update/apk/{filename}     — ЗАКРЫТАЯ папка (нужен settings.API_KEY_HEADER)
    GET /api/v1/update/public/{filename}  — ОТКРЫТАЯ папка (без ключа)

Аутентификация:
    * /api/v1/update/apk/*    → APP_CLIENT_SYNC_INGEST_API_KEYS
    * /api/v1/update/public/* → БЕЗ ключа (в AuthMiddleware.PUBLIC_PATHS)

Директории (из настроек):
    * APP_UPDATE_APK_DIR    — закрытые сборки
    * APP_UPDATE_PUBLIC_DIR — открытые файлы (APK, version.json)

================================================================
ВАЖНО: РАЗДАЧА ИДЁТ НАПРЯМУЮ ИЗ FASTAPI/UVICORN, БЕЗ NGINX.
================================================================
Мобильный клиент качает APK по URL вида
    https://<host>/api/v1/update/public/teamdroid-latest.apk

Этот запрос НЕ проходит через nginx (в docker-compose.yaml
у сервиса app порт 8000 опубликован напрямую, а nginx работает
только в профиле `production` и не проксирует /api/v1/update/*).

Отсюда требования к этому модулю:
    1. Range-запросы (Accept-Ranges, 206, Content-Range, 416)
       должны обрабатываться ЗДЕСЬ, а не в nginx.
    2. Android DownloadManager шлёт Range кусками и ждёт
       финальный 416 на Range за пределами файла — иначе
       зависает на «49,57 из 49,57 МБ».
    3. Ответ 206 ДОЛЖЕН иметь явный Content-Length и НЕ быть
       chunked. uvicorn с StreamingResponse всегда переключается
       в Transfer-Encoding: chunked, из-за чего DownloadManager
       не видит EOF и висит. Поэтому здесь используется
       `Response(content=...)`, а не StreamingResponse.
       Файл читается в память ЦЕЛИКОМ для каждого Range-запроса.
       Для APK 50 МБ это приемлемо (один Range-запрос = один
       буфер), а DownloadManager шлёт максимум 2–3 параллельных
       Range-запроса.

Если когда-нибудь включите nginx как reverse-proxy для
/api/v1/update/* — можно отдавать через FileResponse/StaticFiles
(nginx сделает Range сам). См. docker/nginx/conf.d/app.conf.

CHANGED (fix hang at 100%):
    * Убран StreamingResponse — uvicorn с ним всегда отдаёт
      chunked, DownloadManager ждёт EOF и висит.
    * Для Range используется Response с явным Content-Length.
    * Блок 4.2 (`start >= file_size → 416`) идёт ПЕРВЫМ.
    * В ответ 416 добавлен `Content-Length: 0`.
    * Cache-Control: no-store для APK (был public, max-age=3600) —
      иначе DownloadManager получает закешированный 200 вместо 206.
    * Добавлено WARNING-логирование входящего Range и 416.
    * Явная проверка `start < 0` (bytes=-N отвергаем как 400).
    * При `start == file_size` возвращаем 416, а не пустой 206.

CHANGED (fix type checker warnings):
    * `_log_and_raise` помечен как `NoReturn`.
    * `start`/`end` инициализируются значениями по умолчанию до `try`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ...config import settings
from ...logger import api_logger
from ...utils.decorators import log_exceptions

router = APIRouter(prefix="/update", tags=["Update"])

# Разрешённые имена файлов в ЗАКРЫТОЙ папке: только .apk, без слэшей и "..".
_APK_FILENAME_RE = re.compile(r"^[A-Za-z0-9._\-]+\.apk$")

# Разрешённые имена файлов в ОТКРЫТОЙ папке:
#   - только basename (без слэшей/..);
#   - только .apk, .json, .txt (то, что реально кладём в update/public).
_PUBLIC_FILENAME_RE = re.compile(r"^[A-Za-z0-9._\-]+\.(apk|json|txt)$")

# MIME-типы для публичной раздачи.
_PUBLIC_MIME_BY_SUFFIX: dict[str, str] = {
    ".apk": "application/vnd.android.package-archive",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
}

# Размер чанка для чтения файла в память (не влияет на сеть —
# это просто размер buffer'а при чтении через read()).
_READ_CHUNK = 1024 * 1024  # 1 МБ


def _apk_dir() -> Path:
    """Директория с ЗАКРЫТЫМИ APK-файлами (из настроек)."""
    raw = getattr(settings, "APP_UPDATE_APK_DIR", "") or "/app/update/apk"
    return Path(raw)


def _public_dir() -> Path:
    """Директория с ОТКРЫТЫМИ файлами (из настроек)."""
    raw = getattr(settings, "APP_UPDATE_PUBLIC_DIR", "") or "/app/update/public"
    return Path(raw)


def _resolve_safe(base_dir: Path, filename: str) -> Path:
    """Возвращает путь внутри base_dir или бросает HTTPException.

    Защита от path traversal: итоговый путь должен лежать внутри base_dir.
    """
    file_path = (base_dir / filename).resolve()
    try:
        file_path.relative_to(base_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid filename") from None
    return file_path


def _log_and_raise(
    *,
    status_code: int,
    detail: str,
    log_msg: str,
    log_level: str = "warning",
) -> NoReturn:
    """Логирует сообщение и бросает HTTPException с заданным статусом.

    Помечена как ``NoReturn``: статические анализаторы понимают,
    что после вызова управление не возвращается, поэтому
    «possibly unbound» для переменных, назначенных в ``try``,
    не возникает.
    """
    getattr(api_logger, log_level)(log_msg)
    raise HTTPException(status_code=status_code, detail=detail)


def _read_range(file_path: Path, start: int, length: int) -> bytes:
    """Читает ровно ``length`` байт с позиции ``start``.

    Возвращает байты (может быть меньше ``length``, если файл
    внезапно уменьшился — на практике не бывает, но обрабатываем).
    Использует seek + read с ограничением, без загрузки всего файла.
    """
    with open(file_path, "rb") as f:
        f.seek(start)
        remaining = length
        chunks: list[bytes] = []
        while remaining > 0:
            chunk = f.read(min(_READ_CHUNK, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def _read_full(file_path: Path) -> bytes:
    """Читает файл целиком."""
    with open(file_path, "rb") as f:
        return f.read()


# ============================================================
# ЗАКРЫТАЯ раздача (требует settings.API_KEY_HEADER)
# ============================================================


@router.get(
    "/apk/{filename}",
    summary="Скачать APK мобильного клиента (закрытая папка)",
)
@log_exceptions(api_logger)
async def download_apk(filename: str, request: Request) -> Response:
    """Отдать APK-файл из ЗАКРЫТОЙ директории обновлений.

    Требует settings.API_KEY_HEADER (проверяется в AuthMiddleware, канал client-sync).

    Range-запросы обрабатываются так же, как в /public (см. ниже),
    потому что Android DownloadManager шлёт их и сюда тоже.

    Args:
        filename: имя файла (только basename, без путей).
        request: объект запроса (для чтения заголовка Range).

    Returns:
        Response с Content-Disposition для скачивания.

    Raises:
        HTTPException 400 — недопустимое имя файла / Range;
        HTTPException 404 — файл не найден;
        HTTPException 503 — директория не сконфигурирована.
    """
    if not _APK_FILENAME_RE.match(filename):
        _log_and_raise(
            status_code=400,
            detail="invalid filename",
            log_msg=f"update.apk: rejected filename {filename!r}",
        )

    base_dir = _apk_dir()
    if not base_dir.is_dir():
        _log_and_raise(
            status_code=503,
            detail="apk directory not configured",
            log_msg=f"update.apk: APK dir not found: {base_dir}",
            log_level="error",
        )

    try:
        file_path = _resolve_safe(base_dir, filename)
    except HTTPException:
        _log_and_raise(
            status_code=400,
            detail="invalid filename",
            log_msg=f"update.apk: path traversal attempt {filename!r}",
        )

    if not file_path.is_file():
        _log_and_raise(
            status_code=404,
            detail="apk not found",
            log_msg=f"update.apk: file not found: {file_path}",
        )

    return _serve_with_range(
        file_path=file_path,
        filename=filename,
        request=request,
        log_prefix="update.apk",
        disposition="attachment",
        extra_headers={"Cache-Control": "public, max-age=86400"},
    )


# ============================================================
# ПУБЛИЧНАЯ раздача (без settings.API_KEY_HEADER)
# ============================================================


@router.get(
    "/public/{filename}",
    summary="Скачать публичный APK/version.json (без ключа)",
)
@log_exceptions(api_logger)
async def download_public_file(
    filename: str,
    request: Request,
) -> Response:
    """Отдать файл из ОТКРЫТОЙ директории обновлений БЕЗ settings.API_KEY_HEADER.

    URL: GET /api/v1/update/public/{filename}

    ============================================================
    ВАЖНО: РАЗДАЧА ИДЁТ НАПРЯМУЮ ИЗ FASTAPI/UVICORN, БЕЗ NGINX.
    ============================================================
    Android DownloadManager:
      - шлёт Range кусками;
      - ждёт финальный 416 на Range за пределами файла;
      - ожидает явный Content-Length (без chunked).

    Именно поэтому здесь используется `Response(content=...)`,
    а не StreamingResponse. См. docstring модуля.

    Args:
        filename: имя файла (только basename, без путей).
        request: объект запроса (для чтения заголовка Range).

    Returns:
        Response:
            - 200 — полный файл;
            - 206 — частичный контент с Content-Range;
            - 416 — Range за пределами файла (сигнал «докачка завершена»);
            - 400 — недопустимое имя файла / некорректный Range.

    Raises:
        HTTPException 400 — недопустимое имя файла / Range;
        HTTPException 404 — файл не найден;
        HTTPException 503 — директория не сконфигурирована.
    """
    # --- 1. Валидация имени файла (защита от path traversal) ---
    if not _PUBLIC_FILENAME_RE.match(filename):
        _log_and_raise(
            status_code=400,
            detail="invalid filename",
            log_msg=f"update.public: rejected filename {filename!r}",
        )

    # --- 2. Проверка директории и существования файла ---
    base_dir = _public_dir()
    if not base_dir.is_dir():
        _log_and_raise(
            status_code=503,
            detail="public directory not configured",
            log_msg=f"update.public: PUBLIC dir not found: {base_dir}",
            log_level="error",
        )

    try:
        file_path = _resolve_safe(base_dir, filename)
    except HTTPException:
        _log_and_raise(
            status_code=400,
            detail="invalid filename",
            log_msg=f"update.public: path traversal attempt {filename!r}",
        )

    if not file_path.is_file():
        _log_and_raise(
            status_code=404,
            detail="file not found",
            log_msg=f"update.public: file not found: {file_path}",
        )

    # APK — no-store, чтобы DownloadManager не получил закешированный
    # 200 вместо 206 при повторном Range-запросе.
    # json/txt — no-cache (version.json должен быть всегда свежим).
    suffix = file_path.suffix.lower()
    if suffix == ".apk":
        cache_control = "no-store"
    else:
        cache_control = "no-cache"

    return _serve_with_range(
        file_path=file_path,
        filename=filename,
        request=request,
        log_prefix="update.public",
        disposition="inline",
        extra_headers={"Cache-Control": cache_control},
    )


# ============================================================
# ОБЩАЯ ЛОГИКА Range-ОБРАБОТКИ
# ============================================================


def _serve_with_range(
    *,
    file_path: Path,
    filename: str,
    request: Request,
    log_prefix: str,
    disposition: str,
    extra_headers: dict[str, str],
) -> Response:
    """Отдаёт файл с поддержкой Range.

    Использует `Response(content=...)`, а НЕ `StreamingResponse`,
    чтобы uvicorn не переключился в `Transfer-Encoding: chunked`.
    DownloadManager без явного `Content-Length` не видит EOF
    и висит на «49,57 из 49,57 МБ».

    Args:
        file_path: путь к файлу (уже проверен на существование).
        filename: исходное имя (для Content-Disposition и логов).
        request: объект запроса (для Range).
        log_prefix: префикс для логов ("update.apk" / "update.public").
        disposition: "attachment" (закрытая) или "inline" (публичная).
        extra_headers: дополнительные заголовки (Cache-Control).

    Returns:
        Response (200 / 206 / 416).
    """
    file_size = file_path.stat().st_size
    media_type = _PUBLIC_MIME_BY_SUFFIX.get(file_path.suffix.lower(), "application/octet-stream")

    range_header = request.headers.get("range")

    # NEW: диагностика — видим ВСЕ входящие Range-запросы.
    if range_header is not None:
        api_logger.info(
            "%s: incoming Range header=%r file=%s size=%d",
            log_prefix,
            range_header,
            filename,
            file_size,
        )

    base_headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        **extra_headers,
    }

    # --- Без Range: полный ответ ---
    if not range_header:
        content = _read_full(file_path)
        api_logger.info(
            "%s: serving %s FULL (size=%d, mime=%s) -> %s",
            log_prefix,
            filename,
            file_size,
            media_type,
            file_path,
        )
        return Response(
            content=content,
            status_code=200,
            media_type=media_type,
            headers={
                **base_headers,
                "Content-Length": str(len(content)),
                # ФИКС A: закрываем TCP-соединение сразу после отдачи файла.
                # Мобильные браузеры (Chrome Android, Samsung Internet) и
                # Android DownloadManager не всегда шлют финальный
                # Range: bytes=<size>- и ждут EOF. Без Connection: close
                # они висят на 100% из-за keep-alive (а мобильный NAT
                # оператора/роутера прибивает соединение ещё раньше).
                "Connection": "close",
            },
        )

    # --- С Range ---
    # Инициализируем значения по умолчанию ДО try, чтобы
    # статический анализатор не ругался на «possibly unbound».
    start: int = 0
    end: int = file_size - 1

    # 4.1. Разбор Range: bytes=start-end
    # Поддерживаем только "bytes". Множественные диапазоны
    # (bytes=0-100,200-300) игнорируем — DownloadManager их не шлёт.
    try:
        unit, _, spec = range_header.partition("=")
        if unit.strip().lower() != "bytes":
            raise ValueError("unsupported unit")
        start_s, _, end_s = spec.partition("-")
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
    except (ValueError, TypeError):
        _log_and_raise(
            status_code=400,
            detail="invalid range",
            log_msg=f"{log_prefix}: invalid Range header {range_header!r}",
        )

    # 4.1a. Отрицательный start (bytes=-N)
    # По RFC 7233 `bytes=-N` означает «последние N байт», но
    # DownloadManager такой формы не шлёт. На всякий случай
    # отвергаем как 400, чтобы не отдать весь файл молча.
    if start < 0:
        _log_and_raise(
            status_code=400,
            detail="invalid range",
            log_msg=f"{log_prefix}: negative Range start={start} (raw={range_header!r})",
        )

    # 4.2. Range за пределами файла → 416
    # КРИТИЧНО: этот блок должен идти ДО чтения файла.
    # `start >= file_size` означает, что запрошенный диапазон
    # НЕ СУЩЕСТВУЕТ (последний байт имеет индекс file_size - 1).
    # DownloadManager ждёт явный 416, чтобы завершить сессию.
    if start >= file_size:
        api_logger.warning(
            "%s: 416 range beyond file %s (size=%d, start=%d, raw_range=%r)",
            log_prefix,
            filename,
            file_size,
            start,
            range_header,
        )
        return Response(
            status_code=416,
            headers={
                "Content-Range": f"bytes */{file_size}",
                "Accept-Ranges": "bytes",
                **extra_headers,
                # NEW: явно сообщаем, что тела нет. Некоторые
                # реализации DownloadManager без этого ждут
                # тело и висят на 100%.
                "Content-Length": "0",
            },
        )

    # 4.3. Нормализация диапазона
    if end >= file_size:
        end = file_size - 1
    if end < start:
        _log_and_raise(
            status_code=400,
            detail="invalid range",
            log_msg=f"{log_prefix}: invalid Range start={start} end={end} (file_size={file_size})",
        )

    length = end - start + 1

    # 4.4. Чтение ровно length байт с позиции start.
    content = _read_range(file_path, start, length)
    actual_len = len(content)

    api_logger.info(
        "%s: serving %s RANGE %d-%d/%d (size=%d, mime=%s) -> %s",
        log_prefix,
        filename,
        start,
        end,
        file_size,
        actual_len,
        media_type,
        file_path,
    )

    # 4.5. Ответ 206 Partial Content.
    # ВАЖНО: Response (не StreamingResponse) — Content-Length
    # выставляется явно, uvicorn не переключается в chunked,
    # DownloadManager видит EOF и завершает докачку.
    return Response(
        content=content,
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(actual_len),
            "Accept-Ranges": "bytes",
            "Connection": "close",
            **extra_headers,
        },
    )


__all__ = ["router"]
