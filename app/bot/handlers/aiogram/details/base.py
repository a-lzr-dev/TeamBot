"""
Базовый класс для обработчиков деталей (контакты, чаты и т.д.)
Обеспечивает единообразную навигацию без тяжелой пагинации.
"""

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .....bot.callbacks.generic import GenericListCallbackHandler
from .....bot.dependencies import get_bot_manager
from .....models import MessageActionType, MessageType


class BaseDetailsHandler(GenericListCallbackHandler):
    """
    Базовый обработчик для деталей с простой навигацией.

    Особенности:
    - Не использует пагинацию (детали обычно не требуют множества страниц)
    - Упрощенная навигация (назад, закрыть)
    - Поддержка возврата к родительскому списку

    Используется для:
    - Детали контакта (FK_Type=7)
    - Детали сообщения
    - Другие мелкие списки
    """

    def __init__(self, prefix: str, list_type: str, page_size: int = 20):
        """
        Инициализация базового обработчика деталей.

        Args:
            prefix: Префикс для callback_data
            list_type: Тип списка (для ключей состояния)
            page_size: Размер страницы (по умолчанию 20, но обычно не используется)
        """
        super().__init__(prefix=prefix, list_type=list_type)
        self.PAGE_SIZE = page_size
        self.STATE_SEARCHING = None  # Поиск не поддерживается для деталей

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Загрузка данных. Должен быть переопределен в наследнике.
        """
        raise NotImplementedError("load_data must be implemented")

    async def show_list(
        self,
        event: Message | CallbackQuery,
        state: FSMContext,
        page: int = 0,
        search_query: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Отображение деталей. Должен быть переопределен в наследнике.
        """
        raise NotImplementedError("show_list must be implemented")

    async def on_select(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        item_id: int,
        **kwargs: Any,
    ) -> None:
        """
        Обработка выбора элемента.
        """
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(
            text=f"ℹ️ Выбран элемент #{item_id}",
            event=callback,
        )

    async def get_state_keys(self) -> dict[str, str]:
        """
        Получение ключей для состояния.
        """
        return {
            "page": f"{self.list_type}_page",
            "search_query": f"{self.list_type}_search_query",
            "message_ids": f"{self.list_type}_message_ids",
            "total": f"{self.list_type}_total",
        }

    async def send_details_message(
        self,
        event: Message | CallbackQuery,
        state: FSMContext,
        text: str,
        keyboard: Any,
        cleanup: bool = True,
    ) -> None:
        """
        Унифицированная отправка сообщения с деталями.

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

        if cleanup:
            # Удаление старых сообщений
            state_data = await state.get_data()
            message_ids = state_data.get(f"{self.list_type}_message_ids", [])
            for msg_id in message_ids:
                await bot_manager.delete_message_by_id(chat_id=chat_id, message_id=msg_id)
            await state.update_data(**{f"{self.list_type}_message_ids": []})

        # Отправка нового сообщения
        result = await bot_manager.send_message(
            chat_id=chat_id,
            text=text,
            message_type=MessageType.COMMAND_ACTION,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP if cleanup else None,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        if result.get("success"):
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

    @staticmethod
    def build_navigation_keyboard(
        back_callback: str | None = None,
        back_text: str = "🔙 Назад",
        close_callback: str = "close",
        extra_buttons: list[tuple[str, str]] | None = None,
    ) -> Any:
        """
        Построение навигационной клавиатуры.

        Args:
            back_callback: Callback для кнопки "Назад"
            back_text: Текст кнопки "Назад"
            close_callback: Callback для кнопки "Закрыть"
            extra_buttons: Дополнительные кнопки (текст, callback_data)

        Returns:
            InlineKeyboardMarkup: Клавиатура
        """
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        buttons = []

        if back_callback:
            buttons.append(InlineKeyboardButton(text=back_text, callback_data=back_callback))

        if extra_buttons:
            for text, callback_data in extra_buttons:
                buttons.append(InlineKeyboardButton(text=text, callback_data=callback_data))

        buttons.append(InlineKeyboardButton(text="❌ Закрыть", callback_data=close_callback))

        return InlineKeyboardMarkup(inline_keyboard=[buttons])


__all__ = [
    "BaseDetailsHandler",
]
