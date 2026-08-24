"""
Модуль с тестами для сервиса автоматизации (AutomationService).

Содержит набор асинхронных тестов, проверяющих логику работы с конвертацией документов:
- инициализация сервиса;
- проверка конвертации неподдерживаемых форматов;
- обработка пустого содержимого;
- поведение при отсутствии доступных методов конвертации;
- получение статистики конвертаций;
- получение статуса сервиса;
- проверка здоровья сервиса.

Тесты используют моки для эмуляции наличия/отсутствия внешних библиотек (pywin32, comtypes, LibreOffice).
"""

from unittest.mock import patch

import pytest

from app.services.automation_service import AutomationService


class TestAutomationService:
    """
    Набор тестов для проверки корректности работы AutomationService.

    Тестируются основные функции сервиса автоматизации:
    - инициализация и управление состоянием;
    - конвертация документов в PDF с проверкой форматов и содержимого;
    - сбор статистики по операциям конвертации;
    - предоставление статуса и проверка здоровья.
    """

    @pytest.fixture
    def service(self):
        """Создаёт экземпляр сервиса автоматизации для каждого теста."""
        return AutomationService()

    @pytest.mark.asyncio
    async def test_initialize(self, service):
        """
        Проверяет инициализацию сервиса.

        До вызова initialize() флаг is_initialized должен быть False,
        после — True.
        """
        assert service.is_initialized is False
        await service.initialize()
        assert service.is_initialized is True

    @pytest.mark.asyncio
    async def test_convert_doc_to_pdf_unsupported_format(self, service):
        """
        Проверяет конвертацию документа неподдерживаемого формата.

        При попытке конвертировать .txt файл должен возвращаться результат
        с success=False и сообщением об ошибке о неподдерживаемом формате.
        """
        result = await service.convert_doc_to_pdf(
            doc_content=b"test",
            filename="test.txt",
        )
        assert result["success"] is False
        assert "Неподдерживаемый формат" in result["error"]

    @pytest.mark.asyncio
    async def test_convert_doc_to_pdf_empty_content(self, service):
        """
        Проверяет конвертацию пустого документа.

        При передаче пустого содержимого (b"") должен возвращаться результат
        с success=False и сообщением о том, что документ пуст.
        """
        result = await service.convert_doc_to_pdf(
            doc_content=b"",
            filename="test.docx",
        )
        assert result["success"] is False
        assert "Документ пуст" in result["error"]

    @pytest.mark.asyncio
    async def test_convert_doc_to_pdf_method_not_available(self, service):
        """
        Проверяет поведение при отсутствии доступных методов конвертации.

        Мокаются флаги доступности всех методов (pywin32, comtypes, LibreOffice)
        в значение False. Ожидается, что при вызове convert_doc_to_pdf
        будет возвращена ошибка о недоступности методов конвертации.
        """
        with (
            patch("app.services.automation_service.HAS_PYWIN32", False),
            patch("app.services.automation_service.HAS_COMTYPES", False),
            patch("app.services.automation_service.HAS_LIBREOFFICE", False),
        ):
            result = await service.convert_doc_to_pdf(
                doc_content=b"test content",
                filename="test.docx",
                method="auto",
            )
            assert result["success"] is False
            assert "Нет доступных методов конвертации" in result["error"]

    @pytest.mark.asyncio
    async def test_get_conversion_stats(self, service):
        """
        Проверяет получение статистики конвертаций.

        После инициализации сервиса метод должен возвращать словарь
        со всеми ключами: total, success, failed, success_rate, by_method,
        platform, pywin32_available, libreoffice_available.
        """
        await service.initialize()
        stats = await service.get_conversion_stats()
        assert "total" in stats
        assert "success" in stats
        assert "failed" in stats
        assert "success_rate" in stats
        assert "by_method" in stats
        assert "platform" in stats
        assert "pywin32_available" in stats
        assert "libreoffice_available" in stats

    @pytest.mark.asyncio
    async def test_get_status(self, service):
        """
        Проверяет получение статуса сервиса.

        После инициализации возвращаемый словарь должен содержать
        флаг initialized=True, а также информацию о временной директории
        и статистике конвертаций.
        """
        await service.initialize()
        status = await service.get_status()
        assert status["initialized"] is True
        assert "temp_dir" in status
        assert "conversion_stats" in status

    @pytest.mark.asyncio
    async def test_health_check(self, service):
        """
        Проверяет проверку здоровья сервиса.

        До инициализации должно возвращать False, после — True.
        """
        assert await service.health_check() is False
        await service.initialize()
        assert await service.health_check() is True
