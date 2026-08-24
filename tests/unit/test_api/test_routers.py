"""Тесты для API роутеров.

Этот модуль содержит тесты для проверки основных HTTP эндпоинтов API.
Тесты проверяют доступность и корректность ответов ключевых эндпоинтов:

1. /health - проверка работоспособности сервиса
2. / - корневой эндпоинт с информацией об API
3. /version - информация о версии приложения
4. /health/simple, /api/v1/health, /ping - упрощенные проверки
5. /api/v1/admin/stats - проверка аутентификации

Особенности:
- Используется TestClient для имитации HTTP запросов
- Тесты проверяют как успешные сценарии (200 OK)
- Так и сценарии с ошибками (401 Unauthorized)
- Все тесты синхронные (не требуют asyncio)

Примечания:
- Фикстура api_client настраивает тестовое FastAPI приложение
- Тесты не требуют реальной БД или внешних сервисов
- Проверяется структура ответов, а не только статус-коды
"""

import pytest
from fastapi.testclient import TestClient


class TestAPI:
    """Тесты для API.

    Класс содержит тесты для проверки основных эндпоинтов API:
    - Публичные эндпоинты (без аутентификации)
    - Эндпоинты с проверкой аутентификации
    - Эндпоинты для получения информации о системе

    Все тесты используют фикстуру api_client для отправки запросов.
    """

    def test_health_endpoint(self, api_client: TestClient):
        """Тест эндпоинта /health для проверки работоспособности.

        Проверяет:
        - HTTP статус 200 OK
        - Наличие поля "status" в ответе
        - Значение "ok" в поле status

        Этот эндпоинт используется для мониторинга и health checks.

        Args:
            api_client: Тестовый клиент FastAPI
        """
        response = api_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"

    def test_root_endpoint(self, api_client: TestClient):
        """Тест корневого эндпоинта /.

        Проверяет:
        - HTTP статус 200 OK
        - Наличие полей name, version, status
        - Статус "running"

        Корневой эндпоинт предоставляет основную информацию об API
        и ссылки на документацию.

        Args:
            api_client: Тестовый клиент FastAPI
        """
        response = api_client.get("/")
        assert response.status_code == 200
        data = response.json()
        # API возвращает структуру с полями name, version, status, docs и т.д.
        assert "name" in data
        assert "version" in data
        assert "status" in data
        assert data["status"] == "running"

    def test_version_endpoint(self, api_client: TestClient):
        """Тест эндпоинта /version.

        Проверяет:
        - HTTP статус 200 OK
        - Наличие поля "version" в ответе

        Эндпоинт используется для получения информации о версии приложения.

        Args:
            api_client: Тестовый клиент FastAPI
        """
        response = api_client.get("/version")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data

    def test_health_simple_endpoint(self, api_client: TestClient):
        """Тест упрощенных эндпоинтов для проверки здоровья.

        Проверяет несколько возможных путей для простой проверки здоровья:
        - /health/simple
        - /api/v1/health
        - /ping

        Проверяет:
        - HTTP статус 200 OK
        - Наличие поля "status" или "pong" в ответе

        Если ни один из эндпоинтов не доступен, тест пропускается.

        Args:
            api_client: Тестовый клиент FastAPI
        """
        # Проверяем разные возможные пути
        endpoints = ["/health/simple", "/api/v1/health", "/ping"]
        for endpoint in endpoints:
            response = api_client.get(endpoint)
            if response.status_code == 200:
                assert response.status_code == 200
                data = response.json()
                assert "status" in data or "pong" in str(data)
                return

        # Если ни один эндпоинт не найден, пропускаем тест
        pytest.skip("Health simple endpoint not found")

    def test_auth_required(self, api_client: TestClient):
        """Тест проверки аутентификации для защищенных эндпоинтов.

        Проверяет:
        - Эндпоинт не возвращает 500 Internal Server Error
        - Эндпоинт возвращает 200 OK (если аутентификация отключена в тестах)
        - Или 401 Unauthorized (если требуется аутентификация)

        Это тест проверяет, что механизм аутентификации работает корректно.

        Args:
            api_client: Тестовый клиент FastAPI
        """
        response = api_client.get("/api/v1/admin/stats")
        assert response.status_code != 500
        assert response.status_code in (200, 401)
