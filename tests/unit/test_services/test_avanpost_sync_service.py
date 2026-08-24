"""
Модуль с тестами для сервиса синхронизации данных Avanpost (AvanpostSyncService).

Содержит набор синхронных и асинхронных тестов, проверяющих:
- работу класса статистики SyncStatistics (сбор, агрегация, преобразование);
- инициализацию сервиса и кеширование типов данных;
- получение статуса и проверку здоровья сервиса;
- вспомогательные методы для работы с моделями (определение таблиц, колонок, первичных ключей);
- управление кешем внешних ключей.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.avanpost_sync_service import (
    AvanpostSyncService,
    SyncStatistics,
)


class TestSyncStatistics:
    """
    Набор тестов для проверки корректности работы класса SyncStatistics.

    Тестируются все методы агрегации статистики синхронизации:
    - инициализация с нулевыми значениями;
    - добавление записей (полученные, вставленные, обновлённые, удалённые);
    - добавление ошибок;
    - объединение двух экземпляров статистики;
    - преобразование в словарь для сериализации.
    """

    def test_sync_statistics_init(self):
        """Проверяет, что при инициализации все счётчики установлены в ноль,
        а список ошибок пуст."""
        stats = SyncStatistics()
        assert stats.total_data_types == 0
        assert stats.total_inserted == 0
        assert stats.total_updated == 0
        assert stats.total_deleted == 0
        assert stats.total_received == 0
        assert stats.error_messages == []

    def test_sync_statistics_add_received(self):
        """Проверяет добавление информации о полученных записях.
        Суммарное количество должно равняться upsert + delete,
        а также должны обновиться соответствующие счётчики."""
        stats = SyncStatistics()
        stats.add_received("test_table", upsert_count=5, delete_count=3)
        assert stats.total_received == 8
        assert stats.total_received_upsert == 5
        assert stats.total_received_delete == 3
        assert stats.table_stats["test_table"]["received"] == 8

    def test_sync_statistics_add_insert(self):
        """Проверяет добавление информации о вставленных записях.
        Обновляется общий счётчик и статистика по таблице."""
        stats = SyncStatistics()
        stats.add_insert("test_table", count=5)
        assert stats.total_inserted == 5
        assert stats.tables_with_inserts == {"test_table"}
        assert stats.table_stats["test_table"]["inserted"] == 5

    def test_sync_statistics_add_update(self):
        """Проверяет добавление информации об обновлённых записях."""
        stats = SyncStatistics()
        stats.add_update("test_table", count=3)
        assert stats.total_updated == 3
        assert stats.tables_with_updates == {"test_table"}

    def test_sync_statistics_add_delete(self):
        """Проверяет добавление информации об удалённых записях."""
        stats = SyncStatistics()
        stats.add_delete("test_table", count=2)
        assert stats.total_deleted == 2
        assert stats.tables_with_deletes == {"test_table"}

    def test_sync_statistics_add_error(self):
        """Проверяет добавление ошибок.
        Увеличивается счётчик ошибочных типов данных и заполняется список сообщений."""
        stats = SyncStatistics()
        stats.add_error("test_table", "Test error")
        assert len(stats.error_messages) == 1
        assert stats.tables_with_errors == {"test_table"}
        assert stats.failed_data_types == 1

    def test_sync_statistics_merge(self):
        """Проверяет объединение двух экземпляров статистики.
        Счётчики и множества таблиц должны суммироваться."""
        stats1 = SyncStatistics()
        stats1.add_insert("table1", count=5)

        stats2 = SyncStatistics()
        stats2.add_insert("table2", count=3)
        stats2.add_error("table2", "Error")

        stats1.merge(stats2)
        assert stats1.total_inserted == 8
        assert "table1" in stats1.tables_with_inserts
        assert "table2" in stats1.tables_with_inserts
        assert len(stats1.error_messages) == 1

    def test_sync_statistics_to_dict(self):
        """Проверяет преобразование статистики в словарь.
        Результат должен содержать все ключевые счётчики, статистику по таблицам,
        а также временные метки запуска и завершения."""
        stats = SyncStatistics()
        stats.start()
        stats.add_insert("test_table", count=5)
        stats.finish()

        result = stats.to_dict()
        assert "total_inserted" in result
        assert "total_deleted" in result
        assert "table_stats" in result
        assert "duration_seconds" in result
        assert "start_time" in result
        assert "end_time" in result


class TestAvanpostSyncService:
    """
    Набор тестов для проверки корректности работы AvanpostSyncService.

    Тестируются:
    - инициализация сервиса и кеширование типов данных;
    - получение статуса и проверка здоровья;
    - вспомогательные методы для работы с моделями (определение таблиц, колонок, первичных ключей);
    - управление кешем внешних ключей.
    """

    @pytest.fixture
    def service(self):
        """Создаёт экземпляр сервиса синхронизации Avanpost для каждого теста."""
        return AvanpostSyncService()

    @pytest.mark.asyncio
    async def test_initialize(self, service):
        """Проверяет инициализацию сервиса.
        После вызова initialize() флаг is_initialized должен стать True,
        а кеш типов данных должен быть заполнен (даже если пустой)."""
        assert service.is_initialized is False
        with patch("app.services.avanpost_sync_service.SystemRepository") as mock_repo:
            mock_repo.get_data_types_dict = AsyncMock(return_value={})
            await service.initialize()
            assert service.is_initialized is True
            assert service._data_type_cache == {}

    @pytest.mark.asyncio
    async def test_get_status(self, service):
        """Проверяет получение статуса сервиса.
        Возвращаемый словарь должен содержать информацию об инициализации,
        статусе синхронизации и количестве закешированных типов данных."""
        with patch("app.services.avanpost_sync_service.SystemRepository") as mock_repo:
            mock_repo.get_data_types_dict = AsyncMock(return_value={})
            await service.initialize()

            service._data_type_cache = {1: {"name": "test"}}
            status = await service.get_status()
            assert status["initialized"] is True
            assert status["is_syncing"] is False
            assert status["data_types_cached"] == 1

    @pytest.mark.asyncio
    async def test_health_check(self, service):
        """Проверяет проверку здоровья сервиса.
        До инициализации должно возвращать False, после — True."""
        assert await service.health_check() is False

        with patch("app.services.avanpost_sync_service.SystemRepository") as mock_repo:
            mock_repo.get_data_types_dict = AsyncMock(return_value={})
            await service.initialize()
            assert await service.health_check() is True

    def test_get_model_by_data_type(self, service):
        """Проверяет получение модели по идентификатору типа данных.
        Для известного типа (1) должна возвращаться модель AvanpostDirLanguageModel,
        для неизвестного — None."""
        from app.models.avanpost import AvanpostDirLanguageModel

        model = service._get_model_by_data_type(1)
        assert model == AvanpostDirLanguageModel

        model = service._get_model_by_data_type(9999)
        assert model is None

    def test_get_table_name(self, service):
        """Проверяет получение имени таблицы по типу данных.
        Для типа 1 должно возвращаться 'TAvanpostDirLanguages',
        для неизвестного — None."""
        name = service._get_table_name(1)
        assert name == "TAvanpostDirLanguages"

        name = service._get_table_name(9999)
        assert name is None

    def test_get_model_columns(self, service):
        """Проверяет получение списка колонок модели.
        Для AvanpostDirLanguageModel в списке должны присутствовать FID и FFlagDefault."""
        from app.models.avanpost import AvanpostDirLanguageModel

        columns = service._get_model_columns(AvanpostDirLanguageModel)
        assert "FID" in columns
        assert "FFlagDefault" in columns

    def test_get_pk_columns(self, service):
        """Проверяет получение колонок первичного ключа модели.
        Для AvanpostDirLanguageModel первичным ключом является FID."""
        from app.models.avanpost import AvanpostDirLanguageModel

        pk = service._get_pk_columns(AvanpostDirLanguageModel)
        assert "FID" in pk

    def test_clear_fk_cache(self, service):
        """Проверяет очистку кеша внешних ключей.
        После добавления записи в кеш и вызова clear_fk_cache() кеш должен стать пустым."""
        service._fk_cache["test"] = {1, 2, 3}
        assert len(service._fk_cache) == 1
        service.clear_fk_cache()
        assert len(service._fk_cache) == 0
