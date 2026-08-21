"""
Обработчик деталей чата - список сообщений в чате.

Поддерживает:
- Пагинацию сообщений
- Отображение форматированных сообщений в стиле Telegram
- Кнопки для каждого сообщения (Ответить, Вложения)
- Навигацию между страницами
- Переход из списка чатов
"""

from datetime import datetime
from typing import Any

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .....bot.callbacks.generic import GenericListCallbackHandler
from .....bot.dependencies import get_bot_manager
from .....db import db_manager
from .....db.repositories import AvanpostUserRepository
from .....logger import bot_logger
from .....models import MessageActionType, MessageType
from ....keyboards import ListKeyboardBuilder

# Создание роутера для обработки callback-запросов
router = Router(name="aiogram_chat_details")

# Репозиторий для работы с данными пользователей Avanpost
_avanpost_user_repo = AvanpostUserRepository()


class ChatDetailsStates(StatesGroup):
    """Состояния для деталей чата"""

    viewing_messages = State()


class ChatDetailsHandler(GenericListCallbackHandler):
    """
    Обработчик деталей чата - отображение списка сообщений.

    Наследуется от GenericListCallbackHandler для универсальной обработки:
    - Отображение сообщений с пагинацией
    - Форматирование сообщений в стиле Telegram
    - Кнопки действий для каждого сообщения
    - Навигация между страницами

    Особенности:
    - Использует get_chat_messages_page для загрузки данных
    - Отображает автора, дату и текст сообщения
    - Добавляет кнопки "Ответить" и "Вложения" для каждого сообщения
    - Поиск не поддерживается для сообщений (STATE_SEARCHING = None)
    """

    def __init__(self) -> None:
        """
        Инициализация обработчика деталей чата.

        Устанавливает:
        - Префикс callback_data: "chat_details"
        - Тип списка: "chat_details"
        - Размер страницы: 20 сообщений (больше, чем для обычных списков)
        - Состояние просмотра сообщений
        - Поиск отключен (STATE_SEARCHING = None)
        """
        super().__init__(prefix="chat_details", list_type="chat_details")
        self.PAGE_SIZE = 20  # Больше сообщений на страницу для чатов
        self.STATE_VIEWING = ChatDetailsStates.viewing_messages
        self.STATE_SEARCHING = None  # Поиск не поддерживается для сообщений

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Загрузка данных сообщений чата из БД.

        Args:
            session: Сессия БД
            page: Номер страницы (начиная с 0)
            search_query: Поисковый запрос (не используется для сообщений)
            **kwargs: Дополнительные параметры (avanpost_user_id, chat_id)

        Returns:
            dict: Словарь с данными:
                - items: Список сообщений
                - total: Общее количество
                - page: Текущая страница
                - total_pages: Всего страниц
                - has_prev: Есть ли предыдущая страница
                - has_next: Есть ли следующая страница
                - search_query: Текущий поисковый запрос
                - error: Сообщение об ошибке (если есть)
        """
        avanpost_user_id = kwargs.get("avanpost_user_id")
        chat_id = kwargs.get("chat_id")

        if not avanpost_user_id or not chat_id:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": "User ID or Chat ID not provided",
            }

        try:
            # Получение данных через репозиторий
            data = await _avanpost_user_repo.get_chat_messages_page(
                session=session,
                avanpost_user_id=avanpost_user_id,
                chat_id=chat_id,
                page=page,
                page_size=self.PAGE_SIZE,
            )

            return {
                "items": data.get("messages", []),
                "total": data.get("total", 0),
                "page": data.get("page", 0),
                "total_pages": data.get("total_pages", 0),
                "has_prev": data.get("has_prev", False),
                "has_next": data.get("has_next", False),
                "search_query": search_query,
            }
        except Exception as e:
            bot_logger.error(f"❌ Failed to load chat messages: {e}", exc_info=True)
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
        Отображение сообщений чата.

        Args:
            event: Событие (Message или CallbackQuery)
            state: Состояние FSM
            page: Номер страницы (начиная с 0)
            search_query: Поисковый запрос (не используется)
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

        # Получение ID пользователя Avanpost и чата из состояния или параметров
        state_data = await state.get_data()
        avanpost_user_id = state_data.get("avanpost_user_id") or kwargs.get("avanpost_user_id")
        chat_id_value = state_data.get("selected_chat_id") or kwargs.get("chat_id")
        group_id = state_data.get("group_id")
        selected_user_id = state_data.get("selected_user_id")
        selected_user_name = state_data.get("selected_user_name")
        parent_item_id = state_data.get("parent_item_id")

        if not avanpost_user_id or not chat_id_value:
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Не удалось определить пользователя или чат.",
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
            )
            return

        try:
            # Загрузка данных
            async with db_manager.get_session() as session:
                data = await self.load_data(
                    session, page, search_query, avanpost_user_id=avanpost_user_id, chat_id=chat_id_value
                )

            # Проверка ошибок загрузки
            if data.get("error"):
                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка загрузки сообщений: {data['error']}",
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
                return

            items = data["items"]
            total = data["total"]
            current_page = data["page"]
            total_pages = data["total_pages"]

            # Если сообщения не найдены
            if total == 0:
                empty_text = "💬 **Сообщения чата**\n\n"
                empty_text += "В этом чате пока нет сообщений."

                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=await self.get_back_keyboard(state),
                )
                return

            # Формирование текста с пагинацией
            start_item = current_page * self.PAGE_SIZE + 1
            end_item = min(start_item + self.PAGE_SIZE - 1, total)

            text = "💬 **Сообщения чата**\n\n"
            text += f"📊 Показаны: {start_item}-{end_item} из {total}\n"
            text += f"📄 Страница {current_page + 1} из {total_pages}\n\n"

            # Формирование сообщения в стиле Telegram
            for item in items:
                text += self._format_message(item)

            # Создание клавиатуры с кнопками для каждого сообщения
            builder = ListKeyboardBuilder(
                callback_prefix="chat_details",
                buttons_per_row=2,
                item_icon="",
                max_name_length=0,
            )

            # Добавление кнопок навигации
            extra_buttons = []

            if parent_item_id:
                extra_buttons.append(("🔙 Назад к чатам", f"action_back_{parent_item_id}"))

            # Кнопка "В главное меню"
            if group_id:
                extra_buttons.append(("🏠 В главное меню", "action_home"))

            # Добавление кнопки для каждого сообщения (ответить, вложения)
            message_buttons = []
            for item in items:
                # Кнопка "Ответить" для каждого сообщения
                message_buttons.append(
                    {"id": item["id"], "name": "📝 Ответить", "callback_data": f"chat_details_reply_{item['id']}"}
                )
                # Кнопка "Вложения" если есть вложения
                if item.get("has_attachments", False):
                    message_buttons.append(
                        {
                            "id": item["id"],
                            "name": "📎 Вложения",
                            "callback_data": f"chat_details_attachments_{item['id']}",
                        }
                    )

            keyboard = builder.build(
                items=message_buttons,
                current_page=current_page,
                total_pages=total_pages,
                search_query=search_query,
                extra_buttons=extra_buttons if extra_buttons else None,
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
            bot_logger.error(f"❌ Failed to show chat messages: {e}", exc_info=True)
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Произошла ошибка при загрузке сообщений. Попробуйте позже.",
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
        Обработка выбора действия с сообщением.

        Поддерживает:
        - Ответ на сообщение (reply)
        - Просмотр вложений (attachments)

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            item_id: ID выбранного сообщения
            **kwargs: Дополнительные параметры
        """
        bot_manager = get_bot_manager()

        # Определение типа действия из callback_data
        callback_data = callback.data
        if callback_data and "reply" in callback_data:
            await bot_manager.send_toast(
                text=f"📝 Ответ на сообщение #{item_id}",
                event=callback,
            )
            # TODO: Открыть форму для ответа на сообщение

        elif callback_data and "attachments" in callback_data:
            await bot_manager.send_toast(
                text=f"📎 Вложения сообщения #{item_id}",
                event=callback,
            )
            # TODO: Показать список вложений сообщения

        else:
            await bot_manager.send_toast(
                text=f"📋 Выбрано сообщение #{item_id}",
                event=callback,
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
            "page": "chat_details_page",
            "search_query": "chat_details_search_query",
            "page_before_search": "chat_details_page_before_search",
            "search_message_id": "chat_details_search_message_id",
            "total": "chat_details_total",
            "total_pages": "chat_details_total_pages",
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
        Создание клавиатуры с кнопкой "Назад к чатам".

        Args:
            state: Состояние FSM (не используется, но сохраняется для единообразия)

        Returns:
            InlineKeyboardMarkup: Клавиатура с кнопкой назад
        """
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        state_data = await state.get_data()
        group_id = state_data.get("group_id")
        parent_item_id = state_data.get("parent_item_id")

        buttons = []

        if parent_item_id:
            buttons.append(InlineKeyboardButton(text="🔙 Назад к чатам", callback_data=f"action_back_{parent_item_id}"))

        if group_id:
            buttons.append(InlineKeyboardButton(text="🏠 В главное меню", callback_data="action_home"))

        if not buttons:
            buttons.append(InlineKeyboardButton(text="❌ Закрыть", callback_data="chat_details_close"))

        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    @staticmethod
    def _format_message(item: dict[str, Any]) -> str:
        """
        Форматирование сообщения в стиле Telegram.

        Отображает:
        - Автора сообщения
        - Время отправки (в формате ДД.ММ.ГГГГ ЧЧ:ММ)
        - Текст сообщения (обрезается до 500 символов)
        - Разделитель между сообщениями

        Args:
            item: Словарь с данными сообщения

        Returns:
            str: Отформатированное сообщение
        """
        date = item.get("date", "")
        author = item.get("author_name") or f"Контакт #{item.get('author_contact_id')}"
        text = item.get("text") or ""

        # Обрезка длинного текста
        if text and len(text) > 500:
            text = text[:500] + "..."

        # Формирование сообщение
        result = f"👤 **{author}**\n"
        if date:
            # Преобразование даты в читаемый формат
            try:
                dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                date_str = dt.strftime("%d.%m.%Y %H:%M")
                result += f"🕐 {date_str}\n"
            except (ValueError, TypeError, AttributeError) as e:
                # Альтернативный парсинг, если формат отличается
                try:
                    dt = datetime.strptime(date[:19], "%Y-%m-%dT%H:%M:%S")
                    date_str = dt.strftime("%d.%m.%Y %H:%M")
                    result += f"🕐 {date_str}\n"
                except (ValueError, TypeError):
                    # Если не удалось распарсить - пропускаем
                    bot_logger.debug(f"Could not parse date: {date}, error: {e}")
        if text:
            result += f"📝 {text}\n"
        result += "─" * 30 + "\n"

        return result


# Создание глобального экземпляра для использования в других модулях
chat_details_handler = ChatDetailsHandler()


async def show_chat_details(
    event: Message | CallbackQuery,
    state: FSMContext,
    page: int = 0,
    search_query: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Внешняя функция для отображения сообщений чата.

    Используется для вызова из других модулей (например, из chats.py
    при выборе чата из списка).

    Args:
        event: Событие (Message или CallbackQuery)
        state: Состояние FSM
        page: Номер страницы
        search_query: Поисковый запрос (не используется)
        **kwargs: Дополнительные параметры (avanpost_user_id, chat_id)
    """
    await chat_details_handler.show_list(event, state, page, search_query, **kwargs)


# Регистрация обработчиков колбэков для деталей чата
@router.callback_query(lambda c: c.data.startswith("chat_details_"))
async def handle_chat_details_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик всех callback-запросов, начинающихся с "chat_details_".

    Поддерживает:
    - Навигацию по страницам
    - Выбор действий с сообщениями (reply, attachments)
    - Закрытие списка

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    await chat_details_handler.handle(callback, state)


# Регистрация обработчика текстовых сообщений в режиме просмотра чата
@router.message(ChatDetailsStates.viewing_messages)
async def handle_chat_details_message(message: Message, state: FSMContext) -> None:
    """
    Обработчик текстовых сообщений в режиме просмотра чата.

    Может использоваться для:
    - Ввода текста ответа на сообщение
    - Поиска по сообщениям (если будет добавлен)

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()
    await bot_manager.send_answer(
        text="💬 Введите текст для ответа на сообщение.",
        event=message,
        message_type=MessageType.COMMAND_ACTION_INFO,
        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
    )


__all__ = [
    "router",
    "show_chat_details",
    "chat_details_handler",
    "ChatDetailsStates",
]
