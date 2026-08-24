"""
Сервис автоматизации задач.

Назначение:
    Предоставляет комплексные функции для автоматизации рабочих процессов,
    включая конвертацию документов, управление заявками и сбор статистики.

Основные функции:
    1. Конвертация документов DOC/DOCX в PDF с использованием различных методов
    2. Создание и управление заявками на автоматизацию
    3. Отправка уведомлений о новых заявках
    4. Сбор статистики конвертаций
    5. Управление временными файлами

Технические особенности:
    - Поддержка трёх методов конвертации: pywin32, comtypes, LibreOffice
    - Адаптивный выбор метода в зависимости от платформы
    - Автоматическая очистка временных файлов
    - Интеграция с базой данных через SQLAlchemy
    - Асинхронная архитектура

Зависимости:
    - pywin32 (Windows): для работы с Microsoft Word
    - comtypes (Windows): альтернативный COM-клиент
    - LibreOffice (Linux/macOS): кроссплатформенная конвертация
"""

import asyncio
import contextlib
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..bot.dependencies import get_bot_manager
from ..config import settings
from ..db import AutomationRequestRepository, UserRepository, db_manager
from ..logger import app_logger
from ..models import (
    MessageType,
    UserRequestAutomationPriority,
    UserRequestAutomationStatus,
    datetime_now,
)
from ..utils.decorators import log_exceptions

# ============================================================
# 1. ПРОВЕРКА ПЛАТФОРМЫ И ДОСТУПНОСТИ БИБЛИОТЕК
# ============================================================

# Определение операционной системы
IS_WINDOWS = sys.platform == "win32"


def _check_pywin32() -> tuple[bool, Any, Any]:
    """
    Проверяет доступность библиотеки pywin32 для Windows.

    Returns:
        tuple[bool, Any, Any]: (доступность, модуль pythoncom, модуль win32com)
    """
    if not IS_WINDOWS:
        app_logger.warning("⚠️ Not running on Windows, pywin32 is not available")
        return False, None, None

    try:
        import pythoncom
        import win32com.client

        app_logger.info("✅ pywin32 loaded successfully (Windows)")
        return True, pythoncom, win32com.client
    except ImportError as import_error:
        app_logger.warning(f"⚠️ pywin32 not installed: {import_error}. Install: pip install pywin32")
        return False, None, None


def _check_comtypes() -> tuple[bool, Any]:
    """
    Проверяет доступность библиотеки comtypes для Windows.

    Returns:
        tuple[bool, Any]: (доступность, модуль comtypes.client)
    """
    if not IS_WINDOWS:
        app_logger.warning("⚠️ Not running on Windows, comtypes is not available")
        return False, None

    try:
        import comtypes.client

        app_logger.info("✅ comtypes loaded successfully (Windows)")
        return True, comtypes.client
    except ImportError as import_error:
        app_logger.warning(f"⚠️ comtypes not installed: {import_error}. Install: pip install comtypes")
        return False, None


def _check_libreoffice() -> tuple[bool, Any]:
    """
    Проверяет доступность LibreOffice в системе.

    Returns:
        tuple[bool, Any]: (доступность, модуль subprocess)
    """
    try:
        import subprocess

        # Проверка наличия исполняемого файла soffice
        check_result = subprocess.run(["which", "soffice"], capture_output=True, text=True)
        if check_result.returncode == 0:
            app_logger.info("✅ LibreOffice found")
            return True, subprocess
        else:
            app_logger.warning("⚠️ LibreOffice not found. Install: sudo apt-get install libreoffice")
            return False, None
    except ImportError:
        app_logger.warning("⚠️ subprocess module not available")
        return False, None
    except Exception as check_error:
        app_logger.warning(f"⚠️ LibreOffice check failed: {check_error}")
        return False, None


# Выполнение проверок
HAS_PYWIN32, pythoncom, win32com = _check_pywin32()
HAS_COMTYPES, comtypes_client = _check_comtypes()
HAS_LIBREOFFICE, subprocess_module = _check_libreoffice()
HAS_SUBPROCESS = subprocess_module is not None


# ============================================================
# 2. РЕПОЗИТОРИИ (СИНГЛТОНЫ)
# ============================================================

