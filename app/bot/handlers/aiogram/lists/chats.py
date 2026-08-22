"""
Обработчик списка чатов пользователя (FK_Type=9).

Поддерживает:
- Пагинацию
- Поиск по названию чата
- Выбор чата для просмотра сообщений
- Навигацию между страницами
- Переход из меню действий (FK_Type=9 - Открытие списка чатов)
"""

from typing import Any

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .....bot.callbacks.generic import GenericListCallbackHandler, GenericSearchHandler
from .....bot.dependencies import get_bot_manager
from .....db import db_manager
from .....db.repositories import AvanpostUserRepository
from .....logger import bot_logger
from .....models import MessageActionType, MessageType
from ....keyboards import ListKeyboardBuilder
from ..states import SubMenuStates

# Создание роутера для обработки callback-запросов
router = Router(name="aiogram_chats_list")

# Репозиторий для работы с данными пользователей Avanpost
_avanpost_user_repo = AvanpostUserRepository()


class ChatsListHandler(GenericListCallbackHandler):
    """
    Обработчик списка чатов пользователя (FK_Type=9).

    Наследуется от GenericListCallbackHandler для универсальной обработки:
    - Отображение списка с пагинацией
    - Поиск по названию
    - Обработка выбора чата (переход к сообщениям чата)
    - Навигация между страницами

    Особенности:
    - Загружает данные через get_user_chats_page
    - При выборе чата переходит к деталям чата (ChatDetailsHandler)
    - Использует иконку "💬" для чатов
    """

    def __init__(self) -> None:
        """
        Инициализация обработчика списка чатов.

        Устанавливает:
        - Префикс callback_data: "chats"
        - Тип списка: "chats"
        - Размер страницы: 10 элементов
        - Состояния для просмотра и поиска
        """
        super().__init__(prefix="chats", list_type="chats")
        self.PAGE_SIZE = 10
        self.STATE_VIEWING = SubMenuStates.viewing_chats
        self.STATE_SEARCHING = SubMenuStates.searching_chats

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Загрузка данных чатов из БД.

        Args:
            session: Сессия БД
            page: Номер страницы (начиная с 0)
            search_query: Поисковый запрос (опционально)
            **kwargs: Дополнительные параметры (avanpost_user_id)

        Returns:
            dict: Словарь с данными:
                - items: Список чатов
                - total: Общее количество
                - page: Текущая страница
                - total_pages: Всего страниц
                - has_prev: Есть ли предыдущая страница
                - has_next: Есть ли следующая страница
                - search_query: Текущий поисковый запрос
                - error: Сообщение об ошибке (если есть)
        """
        avanpost_user_id = kwargs.get("avanpost_user_id")
        if not avanpost_user_id:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": "User ID not provided",
            }

        try:
            # Получение данных через репозиторий
            data = await _avanpost_user_repo.get_user_chats_page(
                session=session,
                avanpost_user_id=avanpost_user_id,
                page=page,
                page_size=self.PAGE_SIZE,
                search_query=search_query,
            )

            return {
                "items": data.get("chats", []),
                "total": data.get("total", 0),
                "page": data.get("page", 0),
                "total_pages": data.get("total_pages", 0),
                "has_prev": data.get("has_prev", False),
                "has_next": data.get("has_next", False),
                "search_query": data.get("search_query"),
            }
        except Exception as e:
            bot_logger.error(f"❌ Failed to load chats: {e}", exc_info=True)
            return {
                "items": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": str(e),
            }

    async def show_list(
        self,
        event: Message | CallbackQuery,
        state: FSMContext,
        page: int = 0,
        search_query: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Отображение списка чатов пользователя.

        Args:
            event: Событие (Message или CallbackQuery)
            state: Состояние FSM
            page: Номер страницы (начиная с 0)
            search_query: Поисковый запрос (опционально)
            **kwargs: Дополнительные параметры
        """
        bot_manager = get_bot_manager()

        # Ответ на callback (если это callback)
        if isinstance(event, CallbackQuery):
            await event.answer()

        # Получение ID чата из события
        chat_id = self._get_chat_id(event)
        if not chat_id:
            return

        # Получение ID пользователя Avanpost из состояния или параметров
        state_data = await state.get_data()
        avanpost_user_id = state_data.get("avanpost_user_id") or kwargs.get("avanpost_user_id")
        group_id = state_data.get("group_id")
        selected_user_id = state_data.get("selected_user_id")
        selected_user_name = state_data.get("selected_user_name")

        if not avanpost_user_id:
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Не удалось определить пользователя.",
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
            )
            return

        try:
            # Загрузка данных
            async with db_manager.get_session() as session:
                data = await self.load_data(session, page, search_query, avanpost_user_id=avanpost_user_id)

            # Проверка ошибок загрузки
            if data.get("error"):
                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка загрузки чатов: {data['error']}",
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
                return

            items = data["items"]
            total = data["total"]
            current_page = data["page"]
            total_pages = data["total_pages"]

            # Если чаты не найдены
            if total == 0:
                empty_text = "💬 **Мои чаты**\n\n"
                if search_query:
                    empty_text += f"🔍 По запросу `{search_query}` чаты не найдены."
                else:
                    empty_text += "Нет чатов."

                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=self.get_back_keyboard(state),
                )
                return

            # Формирование текста с пагинацией
            start_item = current_page * self.PAGE_SIZE + 1
            end_item = min(start_item + self.PAGE_SIZE - 1, total)

            text = "💬 **Мои чаты**\n\n"
            if search_query:
                text += f"🔍 **Поиск:** `{search_query}`\n"
            text += f"📊 Показаны: {start_item}-{end_item} из {total}\n"
            text += f"📄 Страница {current_page + 1} из {total_pages}\n\n"

            # Создание клавиатуры
            builder = ListKeyboardBuilder(
                callback_prefix="chats",
                buttons_per_row=2,
                item_icon="💬",
                max_name_length=30,
            )

            # Добавление кнопок навигации
            parent_item_id = state_data.get("parent_item_id")
            extra_buttons = []

            if parent_item_id:
                extra_buttons.append(("🔙 Назад к действиям", f"action_back_{parent_item_id}"))

            # Кнопка "В главное меню"
            if group_id:
                extra_buttons.append(("🏠 В главное меню", "action_home"))

            keyboard = builder.build(
                items=items,
                current_page=current_page,
                total_pages=total_pages,
                search_query=search_query,
                extra_buttons=extra_buttons if extra_buttons else None,
                item_name_formatter=lambda item: self._format_chat_item(item),
            )

            # Сохранение состояния
            state_keys = await self.get_state_keys()
            await state.update_data(
                **{
                    state_keys["page"]: current_page,
                    state_keys["search_query"]: search_query,
                    "selected_user_id": selected_user_id,
                    "selected_user_name": selected_user_name,
                    "group_id": group_id,
                }
            )

            # Отправка сообщения
            await bot_manager.send_message(
                chat_id=chat_id,
                text=text,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

        except Exception as e:
            bot_logger.error(f"❌ Failed to show chats: {e}", exc_info=True)
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Произошла ошибка при загрузке чатов. Попробуйте позже.",
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
            )

    async def on_select(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        item_id: int,
        **kwargs: Any,
    ) -> None:
        """
        Обработка выбора чата - переход к просмотру сообщений чата.

        При выборе чата происходит переход к обработчику деталей чата
        (ChatDetailsHandler), который показывает сообщения.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            item_id: ID выбранного чата
            **kwargs: Дополнительные параметры
        """
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(
            text=f"💬 Открытие чата #{item_id}...",
            event=callback,
        )

        # Переход к обработчику деталей чата
        from .chat_details import ChatDetailsStates, show_chat_details

        # Получение данных из состояния
        state_data = await state.get_data()
        avanpost_user_id = state_data.get("avanpost_user_id") or kwargs.get("avanpost_user_id")
        parent_item_id = state_data.get("parent_item_id")
        group_id = state_data.get("group_id")
        selected_user_id = state_data.get("selected_user_id")
        selected_user_name = state_data.get("selected_user_name")

        if not avanpost_user_id:
            await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
            return

        # Сохранение состояния для просмотра сообщений
        await state.update_data(
            selected_chat_id=item_id,
            chat_details_page=0,
            parent_item_id=parent_item_id,
            group_id=group_id,
            selected_user_id=selected_user_id,
            selected_user_name=selected_user_name,
        )
        await state.set_state(ChatDetailsStates.viewing_messages)

        # Отображение сообщений чата
        await show_chat_details(
            event=callback,
            state=state,
            avanpost_user_id=avanpost_user_id,
            chat_id=item_id,
            page=0,
        )

    async def get_state_keys(self) -> dict[str, str]:
        """
        Получение ключей для хранения состояния.

        Returns:
            dict: Словарь с ключами состояния:
                - page: Ключ для номера страницы
                - search_query: Ключ для поискового запроса
                - page_before_search: Ключ для страницы до поиска
                - search_message_id: Ключ для ID сообщения поиска
                - total: Ключ для общего количества
                - total_pages: Ключ для общего количества страниц
        """
        return {
            "page": "chats_page",
            "search_query": "chats_search_query",
            "page_before_search": "chats_page_before_search",
            "search_message_id": "chats_search_message_id",
            "total": "chats_total",
            "total_pages": "chats_total_pages",
        }

    @staticmethod
    def _get_chat_id(event: Message | CallbackQuery) -> int | None:
        """
        Извлечение ID чата из события.

        Args:
            event: Событие (Message или CallbackQuery)

        Returns:
            int | None: ID чата или None
        """
        if isinstance(event, Message):
            chat_id = event.chat.id
            return int(chat_id) if chat_id is not None else None
        if isinstance(event, CallbackQuery) and event.message:
            chat_id = event.message.chat.id
            return int(chat_id) if chat_id is not None else None
        return None

    @staticmethod
    async def get_back_keyboard(state: FSMContext) -> Any:
        """
        Создание клавиатуры с кнопкой "Назад".

        Args:
            state: Состояние FSM

        Returns:
            InlineKeyboardMarkup: Клавиатура с кнопкой назад
        """
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        state_data = await state.get_data()
        group_id = state_data.get("group_id")
        parent_item_id = state_data.get("parent_item_id")

        buttons = []

        if parent_item_id:
            buttons.append(
                InlineKeyboardButton(text="🔙 Назад к действиям", callback_data=f"action_back_{parent_item_id}")
            )

        if group_id:
            buttons.append(InlineKeyboardButton(text="🏠 В главное меню", callback_data="action_home"))

        if not buttons:
            buttons.append(InlineKeyboardButton(text="❌ Закрыть", callback_data="chats_close"))

        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    @staticmethod
    def _format_chat_item(item: dict[str, Any]) -> str:
        """
        Форматирование элемента чата для отображения.

        Args:
            item: Словарь с данными чата

        Returns:
            str: Отформатированное название чата
        """
        name = item.get("name")
        if name is None:
            item_id = item.get("id", "?")
            name = f"Чат #{item_id}"
        return name


