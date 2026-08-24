"""
Тесты для сервисов приложения.

Данный модуль объединяет все тесты сервисного слоя, обеспечивая централизованный импорт
для удобного запуска и организации тестового пакета.

Включает тесты для следующих сервисов:
- automation_service - сервис автоматизации (конвертация документов);
- avanpost_sync_service - сервис синхронизации данных Avanpost;
- auth_service - сервис аутентификации (хеширование паролей);
- error_service_extended - расширенные тесты сервиса ошибок;
- message_lifetime_service - сервис управления временем жизни сообщений;
- notification_service - сервис уведомлений;
- reminder_service - сервис напоминаний;
- seed_service - сервис начального заполнения базы данных.
"""

from . import (
    test_auth_service as test_auth_service,
)
from . import (
    test_automation_service as test_automation_service,
)
from . import (
    test_avanpost_sync_service as test_avanpost_sync_service,
)
from . import (
    test_error_service_extended as test_error_service_extended,
)
from . import (
    test_message_lifetime_service as test_message_lifetime_service,
)
from . import (
    test_notification_service as test_notification_service,
)
from . import (
    test_reminder_service as test_reminder_service,
)
from . import (
    test_seed_service as test_seed_service,
)
