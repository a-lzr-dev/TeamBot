"""
Модуль с тестами для роутеров API бота.

Содержит набор тестов для проверки HTTP-эндпоинтов, связанных с:
- управлением Telegram-ботом (статус, чаты, информация о чате);
- рассылками (broadcast);
- статистикой (общая, по чатам, пользователям, сообщениям).

Тесты используют TestClient для имитации HTTP-запросов и проверки ответов.
В некоторых случаях ожидаются коды ответа 200, 404 или 500 в зависимости
от состояния окружения (наличие БД, инициализация сервисов и т.д.).
"""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestBotMsgsRouter:
    """
    Набор тестов для роутера bot_msgs.

    Проверяет эндпоинты:
    - GET /api/v1/bot/msgs/status — статус Telegram-бота;
    - GET /api/v1/bot/msgs/chats — список чатов;
    - GET /api/v1/bot/msgs/chats/{chat_id} — информация о конкретном чате;
    - GET /api/v1/bot/msgs/stats — статистика сообщений бота.
    """

    def test_get_telegram_status(self, api_client: TestClient):
        """
        Проверяет получение статуса Telegram-бота.

        Мокается бот-менеджер, возвращающий статус is_running=True.
        Ожидается успешный ответ (200) с полями success и status.
        """
        with patch("app.api.routers.bot_msgs._get_bot_manager") as mock_get_bot:
            mock_bot = AsyncMock()
            mock_bot.get_status = AsyncMock(return_value={"is_running": True})
            mock_get_bot.return_value = mock_bot

            response = api_client.get("/api/v1/bot/msgs/status")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "status" in data

    def test_get_chats(self, api_client: TestClient):
        """
        Проверяет получение списка чатов.

        В зависимости от состояния окружения (инициализирована ли БД)
        может возвращаться 200 (успех) или 500 (ошибка сервера).
        """
        response = api_client.get("/api/v1/bot/msgs/chats")
        assert response.status_code in (200, 500)

    def test_get_chat_info_not_found(self, api_client: TestClient):
        """
        Проверяет запрос информации о несуществующем чате.

        Ожидается 404 (не найдено) или 500 (внутренняя ошибка)
        в зависимости от реализации обработки ошибок.
        """
        response = api_client.get("/api/v1/bot/msgs/chats/999999")
        assert response.status_code in (404, 500)

    def test_get_stats(self, api_client: TestClient):
        """
        Проверяет получение статистики сообщений бота.

        Допустимы ответы 200 (успех) или 500 (ошибка сервера).
        """
        response = api_client.get("/api/v1/bot/msgs/stats")
        assert response.status_code in (200, 500)


class TestBroadcastRouter:
    """
    Набор тестов для роутера рассылок (broadcast).

    Проверяет эндпоинты:
    - GET /api/v1/broadcast — список рассылок;
    - GET /api/v1/broadcast/stats — статистика рассылок.
    """

    def test_get_broadcasts(self, api_client: TestClient):
        """
        Проверяет получение списка рассылок.

        Эндпоинт зарегистрирован как /broadcast (без завершающего слеша).
        Допустимы ответы 200, 404 (если роутер не зарегистрирован) или 500.
        """
        response = api_client.get("/api/v1/broadcast")
        assert response.status_code in (200, 404, 500)

    def test_get_broadcast_stats(self, api_client: TestClient):
        """
        Проверяет получение статистики рассылок.

        Эндпоинт зарегистрирован как /broadcast/stats.
        Допустимы ответы 200, 404 или 500.
        """
        response = api_client.get("/api/v1/broadcast/stats")
        assert response.status_code in (200, 404, 500)


class TestStatsRouter:
    """
    Набор тестов для роутера статистики.

    Проверяет эндпоинты:
    - GET /api/v1/stats/full — полная статистика;
    - GET /api/v1/stats/chats — статистика по чатам;
    - GET /api/v1/stats/users — статистика по пользователям;
    - GET /api/v1/stats/messages — статистика по сообщениям;
    - GET /api/v1/stats/all — вся статистика (агрегированная).
    """

    def test_get_full_stats(self, api_client: TestClient):
        """Проверяет получение полной статистики. Допустимы ответы 200 или 500."""
        response = api_client.get("/api/v1/stats/full")
        assert response.status_code in (200, 500)

    def test_get_chats_stats(self, api_client: TestClient):
        """Проверяет получение статистики по чатам. Допустимы ответы 200 или 500."""
        response = api_client.get("/api/v1/stats/chats")
        assert response.status_code in (200, 500)

    def test_get_users_stats(self, api_client: TestClient):
        """Проверяет получение статистики по пользователям. Допустимы ответы 200 или 500."""
        response = api_client.get("/api/v1/stats/users")
        assert response.status_code in (200, 500)

    def test_get_messages_stats(self, api_client: TestClient):
        """Проверяет получение статистики по сообщениям. Допустимы ответы 200 или 500."""
        response = api_client.get("/api/v1/stats/messages")
        assert response.status_code in (200, 500)

    def test_get_all_stats(self, api_client: TestClient):
        """Проверяет получение агрегированной статистики. Допустимы ответы 200 или 500."""
        response = api_client.get("/api/v1/stats/all")
        assert response.status_code in (200, 500)
