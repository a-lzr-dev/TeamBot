import asyncio
import contextlib
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..bot.dependencies import get_bot_manager
from ..config import settings
from ..db import AutomationRequestRepository, UserRepository, db_manager
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import (
    MessageType,
    UserRequestAutomationPriority,
    UserRequestAutomationStatus,
    datetime_now,
)

# Проверка, что на Windows
IS_WINDOWS = sys.platform == "win32"

# Импорт pywin32 (только для Windows)
if IS_WINDOWS:
    try:
        import pythoncom
        import win32com.client

        HAS_PYWIN32 = True
        app_logger.info("✅ pywin32 loaded successfully (Windows)")
    except ImportError as import_error:
        pythoncom = None
        win32com = None
        HAS_PYWIN32 = False
        app_logger.warning(f"⚠️ pywin32 not installed: {import_error}. Install: pip install pywin32")
else:
    pythoncom = None
    win32com = None
    HAS_PYWIN32 = False
    app_logger.warning("⚠️ Not running on Windows, pywin32 is not available")

# Импорт comtypes (альтернатива для Windows)
if IS_WINDOWS:
    try:
        import comtypes.client

        HAS_COMTYPES = True
        app_logger.info("✅ comtypes loaded successfully (Windows)")
    except ImportError as import_error:
        comtypes = None
        HAS_COMTYPES = False
        app_logger.warning(f"⚠️ comtypes not installed: {import_error}. Install: pip install comtypes")
else:
    comtypes = None
    HAS_COMTYPES = False

# Импорт subprocess (всегда доступен, но проверяем наличие LibreOffice)
try:
    import subprocess

    HAS_SUBPROCESS = True
except ImportError as import_error:
    subprocess = None  # type: ignore[assignment]
    HAS_SUBPROCESS = False
    app_logger.warning(f"⚠️ subprocess module not available: {import_error}")

# Проверка наличия LibreOffice
HAS_LIBREOFFICE = False
if HAS_SUBPROCESS and subprocess is not None:
    try:
        check_result = subprocess.run(["which", "soffice"], capture_output=True, text=True)
        if check_result.returncode == 0:
            HAS_LIBREOFFICE = True
            app_logger.info("✅ LibreOffice found")
        else:
            app_logger.warning("⚠️ LibreOffice not found. Install: sudo apt-get install libreoffice")
    except Exception as check_error:
        app_logger.warning(f"⚠️ LibreOffice check failed: {check_error}")