# Создание глобальных экземпляров для использования в других модулях
chats_handler = ChatsListHandler()
chats_search_handler = GenericSearchHandler(chats_handler)


async def show_chats_list(
    event: Message | CallbackQuery,
    state: FSMContext,
    page: int = 0,
    search_query: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Внешняя функция для отображения списка чатов.

    Используется для вызова из других модулей (например, из actions.py
    при FK_Type=9 - Открытие списка чатов).

    Args:
        event: Событие (Message или CallbackQuery)
        state: Состояние FSM
        page: Номер страницы
        search_query: Поисковый запрос
        **kwargs: Дополнительные параметры (avanpost_user_id)
    """
    await chats_handler.show_list(event, state, page, search_query, **kwargs)


# Регистрация обработчиков колбэков для чатов
@router.callback_query(lambda c: c.data.startswith("chats_"))
async def handle_chats_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик всех callback-запросов, начинающихся с "chats_".

    Поддерживает:
    - Навигацию по страницам
    - Выбор чата
    - Закрытие списка
    - Поиск по чатам

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    await chats_handler.handle(callback, state)


# Регистрация обработчика поисковых запросов
@router.message(SubMenuStates.searching_chats)
async def handle_chats_search(message: Message, state: FSMContext) -> None:
    """
    Обработчик текстовых сообщений в режиме поиска чатов.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    await chats_search_handler.handle_search_query(message, state)


__all__ = [
    "router",
    "show_chats_list",
    "chats_handler",
]
