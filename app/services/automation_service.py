import asyncio
import contextlib
import sys
import tempfile
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings
from ..db import db_manager
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import MessageType, UserModel, datetime_now

# ============ ИМПОРТЫ ДЛЯ PYWIN32 ============

# Проверка, что мы на Windows
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    try:
        HAS_PYWIN32 = True
        app_logger.info("✅ pywin32 loaded successfully (Windows)")
    except ImportError as e:
        HAS_PYWIN32 = False
        app_logger.warning(f"⚠️ pywin32 not installed: {e}. Install: pip install pywin32")
else:
    HAS_PYWIN32 = False
    app_logger.warning("⚠️ Not running on Windows, pywin32 is not available")

# Для конвертации через LibreOffice (fallback для Linux/macOS)
try:
    import subprocess

    HAS_LIBREOFFICE = True
except ImportError:
    HAS_LIBREOFFICE = False

# Для конвертации через comtypes (альтернатива)
try:
    import comtypes.client

    HAS_COMTYPES = True
except ImportError:
    HAS_COMTYPES = False


class ConversionStats(TypedDict, total=False):
    """Тип для статистики конвертаций"""

    total: int
    success: int
    failed: int
    by_method: dict[str, int]
    enabled: bool
    max_entries: int


class AutomationService:
    """Сервис для автоматизации задач"""

    def __init__(self) -> None:
        self._initialized = False
        self._temp_dir = Path(tempfile.gettempdir()) / "teambot_automation"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

        # Хранилище заявок (в реальном проекте - БД)
        self._requests: list[dict[str, Any]] = []

        # Статистика конвертаций с явными типами
        self._conversion_stats: ConversionStats = {
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

    # ============ ОСНОВНОЙ МЕТОД КОНВЕРТАЦИИ ============

    @log_exceptions(app_logger)
    async def convert_doc_to_pdf(
        self, doc_content: bytes, filename: str = "document.docx", user_id: int | None = None, method: str | None = None
    ) -> dict[str, Any]:
        """
        Конвертация DOC/DOCX в PDF с использованием pywin32

        Args:
            doc_content: Содержимое документа в байтах
            filename: Имя файла
            user_id: ID пользователя (для логирования)
            method: Метод конвертации (auto, pywin32, comtypes, libreoffice)

        Returns:
            Dict с результатом
        """
        if method is None:
            method = settings.AUTOMATION_CONVERSION_METHOD

        # Безопасное обновление статистики
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
            # Сохранение временного DOC-файла
            with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False, dir=str(self._temp_dir)) as tmp_doc:
                tmp_doc.write(doc_content)
                temp_doc_path = Path(tmp_doc.name)

            app_logger.debug(f"📄 Temp DOC: {temp_doc_path} ({temp_doc_path.stat().st_size} bytes)")

            # Определение имени PDF-файла
            base_name = Path(filename).stem
            pdf_filename = f"{base_name}.pdf"

            # Создание временного PDF-файла
            temp_pdf_path = self._temp_dir / f"{base_name}_{datetime_now().strftime('%Y%m%d_%H%M%S')}.pdf"

            # Конвертация выбранным методом
            conversion_success = False
            error_message: str | None = None

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
            with open(temp_pdf_path, "rb") as f:
                pdf_content = f.read()

            file_size = len(pdf_content)

            self._conversion_stats["success"] = self._conversion_stats.get("success", 0) + 1

            # Безопасное обновление словаря by_method
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

        except Exception as e:
            self._conversion_stats["failed"] = self._conversion_stats.get("failed", 0) + 1
            app_logger.error(f"❌ DOC to PDF conversion failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Ошибка конвертации: {str(e)}",
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
        """
        Конвертация через pywin32 (использует Microsoft Word)
        Самый надежный метод на Windows
        """
        if not HAS_PYWIN32:
            return False, "pywin32 not available"

        try:
            # Импорт внутри функции
            import pythoncom
            import win32com.client

            # Инициализация COM в отдельном потоке
            def convert_in_thread() -> tuple[bool, str | None]:
                pythoncom.CoInitialize()

                try:
                    word = None

                    try:
                        # Создание экземпляра Word
                        word = win32com.client.Dispatch("Word.Application")
                        word.Visible = False
                        word.DisplayAlerts = False

                        # Открытие документа
                        doc = word.Documents.Open(doc_path)

                        # Сохранение как PDF
                        # 17 = wdFormatPDF
                        doc.SaveAs(pdf_path, FileFormat=17)

                        # Закрытие документа
                        doc.Close()

                        return True, None

                    except Exception as e:
                        return False, str(e)

                    finally:
                        # Закрытие Word
                        if word:
                            with contextlib.suppress(BaseException):
                                word.Quit()

                finally:
                    pythoncom.CoUninitialize()

            # Запуск в отдельном потоке (блокирующая операция)
            success, error = await asyncio.to_thread(convert_in_thread)

            if success:
                return True, None
            else:
                return False, f"pywin32 conversion failed: {error}"

        except Exception as e:
            return False, f"pywin32 error: {str(e)}"

    @staticmethod
    async def _convert_with_comtypes(doc_path: str, pdf_path: str) -> tuple[bool, str | None]:
        """
        Конвертация через comtypes (альтернатива pywin32)
        """
        if not HAS_COMTYPES:
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

                except Exception as e:
                    return False, str(e)

            success, error = await asyncio.to_thread(convert_in_thread)

            if success:
                return True, None
            else:
                return False, f"comtypes conversion failed: {error}"

        except Exception as e:
            return False, f"comtypes error: {str(e)}"

    @staticmethod
    async def _convert_with_libreoffice(doc_path: str, pdf_path: str) -> tuple[bool, str | None]:
        """
        Конвертация через LibreOffice (для Linux/macOS)
        Fallback, если pywin32 не доступен
        """
        try:
            # Проверка наличия LibreOffice
            result = subprocess.run(["which", "soffice"], capture_output=True, text=True)

            if result.returncode != 0:
                return False, "LibreOffice not found. Install: sudo apt-get install libreoffice"

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

        except Exception as e:
            return False, f"LibreOffice error: {str(e)}"

    @staticmethod
    async def _cleanup_temp_files(doc_path: Path | None, pdf_path: Path | None) -> None:
        """Очистка временных файлов"""
        for path in [doc_path, pdf_path]:
            if path and path.exists():
                try:
                    path.unlink()
                    app_logger.debug(f"🗑️ Deleted temp file: {path}")
                except Exception as e:
                    app_logger.warning(f"⚠️ Could not delete temp file {path}: {e}")

    # ============ ЗАЯВКИ НА АВТОМАТИЗАЦИЮ ============

    @log_exceptions(app_logger)
    async def create_automation_request(
        self,
        user_id: int,
        title: str,
        description: str,
        priority: str = "medium",
        chat_id: int | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Создание заявки на автоматизацию"""
        if session is None:
            async with db_manager.get_session() as sess:
                return await self.create_automation_request(user_id, title, description, priority, chat_id, sess)

        app_logger.info(f"📝 Creating automation request from user {user_id}: {title}")

        # Проверка пользователя
        stmt = select(UserModel).where(user_id == UserModel.FID)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            app_logger.warning(f"⚠️ User {user_id} not found")
            return {"success": False, "error": "Пользователь не найден", "request_id": None}

        # Формирование заявки
        request = {
            "id": len(self._requests) + 1,
            "user_id": user_id,
            "user_name": user.fullname or user.FUserName,
            "title": title,
            "description": description,
            "priority": priority,
            "chat_id": chat_id,
            "status": "new",
            "created_at": datetime_now().isoformat(),
            "updated_at": datetime_now().isoformat(),
        }

        # Сохранение в памяти (в реальном проекте - в БД)
        self._requests.append(request)

        # Отправка уведомления в чат поддержки
        if chat_id:
            await self._send_request_notification(request, chat_id)

        app_logger.info(f"✅ Automation request created: #{request['id']}")

        return {"success": True, "request_id": request["id"], "request": request, "error": None}

    @staticmethod
    async def _send_request_notification(request: dict[str, Any], chat_id: int) -> None:
        """Отправка уведомления о новой заявке в Telegram"""
        try:
            from ..tg import tg_manager

            priority_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(
                request["priority"], "🟡"
            )

            message = (
                f"📋 **Новая заявка на автоматизацию**\n\n"
                f"#{request['id']} {priority_emoji} **{request['title']}**\n\n"
                f"👤 **Пользователь:** {request['user_name']}\n"
                f"🆔 **User ID:** {request['user_id']}\n"
                f"📅 **Создана:** {request['created_at']}\n"
                f"📊 **Приоритет:** {request['priority'].upper()}\n\n"
                f"📝 **Описание:**\n{request['description']}\n\n"
                f"Статус: 🆕 Новая"
            )

            result = await tg_manager.send_message(
                chat_id=chat_id, message_type=MessageType.BOT_RESPONSE, text=message, parse_mode="Markdown"
            )

            if result.get("success"):
                app_logger.info(f"✅ Request notification sent to chat {chat_id}")
            else:
                app_logger.warning(f"⚠️ Failed to send notification: {result.get('error')}")

        except Exception as e:
            app_logger.error(f"❌ Failed to send notification: {e}")

    @log_exceptions(app_logger)
    async def get_requests(self, user_id: int | None = None, status: str | None = None) -> list[dict[str, Any]]:
        """Получение списка заявок"""
        requests = self._requests

        if user_id:
            requests = [r for r in requests if r["user_id"] == user_id]

        if status:
            requests = [r for r in requests if r["status"] == status]

        return requests

    @log_exceptions(app_logger)
    async def update_request_status(self, request_id: int, status: str, note: str | None = None) -> dict[str, Any]:
        """Обновление статуса заявки"""
        for request in self._requests:
            if request["id"] == request_id:
                request["status"] = status
                request["updated_at"] = datetime_now().isoformat()
                if note:
                    request["note"] = note

                app_logger.info(f"✅ Request #{request_id} status updated to {status}")
                return {"success": True, "request": request, "error": None}

        return {"success": False, "error": f"Заявка #{request_id} не найдена", "request": None}

    @log_exceptions(app_logger)
    async def get_conversion_stats(self) -> dict[str, Any]:
        """Получение статистики конвертаций"""
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
        }


automation_service = AutomationService()
