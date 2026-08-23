"""
Обработчик списка точек маршрута (FK_Type=4).

Поддерживает:
- Пагинацию
- Поиск по названию точки
- Отображение детальной информации о точке
- Навигацию между страницами
- Переход из заказов перевозчика (FK_Type=11 -> FK_Type=4)
"""

from typing import Any

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks.generic import GenericSearchHandler
from app.bot.dependencies import get_bot_manager
from app.bot.keyboards import ListKeyboardBuilder
from app.db import db_manager
from app.db.repositories import AvanpostUserRepository
from app.logger import bot_logger
from app.models import MessageActionType, MessageType

from .base import BaseListHandler

# Создание роутера для обработки callback-запросов
router = Router(name="aiogram_route_points_list")

# Репозиторий для работы с данными пользователей Avanpost
_avanpost_user_repo = AvanpostUserRepository()


class RoutePointsStates(StatesGroup):
    """Состояния для просмотра точек маршрута."""

    viewing_route_points = State()
    searching_route_points = State()


class RoutePointsListHandler(BaseListHandler):
    """
    Обработчик списка точек маршрута (FK_Type=4).

    Наследуется от BaseListHandler для универсальной обработки:
    - Отображение списка с пагинацией
    - Поиск по названию
    - Обработка выбора элемента
    - Навигация между страницами
    """

    def __init__(self) -> None:
        """
        Инициализация обработчика списка точек маршрута.

        Устанавливает:
        - Префикс callback_data: "route_points"
        - Тип списка: "route_points"
        - Размер страницы: 10 элементов
        - Состояния для просмотра и поиска
        """
        super().__init__(prefix="route_points", list_type="route_points", page_size=10)
        self.STATE_VIEWING = RoutePointsStates.viewing_route_points
        self.STATE_SEARCHING = RoutePointsStates.searching_route_points

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Загрузка данных точек маршрута из БД.

        Args:
            session: Сессия БД
            page: Номер страницы (начиная с 0)
            search_query: Поисковый запрос (опционально)
            **kwargs: Дополнительные параметры (avanpost_user_id, mission_id)

        Returns:
            dict: Словарь с данными:
                - items: Список точек маршрута
                - mission_name: Название миссии
                - total: Общее количество
                - page: Текущая страница
                - total_pages: Всего страниц
                - has_prev: Есть ли предыдущая страница
                - has_next: Есть ли следующая страница
                - search_query: Текущий поисковый запрос
                - error: Сообщение об ошибке (если есть)
        """
        avanpost_user_id = kwargs.get("avanpost_user_id")
        mission_id = kwargs.get("mission_id")

        if not avanpost_user_id or not mission_id:
            return {
                "items": [],
                "mission_name": None,
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": "User ID or Mission ID not provided",
            }

        try:
            data = await _avanpost_user_repo.get_mission_items_page(
                session=session,
                mission_id=mission_id,
                page=page,
                page_size=self.PAGE_SIZE,
                search_query=search_query,
            )

            return {
                "items": data.get("items", []),
                "mission_name": data.get("mission_name"),
                "total": data.get("total", 0),
                "page": data.get("page", 0),
                "total_pages": data.get("total_pages", 0),
                "has_prev": data.get("has_prev", False),
                "has_next": data.get("has_next", False),
                "search_query": data.get("search_query"),
            }
        except Exception as e:
            bot_logger.error(f"❌ Failed to load route points: {e}", exc_info=True)
            return {
                "items": [],
                "mission_name": None,
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
        Отображение списка точек маршрута.

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

        # Получение данных из состояния
        state_data = await state.get_data()
        avanpost_user_id = state_data.get("avanpost_user_id") or kwargs.get("avanpost_user_id")
        mission_id = state_data.get("selected_mission_id") or kwargs.get("mission_id")
        group_id = state_data.get("group_id")
        selected_user_id = state_data.get("selected_user_id")
        selected_user_name = state_data.get("selected_user_name")
        # parent_item_id = state_data.get("parent_item_id")

        if not avanpost_user_id or not mission_id:
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Не удалось определить пользователя или миссию.",
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
                    mission_id=mission_id,
                )

            # Проверка ошибок загрузки
            if data.get("error"):
                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка загрузки маршрута: {data['error']}",
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
                return

            items = data["items"]
            total = data["total"]
            mission_name = data.get("mission_name", "Маршрут")
            current_page = data["page"]
            total_pages = data["total_pages"]

            # Если точки не найдены
            if total == 0:
                empty_text = f"🗺️ **Маршрут: {mission_name}**\n\n"
                if search_query:
                    empty_text += f"🔍 По запросу `{search_query}` точки не найдены."
                else:
                    empty_text += "Нет точек в маршруте."

                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode=None,
                    reply_markup=await self.get_back_keyboard(state),
                )
                return

            # Формирование заголовка
            text = self.format_header(
                title=f"🗺️ **Маршрут: {mission_name}**",
                total=total,
                current_page=current_page,
                total_pages=total_pages,
                search_query=search_query,
            )

            # Создание клавиатуры
            builder = ListKeyboardBuilder(
                callback_prefix="route_points",
                buttons_per_row=2,
                item_icon="📍",
                max_name_length=30,
            )

            # Добавление кнопок навигации
            extra_buttons = []

            # Кнопка "Назад к заказам"
            extra_buttons.append(("🔙 Назад к заказам", "carrier_orders_back"))

            # Кнопка "В главное меню"
            if group_id:
                extra_buttons.append(("🏠 В главное меню", "action_home"))

            keyboard = builder.build(
                items=items,
                current_page=current_page,
                total_pages=total_pages,
                search_query=search_query,
                extra_buttons=extra_buttons if extra_buttons else None,
                item_name_formatter=lambda item: self._format_route_point_item(item),
                hide_pagination_if_single=True,
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
                    "selected_mission_id": mission_id,
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
            bot_logger.error(f"❌ Failed to show route points: {e}", exc_info=True)
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Произошла ошибка при загрузке маршрута. Попробуйте позже.",
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
        Обработка выбора точки маршрута.

        При выборе точки показывается детальная информация о точке.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            item_id: ID выбранной точки
            **kwargs: Дополнительные параметры
        """
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(
            text=f"📍 Информация о точке #{item_id}",
            event=callback,
        )

        # TODO: Добавить отображение детальной информации о точке маршрута

    async def get_state_keys(self) -> dict[str, str]:
        """
        Получение ключей для хранения состояния.

        Returns:
            dict: Словарь с ключами состояния
        """
        return {
            "page": "route_points_page",
            "search_query": "route_points_search_query",
            "page_before_search": "route_points_page_before_search",
            "search_message_id": "route_points_search_message_id",
            "total": "route_points_total",
            "total_pages": "route_points_total_pages",
        }

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
        # parent_item_id = state_data.get("parent_item_id")

        buttons = [
            InlineKeyboardButton(text="🔙 Назад к заказам", callback_data="carrier_orders_back"),
        ]

        if group_id:
            buttons.append(InlineKeyboardButton(text="🏠 В главное меню", callback_data="action_home"))

        if not buttons:
            buttons.append(InlineKeyboardButton(text="❌ Закрыть", callback_data="route_points_close"))

        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    @staticmethod
    def _format_route_point_item(item: dict[str, Any]) -> str:
        """
        Форматирование элемента точки маршрута для отображения.

        Args:
            item: Словарь с данными точки

        Returns:
            str: Отформатированное описание точки
        """
        name = item.get("name", f"Точка #{item.get('id', '?')}")
        description = item.get("description")
        # position = item.get("position")

        if description:
            desc_preview = description[:100] + "..." if len(description) > 100 else description
            return f"{name}\n   📝 {desc_preview}"

        return name  # type: ignore[no-any-return]


