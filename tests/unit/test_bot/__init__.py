"""
Модуль для объединения тестов бота.

Данный модуль импортирует все тесты для компонентов бота,
обеспечивая централизованный доступ к тестовым наборам.

Импортируемые модули:
- test_keyboards — тесты клавиатур и кнопок бота;
- test_manager — тесты менеджера бота (BotManager);
- test_action — тесты обработчиков callback-запросов (action callbacks).
"""

from . import (
    test_keyboards as test_keyboards,
)
from . import (
    test_manager as test_manager,
)
from .callbacks import test_actions as test_actions
