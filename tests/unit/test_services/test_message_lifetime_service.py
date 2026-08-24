"""
Модуль с тестами для сервиса управления временем жизни сообщений (MessageLifetimeService).

Содержит набор асинхронных тестов, проверяющих логику работы с истекающими сообщениями:
- запуск и остановка фонового сервиса;
- получение статистики по сообщениям с истекшим сроком жизни;
- принудительная проверка и удаление истекших сообщений с синхронизацией с ботом.
Все тесты используют моки для изоляции от репозиториев, базы данных и бота.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.message_lifetime_service import MessageLifetimeService


class TestMessageLifetimeService:
    """
    Набор тестов для проверки корректности работы MessageLifetimeService.

    Тестируются основные функции сервиса:
    - управление состоянием (запуск/остановка);
    - сбор статистики по сообщениям с истекшим сроком жизни;
    - принудительная проверка и удаление истекших сообщений.
    """

    @pytest.fixture
    def service(self):
        """Создаёт экземпляр сервиса управления временем жизни сообщений для каждого теста."""
        return MessageLifetimeService()

    @pytest.mark.asyncio
    async def test_start_stop(self, service):
        """
        Проверяет запуск и остановку сервиса.

        Ожидается, что после вызова start() флаг is_running станет True,
        а после stop() — False.
        """
        assert service.is_running is False

        await service.start()
        assert service.is_running is True

        await service.stop()
        assert service.is_running is False

    @pytest.mark.asyncio
    async def test_get_stats(self, service):
        """
        Проверяет получение статистики по сообщениям.

        Мокается репозиторий сообщений, возвращающий предопределённую статистику.
        Ожидается, что метод сервиса вернёт словарь, содержащий как данные из
        репозитория, так и служебную информацию о самом сервисе (статус запуска).
        """
        with patch("app.services.message_lifetime_service._message_repo") as mock_repo:
            mock_repo.get_message_lifetime_stats = AsyncMock(
                return_value={
                    "total": 100,
                    "deleted": 10,
                    "with_expiration": 50,
                    "expired_not_deleted": 5,
                    "expiration_rate": 50.0,
                }
            )

            stats = await service.get_stats()

            assert stats["total"] == 100
            assert stats["deleted"] == 10
            assert stats["with_expiration"] == 50
            assert stats["expired_not_deleted"] == 5

            assert "service" in stats
            assert stats["service"]["is_running"] is False

    @pytest.mark.asyncio
    async def test_force_check(self, service):
        """
        Проверяет принудительную проверку и удаление истекших сообщений.

        Мокаются все внешние зависимости:
        - менеджер базы данных для получения сессии;
        - репозиторий сообщений для поиска истекших и их удаления;
        - бот-менеджер для получения статуса (бот выключен, поэтому удаление через бот не происходит).

        Ожидается, что метод вернёт словарь с количеством найденных и удалённых сообщений,
        а также с количеством удалённых через бот (0, так как бот выключен).
        """
        with patch("app.services.message_lifetime_service.db_manager") as mock_db_manager:
            mock_session = AsyncMock()
            mock_db_manager.get_session.return_value.__aenter__.return_value = mock_session

            with patch("app.services.message_lifetime_service._message_repo") as mock_repo:
                mock_repo.get_expired_messages = AsyncMock(return_value=[MagicMock(FID=1), MagicMock(FID=2)])
                mock_repo.mark_messages_as_deleted = AsyncMock(return_value=2)

                with patch("app.bot.dependencies.get_bot_manager") as mock_get_bot:
                    mock_bot = AsyncMock()
                    mock_bot.get_status = AsyncMock(return_value={"is_running": False})
                    mock_get_bot.return_value = mock_bot

                    result = await service.force_check()
                    assert result["deleted"] == 2
                    assert result["found"] == 2
                    assert result["bot_deleted"] == 0