# Создание глобальных экземпляров для использования в других модулях
route_points_handler = RoutePointsListHandler()
route_points_search_handler = GenericSearchHandler(route_points_handler)


async def show_route_points_list(
    event: Message | CallbackQuery,
    state: FSMContext,
    page: int = 0,
    search_query: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Внешняя функция для отображения списка точек маршрута.

    Используется для вызова из других модулей.

    Args:
        event: Событие (Message или CallbackQuery)
        state: Состояние FSM
        page: Номер страницы
        search_query: Поисковый запрос
        **kwargs: Дополнительные параметры (avanpost_user_id, mission_id)
    """
    await route_points_handler.show_list(event, state, page, search_query, **kwargs)


# Регистрация обработчиков в роутере
@router.callback_query(lambda c: c.data.startswith("route_points_"))
async def handle_route_points_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик всех callback-запросов, начинающихся с "route_points_".

    Поддерживает:
    - Навигацию по страницам
    - Выбор точки
    - Закрытие списка
    - Поиск по точкам

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    await route_points_handler.handle(callback, state)


# Регистрация обработчика поисковых запросов
@router.message(RoutePointsStates.searching_route_points)
async def handle_route_points_search(message: Message, state: FSMContext) -> None:
    """
    Обработчик текстовых сообщений в режиме поиска точек маршрута.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    await route_points_search_handler.handle_search_query(message, state)


__all__ = [
    "router",
    "show_route_points_list",
    "route_points_handler",
    "RoutePointsStates",
]