# Репозитории создаются один раз на уровне модуля для переиспользования
_request_repo = AutomationRequestRepository()  # Репозиторий для заявок
_user_repo = UserRepository()  # Репозиторий для пользователей


# ============================================================
# 3. ОСНОВНОЙ КЛАСС СЕРВИСА
# ============================================================


class AutomationService:
    """
    Сервис для автоматизации задач.

    Предоставляет методы для:
    - Конвертации документов DOC/DOCX в PDF
    - Создания и управления заявками на автоматизацию
    - Сбора статистики
    - Управления временными файлами

    Attributes:
        _initialized (bool): Флаг инициализации сервиса
        _temp_dir (Path): Путь к временной директории
        _conversion_stats (dict): Статистика конвертаций
    """

    def __init__(self) -> None:
        """Инициализация сервиса автоматизации.

        Создаёт временную директорию и инициализирует структуру статистики.
        """
        self._initialized: bool = False
        self._temp_dir: Path = Path(tempfile.gettempdir()) / "teambot_automation"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

        # Статистика конвертаций
        self._conversion_stats: dict[str, Any] = {
            "total": 0,  # Всего конвертаций
            "success": 0,  # Успешных конвертаций
            "failed": 0,  # Неудачных конвертаций
            "by_method": {},  # Статистика по методам
            "enabled": getattr(settings, "AUTOMATION_STATS_ENABLED", True),
            "max_entries": getattr(settings, "AUTOMATION_STATS_MAX_ENTRIES", 1000),
        }

    # ============================================================
    # 3.1. ИНИЦИАЛИЗАЦИЯ
    # ============================================================

    @property
    def is_initialized(self) -> bool:
        """Проверяет, инициализирован ли сервис."""
        return self._initialized

    async def initialize(self) -> None:
        """Инициализация сервиса.

        Проверяет доступность всех методов конвертации и выводит
        информацию о состоянии платформы и библиотек.
        """
        if self._initialized:
            return

        self._initialized = True

        # Вывод информации о состоянии
        app_logger.info("✅ AutomationService initialized")
        app_logger.info(f"📁 Temp directory: {self._temp_dir}")
        app_logger.info(f"🖥️ Platform: {sys.platform}")
        app_logger.info(f"📦 pywin32 available: {HAS_PYWIN32}")
        app_logger.info(f"📦 comtypes available: {HAS_COMTYPES}")
        app_logger.info(f"📦 LibreOffice available: {HAS_LIBREOFFICE}")

    # ============================================================
    # 3.2. КОНВЕРТАЦИЯ ДОКУМЕНТОВ
    # ============================================================

    @log_exceptions(app_logger)
    async def convert_doc_to_pdf(
        self,
        doc_content: bytes | Any,
        filename: str = "document.docx",
        user_id: int | None = None,
        method: str | None = None,
    ) -> dict[str, Any]:
        """
        Конвертация DOC/DOCX в PDF.

        Поддерживает три метода конвертации:
        1. pywin32 (Windows, использует Microsoft Word)
        2. comtypes (Windows, альтернатива pywin32)
        3. LibreOffice (Linux/macOS, кроссплатформенный)

        Args:
            doc_content: Содержимое документа (bytes или BytesIO)
            filename: Имя исходного файла
            user_id: ID пользователя (для логирования)
            method: Метод конвертации (auto, pywin32, comtypes, libreoffice)

        Returns:
            dict[str, Any]: Результат конвертации с полями:
                - success: bool
                - pdf_content: bytes | None
                - pdf_filename: str | None
                - file_size: int | None
                - conversion_method: str | None
                - error: str | None
        """
        if method is None:
            method = settings.AUTOMATION_CONVERSION_METHOD

        # Обновление статистики
        self._conversion_stats["total"] = self._conversion_stats.get("total", 0) + 1

        app_logger.info(f"🔄 Converting DOC to PDF: {filename} (user={user_id}, method={method})")

        # Проверка расширения файла
        file_ext = Path(filename).suffix.lower()
        if file_ext not in [".doc", ".docx"]:
            return {
                "success": False,
                "error": f"Неподдерживаемый формат: {file_ext}. Разрешены: .doc, .docx",
                "pdf_content": None,
                "pdf_filename": None,
                "file_size": None,
            }

        # Автоматический выбор метода
        if method == "auto":
            method = self._select_conversion_method()
            if method is None:
                return {
                    "success": False,
                    "error": "Нет доступных методов конвертации. Установите pywin32 (Windows) или LibreOffice (Linux/macOS)",
                    "pdf_content": None,
                    "pdf_filename": None,
                    "file_size": None,
                }

        app_logger.debug(f"🔄 Using conversion method: {method}")

        # Подготовка временных файлов
        temp_doc_path: Path | None = None
        temp_pdf_path: Path | None = None

        try:
            # Чтение содержимого документа
            content_bytes = self._prepare_content_bytes(doc_content)
            if content_bytes is None:
                return {
                    "success": False,
                    "error": "Документ пуст",
                    "pdf_content": None,
                    "pdf_filename": None,
                    "file_size": None,
                }

            # Сохранение временного DOC-файла
            temp_doc_path = self._save_temp_file(content_bytes, filename)
            app_logger.debug(f"📄 Temp DOC: {temp_doc_path} ({temp_doc_path.stat().st_size} bytes)")

            # Подготовка пути для PDF
            pdf_filename = f"{Path(filename).stem}.pdf"
            temp_pdf_path = self._prepare_pdf_path(filename)

            # Выполнение конвертации
            conversion_success, error_message = await self._convert_by_method(
                method, str(temp_doc_path), str(temp_pdf_path)
            )

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

            # Чтение результата
            pdf_content = self._read_pdf_file(temp_pdf_path)
            file_size = len(pdf_content)

            # Обновление статистики успеха
            self._conversion_stats["success"] = self._conversion_stats.get("success", 0) + 1
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

    # ============================================================
    # 3.2.1. Вспомогательные методы конвертации
    # ============================================================

    @staticmethod
    def _select_conversion_method() -> str | None:
        """
        Автоматически выбирает доступный метод конвертации.

        Returns:
            str | None: Название метода или None, если методы недоступны
        """
        if HAS_PYWIN32 and IS_WINDOWS:
            return "pywin32"
        elif HAS_COMTYPES and IS_WINDOWS:
            return "comtypes"
        elif HAS_LIBREOFFICE:
            return "libreoffice"
        return None

    @staticmethod
    def _prepare_content_bytes(doc_content: Any) -> bytes | None:
        """
        Преобразует входные данные в байтовый формат.

        Args:
            doc_content: Содержимое документа (bytes, BytesIO или другой объект)

        Returns:
            bytes | None: Содержимое в виде байтов или None при ошибке
        """
        if hasattr(doc_content, "read"):
            # Это BytesIO или подобный объект
            content_bytes = doc_content.read()
        elif isinstance(doc_content, bytes):
            content_bytes = doc_content
        else:
            # Преобразование в bytes
            content_bytes = bytes(doc_content)

        if not content_bytes:
            return None
        return content_bytes  # type: ignore[no-any-return]

    def _save_temp_file(self, content_bytes: bytes, filename: str) -> Path:
        """
        Сохраняет содержимое во временный файл.

        Args:
            content_bytes: Содержимое файла в байтах
            filename: Исходное имя файла

        Returns:
            Path: Путь к созданному временному файлу
        """
        file_ext = Path(filename).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False, dir=str(self._temp_dir)) as tmp_doc:
            tmp_doc.write(content_bytes)
            return Path(tmp_doc.name)

    def _prepare_pdf_path(self, filename: str) -> Path:
        """
        Создаёт путь для PDF-файла с временной меткой.

        Args:
            filename: Исходное имя файла

        Returns:
            Path: Путь для сохранения PDF
        """
        base_name = Path(filename).stem
        timestamp = datetime_now().strftime("%Y%m%d_%H%M%S")
        return self._temp_dir / f"{base_name}_{timestamp}.pdf"

    @staticmethod
    def _read_pdf_file(pdf_path: Path) -> bytes:
        """
        Читает содержимое PDF-файла.

        Args:
            pdf_path: Путь к PDF-файлу

        Returns:
            bytes: Содержимое файла
        """
        with open(pdf_path, "rb") as pdf_file:
            return pdf_file.read()

    async def _convert_by_method(self, method: str, doc_path: str, pdf_path: str) -> tuple[bool, str | None]:
        """
        Выполняет конвертацию выбранным методом.

        Args:
            method: Название метода конвертации
            doc_path: Путь к исходному DOC-файлу
            pdf_path: Путь для сохранения PDF

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
        if method == "pywin32" and HAS_PYWIN32:
            return await self._convert_with_pywin32(doc_path, pdf_path)
        elif method == "comtypes" and HAS_COMTYPES:
            return await self._convert_with_comtypes(doc_path, pdf_path)
        elif method == "libreoffice" and HAS_LIBREOFFICE:
            return await self._convert_with_libreoffice(doc_path, pdf_path)
        else:
            return False, f"Метод {method} не доступен"

    @staticmethod
    async def _convert_with_pywin32(doc_path: str, pdf_path: str) -> tuple[bool, str | None]:
        """
        Конвертация через pywin32 (использует Microsoft Word).

        Доступен только на Windows. Использует COM-объект Word.Application
        для открытия документа и сохранения в PDF.

        Args:
            doc_path: Путь к DOC/DOCX файлу
            pdf_path: Путь для сохранения PDF

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
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
                    word = win32com.Dispatch("Word.Application")
                    word.Visible = False
                    word.DisplayAlerts = False

                    # Открытие документа
                    doc = word.Documents.Open(doc_path)

                    # Сохранение как PDF (17 = wdFormatPDF)
                    doc.SaveAs(pdf_path, FileFormat=17)

                    # Закрытие документа
                    doc.Close()

                    return True, None

                except Exception as pywin32_err:
                    return False, str(pywin32_err)

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
        """
        Конвертация через comtypes (альтернатива pywin32).

        Доступен только на Windows. Использует COM-объект Word.Application
        через библиотеку comtypes.

        Args:
            doc_path: Путь к DOC/DOCX файлу
            pdf_path: Путь для сохранения PDF

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
        if not HAS_COMTYPES or comtypes_client is None:
            return False, "comtypes not available"

        try:

            def convert_in_thread() -> tuple[bool, str | None]:
                try:
                    # Создание экземпляра Word
                    word = comtypes_client.CreateObject("Word.Application")
                    word.Visible = False

                    # Открытие документа
                    doc = word.Documents.Open(doc_path)

                    # Сохранение как PDF
                    doc.SaveAs(pdf_path, FileFormat=17)  # wdFormatPDF

                    # Закрытие
                    doc.Close()
                    word.Quit()

                    return True, None

                except Exception as comtypes_err:
                    return False, str(comtypes_err)

            success, error = await asyncio.to_thread(convert_in_thread)

            if success:
                return True, None
            else:
                return False, error or "comtypes conversion failed"

        except Exception as comtypes_error:
            return False, f"comtypes error: {str(comtypes_error)}"

    @staticmethod
    async def _convert_with_libreoffice(doc_path: str, pdf_path: str) -> tuple[bool, str | None]:
        """
        Конвертация через LibreOffice (для Linux/macOS).

        Использует утилиту командной строки soffice для конвертации
        документа в PDF без графического интерфейса (headless mode).

        Args:
            doc_path: Путь к DOC/DOCX файлу
            pdf_path: Путь для сохранения PDF

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
        if not HAS_LIBREOFFICE or subprocess_module is None:
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
        """
        Очистка временных файлов.

        Удаляет временные DOC и PDF файлы после завершения конвертации.

        Args:
            doc_path: Путь к временному DOC файлу
            pdf_path: Путь к временному PDF файлу
        """
        for path in [doc_path, pdf_path]:
            if path and path.exists():
                try:
                    path.unlink()
                    app_logger.debug(f"🗑️ Deleted temp file: {path}")
                except Exception as cleanup_error:
                    app_logger.warning(f"⚠️ Could not delete temp file {path}: {cleanup_error}")

    # ============================================================
    # 3.3. УПРАВЛЕНИЕ ЗАЯВКАМИ
    # ============================================================

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
            dict[str, Any]: Результат операции с полями:
                - success: bool
                - request_id: int | None
                - request: dict | None
                - error: str | None
        """
        app_logger.info(f"📝 Creating automation request from user {user_id}: {title}")

        # Проверка пользователя через репозиторий
        user = await _user_repo.get_user_by_id(session, user_id)
        if not user:
            app_logger.warning(f"⚠️ User {user_id} not found")
            return {"success": False, "error": "Пользователь не найден", "request_id": None}

        # Преобразование приоритета
        priority_enum = self._parse_priority(priority)
        if priority_enum is None:
            return {"success": False, "error": f"Неверный приоритет: {priority}", "request_id": None}

        try:
            # Сохранение в БД через репозиторий
            request = await _request_repo.create(
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
            list[dict[str, Any]]: Список отформатированных заявок
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.get_requests(  # type: ignore[no-any-return]
                    user_id=user_id,
                    status=status,
                    priority=priority,
                    limit=limit,
                    offset=offset,
                    session=new_session,
                )

        # Преобразование статуса и приоритета
        status_enum = self._parse_status(status) if status else None
        priority_enum = self._parse_priority(priority) if priority else None

        # Получение заявок через репозиторий
        requests = await _request_repo.get_all(
            session=session,
            status=status_enum,
            priority=priority_enum,
            user_id=user_id,
            limit=limit,
            offset=offset,
            load_user=True,
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
            dict[str, Any] | None: Отформатированная заявка или None
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.get_request_by_id(request_id, new_session)  # type: ignore[no-any-return]

        request = await _request_repo.get_by_id(session, request_id)
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
            dict[str, Any]: Результат операции с полями:
                - success: bool
                - request: dict | None
                - error: str | None
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.update_request_status(  # type: ignore[no-any-return]
                    request_id=request_id,
                    status=status,
                    note=note,
                    completed_by=completed_by,
                    session=new_session,
                )

        # Преобразование статуса
        status_enum = self._parse_status(status)
        if status_enum is None:
            return {"success": False, "error": f"Неверный статус: {status}"}

        try:
            # Обновление статуса через репозиторий
            success, request = await _request_repo.update_status(
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

            # Получаем обновленную заявку
            updated_request = await _request_repo.get_by_id(session, request_id)

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
            dict[str, Any]: Результат операции с полями:
                - success: bool
                - request: dict | None
                - error: str | None
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.update_request_priority(  # type: ignore[no-any-return]
                    request_id=request_id,
                    priority=priority,
                    session=new_session,
                )

        # Преобразование приоритета
        priority_enum = self._parse_priority(priority)
        if priority_enum is None:
            return {"success": False, "error": f"Неверный приоритет: {priority}"}

        try:
            # Обновление приоритета через репозиторий
            success, request = await _request_repo.update_priority(
                session=session,
                request_id=request_id,
                priority=priority_enum,
            )

            if not success:
                return {"success": False, "error": f"Заявка #{request_id} не найдена"}

            await session.commit()

            app_logger.info(f"✅ Request #{request_id} priority updated to {priority}")

            # Получаем обновленную заявку
            updated_request = await _request_repo.get_by_id(session, request_id)

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
            dict[str, Any]: Результат операции с полями:
                - success: bool
                - message: str | None
                - error: str | None
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.delete_request(  # type: ignore[no-any-return]
                    request_id=request_id,
                    soft=soft,
                    session=new_session,
                )

        try:
            if soft:
                # Мягкое удаление - меняем статус
                success, _ = await _request_repo.update_status(
                    session=session,
                    request_id=request_id,
                    status=UserRequestAutomationStatus.CANCELLED,
                    note="Удалено пользователем",
                )
            else:
                # Жесткое удаление
                success = await _request_repo.delete(
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

    # ============================================================
    # 3.4. СТАТИСТИКА
    # ============================================================

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
            dict[str, Any]: Статистика по заявкам
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self.get_stats(  # type: ignore[no-any-return]
                    user_id=user_id,
                    start_date=start_date,
                    end_date=end_date,
                    session=new_session,
                )

        # Парсинг дат
        start_dt = self._parse_date(start_date) if start_date else None
        end_dt = self._parse_date(end_date) if end_date else None

        # Получение статистики через репозиторий
        return await _request_repo.get_stats(  # type: ignore[no-any-return]
            session=session,
            user_id=user_id,
            start_date=start_dt,
            end_date=end_dt,
        )

    @log_exceptions(app_logger)
    async def get_conversion_stats(self) -> dict[str, Any]:
        """
        Получение статистики конвертаций.

        Returns:
            dict[str, Any]: Статистика конвертаций с полями:
                - total: int
                - success: int
                - failed: int
                - success_rate: float
                - by_method: dict
                - platform: str
                - pywin32_available: bool
                - comtypes_available: bool
                - libreoffice_available: bool
                - enabled: bool
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

    # ============================================================
    # 3.5. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================

    @staticmethod
    def _parse_priority(priority: str) -> UserRequestAutomationPriority | None:
        """
        Преобразует строковое значение приоритета в Enum.

        Args:
            priority: Строковое значение приоритета

        Returns:
            UserRequestAutomationPriority | None: Enum приоритета или None
        """
        priority_map = {
            "low": UserRequestAutomationPriority.LOW,
            "medium": UserRequestAutomationPriority.MEDIUM,
            "high": UserRequestAutomationPriority.HIGH,
            "critical": UserRequestAutomationPriority.CRITICAL,
        }
        return priority_map.get(priority.lower())

    @staticmethod
    def _parse_status(status: str) -> UserRequestAutomationStatus | None:
        """
        Преобразует строковое значение статуса в Enum.

        Args:
            status: Строковое значение статуса

        Returns:
            UserRequestAutomationStatus | None: Enum статуса или None
        """
        try:
            return UserRequestAutomationStatus(status)
        except ValueError:
            return None

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """
        Преобразует строку даты в объект datetime.

        Args:
            date_str: Строка даты в ISO формате

        Returns:
            datetime | None: Объект datetime или None при ошибке
        """
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            app_logger.warning(f"⚠️ Invalid date format: {date_str}")
            return None

    @staticmethod
    def _format_request(request: Any) -> dict[str, Any]:
        """
        Форматирование заявки для вывода.

        Args:
            request: Модель заявки

        Returns:
            dict[str, Any]: Отформатированная заявка
        """
        return {
            "id": request.FID,
            "user_id": request.fk_user,
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
            message = AutomationService._build_notification_message(request)

            # Отправляем в каждый чат из списка
            for chat_id in chats:
                send_kwargs = {
                    "chat_id": chat_id,
                    "text": message,
                    "message_type": MessageType.SYSTEM_ALERT,
                    "parse_mode": "Markdown",
                }

                # Добавление топика, если он настроен и чат является основным
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
    def _build_notification_message(request: Any) -> str:
        """
        Создаёт текст уведомления о новой заявке.

        Args:
            request: Модель заявки

        Returns:
            str: Текст уведомления в формате Markdown
        """
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

        description = request.FDescription[:300]
        if len(request.FDescription) > 300:
            description += "..."

        return (
            f"📋 **Новая заявка на автоматизацию**\n\n"
            f"#{request.FID} {priority_emoji} **{request.FTitle}**\n\n"
            f"👤 **Пользователь:** {request.user.fullname if request.user else request.fk_user}\n"
            f"🆔 **User ID:** {request.fk_user}\n"
            f"📅 **Создана:** {request.FCreatedAt.strftime('%d.%m.%Y %H:%M')}\n"
            f"📊 **Приоритет:** {request.FPriority.value.upper()}\n\n"
            f"📝 **Описание:**\n{description}\n\n"
            f"Статус: {status_emoji} {request.FStatus.value.upper()}"
        )

    # ============================================================
    # 3.6. СТАТУС И ЗДОРОВЬЕ
    # ============================================================

    async def get_status(self) -> dict[str, Any]:
        """
        Получение статуса сервиса.

        Returns:
            dict[str, Any]: Статус сервиса с полями:
                - initialized: bool
                - temp_dir: str
                - conversion_stats: dict
                - platform: str
                - pywin32_available: bool
                - comtypes_available: bool
                - libreoffice_available: bool
        """
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
        """
        Проверка здоровья сервиса.

        Returns:
            bool: True если сервис инициализирован
        """
        return self._initialized


automation_service = AutomationService()

__all__ = [
    "AutomationService",
    "automation_service",
]
