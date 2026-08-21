"""
Обработчик списка заказов перевозчика (FK_Type=11).

Поддерживает:
- Пагинацию
- Поиск по названию
- Отображение детальной информации о заказах
- Навигацию между страницами
- Переход из списка заказов заказчика (FK_Type=8 -> FK_Type=11)
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
from ..states import CarrierOrderStates

# Создание роутера для обработки callback-запросов
router = Router(name="aiogram_carrier_orders_list")

# Репозиторий для работы с данными пользователей Avanpost
_avanpost_user_repo = AvanpostUserRepository()


class CarrierOrdersListHandler(GenericListCallbackHandler):
    """
    Обработчик списка заказов перевозчика (FK_Type=11).

    Наследуется от GenericListCallbackHandler для универсальной обработки:
    - Отображение списка с пагинацией
    - Поиск по названию
    - Обработка выбора элемента
    - Навигация между страницами

    Особенности:
    - Загружает данные через get_carrier_orders_page
    - Отображает дополнительную информацию (статус, приоритет)
    - Поддерживает переход из списка заказов заказчика
    - Использует buttons_per_row=1 для детального отображения
    """

    def __init__(self) -> None:
        """
        Инициализация обработчика списка заказов перевозчика.

        Устанавливает:
        - Префикс callback_data: "carrier_orders"
        - Тип списка: "carrier_orders"
        - Размер страницы: 10 элементов
        - Состояния для просмотра и поиска
        """
        super().__init__(prefix="carrier_orders", list_type="заказов перевозчиков")
        self.PAGE_SIZE = 10
        self.STATE_VIEWING = CarrierOrderStates.viewing_orders
        self.STATE_SEARCHING = CarrierOrderStates.searching_orders

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Загрузка данных заказов перевозчика из БД.

        Args:
            session: Сессия БД
            page: Номер страницы (начиная с 0)
            search_query: Поисковый запрос (опционально)
            **kwargs: Дополнительные параметры (avanpost_user_id)

        Returns:
            dict: Словарь с данными:
                - items: Список заказов перевозчика
                - total: Общее количество
                - page: Текущая страница
                - total_pages: Всего страниц
                - has_prev: Есть ли предыдущая страница
                - has_next: Есть ли следующая страница
                - search_query: Текущий поисковый запрос
                - error: Сообщение об ошибке (если есть)
        """
        avanpost_user_id = kwargs.get("avanpost_user_id")
        order_id = kwargs.get("order_id")
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
            data = await _avanpost_user_repo.get_carrier_orders_page(
                session=session,
                avanpost_user_id=avanpost_user_id,
                order_id=order_id,
                page=page,
                page_size=self.PAGE_SIZE,
                search_query=search_query,
            )

            return {
                "items": data.get("orders", []),
                "total": data.get("total", 0),
                "page": data.get("page", 0),
                "total_pages": data.get("total_pages", 0),
                "has_prev": data.get("has_prev", False),
                "has_next": data.get("has_next", False),
                "search_query": data.get("search_query"),
            }
        except Exception as e:
            bot_logger.error(f"❌ Failed to load carrier orders: {e}", exc_info=True)
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
        Отображение списка заказов перевозчика.

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
        order_id = state_data.get("selected_order_id") or kwargs.get("order_id")
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
                data = await self.load_data(
                    session,
                    page,
                    search_query,
                    avanpost_user_id=avanpost_user_id,
                    order_id=order_id,
                )

            # Проверка ошибок загрузки
            if data.get("error"):
                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка загрузки заказов: {data['error']}",
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
                return

            items = data["items"]
            total = data["total"]
            current_page = data["page"]
            total_pages = data["total_pages"]

            # Если заказы не найдены
            if total == 0:
                empty_text = "📋 **Заказы перевозчиков**\n\n"
                if search_query:
                    empty_text += f"🔍 По запросу `{search_query}` заказы не найдены."
                else:
                    empty_text += "Нет заказов."

                # Формирование кнопки "Назад к заказам"
                extra_buttons = []
                parent_item_id = state_data.get("parent_item_id")

                # Если есть order_id - мы пришли из заказов заказчика
                if order_id is not None:
                    extra_buttons.append(("🔙 Назад к заказам", "orders_back_to_list"))
                elif parent_item_id:
                    extra_buttons.append(("🔙 Назад к действиям", f"action_back_{parent_item_id}"))

                # Кнопка "В главное меню"
                if group_id:
                    extra_buttons.append(("🏠 В главное меню", "action_home"))

                keyboard = self.get_back_keyboard(state, extra_buttons)

                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                return

            # Формирование текста с пагинацией
            start_item = current_page * self.PAGE_SIZE + 1
            end_item = min(start_item + self.PAGE_SIZE - 1, total)

            text = "📋 **Заказы перевозчиков**\n\n"
            if search_query:
                text += f"🔍 **Поиск:** `{search_query}`\n"
            text += f"📊 Показаны: {start_item}-{end_item} из {total}\n"
            text += f"📄 Страница {current_page + 1} из {total_pages}\n\n"

            # Создание клавиатуры с дополнительной информацией
            builder = ListKeyboardBuilder(
                callback_prefix="carrier_orders",
                buttons_per_row=1,
                item_icon="🚛",
                max_name_length=120,
            )

            # Добавление кнопок навигации
            parent_item_id = state_data.get("parent_item_id")
            extra_buttons = []

            # Если есть order_id - мы пришли из заказов заказчика
            if order_id is not None:
                extra_buttons.append(("🔙 Назад к заказам", "orders_back_to_list"))
            elif parent_item_id:
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
                item_name_formatter=lambda item: self._format_order_item(item),
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
            bot_logger.error(f"❌ Failed to show carrier orders: {e}", exc_info=True)
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Произошла ошибка при загрузке заказов. Попробуйте позже.",
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
        Обработка выбора заказа перевозчика.

        При выборе заказа показывается детальная информация о заказе.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            item_id: ID выбранного заказа (ID миссии)
            **kwargs: Дополнительные параметры
        """
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(
            text=f"📋 Детали заказа перевозчика #{item_id}",
            event=callback,
        )

        # TODO: Добавить отображение детальной информации о заказе перевозчика

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
            "page": "carrier_orders_page",
            "search_query": "carrier_orders_search_query",
            "page_before_search": "carrier_orders_page_before_search",
            "search_message_id": "carrier_orders_search_message_id",
            "total": "carrier_orders_total",
            "total_pages": "carrier_orders_total_pages",
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
    def get_back_keyboard(
        state: FSMContext,
        extra_buttons: list[tuple[str, str]] | None = None,
    ) -> Any:
        """
        Создание клавиатуры с кнопкой "Назад".

        Args:
            state: Состояние FSM (не используется, но сохраняется для единообразия)
            extra_buttons: Список дополнительных кнопок (текст, callback_data)

        Returns:
            InlineKeyboardMarkup: Клавиатура с кнопкой назад
        """
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        # Базовые кнопки
        buttons = []

        # Дополнительные кнопки
        if extra_buttons:
            for text, callback_data in extra_buttons:
                buttons.append(InlineKeyboardButton(text=text, callback_data=callback_data))

        # Кнопка закрытия, если нет других кнопок
        if not buttons:
            buttons.append(InlineKeyboardButton(text="❌ Закрыть", callback_data="carrier_orders_close"))

        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    @staticmethod
    def _format_order_item(item: dict[str, Any]) -> str:
        """
        Форматирование элемента заказа перевозчика с дополнительной информацией.

        Отображает:
        - Название заказа
        - Дополнительную информацию (маршрут, статус, приоритет)
        - Индикаторы текущего/следующего заказа

        Args:
            item: Словарь с данными заказа

        Returns:
            str: Отформатированное описание заказа
        """
        name = item.get("name")
        if name is None:
            item_id = item.get("id", "?")
            name = f"Заказ перевозчика #{item_id}"

        info = item.get("info")
        if info:
            info_preview = info[:100] + "..." if len(info) > 100 else info
            return f"{name}\n   📝 {info_preview}"

        return f"{name}"


# Создание глобальных экземпляров для использования в других модулях
carrier_orders_handler = CarrierOrdersListHandler()
carrier_orders_search_handler = GenericSearchHandler(carrier_orders_handler)


async def show_carrier_orders_list(
    event: Message | CallbackQuery,
    state: FSMContext,
    order_id: int | None = None,
    page: int = 0,
    search_query: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Внешняя функция для отображения списка заказов перевозчика.

    Используется для вызова из других модулей (например, из actions.py
    при FK_Type=11 или из orders.py при переходе из заказов заказчика).

    Args:
        event: Событие (Message или CallbackQuery)
        state: Состояние FSM
        order_id: ID заказа заказчика
        page: Номер страницы
        search_query: Поисковый запрос
        **kwargs: Дополнительные параметры
    """
    await carrier_orders_handler.show_list(event, state, page, search_query, order_id=order_id, **kwargs)


