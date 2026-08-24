"""Базовый класс для всех обработчиков списков.

Обеспечивает единообразное отображение пагинации.
"""

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .....bot.callbacks.generic import GenericListCallbackHandler
from .....bot.dependencies import get_bot_manager
from .....models import MessageActionType, MessageType


class BaseListHandler(GenericListCallbackHandler):
    """Базовый обработчик списков с унифицированной пагинацией.

    Все обработчики списков должны наследоваться от этого класса.
    Предоставляет:
    - Единое форматирование заголовка списка
    - Управление отображением пагинации (скрытие при 1 странице)
    - Единые настройки размера страницы
    """

    def __init__(self, prefix: str, list_type: str, page_size: int = 10):
        """Инициализация базового обработчика.

        Args:
            prefix: Префикс для callback_data
            list_type: Тип списка (для ключей состояния)
            page_size: Размер страницы
        """
        super().__init__(prefix=prefix, list_type=list_type)
        self.PAGE_SIZE = page_size

    def format_header(
        self,
        title: str,
        total: int,
        current_page: int,
        total_pages: int,
        search_query: str | None = None,
    ) -> str:
        """Унифицированное форматирование заголовка списка.

        Args:
            title: Заголовок списка
            total: Общее количество элементов
            current_page: Текущая страница (0-based)
            total_pages: Всего страниц
            search_query: Поисковый запрос (опционально)

        Returns:
            str: Отформатированный заголовок
        """
        text = f"{title}\n\n"

        if search_query:
            text += f"🔍 **Поиск:** `{search_query}`\n"

        # Отображение информации о страницах только если их больше 1
        if total_pages > 1:
            start_item = current_page * self.PAGE_SIZE + 1
            end_item = min(start_item + self.PAGE_SIZE - 1, total)
            text += f"📊 Показаны: {start_item}-{end_item} из {total}\n"
            text += f"📄 Страница {current_page + 1} из {total_pages}\n\n"

        return text

    @staticmethod
    def should_show_pagination(total_pages: int) -> bool:
        """Проверка, нужно ли показывать пагинацию.

        Args:
            total_pages: Всего страниц

        Returns:
            bool: True если страниц > 1
        """
        return total_pages > 1

    async def send_list_message(
        self,
        event: Message | CallbackQuery,
        state: FSMContext,
        text: str,
        keyboard: Any,
        cleanup: bool = True,
    ) -> None:
        """Унифицированная отправка сообщения со списком.

        Args:
            event: Событие (Message или CallbackQuery)
            state: Состояние FSM
            text: Текст сообщения
            keyboard: Клавиатура
            cleanup: Удалять ли старые сообщения
        """
        bot_manager = get_bot_manager()
        chat_id = self._get_chat_id(event)

        if not chat_id:
            return

        # Сохраняем ID сообщения для последующей очистки
        result = await bot_manager.send_message(
            chat_id=chat_id,
            text=text,
            message_type=MessageType.COMMAND_ACTION,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP if cleanup else None,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        if result.get("success") and cleanup:
            # Сохраняем ID для очистки
            #            state_keys = await self.get_state_keys()
            state_data = await state.get_data()
            message_ids = state_data.get(f"{self.list_type}_message_ids", [])
            message_ids.append(result.get("message_id"))
            await state.update_data(**{f"{self.list_type}_message_ids": message_ids})

    @staticmethod
    def _get_chat_id(event: Message | CallbackQuery) -> int | None:
        """Получение ID чата из события."""
        if isinstance(event, Message):
            return event.chat.id if event.chat else None
        if isinstance(event, CallbackQuery) and event.message:
            return event.message.chat.id if event.message.chat else None
        return None

    async def get_state_keys(self) -> dict[str, str]:
        """Получение ключей для состояния."""
        return {
            "page": f"{self.list_type}_page",
            "search_query": f"{self.list_type}_search_query",
            "page_before_search": f"{self.list_type}_page_before_search",
            "search_message_id": f"{self.list_type}_search_message_id",
            "message_ids": f"{self.list_type}_message_ids",
            "total": f"{self.list_type}_total",
            "total_pages": f"{self.list_type}_total_pages",
        }


__all__ = [
    "BaseListHandler",
]
