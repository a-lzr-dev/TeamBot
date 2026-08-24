"""
Модуль для объединения тестов Aiogram-обработчиков.

Данный модуль импортирует все тесты для обработчиков сообщений Aiogram,
обеспечивая централизованный доступ к тестовым наборам.

Импортируемые модули:
- test_actions — тесты обработчиков действий (action handlers);
- test_auth — тесты обработчиков аутентификации;
- test_broadcast — тесты обработчиков рассылок;
- test_commands — тесты обработчиков команд (command handlers).
"""

from .aiogram import (
    test_actions as test_actions,
)
from .aiogram import (
    test_auth as test_auth,
)
from .aiogram import (
    test_broadcast as test_broadcast,
)
from .aiogram import (
    test_commands as test_commands,
)