# Регистрация обработчиков в роутере
@router.callback_query(lambda c: c.data == "carrier_orders_back")
async def handle_carrier_orders_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к списку заказов заказчика."""
    from ....dependencies import get_bot_manager
    from .orders import show_orders_list

    bot_manager = get_bot_manager()
    await bot_manager.send_toast(text="🔙 Возврат к заказам...", event=callback)

    # Получение данных из состояния
    state_data = await state.get_data()
    avanpost_user_id = state_data.get("avanpost_user_id")
    parent_item_id = state_data.get("parent_item_id")
    group_id = state_data.get("group_id")
    selected_user_id = state_data.get("selected_user_id")
    selected_user_name = state_data.get("selected_user_name")

    if not avanpost_user_id:
        await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
        return

    # Переключение состояния на просмотр заказов заказчика
    from ..states import SubMenuStates

    await state.set_state(SubMenuStates.viewing_orders)
    await state.update_data(
        orders_page=0,
        orders_search_query=None,
        parent_item_id=parent_item_id,
        avanpost_user_id=avanpost_user_id,
        selected_order_id=None,
        group_id=group_id,
        selected_user_id=selected_user_id,
        selected_user_name=selected_user_name,
    )

    # Отображение списка заказов заказчика
    await show_orders_list(
        event=callback,
        state=state,
        avanpost_user_id=avanpost_user_id,
        page=0,
    )


@router.callback_query(lambda c: c.data.startswith("carrier_orders_"))
async def handle_carrier_orders_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик всех callback-запросов, начинающихся с "carrier_orders_".

    Поддерживает:
    - Навигацию по страницам
    - Выбор заказа
    - Закрытие списка
    - Поиск по заказам

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    await carrier_orders_handler.handle(callback, state)


# Регистрация обработчика поисковых запросов
@router.message(CarrierOrderStates.searching_orders)
async def handle_carrier_orders_search(message: Message, state: FSMContext) -> None:
    """
    Обработчик текстовых сообщений в режиме поиска заказов перевозчика.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    await carrier_orders_search_handler.handle_search_query(message, state)


__all__ = [
    "router",
    "show_carrier_orders_list",
    "carrier_orders_handler",
    "CarrierOrderStates",
]
