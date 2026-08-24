"""
Модуль с тестами для роутера автоматизации (AutomationRouter).

Содержит набор тестов для проверки HTTP-эндпоинтов, связанных с автоматизацией:
- конвертация документов в PDF (проверка форматов и пустых файлов);
- создание заявок на автоматизацию (валидация приоритета, проверка пользователя);
- получение списка заявок;
- обновление статуса заявки.

Тесты используют TestClient для имитации HTTP-запросов и проверки ответов,
а также моки для изоляции от внешних зависимостей (репозитории, сервисы).
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


class TestAutomationRouter:
    """
    Набор тестов для роутера автоматизации.

    Проверяет эндпоинты:
    - POST /api/v1/automation/convert/doc-to-pdf — конвертация документа в PDF;
    - POST /api/v1/automation/request — создание заявки на автоматизацию;
    - GET /api/v1/automation/requests — получение списка заявок;
    - PATCH /api/v1/automation/requests/{request_id}/status — обновление статуса заявки.
    """

    @pytest.fixture
    def api_client(self, api_client):
        """Возвращает клиент API с уже настроенными моками (если необходимо)."""
        return api_client

    def test_convert_doc_to_pdf_unsupported_file(self, api_client: TestClient):
        """
        Проверяет попытку конвертации неподдерживаемого формата файла.

        При загрузке .txt файла должен возвращаться код 400 с сообщением
        о неподдерживаемом формате.
        """
        files = {"file": ("test.txt", b"content", "text/plain")}
        response = api_client.post("/api/v1/automation/convert/doc-to-pdf", files=files)
        assert response.status_code == 400
        assert "Неподдерживаемый формат" in response.json()["detail"]

    def test_convert_doc_to_pdf_empty_file(self, api_client: TestClient):
        """
        Проверяет попытку конвертации пустого файла.

        При загрузке пустого .docx файла должен возвращаться код 400
        с сообщением о том, что файл пуст.
        """
        files = {"file": ("test.docx", b"", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        response = api_client.post("/api/v1/automation/convert/doc-to-pdf", files=files)
        assert response.status_code == 400
        assert "Файл пуст" in response.json()["detail"]

    def test_create_automation_request_invalid_priority(self, api_client: TestClient):
        """
        Проверяет создание заявки с неверным значением приоритета.

        При передаче приоритета "invalid" должен возвращаться код 400
        с сообщением о неверном приоритете.
        """
        data = {
            "user_id": 123,
            "title": "Test Request",
            "description": "Test description",
            "priority": "invalid",
        }
        response = api_client.post("/api/v1/automation/request", json=data)
        assert response.status_code == 400
        assert "Неверный приоритет" in response.json()["detail"]

    @patch("app.api.routers.automation._user_repo")
    def test_create_automation_request_user_not_found(self, mock_user_repo, api_client: TestClient):
        """
        Проверяет создание заявки для несуществующего пользователя.

        Мокается репозиторий пользователей, возвращающий None.
        Ожидается код 404 с сообщением о том, что пользователь не найден.
        """
        mock_user_repo.get_user_by_id = AsyncMock(return_value=None)

        data = {
            "user_id": 999,
            "title": "Test Request",
            "description": "Test description",
            "priority": "medium",
        }
        response = api_client.post("/api/v1/automation/request", json=data)
        assert response.status_code == 404
        assert "Пользователь с ID 999 не найден" in response.json()["error"]

    def test_get_automation_requests(self, api_client: TestClient):
        """
        Проверяет получение списка заявок на автоматизацию.

        Мокается сервис автоматизации, возвращающий пустой список.
        Ожидается код 200 с полями success, requests и count.
        """
        with patch("app.api.routers.automation.automation_service") as mock_service:
            mock_service.get_requests = AsyncMock(return_value=[])

            response = api_client.get("/api/v1/automation/requests")
            assert response.status_code == 200
            data = response.json()
            assert "success" in data
            assert "requests" in data
            assert "count" in data

    def test_update_request_status_invalid_status(self, api_client: TestClient):
        """
        Проверяет обновление статуса заявки с неверным значением.

        При передаче статуса "invalid" должен возвращаться код 400
        с сообщением о неверном статусе.
        """
        response = api_client.patch("/api/v1/automation/requests/1/status?status=invalid")
        assert response.status_code == 400
        assert "Неверный статус" in response.json()["detail"]
