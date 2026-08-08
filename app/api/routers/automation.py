from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.repositories.users import UserRepository
from ...exceptions import log_exceptions
from ...logger import api_logger
from ...services.automation_service import automation_service
from ...utils.datetime import get_timestamp
from ..dependencies import get_session

router = APIRouter(prefix="/automation", tags=["Automation"])


class ConvertDocRequest(BaseModel):
    """Модель запроса для конвертации DOC в PDF"""

    doc_base64: str | None = Field(
        None, description="Документ в формате base64 (опционально, если используется загрузка файла)"
    )
    filename: str = Field("document.docx", description="Имя исходного файла", max_length=100)
    user_id: int | None = Field(None, description="ID пользователя")


class ConvertDocResponse(BaseModel):
    """Модель ответа для конвертации"""

    success: bool = Field(..., description="Успешность операции")
    pdf_filename: str | None = Field(None, description="Имя PDF-файла")
    file_size: int | None = Field(None, description="Размер PDF-файла в байтах")
    error: str | None = Field(None, description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время операции")


class AutomationRequest(BaseModel):
    """Модель запроса для создания заявки"""

    user_id: int = Field(..., description="ID пользователя", gt=0)
    title: str = Field(..., description="Название заявки", min_length=3, max_length=200)
    description: str = Field(..., description="Описание заявки", min_length=10)
    priority: str = Field("medium", description="Приоритет: low, medium, high, critical")
    chat_id: int | None = Field(None, description="ID чата Telegram для уведомлений")


class AutomationRequestResponse(BaseModel):
    """Модель ответа для заявки"""

    success: bool = Field(..., description="Успешность операции")
    request_id: int | None = Field(None, description="ID заявки")
    error: str | None = Field(None, description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время операции")


class RequestStatusResponse(BaseModel):
    """Модель ответа со списком заявок"""

    success: bool = Field(..., description="Успешность операции")
    requests: list[dict] = Field(default_factory=list, description="Список заявок")
    count: int = Field(0, description="Количество заявок")
    error: str | None = Field(None, description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время операции")


# ============ ЭНДПОИНТЫ ============


@router.post(
    "/convert/doc-to-pdf",
    response_model=ConvertDocResponse,
    summary="Конвертировать DOC в PDF",
    description="Преобразует документ DOC/DOCX в PDF",
)
@log_exceptions(api_logger)
async def convert_doc_to_pdf(
    file: UploadFile = File(...),  # noqa: B008
    user_id: int | None = Form(None),  # noqa: B008
) -> JSONResponse | Response:
    """
    Конвертация DOC/DOCX в PDF через загрузку файла

    Args:
        file: Загружаемый DOC/DOCX файл
        user_id: ID пользователя (опционально)

    Returns:
        PDF файл или JSON с ошибкой
    """
    api_logger.info(f"📄 Converting DOC to PDF: {file.filename} (user={user_id})")

    # Проверка типа файла
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла не указано")

    allowed_extensions = [".doc", ".docx"]
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400, detail=f"Неподдерживаемый формат. Разрешены: {', '.join(allowed_extensions)}"
        )

    try:
        # Чтение содержимого файла
        doc_content = await file.read()

        if not doc_content:
            raise HTTPException(status_code=400, detail="Файл пуст")

        if len(doc_content) > settings.AUTOMATION_MAX_FILE_SIZE:
            max_size_mb = settings.AUTOMATION_MAX_FILE_SIZE // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"Файл слишком большой (макс. {max_size_mb}MB)")

        # Конвертация
        result = await automation_service.convert_doc_to_pdf(
            doc_content=doc_content, filename=file.filename, user_id=user_id
        )

        if not result["success"]:
            return JSONResponse(
                status_code=500,
                content=ConvertDocResponse(
                    success=False, pdf_filename=None, file_size=None, error=result["error"], timestamp=get_timestamp()
                ).model_dump(),
            )

        # Возврат PDF-файла
        return Response(
            content=result["pdf_content"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={result['pdf_filename']}",
                "Content-Length": str(result["file_size"]),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
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
    description="Преобразует документ DOC/DOCX в PDF с передачей в base64",
)
@log_exceptions(api_logger)
async def convert_doc_to_pdf_base64(request: ConvertDocRequest) -> JSONResponse:
    """
    Конвертация DOC/DOCX в PDF через base64

    Args:
        request: Запрос с base64-документом

    Returns:
        PDF в base64 или JSON с ошибкой
    """
    import base64

    api_logger.info(f"📄 Converting DOC to PDF (base64): {request.filename} (user={request.user_id})")

    if not request.doc_base64:
        raise HTTPException(status_code=400, detail="Документ не передан")

    try:
        # Декодирование base64
        doc_content = base64.b64decode(request.doc_base64)

        if not doc_content:
            raise HTTPException(status_code=400, detail="Документ пуст")

        if len(doc_content) > settings.AUTOMATION_MAX_FILE_SIZE:
            max_size_mb = settings.AUTOMATION_MAX_FILE_SIZE // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"Файл слишком большой (макс. {max_size_mb}MB)")

        # Конвертация
        result = await automation_service.convert_doc_to_pdf(
            doc_content=doc_content, filename=request.filename, user_id=request.user_id
        )

        if not result["success"]:
            return JSONResponse(
                status_code=500,
                content=ConvertDocResponse(
                    success=False, pdf_filename=None, file_size=None, error=result["error"], timestamp=get_timestamp()
                ).model_dump(),
            )

        # Кодирование PDF в base64
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
    description="Создает новую заявку на автоматизацию",
)
@log_exceptions(api_logger)
async def create_automation_request(
    request: AutomationRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Создание заявки на автоматизацию"""
    api_logger.info(f"📝 Creating automation request from user {request.user_id}")

    # Проверка приоритета
    valid_priorities = ["low", "medium", "high", "critical"]
    if request.priority not in valid_priorities:
        raise HTTPException(status_code=400, detail=f"Неверный приоритет. Допустимые: {', '.join(valid_priorities)}")

    # Проверка пользователя через репозиторий
    user = await UserRepository.get_user_by_id(session, request.user_id)
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

    try:
        result = await automation_service.create_automation_request(
            user_id=request.user_id,
            title=request.title,
            description=request.description,
            priority=request.priority,
            chat_id=request.chat_id,
            session=session,
        )

        if not result["success"]:
            return JSONResponse(
                status_code=500,
                content=AutomationRequestResponse(
                    success=False, request_id=None, error=result["error"], timestamp=get_timestamp()
                ).model_dump(),
            )

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
    description="Возвращает список заявок на автоматизацию",
)
@log_exceptions(api_logger)
async def get_automation_requests(
    user_id: int | None = None,
    status: str | None = None,
) -> JSONResponse:
    """Получение списка заявок"""
    api_logger.info(f"📋 Getting automation requests (user={user_id}, status={status})")

    try:
        requests = await automation_service.get_requests(user_id=user_id, status=status)

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
    description="Обновляет статус заявки на автоматизацию",
)
@log_exceptions(api_logger)
async def update_request_status(
    request_id: int,
    status: str,
    note: str | None = None,
) -> JSONResponse:
    """Обновление статуса заявки"""
    api_logger.info(f"🔄 Updating request #{request_id} status to {status}")

    valid_statuses = ["new", "in_progress", "completed", "cancelled", "rejected"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Неверный статус. Допустимые: {', '.join(valid_statuses)}")

    try:
        result = await automation_service.update_request_status(request_id=request_id, status=status, note=note)

        if not result["success"]:
            return JSONResponse(
                status_code=404, content={"success": False, "error": result["error"], "timestamp": get_timestamp()}
            )

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
