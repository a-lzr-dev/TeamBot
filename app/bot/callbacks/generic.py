"""
Универсальные обработчики колбэков для типовых операций:
- Пагинация
- Поиск
- Выбор элемента
- Закрытие списка
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypeVar

# Импорты для type checking
if TYPE_CHECKING:
    from collections.abc import Callable

    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery, Message

# Runtime imports
from ...logger import bot_logger
from ..keyboards import ListKeyboardBuilder
from .base import BaseCallbackHandler, CallbackHandler

# ============================================================
# Протоколы для универсальной обработки
# ============================================================

T = TypeVar("T")


class ListItemData(Protocol):
    """Протокол для элемента списка"""

    id: int
    name: str


class ListStateProtocol(Protocol):
    """Протокол для состояния списка"""

    @property
    def page(self) -> int: ...
    @property
    def search_query(self) -> str | None: ...
    @property
    def total(self) -> int: ...
    @property
    def total_pages(self) -> int: ...
    @property
    def has_prev(self) -> bool: ...
    @property
    def has_next(self) -> bool: ...


class ListHandlerProtocol(Protocol):
    """Протокол для обработчика списка"""

    async def show_list(
        self,
        event: Message | CallbackQuery,
        state: FSMContext,
        page: int = 0,
        search_query: str | None = None,
        **kwargs: Any,
    ) -> None: ...

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def on_select(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        item_id: int,
        **kwargs: Any,
    ) -> None: ...

    async def get_state_keys(self) -> dict[str, str]: ...


# ============================================================
# Универсальный обработчик списка (Callback версия)
# ============================================================


class GenericListCallbackHandler(BaseCallbackHandler):
    """
    Универсальный обработчик для списков с пагинацией и поиском.

    Поддерживает:
    - page_<page>[_search_<query>] - переключение страницы
    - search - переход в режим поиска
    - cancel_search - отмена поиска
    - close - закрытие списка
    - select_<id> - выбор элемента

    Usage:
        class MyListHandler(GenericListCallbackHandler):
            async def load_data(self, session, page, search_query, **kwargs):
                # Загрузка данных из БД
                return {"items": [...], "total": 10, "total_pages": 2, ...}

            async def show_list(self, event, state, page=0, search_query=None, **kwargs):
                # Отображение списка
                data = await self.load_data(...)
                text = self.format_list_text(data)
                keyboard = self.get_list_keyboard(data)
                await self.send_list_message(event, text, keyboard)

            async def on_select(self, callback, state, item_id, **kwargs):
                # Действие при выборе элемента
                ...
    """

    # Имена для callback_data (можно переопределить в наследниках)
    PREFIX_LIST = "list_"
    PREFIX_CLOSE = "close"
    PREFIX_SEARCH = "search"
    PREFIX_CANCEL_SEARCH = "cancel_search"
    PREFIX_SELECT = "select_"
    PREFIX_PAGE = "page_"
    PREFIX_ACTION = "action_"

    # Состояния (можно переопределить)
    STATE_VIEWING = None
    STATE_SEARCHING = None

    # Настройки
    PAGE_SIZE = 10
    MAX_PREVIEW_LENGTH = 20

    def __init__(self, prefix: str | None = None, list_type: str = "list"):
        super().__init__(prefix or f"{self.PREFIX_LIST}{list_type}_")
        self.list_type = list_type

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """Основной метод обработки колбэков"""
        callback_data = callback.data
        bot_logger.debug(f"🔍 [GenericListCallbackHandler] Received: {callback_data}, prefix={self.prefix}")

        if not callback_data:
            await CallbackHandler.answer(callback, "Неизвестное действие")
            return None

        # Проверка, чтобы профекс заканчивался на "_"
        prefix_with_underscore = self.prefix if self.prefix.endswith("_") else f"{self.prefix}_"

        # Проверка, начинается ли callback_data с префикса (с подчеркиванием)
        if callback_data.startswith(prefix_with_underscore):
            # Удаление префикса полностью
            rest = callback_data[len(prefix_with_underscore) :]
            bot_logger.debug(f"🔍 [GenericListCallbackHandler] rest={rest}")

            # Проверка специальных команд
            if rest == self.PREFIX_CLOSE:
                bot_logger.debug("🔍 [GenericListCallbackHandler] Handling CLOSE command")
                return await self._handle_close(callback, state, **kwargs)

            if rest == self.PREFIX_SEARCH:
                bot_logger.debug("🔍 [GenericListCallbackHandler] Handling SEARCH command")
                return await self._handle_search(callback, state, **kwargs)

            if rest == self.PREFIX_CANCEL_SEARCH:
                bot_logger.debug("🔍 [GenericListCallbackHandler] Handling CANCEL_SEARCH command")
                return await self._handle_cancel_search(callback, state, **kwargs)

            # Для команд с параметрами (page_, select_)
            if rest.startswith(self.PREFIX_PAGE):
                data_parts = rest.split("_")
                bot_logger.debug(f"🔍 [GenericListCallbackHandler] PAGE data_parts={data_parts}")
                return await self._handle_page(callback, state, data_parts, **kwargs)

            if rest.startswith(self.PREFIX_SELECT):
                data_parts = rest.split("_")
                bot_logger.debug(f"🔍 [GenericListCallbackHandler] SELECT data_parts={data_parts}")
                return await self._handle_select(callback, state, data_parts, **kwargs)

            # Если ничего не подошло
            bot_logger.debug(f"ℹ️ Unknown rest: {rest}")

        # Если не обработано - передаем дальше
        bot_logger.debug(f"ℹ️ Unhandled callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    # ==================== ОБРАБОТЧИКИ ====================

    async def _handle_close(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Закрытие списка"""
        await CallbackHandler.answer(callback)

        # Проверка, не находится ли в режиме поиска
        current_state = await state.get_state()
        if self.STATE_SEARCHING and current_state == self.STATE_SEARCHING:
            # Возврат к списку из поиска
            await self._return_to_list_from_search(callback, state, **kwargs)
            return

        # Очистка состояния
        await self._clear_state(state)

        # Удаление сообщения
        if callback.message:
            try:
                await callback.message.delete()
                bot_logger.debug(f"🗑️ {self.list_type} list closed")
            except Exception as e:
                bot_logger.warning(f"⚠️ Could not delete message: {e}")

        await self._on_closed(callback, state, **kwargs)

    async def _handle_search(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Переход в режим поиска"""
        bot_logger.debug(f"🔍 [_handle_search] START: {callback.data}")
        await CallbackHandler.answer(callback, "🔍 Введите поисковый запрос", show_alert=False)

        if self.STATE_SEARCHING:
            await state.set_state(self.STATE_SEARCHING)

        # Сохранение текущей страницы
        state_data = await state.get_data()
        state_keys = await self.get_state_keys()
        current_page = state_data.get(state_keys["page"], 0)
        await state.update_data(**{state_keys["page_before_search"]: current_page})

        # Удаление текущего сообщения
        if callback.message:
            try:
                await callback.message.delete()
                bot_logger.debug(f"🗑️ Deleted {self.list_type} list before search")
            except Exception as e:
                bot_logger.warning(f"⚠️ Could not delete message: {e}")

        # Отправка сообщения с приглашением
        search_prompt = await self._send_search_prompt(callback, state, **kwargs)
        if search_prompt and search_prompt.get("success"):
            search_msg_id = search_prompt.get("message_id")
            if search_msg_id:
                await state.update_data(**{state_keys["search_message_id"]: search_msg_id})

        await self._on_search_started(callback, state, **kwargs)

    async def _handle_cancel_search(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Отмена поиска - возврат к списку"""
        await CallbackHandler.answer(callback, "👥 Возврат к списку", show_alert=False)
        await self._return_to_list_from_search(callback, state, **kwargs)

    async def _handle_page(
        self, callback: CallbackQuery, state: FSMContext, data_parts: list[str], **kwargs: Any
    ) -> None:
        """Обработка пагинации"""
        await CallbackHandler.answer(callback)

        try:
            state_keys = await self.get_state_keys()
            state_data = await state.get_data()

            # Получение номера страницы и поискового запроса
            page = 0
            search_query = None

            if len(data_parts) >= 2:
                # format: page_<page>_search_<query>  или  page_<page>
                page = int(data_parts[1])
                if len(data_parts) >= 4 and data_parts[2] == "search":
                    search_query = data_parts[3]

            # Если поисковый запрос не передан - берем из состояния
            if search_query is None:
                search_query = state_data.get(state_keys["search_query"])

            # Отображение списка
            await self.show_list(
                event=callback,
                state=state,
                page=page,
                search_query=search_query,
                **kwargs,
            )

        except (ValueError, IndexError) as e:
            bot_logger.warning(f"⚠️ Invalid page data: {data_parts}, error: {e}")
            await CallbackHandler.answer(callback, "Неверный формат данных")

    async def _handle_select(
        self, callback: CallbackQuery, state: FSMContext, data_parts: list[str], **kwargs: Any
    ) -> None:
        """Обработка выбора элемента"""
        if len(data_parts) < 2:
            await CallbackHandler.answer(callback, "Неверный формат данных")
            return

        try:
            item_id = int(data_parts[1])
            await self.on_select(callback, state, item_id, **kwargs)
        except ValueError:
            await CallbackHandler.answer(callback, "Неверный ID")

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    async def _return_to_list_from_search(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Возврат к списку из режима поиска"""
        state_keys = await self.get_state_keys()
        state_data = await state.get_data()

        # Сброс состояния поиска
        if self.STATE_SEARCHING:
            await state.set_state(None)

        page = state_data.get(state_keys["page_before_search"], 0)

        # Очистка временных данных
        await state.update_data(
            **{
                state_keys["page_before_search"]: 0,
                state_keys["search_query"]: None,
                state_keys["search_message_id"]: None,
            }
        )

        # Удаление сообщения с поиском
        if callback.message:
            try:
                await callback.message.delete()
                bot_logger.debug(f"🗑️ Deleted search message for {self.list_type}")
            except Exception as e:
                bot_logger.warning(f"⚠️ Could not delete message: {e}")

        # Отображение списка
        await self.show_list(
            event=callback,
            state=state,
            page=page,
            search_query=None,
            **kwargs,
        )

    async def _clear_state(self, state: FSMContext) -> None:
        """Очистка состояния"""
        state_keys = await self.get_state_keys()
        await state.update_data(
            **{
                state_keys["page"]: 0,
                state_keys["search_query"]: None,
                state_keys["page_before_search"]: 0,
                state_keys["search_message_id"]: None,
            }
        )
        if self.STATE_VIEWING or self.STATE_SEARCHING:
            await state.set_state(None)

    # ==================== МЕТОДЫ ДЛЯ ПЕРЕОПРЕДЕЛЕНИЯ ====================

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Загрузка данных для списка.

        Должен возвращать:
        {
            "items": list[dict],  # Список элементов с полями id, name
            "total": int,
            "page": int,
            "total_pages": int,
            "has_prev": bool,
            "has_next": bool,
            "search_query": str | None,
        }
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
        """Отображение списка"""
        raise NotImplementedError("show_list must be implemented")

    async def on_select(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        item_id: int,
        **kwargs: Any,
    ) -> None:
        """Обработка выбора элемента"""
        raise NotImplementedError("on_select must be implemented")

    async def get_state_keys(self) -> dict[str, str]:
        """Получение ключей для состояния"""
        return {
            "page": f"{self.list_type}_page",
            "search_query": f"{self.list_type}_search_query",
            "page_before_search": f"{self.list_type}_page_before_search",
            "search_message_id": f"{self.list_type}_search_message_id",
            "total": f"{self.list_type}_total",
            "total_pages": f"{self.list_type}_total_pages",
        }

    async def _send_search_prompt(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> dict[str, Any]:
        """Отправка приглашения для поиска"""
        from ...bot.dependencies import get_bot_manager

        bot_manager = get_bot_manager()
        return await bot_manager.send_answer(
            text=f"🔍 **Поиск {self.list_type}**\n\nВведите поисковый запрос.\nМинимум 2 символа.",
            event=callback,
            parse_mode="Markdown",
            reply_markup=self.get_search_cancel_keyboard(),
        )

    def get_search_cancel_keyboard(self) -> Any:
        """Клавиатура для отмены поиска"""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        # Использование префикса для callback_data
        prefix_with_underscore = self.prefix if self.prefix.endswith("_") else f"{self.prefix}_"

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Отменить поиск", callback_data=f"{prefix_with_underscore}{self.PREFIX_CANCEL_SEARCH}"
                    )
                ]
            ]
        )

    def get_close_keyboard(self) -> Any:
        """Клавиатура с кнопкой закрытия"""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"{self.prefix}{self.PREFIX_CLOSE}")]
            ]
        )

    def get_list_keyboard(
        self,
        items: list[dict[str, Any]],
        current_page: int,
        total_pages: int,
        has_prev: bool,
        has_next: bool,
        search_query: str | None,
        extra_buttons: list[tuple[str, str]] | None = None,
        buttons_per_row: int = 3,
    ) -> Any:
        """
        Универсальная клавиатура для списка (использует ListKeyboardBuilder).
        """
        builder = ListKeyboardBuilder(
            callback_prefix=self.prefix[:-1] if self.prefix.endswith("_") else self.prefix,
            buttons_per_row=buttons_per_row,
            item_icon="📌",
            max_name_length=self.MAX_PREVIEW_LENGTH,
        )

        return builder.build(
            items=items,
            current_page=current_page,
            total_pages=total_pages,
            search_query=search_query,
            extra_buttons=extra_buttons,
        )

    # ==================== ФОРМАТИРОВАНИЕ ТЕКСТА ====================

    def format_list_text(
        self,
        title: str,
        data: dict[str, Any],
        item_formatter: Callable[[dict[str, Any]], str] | None = None,
    ) -> str:
        """
        Форматирование текста списка.

        Args:
            title: Заголовок списка
            data: Данные списка
            item_formatter: Функция форматирования элемента (принимает dict, возвращает str)
        """
        items = data.get("items", [])
        total = data.get("total", 0)
        current_page = data.get("page", 0)
        total_pages = data.get("total_pages", 0)
        search_query = data.get("search_query")

        if total == 0:
            text = f"📋 **{title}**\n\n"
            if search_query:
                text += f"🔍 По запросу `{search_query}` ничего не найдено."
            else:
                text += "Нет данных."
            return text

        start_item = current_page * self.PAGE_SIZE + 1
        end_item = min(start_item + self.PAGE_SIZE - 1, total)

        text = f"📋 **{title}**\n\n"
        if search_query:
            text += f"🔍 **Поиск:** `{search_query}`\n"
        text += f"📊 Показаны: {start_item}-{end_item} из {total}\n"
        text += f"📄 Страница {current_page + 1} из {total_pages}\n\n"

        if item_formatter:
            for item in items:
                text += item_formatter(item)
        else:
            for item in items:
                name = item.get("name", f"Item #{item.get('id', '?')}")
                text += f"• {name}\n"

        return text

    # ==================== КОЛБЭКИ СОБЫТИЙ ====================

    async def _on_closed(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Событие при закрытии списка"""
        pass

    async def _on_search_started(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Событие при начале поиска"""
        pass


# ============================================================
# Универсальный обработчик для текстовых поисковых запросов
# ============================================================


class GenericSearchHandler:
    """
    Универсальный обработчик для текстовых поисковых запросов.

    Используется совместно с GenericListCallbackHandler.
    """

    def __init__(self, list_handler: GenericListCallbackHandler):
        self.list_handler = list_handler

    async def handle_search_query(
        self,
        message: Message,
        state: FSMContext,
        chat_id: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Обработка поискового запроса"""
        from ...bot.dependencies import get_bot_manager

        bot_manager = get_bot_manager()

        if not message.from_user:
            await bot_manager.send_answer(
                text="❌ Не удалось определить пользователя.",
                event=message,
                delete_by_type="search_cleanup",
            )
            return

        query = message.text.strip() if message.text else ""

        if not query or len(query) < 2:
            await bot_manager.send_answer(
                text="ℹ️ Введите минимум 2 символа для поиска.",
                event=message,
                delete_by_type="search_cleanup",
            )
            return

        # Очистка сообщения с приглашением
        state_keys = await self.list_handler.get_state_keys()
        data = await state.get_data()
        search_prompt_id = data.get(state_keys["search_message_id"])

        if search_prompt_id:
            try:
                await bot_manager.delete_message_by_id(chat_id=message.chat.id, message_id=search_prompt_id)
            except Exception as e:
                bot_logger.warning(f"⚠️ Could not delete search prompt: {e}")
            await state.update_data(**{state_keys["search_message_id"]: None})

        # Удаление сообщения пользователя
        await bot_manager.delete_message_by_link(message)

        # Отображение результатов
        await self.list_handler.show_list(
            event=message,
            state=state,
            page=0,
            search_query=query,
            **kwargs,
        )


__all__ = [
    "GenericListCallbackHandler",
    "GenericSearchHandler",
    "ListHandlerProtocol",
    "ListItemData",
    "ListStateProtocol",
]
