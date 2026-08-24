"""
Модуль с тестами для сервиса начального заполнения базы данных (SeedService).

Содержит набор асинхронных тестов, проверяющих логику работы AvanpostSeedService:
- полный цикл заполнения всех системных таблиц;
- успешное заполнение системных таблиц с использованием моков репозиториев;
- обработка ошибок при сбоях в процессе заполнения.
Тесты покрывают сценарии взаимодействия с системными, пользовательскими,
справочными и внешними репозиториями.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.seed_service import AvanpostSeedService


class TestAvanpostSeedService:
    """
    Набор тестов для проверки корректности работы AvanpostSeedService.

    Проверяются методы seed_all и seed_system_tables в различных условиях:
    - успешное выполнение всех этапов;
    - обработка исключений при работе с БД;
    - использование моков для изоляции зависимостей.
    """

    @pytest.mark.asyncio
    async def test_seed_all(self):
        """Проверяет, что метод seed_all вызывает seed_system_tables и возвращает True при успехе."""
        with patch.object(AvanpostSeedService, "seed_system_tables", AsyncMock(return_value=True)):
            result = await AvanpostSeedService.seed_all()
            assert result is True

    @pytest.mark.asyncio
    async def test_seed_system_tables_success(self, db_session):
        """
        Проверяет успешное выполнение seed_system_tables.

        Мокаются все внешние зависимости (репозитории), имитируется успешное
        выполнение операций создания типов данных, записей синхронизации,
        пользователей и проверки языков.
        Ожидается, что метод вернёт True.
        """
        with patch("app.services.seed_service._system_repo") as mock_system:
            mock_system.get_data_types_dict = AsyncMock(return_value={})
            mock_system.create_data_types_bulk = AsyncMock(return_value=5)
            mock_system.create_sync_records_bulk = AsyncMock(return_value=3)

            with patch("app.services.seed_service._user_repo") as mock_user:
                mock_user.get_all_avanpost_users = AsyncMock(return_value=[])
                mock_user.get_avanpost_user_data = AsyncMock(return_value=None)
                mock_user.create_or_update_avanpost_user_upsert = AsyncMock(return_value=(True, None))

                with patch("app.services.seed_service._avanpost_repo") as mock_avanpost:
                    mock_avanpost.get_user_ids_default_adding = AsyncMock(return_value=[1, 2, 3])

                    with patch("app.services.seed_service._dir_lang_repo") as mock_lang:
                        mock_lang.ensure_language = AsyncMock()

                        result = await AvanpostSeedService.seed_system_tables(db_session, show_logs=False)
                        assert result is True

    @pytest.mark.asyncio
    async def test_seed_system_tables_error(self, db_session):
        """
        Проверяет поведение seed_system_tables при возникновении ошибки.

        Мокается репозиторий _system_repo так, что его метод get_data_types_dict
        выбрасывает исключение. Ожидается, что метод обработает ошибку и вернёт False.
        """
        with patch("app.services.seed_service._system_repo") as mock_system:
            mock_system.get_data_types_dict = AsyncMock(side_effect=Exception("Database error"))

            result = await AvanpostSeedService.seed_system_tables(db_session, show_logs=False)
            assert result is False
