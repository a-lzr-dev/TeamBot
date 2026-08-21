"""
Модуль роутера для автоматизации процессов.

Этот модуль предоставляет API эндпоинты для автоматизации различных задач:
- Конвертация документов DOC/DOCX в PDF
- Создание и управление заявками на автоматизацию
- Просмотр статуса заявок
- Обновление статуса заявок

Все эндпоинты используют общий префикс /automation и требуют аутентификации.
Модуль интегрируется с сервисом automation_service и репозиторием пользователей.

Роуты:
    POST /convert/doc-to-pdf - Конвертация DOC в PDF через загрузку файла
    POST /convert/doc-to-pdf/base64 - Конвертация DOC в PDF через base64
    POST /request - Создание заявки на автоматизацию
    GET /requests - Получение списка заявок
    PATCH /requests/{request_id}/status - Обновление статуса заявки
"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.repositories.users import UserRepository
from ...logger import api_logger
from ...services.automation_service import automation_service
from ...utils.datetime import get_timestamp
from ...utils.decorators import log_exceptions
from ..dependencies import get_session

# Создание роутера с префиксом /automation и тегом для документации
router = APIRouter(prefix="/automation", tags=["Automation"])

# Репозиторий пользователей (создается один раз на уровне модуля для переиспользования)
_user_repo = UserRepository()


class ConvertDocRequest(BaseModel):
    """
    Модель запроса для конвертации DOC в PDF через base64.

    Используется в эндпоинте /convert/doc-to-pdf/base64 для передачи
    документа в закодированном виде.
    """

    doc_base64: str | None = Field(
        None, description="Документ в формате base64 (опционально, если используется загрузка файла)"
    )
    filename: str = Field("document.docx", description="Имя исходного файла", max_length=100)
    user_id: int | None = Field(None, description="ID пользователя для логирования и аудита")


class ConvertDocResponse(BaseModel):
    """
    Модель ответа для операции конвертации документа.

    Используется как для успешной конвертации, так и для ошибок.
    """

    success: bool = Field(..., description="Успешность операции")
    pdf_filename: str | None = Field(None, description="Имя сгенерированного PDF-файла")
    file_size: int | None = Field(None, description="Размер PDF-файла в байтах")
    error: str | None = Field(None, description="Сообщение об ошибке, если есть")
    timestamp: str = Field(..., description="Время выполнения операции в ISO формате")


class AutomationRequest(BaseModel):
    """
    Модель запроса для создания новой заявки на автоматизацию.

    Используется в эндпоинте /request для создания заявки.
    """

    user_id: int = Field(..., description="ID пользователя, создающего заявку", gt=0)
    title: str = Field(..., description="Название заявки", min_length=3, max_length=200)
    description: str = Field(..., description="Подробное описание заявки", min_length=10)
    priority: str = Field(
        "medium", description="Приоритет заявки: low (низкий), medium (средний), high (высокий), critical (критический)"
    )
    chat_id: int | None = Field(None, description="ID чата Telegram для отправки уведомлений о статусе заявки")


class AutomationRequestResponse(BaseModel):
    """
    Модель ответа при создании заявки на автоматизацию.

    Содержит ID созданной заявки или информацию об ошибке.
    """

    success: bool = Field(..., description="Успешность операции")
    request_id: int | None = Field(None, description="ID созданной заявки")
    error: str | None = Field(None, description="Сообщение об ошибке, если есть")
    timestamp: str = Field(..., description="Время выполнения операции")


class RequestStatusResponse(BaseModel):
    """
    Модель ответа со списком заявок на автоматизацию.

    Используется в эндпоинте /requests для возврата списка заявок.
    """

    success: bool = Field(..., description="Успешность операции")
    requests: list[dict] = Field(default_factory=list, description="Список заявок с полной информацией")
    count: int = Field(0, description="Количество возвращенных заявок")
    error: str | None = Field(None, description="Сообщение об ошибке, если есть")
    timestamp: str = Field(..., description="Время выполнения операции")


# ============ ЭНДПОИНТЫ ============


@router.post(
    "/convert/doc-to-pdf",
    response_model=ConvertDocResponse,
    summary="Конвертировать DOC в PDF",
    description="Преобразует документ в формате DOC или DOCX в PDF через загрузку файла",
)
@log_exceptions(api_logger)
async def convert_doc_to_pdf(
    file: UploadFile = File(...),  # noqa: B008
    user_id: int | None = Form(None),  # noqa: B008
) -> JSONResponse | Response:
    """
    Конвертация DOC/DOCX в PDF через загрузку файла.

    Принимает файл через multipart/form-data и возвращает PDF файл
    в виде бинарного ответа для скачивания.

    Args:
        file: Загружаемый DOC/DOCX файл (обязательный)
        user_id: ID пользователя (опционально, для аудита)

    Returns:
        Response: PDF файл для скачивания при успехе
        JSONResponse: Информация об ошибке при неудаче

    Raises:
        HTTPException: При ошибках валидации (неверный формат, пустой файл, превышение размера)

    Notes:
        - Поддерживаются только .doc и .docx расширения
        - Максимальный размер файла берется из settings.AUTOMATION_MAX_FILE_SIZE
        - При успехе возвращается бинарный PDF с заголовком Content-Disposition для скачивания
    """
    api_logger.info(f"📄 Converting DOC to PDF: {file.filename} (user={user_id})")

    # Проверка наличия имени файла
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла не указано")

    # Проверка расширения файла
    allowed_extensions = [".doc", ".docx"]
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400, detail=f"Неподдерживаемый формат. Разрешены: {', '.join(allowed_extensions)}"
        )

    try:
        # Чтение содержимого загруженного файла
        doc_content = await file.read()

        # Проверка, что файл не пустой
        if not doc_content:
            raise HTTPException(status_code=400, detail="Файл пуст")

        # Проверка размера файла
        if len(doc_content) > settings.AUTOMATION_MAX_FILE_SIZE:
            max_size_mb = settings.AUTOMATION_MAX_FILE_SIZE // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"Файл слишком большой (макс. {max_size_mb}MB)")

        # Вызов сервиса для конвертации
        result = await automation_service.convert_doc_to_pdf(
            doc_content=doc_content, filename=file.filename, user_id=user_id
        )

        # Обработка ошибки конвертации
        if not result["success"]:
            return JSONResponse(
                status_code=500,
                content=ConvertDocResponse(
                    success=False, pdf_filename=None, file_size=None, error=result["error"], timestamp=get_timestamp()
                ).model_dump(),
            )

        # Возврат PDF-файла для скачивания
        return Response(
            content=result["pdf_content"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={result['pdf_filename']}",
                "Content-Length": str(result["file_size"]),
            },
        )

    except HTTPException:
        # Пробрасываем HTTP исключения дальше для обработки FastAPI
        raise
    except Exception as e:
        # Логируем неожиданные ошибки и возвращаем JSON с ошибкой
        api_logger.error(f"❌ DOC to PDF conversion failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ConvertDocResponse(
                success=False,
                pdf_filename=None,
                file_size=None,
                error=f"Ошибка конвертации: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.post(
    "/convert/doc-to-pdf/base64",
    response_model=ConvertDocResponse,
    summary="Конвертировать DOC в PDF (base64)",
    description="Преобразует документ DOC/DOCX в PDF с передачей данных в формате base64",
)
@log_exceptions(api_logger)
async def convert_doc_to_pdf_base64(request: ConvertDocRequest) -> JSONResponse:
    """
    Конвертация DOC/DOCX в PDF через base64.

    Принимает документ в base64 и возвращает PDF также в base64.
    Удобно для интеграции с системами, где нет прямой загрузки файлов.

    Args:
        request: Объект запроса с base64-документом и метаданными

    Returns:
        JSONResponse: Содержит PDF в base64 или информацию об ошибке

    Raises:
        HTTPException: При ошибках валидации

    Notes:
        - Документ должен быть передан в base64
        - Максимальный размер файла берется из настроек
        - Возвращает PDF в base64 вместе с именем файла и размером
    """
    import base64

    api_logger.info(f"📄 Converting DOC to PDF (base64): {request.filename} (user={request.user_id})")

    # Проверка наличия документа в запросе
    if not request.doc_base64:
        raise HTTPException(status_code=400, detail="Документ не передан")

    try:
        # Декодирование base64 в байты
        doc_content = base64.b64decode(request.doc_base64)

        # Проверка, что документ не пустой
        if not doc_content:
            raise HTTPException(status_code=400, detail="Документ пуст")

        # Проверка размера документа
        if len(doc_content) > settings.AUTOMATION_MAX_FILE_SIZE:
            max_size_mb = settings.AUTOMATION_MAX_FILE_SIZE // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"Файл слишком большой (макс. {max_size_mb}MB)")

        # Вызов сервиса для конвертации
        result = await automation_service.convert_doc_to_pdf(
            doc_content=doc_content, filename=request.filename, user_id=request.user_id
        )

        # Обработка ошибки конвертации
        if not result["success"]:
            return JSONResponse(
                status_code=500,
                content=ConvertDocResponse(
                    success=False, pdf_filename=None, file_size=None, error=result["error"], timestamp=get_timestamp()
                ).model_dump(),
            )

        # Кодирование PDF в base64 для ответа
        pdf_base64 = base64.b64encode(result["pdf_content"]).decode("utf-8")

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "pdf_base64": pdf_base64,
                "pdf_filename": result["pdf_filename"],
                "file_size": result["file_size"],
                "timestamp": get_timestamp(),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ DOC to PDF conversion (base64) failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ConvertDocResponse(
                success=False,
                pdf_filename=None,
                file_size=None,
                error=f"Ошибка конвертации: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.post(
    "/request",
    response_model=AutomationRequestResponse,
    summary="Создать заявку на автоматизацию",
    description="Создает новую заявку на автоматизацию для пользователя",
)
@log_exceptions(api_logger)
async def create_automation_request(
    request: AutomationRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Создание заявки на автоматизацию.

    Проверяет существование и аутентификацию пользователя,
    затем создает заявку с указанными параметрами.

    Args:
        request: Данные для создания заявки
        session: Асинхронная сессия БД (внедряется через Depends)

    Returns:
        JSONResponse: ID созданной заявки или ошибка

    Raises:
        HTTPException: При неверном приоритете

    Notes:
        - Пользователь должен существовать и быть аутентифицирован
        - Приоритет должен быть одним из: low, medium, high, critical
        - При успехе возвращается HTTP 201 (Created)
        - Если указан chat_id, будут отправлены уведомления в Telegram
    """
    api_logger.info(f"📝 Creating automation request from user {request.user_id}")

    # Валидация приоритета
    valid_priorities = ["low", "medium", "high", "critical"]
    if request.priority not in valid_priorities:
        raise HTTPException(status_code=400, detail=f"Неверный приоритет. Допустимые: {', '.join(valid_priorities)}")

    # Проверка существования пользователя
    user = await _user_repo.get_user_by_id(session, request.user_id)

    # Проверка, что пользователь существует и авторизован в системе
    if not user:
        return JSONResponse(
            status_code=404,
            content=AutomationRequestResponse(
                success=False,
                request_id=None,
                error=f"Пользователь с ID {request.user_id} не найден",
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    if not user.is_authenticated:
        return JSONResponse(
            status_code=403,
            content=AutomationRequestResponse(
                success=False,
                request_id=None,
                error=f"Пользователь с ID {request.user_id} не авторизован в системе",
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    try:
        # Создание заявки через сервис автоматизации
        result = await automation_service.create_automation_request(
            user_id=request.user_id,
            title=request.title,
            description=request.description,
            priority=request.priority,
            chat_id=request.chat_id,
            session=session,
        )

        # Обработка ошибки создания
        if not result["success"]:
            return JSONResponse(
                status_code=500,
                content=AutomationRequestResponse(
                    success=False, request_id=None, error=result["error"], timestamp=get_timestamp()
                ).model_dump(),
            )

        # Успешное создание заявки
        return JSONResponse(
            status_code=201,
            content=AutomationRequestResponse(
                success=True, request_id=result["request_id"], error=None, timestamp=get_timestamp()
            ).model_dump(),
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to create automation request: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=AutomationRequestResponse(
                success=False, request_id=None, error=f"Ошибка создания заявки: {str(e)}", timestamp=get_timestamp()
            ).model_dump(),
        )


@router.get(
    "/requests",
    response_model=RequestStatusResponse,
    summary="Получить список заявок",
    description="Возвращает список заявок на автоматизацию с возможностью фильтрации",
)
@log_exceptions(api_logger)
async def get_automation_requests(
    user_id: int | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение списка заявок на автоматизацию.

    Поддерживает фильтрацию по пользователю и статусу.

    Args:
        user_id: ID пользователя (опционально, фильтр по пользователю)
        status: Статус заявки (опционально, фильтр по статусу)
        session: Асинхронная сессия БД (внедряется через Depends)

    Returns:
        JSONResponse: Список заявок с полной информацией

    Notes:
        - Если user_id не указан, возвращаются все заявки
        - Если статус не указан, возвращаются заявки всех статусов
        - Статусы: new, in_progress, completed, cancelled, rejected
        - Заявки возвращаются отсортированными по дате создания (новые сверху)
    """
    api_logger.info(f"📋 Getting automation requests (user={user_id}, status={status})")

    try:
        # Получение заявок через сервис с фильтрацией
        requests = await automation_service.get_requests(
            user_id=user_id,
            status=status,
            session=session,
        )

        # Успешный ответ со списком заявок
        return JSONResponse(
            status_code=200,
            content=RequestStatusResponse(
                success=True, requests=requests, count=len(requests), error=None, timestamp=get_timestamp()
            ).model_dump(),
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get requests: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=RequestStatusResponse(
                success=False, requests=[], count=0, error=str(e), timestamp=get_timestamp()
            ).model_dump(),
        )


@router.patch(
    "/requests/{request_id}/status",
    summary="Обновить статус заявки",
    description="Обновляет статус заявки на автоматизацию с возможностью добавления заметки",
)
@log_exceptions(api_logger)
async def update_request_status(
    request_id: int,
    status: str,
    note: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Обновление статуса заявки на автоматизацию.

    Позволяет менять статус заявки и добавлять комментарий.

    Args:
        request_id: ID заявки для обновления (из пути)
        status: Новый статус заявки (параметр запроса)
        note: Дополнительная заметка (опционально, параметр запроса)
        session: Асинхронная сессия БД (внедряется через Depends)

    Returns:
        JSONResponse: Обновленная информация о заявке или ошибка

    Raises:
        HTTPException: При неверном статусе

    Notes:
        - Допустимые статусы: new, in_progress, completed, cancelled, rejected
        - При успехе возвращается обновленная информация о заявке
        - Если указан chat_id у заявки, отправляется уведомление в Telegram
        - Время изменения автоматически обновляется
    """
    api_logger.info(f"🔄 Updating request #{request_id} status to {status}")

    # Валидация статуса
    valid_statuses = ["new", "in_progress", "completed", "cancelled", "rejected"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Неверный статус. Допустимые: {', '.join(valid_statuses)}")

    try:
        # Обновление статуса через сервис
        result = await automation_service.update_request_status(
            request_id=request_id,
            status=status,
            note=note,
            session=session,
        )

        # Обработка ошибки (заявка не найдена)
        if not result["success"]:
            return JSONResponse(
                status_code=404, content={"success": False, "error": result["error"], "timestamp": get_timestamp()}
            )

        # Успешное обновление
        return JSONResponse(
            status_code=200, content={"success": True, "request": result["request"], "timestamp": get_timestamp()}
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to update request: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Ошибка обновления: {str(e)}", "timestamp": get_timestamp()},
        )


__all__ = ["router"]