class AutomationService:
    """Сервис для автоматизации задач"""

    def __init__(self) -> None:
        self._initialized = False
        self._temp_dir = Path(tempfile.gettempdir()) / "teambot_automation"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

        # Статистика конвертаций
        self._conversion_stats: dict[str, Any] = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "by_method": {},
            "enabled": getattr(settings, "AUTOMATION_STATS_ENABLED", True),
            "max_entries": getattr(settings, "AUTOMATION_STATS_MAX_ENTRIES", 1000),
        }

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def initialize(self) -> None:
        """Инициализация сервиса"""
        if self._initialized:
            return

        self._initialized = True

        # Проверка доступности pywin32
        if not HAS_PYWIN32:
            app_logger.warning("⚠️ pywin32 not available. Conversions will fail on Windows.")
            if not IS_WINDOWS:
                app_logger.info("ℹ️ Running on non-Windows platform. Consider using docx2pdf with LibreOffice.")

        app_logger.info("✅ AutomationService initialized")
        app_logger.info(f"📁 Temp directory: {self._temp_dir}")
        app_logger.info(f"🖥️ Platform: {sys.platform}")
        app_logger.info(f"📦 pywin32 available: {HAS_PYWIN32}")
        app_logger.info(f"📦 comtypes available: {HAS_COMTYPES}")
        app_logger.info(f"📦 LibreOffice available: {HAS_LIBREOFFICE}")

    # ============ ОСНОВНОЙ МЕТОД КОНВЕРТАЦИИ ============

    @log_exceptions(app_logger)
    async def convert_doc_to_pdf(
        self,
        doc_content: bytes | Any,  # может быть bytes или BytesIO
        filename: str = "document.docx",
        user_id: int | None = None,
        method: str | None = None,
    ) -> dict[str, Any]:
        """
        Конвертация DOC/DOCX в PDF.

        Args:
            doc_content: Содержимое документа (bytes или BytesIO)
            filename: Имя файла
            user_id: ID пользователя (для логирования)
            method: Метод конвертации (auto, pywin32, comtypes, libreoffice)

        Returns:
            Dict с результатом
        """
        if method is None:
            method = settings.AUTOMATION_CONVERSION_METHOD

        self._conversion_stats["total"] = self._conversion_stats.get("total", 0) + 1

        app_logger.info(f"🔄 Converting DOC to PDF: {filename} (user={user_id}, method={method})")

        # Проверка расширения
        file_ext = Path(filename).suffix.lower()
        if file_ext not in [".doc", ".docx"]:
            return {
                "success": False,
                "error": f"Неподдерживаемый формат: {file_ext}. Разрешены: .doc, .docx",
                "pdf_content": None,
                "pdf_filename": None,
                "file_size": None,
            }

        # Определение метода
        if method == "auto":
            if HAS_PYWIN32 and IS_WINDOWS:
                method = "pywin32"
            elif HAS_COMTYPES and IS_WINDOWS:
                method = "comtypes"
            elif HAS_LIBREOFFICE:
                method = "libreoffice"
            else:
                return {
                    "success": False,
                    "error": "Нет доступных методов конвертации. Установите pywin32 (Windows) или LibreOffice (Linux/macOS)",
                    "pdf_content": None,
                    "pdf_filename": None,
                    "file_size": None,
                }

        app_logger.debug(f"🔄 Using conversion method: {method}")

        temp_doc_path = None
        temp_pdf_path = None

        try:
            if hasattr(doc_content, "read"):
                # Это BytesIO или подобный объект
                content_bytes = doc_content.read()
            elif isinstance(doc_content, bytes):
                content_bytes = doc_content
            else:
                # Преобразование в bytes
                content_bytes = bytes(doc_content)

            if not content_bytes:
                return {
                    "success": False,
                    "error": "Документ пуст",
                    "pdf_content": None,
                    "pdf_filename": None,
                    "file_size": None,
                }

            # Сохранение временного DOC-файла
            with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False, dir=str(self._temp_dir)) as tmp_doc:
                tmp_doc.write(content_bytes)
                temp_doc_path = Path(tmp_doc.name)

            app_logger.debug(f"📄 Temp DOC: {temp_doc_path} ({temp_doc_path.stat().st_size} bytes)")

            # Определение имени PDF-файла
            base_name = Path(filename).stem
            pdf_filename = f"{base_name}.pdf"

            # Создание временного PDF-файла
            temp_pdf_path = self._temp_dir / f"{base_name}_{datetime_now().strftime('%Y%m%d_%H%M%S')}.pdf"

            # Конвертация выбранным методом
            conversion_success = False

            if method == "pywin32" and HAS_PYWIN32:
                conversion_success, error_message = await self._convert_with_pywin32(
                    str(temp_doc_path), str(temp_pdf_path)
                )
            elif method == "comtypes" and HAS_COMTYPES:
                conversion_success, error_message = await self._convert_with_comtypes(
                    str(temp_doc_path), str(temp_pdf_path)
                )
            elif method == "libreoffice" and HAS_LIBREOFFICE:
                conversion_success, error_message = await self._convert_with_libreoffice(
                    str(temp_doc_path), str(temp_pdf_path)
                )
            else:
                error_message = f"Метод {method} не доступен"

            # Проверка результата
            if not conversion_success or not temp_pdf_path.exists():
                self._conversion_stats["failed"] = self._conversion_stats.get("failed", 0) + 1
                return {
                    "success": False,
                    "error": error_message or "Не удалось сконвертировать документ",
                    "pdf_content": None,
                    "pdf_filename": None,
                    "file_size": None,
                }

            # Чтение PDF-файла
            with open(temp_pdf_path, "rb") as pdf_file:
                pdf_content = pdf_file.read()

            file_size = len(pdf_content)

            self._conversion_stats["success"] = self._conversion_stats.get("success", 0) + 1

            # Обновление статистики по методам
            by_method = self._conversion_stats.get("by_method", {})
            by_method[method] = by_method.get(method, 0) + 1
            self._conversion_stats["by_method"] = by_method

            app_logger.info(f"✅ DOC converted to PDF: {pdf_filename} ({file_size} bytes, method={method})")

            return {
                "success": True,
                "pdf_content": pdf_content,
                "pdf_filename": pdf_filename,
                "file_size": file_size,
                "conversion_method": method,
                "error": None,
            }

        except Exception as conversion_error:
            self._conversion_stats["failed"] = self._conversion_stats.get("failed", 0) + 1
            app_logger.error(f"❌ DOC to PDF conversion failed: {conversion_error}", exc_info=True)
            return {
                "success": False,
                "error": f"Ошибка конвертации: {str(conversion_error)}",
                "pdf_content": None,
                "pdf_filename": None,
                "file_size": None,
            }

        finally:
            # Очистка временных файлов
            await self._cleanup_temp_files(temp_doc_path, temp_pdf_path)

    # ============ МЕТОДЫ КОНВЕРТАЦИИ ============

    @staticmethod
    async def _convert_with_pywin32(doc_path: str, pdf_path: str) -> tuple[bool, str | None]:
        """Конвертация через pywin32 (использует Microsoft Word)"""
        if not HAS_PYWIN32 or win32com is None:
            return False, "pywin32 not available"

        try:
            # Инициализация COM в отдельном потоке
            def convert_in_thread() -> tuple[bool, str | None]:
                with contextlib.suppress(Exception):
                    if pythoncom is not None:
                        pythoncom.CoInitialize()

                word = None
                try:
                    # Создание экземпляра Word
                    word = win32com.client.Dispatch("Word.Application")
                    word.Visible = False
                    word.DisplayAlerts = False

                    # Открытие документа
                    doc = word.Documents.Open(doc_path)

                    # Сохранение как PDF (17 = wdFormatPDF)
                    doc.SaveAs(pdf_path, FileFormat=17)

                    # Закрытие документа
                    doc.Close()

                    return True, None

                except Exception as pywin32_error:
                    return False, str(pywin32_error)

                finally:
                    # Закрытие Word
                    if word:
                        with contextlib.suppress(BaseException):
                            word.Quit()

                    with contextlib.suppress(Exception):
                        if pythoncom is not None:
                            pythoncom.CoUninitialize()

            # Запуск в отдельном потоке (блокирующая операция)
            success, error = await asyncio.to_thread(convert_in_thread)

            if success:
                return True, None
            else:
                return False, error or "pywin32 conversion failed"

        except Exception as pywin32_error:
            return False, f"pywin32 error: {str(pywin32_error)}"

    @staticmethod
    async def _convert_with_comtypes(doc_path: str, pdf_path: str) -> tuple[bool, str | None]:
        """Конвертация через comtypes (альтернатива pywin32)"""
        if not HAS_COMTYPES or comtypes is None:
            return False, "comtypes not available"

        try:

            def convert_in_thread() -> tuple[bool, str | None]:
                try:
                    # Создание экземпляра Word
                    word = comtypes.client.CreateObject("Word.Application")
                    word.Visible = False

                    # Открытие документа
                    doc = word.Documents.Open(doc_path)

                    # Сохранение как PDF
                    doc.SaveAs(pdf_path, FileFormat=17)  # wdFormatPDF

                    # Закрытие
                    doc.Close()
                    word.Quit()

                    return True, None

                except Exception as comtypes_error:
                    return False, str(comtypes_error)

            success, error = await asyncio.to_thread(convert_in_thread)

            if success:
                return True, None
            else:
                return False, error or "comtypes conversion failed"

        except Exception as comtypes_error:
            return False, f"comtypes error: {str(comtypes_error)}"

    @staticmethod
    async def _convert_with_libreoffice(doc_path: str, pdf_path: str) -> tuple[bool, str | None]:
        """Конвертация через LibreOffice (для Linux/macOS)"""
        if not HAS_LIBREOFFICE or subprocess is None:
            return False, "LibreOffice not available"

        try:
            # Команда конвертации
            cmd = ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(Path(pdf_path).parent), doc_path]

            # Запуск конвертации
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return False, f"LibreOffice error: {stderr.decode()}"

            # Проверка созданного файла
            expected_pdf = Path(doc_path).with_suffix(".pdf")
            if expected_pdf.exists():
                # Перемещение в нужную папку
                expected_pdf.rename(pdf_path)
                return True, None
            else:
                return False, "PDF file not created"

        except Exception as libreoffice_error:
            return False, f"LibreOffice error: {str(libreoffice_error)}"

    @staticmethod
    async def _cleanup_temp_files(doc_path: Path | None, pdf_path: Path | None) -> None:
        """Очистка временных файлов"""
        for path in [doc_path, pdf_path]:
            if path and path.exists():
                try:
                    path.unlink()
                    app_logger.debug(f"🗑️ Deleted temp file: {path}")
                except Exception as cleanup_error:
                    app_logger.warning(f"⚠️ Could not delete temp file {path}: {cleanup_error}")

    # ============ ЗАЯВКИ НА АВТОМАТИЗАЦИЮ (БД) ============

    @log_exceptions(app_logger)
    async def create_automation_request(
        self,
        *,
        user_id: int,
        title: str,
        description: str,
        priority: str = "medium",
        chat_id: int | None = None,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """
        Создание заявки на автоматизацию в БД.

        Args:
            user_id: ID пользователя
            title: Название заявки
            description: Описание заявки
            priority: Приоритет (low, medium, high, critical)
            chat_id: ID чата для уведомлений
            session: Сессия БД

        Returns:
            dict: Результат операции
        """
        app_logger.info(f"📝 Creating automation request from user {user_id}: {title}")

        # Проверка пользователя через репозиторий
        user = await UserRepository.get_user_by_id(session, user_id)

        if not user:
            app_logger.warning(f"⚠️ User {user_id} not found")
            return {"success": False, "error": "Пользователь не найден", "request_id": None}

        # Преобразование приоритета
        priority_map = {
            "low": UserRequestAutomationPriority.LOW,
            "medium": UserRequestAutomationPriority.MEDIUM,
            "high": UserRequestAutomationPriority.HIGH,
            "critical": UserRequestAutomationPriority.CRITICAL,
        }
        priority_enum = priority_map.get(priority.lower(), UserRequestAutomationPriority.MEDIUM)

        try:
            # Сохранение в БД через репозиторий
            request = await AutomationRequestRepository.create(
                session=session,
                user_id=user_id,
                title=title,
                description=description,
                priority=priority_enum,
                chat_id=chat_id,
            )

            await session.commit()

            app_logger.info(f"✅ Automation request created: #{request.FID}")

            # Отправка уведомления в чат поддержки (в топик Jobs)
            await self._send_request_notification(request)

            return {
                "success": True,
                "request_id": request.FID,
                "request": self._format_request(request),
                "error": None,
            }

        except Exception as create_error:
            app_logger.error(f"❌ Failed to create automation request: {create_error}", exc_info=True)
            await session.rollback()
            return {"success": False, "error": str(create_error), "request_id": None}

    @log_exceptions(app_logger)
    async def get_requests(
        self,
        user_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """
        Получение списка заявок из БД.

        Args:
            user_id: ID пользователя (опционально)
            status: Статус заявки (опционально)
            priority: Приоритет (опционально)
            limit: Лимит записей
            offset: Смещение
            session: Сессия БД (опционально)

        Returns:
            list[dict]: Список заявок
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.get_requests(
                    user_id=user_id,
                    status=status,
                    priority=priority,
                    limit=limit,
                    offset=offset,
                    session=new_session,
                )

        # Преобразование статуса
        status_enum = None
        if status:
            try:
                status_enum = UserRequestAutomationStatus(status)
            except ValueError as status_error:
                app_logger.warning(f"⚠️ Invalid status: {status}, error: {status_error}")

        # Преобразование приоритета
        priority_enum = None
        if priority:
            try:
                priority_enum = UserRequestAutomationPriority(priority)
            except ValueError as priority_error:
                app_logger.warning(f"⚠️ Invalid priority: {priority}, error: {priority_error}")

        requests = await AutomationRequestRepository.get_all(
            session=session,
            status=status_enum,
            priority=priority_enum,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

        return [self._format_request(req) for req in requests]

    @log_exceptions(app_logger)
    async def get_request_by_id(
        self,
        request_id: int,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        """
        Получение заявки по ID.

        Args:
            request_id: ID заявки
            session: Сессия БД (опционально)

        Returns:
            dict | None: Заявка или None
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.get_request_by_id(request_id, new_session)

        from sqlalchemy import select

        from ..models import UserRequestAutomationModel

        stmt = (
            select(UserRequestAutomationModel)
            .options(selectinload(UserRequestAutomationModel.user))
            .where(UserRequestAutomationModel.FID == request_id)
        )

        result = await session.execute(stmt)
        request = result.scalar_one_or_none()

        if not request:
            return None

        return self._format_request(request)

    @log_exceptions(app_logger)
    async def update_request_status(
        self,
        request_id: int,
        status: str,
        note: str | None = None,
        completed_by: int | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """
        Обновление статуса заявки.

        Args:
            request_id: ID заявки
            status: Новый статус
            note: Примечание
            completed_by: ID пользователя, завершившего заявку
            session: Сессия БД (опционально)

        Returns:
            dict: Результат операции
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.update_request_status(
                    request_id=request_id,
                    status=status,
                    note=note,
                    completed_by=completed_by,
                    session=new_session,
                )

        # Преобразование статуса
        try:
            status_enum = UserRequestAutomationStatus(status)
        except ValueError as status_error:
            return {"success": False, "error": f"Неверный статус: {status}, error: {status_error}"}

        try:
            success, request = await AutomationRequestRepository.update_status(
                session=session,
                request_id=request_id,
                status=status_enum,
                note=note,
                completed_by=completed_by,
            )

            if not success:
                return {"success": False, "error": f"Заявка #{request_id} не найдена"}

            await session.commit()

            app_logger.info(f"✅ Request #{request_id} status updated to {status}")

            from sqlalchemy import select

            from ..models import UserRequestAutomationModel

            stmt = (
                select(UserRequestAutomationModel)
                .options(selectinload(UserRequestAutomationModel.user))
                .where(UserRequestAutomationModel.FID == request_id)
            )
            result = await session.execute(stmt)
            updated_request = result.scalar_one_or_none()

            return {
                "success": True,
                "request": self._format_request(updated_request) if updated_request else None,
                "error": None,
            }

        except Exception as update_error:
            app_logger.error(f"❌ Failed to update request status: {update_error}", exc_info=True)
            await session.rollback()
            return {"success": False, "error": str(update_error)}

    @log_exceptions(app_logger)
    async def update_request_priority(
        self,
        request_id: int,
        priority: str,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """
        Обновление приоритета заявки.

        Args:
            request_id: ID заявки
            priority: Новый приоритет
            session: Сессия БД (опционально)

        Returns:
            dict: Результат операции
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.update_request_priority(
                    request_id=request_id,
                    priority=priority,
                    session=new_session,
                )

        # Преобразование приоритета
        try:
            priority_enum = UserRequestAutomationPriority(priority)
        except ValueError as priority_error:
            return {"success": False, "error": f"Неверный приоритет: {priority}, error: {priority_error}"}

        try:
            success, request = await AutomationRequestRepository.update_priority(
                session=session,
                request_id=request_id,
                priority=priority_enum,
            )

            if not success:
                return {"success": False, "error": f"Заявка #{request_id} не найдена"}

            await session.commit()

            app_logger.info(f"✅ Request #{request_id} priority updated to {priority}")

            from sqlalchemy import select

            from ..models import UserRequestAutomationModel

            stmt = (
                select(UserRequestAutomationModel)
                .options(selectinload(UserRequestAutomationModel.user))
                .where(UserRequestAutomationModel.FID == request_id)
            )
            result = await session.execute(stmt)
            updated_request = result.scalar_one_or_none()

            return {
                "success": True,
                "request": self._format_request(updated_request) if updated_request else None,
                "error": None,
            }

        except Exception as update_error:
            app_logger.error(f"❌ Failed to update request priority: {update_error}", exc_info=True)
            await session.rollback()
            return {"success": False, "error": str(update_error)}

    @log_exceptions(app_logger)
    async def get_stats(
        self,
        user_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """
        Получение статистики по заявкам.

        Args:
            user_id: ID пользователя (опционально)
            start_date: Начальная дата (ISO формат)
            end_date: Конечная дата (ISO формат)
            session: Сессия БД (опционально)

        Returns:
            dict: Статистика
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.get_stats(
                    user_id=user_id,
                    start_date=start_date,
                    end_date=end_date,
                    session=new_session,
                )

        # Парсинг дат
        start_dt = None
        end_dt = None

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            except ValueError as start_error:
                app_logger.warning(f"⚠️ Invalid start_date: {start_date}, error: {start_error}")

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            except ValueError as end_error:
                app_logger.warning(f"⚠️ Invalid end_date: {end_date}, error: {end_error}")

        return await AutomationRequestRepository.get_stats(
            session=session,
            user_id=user_id,
            start_date=start_dt,
            end_date=end_dt,
        )

    @log_exceptions(app_logger)
    async def delete_request(
        self,
        request_id: int,
        soft: bool = True,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """
        Удаление заявки.

        Args:
            request_id: ID заявки
            soft: Мягкое удаление (изменение статуса на CANCELLED)
            session: Сессия БД (опционально)

        Returns:
            dict: Результат операции
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.delete_request(
                    request_id=request_id,
                    soft=soft,
                    session=new_session,
                )

        try:
            if soft:
                # Мягкое удаление - меняем статус
                success, _ = await AutomationRequestRepository.update_status(
                    session=session,
                    request_id=request_id,
                    status=UserRequestAutomationStatus.CANCELLED,
                    note="Удалено пользователем",
                )
            else:
                # Жесткое удаление
                success = await AutomationRequestRepository.delete(
                    session=session,
                    request_id=request_id,
                    soft=False,
                )

            if not success:
                return {"success": False, "error": f"Заявка #{request_id} не найдена"}

            await session.commit()

            app_logger.info(f"✅ Request #{request_id} deleted (soft={soft})")

            return {
                "success": True,
                "message": f"Заявка #{request_id} {'отменена' if soft else 'удалена'}",
                "error": None,
            }

        except Exception as delete_error:
            app_logger.error(f"❌ Failed to delete request: {delete_error}", exc_info=True)
            await session.rollback()
            return {"success": False, "error": str(delete_error)}

    # ============ СТАТИСТИКА КОНВЕРТАЦИЙ ============

    @log_exceptions(app_logger)
    async def get_conversion_stats(self) -> dict[str, Any]:
        """
        Получение статистики конвертаций.

        Returns:
            dict: Статистика конвертаций
        """
        total = self._conversion_stats.get("total", 0)
        success = self._conversion_stats.get("success", 0)
        failed = self._conversion_stats.get("failed", 0)

        success_rate = (success / total * 100) if total > 0 else 0

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "success_rate": success_rate,
            "by_method": self._conversion_stats.get("by_method", {}),
            "platform": sys.platform,
            "pywin32_available": HAS_PYWIN32,
            "comtypes_available": HAS_COMTYPES,
            "libreoffice_available": HAS_LIBREOFFICE,
            "enabled": self._conversion_stats.get("enabled", True),
        }

    # ============ ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ============

    @staticmethod
    async def _send_request_notification(request: Any) -> None:
        """
        Отправка уведомления о новой заявке в Telegram.

        Уведомление отправляется в топик Jobs для централизованного
        отслеживания заявок на автоматизацию.

        Args:
            request: Модель заявки
        """
        try:
            # Получаем настройки для уведомлений
            chats = settings.automation_get_notification_chats
            topic_id = settings.automation_get_notification_topic

            if not chats:
                app_logger.warning("⚠️ No chats configured for automation notifications")
                return

            # Формируем сообщение
            priority_emoji = {
                UserRequestAutomationPriority.LOW: "🟢",
                UserRequestAutomationPriority.MEDIUM: "🟡",
                UserRequestAutomationPriority.HIGH: "🟠",
                UserRequestAutomationPriority.CRITICAL: "🔴",
            }.get(request.FPriority, "🟡")

            status_emoji = {
                UserRequestAutomationStatus.NEW: "🆕",
                UserRequestAutomationStatus.IN_PROGRESS: "🔄",
                UserRequestAutomationStatus.COMPLETED: "✅",
                UserRequestAutomationStatus.CANCELLED: "❌",
                UserRequestAutomationStatus.REJECTED: "⛔",
            }.get(request.FStatus, "📌")

            message = (
                f"📋 **Новая заявка на автоматизацию**\n\n"
                f"#{request.FID} {priority_emoji} **{request.FTitle}**\n\n"
                f"👤 **Пользователь:** {request.user.fullname if request.user else request.FK_User}\n"
                f"🆔 **User ID:** {request.FK_User}\n"
                f"📅 **Создана:** {request.FCreatedAt.strftime('%d.%m.%Y %H:%M')}\n"
                f"📊 **Приоритет:** {request.FPriority.value.upper()}\n\n"
                f"📝 **Описание:**\n{request.FDescription[:300]}{'...' if len(request.FDescription) > 300 else ''}\n\n"
                f"Статус: {status_emoji} {request.FStatus.value.upper()}"
            )

            # Отправляем в каждый чат из списка
            for chat_id in chats:
                send_kwargs = {
                    "chat_id": chat_id,
                    "text": message,
                    "message_type": MessageType.SYSTEM_ALERT,
                    "parse_mode": "Markdown",
                }

                # Добавляем топик, если он настроен и чат является основным
                if topic_id and chat_id == settings.SUPPORT_CHAT_ID:
                    send_kwargs["message_thread_id"] = topic_id
                    app_logger.info(f"📨 Sending automation notification to topic {topic_id} in chat {chat_id}")
                else:
                    app_logger.info(f"📨 Sending automation notification to chat {chat_id}")

                bot_manager = get_bot_manager()
                send_result = await bot_manager.send_message(**send_kwargs)

                if send_result.get("success"):
                    app_logger.info(f"✅ Request notification sent to chat {chat_id}")
                else:
                    app_logger.warning(f"⚠️ Failed to send notification to chat {chat_id}: {send_result.get('error')}")

        except Exception as notify_error:
            app_logger.error(f"❌ Failed to send notification: {notify_error}")

    @staticmethod
    def _format_request(request: Any) -> dict[str, Any]:
        """
        Форматирование заявки для вывода.

        Args:
            request: Модель заявки

        Returns:
            dict: Отформатированная заявка
        """
        return {
            "id": request.FID,
            "user_id": request.FK_User,
            "user_name": request.user.fullname if request.user else None,
            "title": request.FTitle,
            "description": request.FDescription,
            "priority": request.FPriority.value,
            "status": request.FStatus.value,
            "chat_id": request.FK_Chat,
            "note": request.FNote,
            "completed_at": request.FCompletedAt.isoformat() + "Z" if request.FCompletedAt else None,
            "completed_by": request.FCompletedBy,
            "created_at": request.FCreatedAt.isoformat() + "Z",
            "updated_at": request.FUpdatedAt.isoformat() + "Z",
        }

    # ============ СТАТУС И ЗДОРОВЬЕ ============

    async def get_status(self) -> dict[str, Any]:
        """Получение статуса сервиса"""
        return {
            "initialized": self._initialized,
            "temp_dir": str(self._temp_dir),
            "conversion_stats": self._conversion_stats,
            "platform": sys.platform,
            "pywin32_available": HAS_PYWIN32,
            "comtypes_available": HAS_COMTYPES,
            "libreoffice_available": HAS_LIBREOFFICE,
        }

    async def health_check(self) -> bool:
        """Проверка здоровья сервиса"""
        return self._initialized


automation_service = AutomationService()

__all__ = [
    "AutomationService",
    "automation_service",
]
