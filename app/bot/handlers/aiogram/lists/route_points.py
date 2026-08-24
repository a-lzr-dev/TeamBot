"""Обработчик списка точек маршрута (FK_Type=4).

Поддерживает:
- Отображение точек маршрута с нумерацией (FPosition)
- Ссылка "Подробнее" для каждой точки
- Пагинацию
- Поиск по названию точки
- Навигацию между страницами
- Переход из заказов перевозчика (FK_Type=11 -> FK_Type=4)
"""

from typing import Any

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callbacks.generic import GenericSearchHandler
from app.bot.dependencies import get_bot_manager
from app.config import settings
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
    viewing_point_details = State()
    searching_route_points = State()


class RoutePointsListHandler(BaseListHandler):
    """Обработчик списка точек маршрута (FK_Type=4).

    Наследуется от BaseListHandler для универсальной обработки:
    - Отображение списка с пагинацией
    - Поиск по названию
    - Обработка выбора элемента
    - Навигация между страницами
    """

    def __init__(self) -> None:
        """Инициализация обработчика списка точек маршрута.

        Устанавливает:
        - Префикс callback_data: "route_points"
        - Тип списка: "route_points"
        - Размер страницы: 10 элементов
        - Состояния для просмотра и поиска
        """
        super().__init__(prefix="route_points", list_type="route_points", page_size=10)
        self.STATE_VIEWING = RoutePointsStates.viewing_route_points
        self.STATE_SEARCHING = RoutePointsStates.searching_route_points
        self.PAGE_SIZE = 10

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Загрузка данных точек маршрута из БД.

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
        """Отображение списка точек маршрута с нумерацией и ссылками "Подробнее"."""
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
        parent_item_id = state_data.get("parent_item_id")

        if not avanpost_user_id or not mission_id:
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Не удалось определить пользователя или миссию.",
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="HTML",
                reply_markup=await self.get_back_keyboard(state),
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
                    parse_mode="HTML",
                    reply_markup=await self.get_back_keyboard(state),
                )
                return

            items = data["items"]
            total = data["total"]
            mission_name = data.get("mission_name", "Маршрут")
            current_page = data["page"]
            total_pages = data["total_pages"]

            # Если точки не найдены
            if total == 0:
                empty_text = f"🗺️ <b>Маршрут: {mission_name}</b>\n\n"
                if search_query:
                    empty_text += f"🔍 По запросу <code>{search_query}</code> точки не найдены."
                else:
                    empty_text += "Нет точек в маршруте."

                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="HTML",
                    reply_markup=await self.get_back_keyboard(state),
                )
                return

            # Формирование заголовка
            start_item = current_page * self.PAGE_SIZE + 1
            end_item = min(start_item + self.PAGE_SIZE - 1, total)

            header = (
                f"🗺️ <b>Маршрут: {mission_name}</b>\n\n"
                f"📊 Показаны: {start_item}-{end_item} из {total}\n"
                f"📄 Страница {current_page + 1} из {total_pages}\n\n"
            )

            # Форматирование точек с нумерацией и ссылкой "Подробнее"
            formatted_items = []
            bot_username = settings.BOT_USERNAME

            for idx, item in enumerate(items, start=start_item):
                position = item.get("position")
                if position is None:
                    position = idx

                name = item.get("name", f"Точка #{item.get('id', '?')}")
                description = item.get("description")
                item_id = item.get("id")

                line = f"📍 <b>{position}.</b> {name}"

                if description:
                    desc_preview = description[:100] + "..." if len(description) > 100 else description
                    line += f"\n   📝 {desc_preview}"

                if item_id and bot_username:
                    deep_link = f"https://t.me/{bot_username}?start=route_point_{item_id}"
                    line += f"\n   🔗 <a href='{deep_link}'>Подробнее</a>"

                formatted_items.append(line)

            # Объединение всех точек
            full_text = header + "\n".join(formatted_items)

            # Проверка, помещается ли всё в одно сообщение
            if len(full_text) > 4000:
                # Разбиваем на части
                await self._send_split_messages(
                    bot_manager=bot_manager,
                    chat_id=chat_id,
                    header=header,
                    items=formatted_items,
                    state=state,
                )
            else:
                # Отправка одним сообщением с клавиатурой
                keyboard = await self._build_keyboard(
                    current_page=current_page,
                    total_pages=total_pages,
                    total=total,
                    parent_item_id=parent_item_id,
                    group_id=group_id,
                    state=state,
                )

                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=full_text,
                    message_type=MessageType.COMMAND_ACTION,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="HTML",
                    reply_markup=keyboard,
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
                    "route_points_total": total,
                }
            )

        except Exception as e:
            bot_logger.error(f"❌ Failed to show route points: {e}", exc_info=True)
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Произошла ошибка при загрузке маршрута. Попробуйте позже.",
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="HTML",
                reply_markup=await self.get_back_keyboard(state),
            )

    async def _send_split_messages(
        self,
        bot_manager: Any,
        chat_id: int,
        header: str,
        items: list[str],
        state: FSMContext,
    ) -> None:
        """Отправка длинного списка точек разбитыми сообщениями.

        Args:
            bot_manager: Менеджер бота
            chat_id: ID чата
            header: Заголовок сообщения
            items: Список отформатированных точек
            state: Состояние FSM
        """
        state_data = await state.get_data()
        parent_item_id = state_data.get("parent_item_id")
        group_id = state_data.get("group_id")

        current_text = header
        batch_items: list[str] = []

        for formatted_item in items:
            test_text = current_text + "\n".join(batch_items) + "\n" + formatted_item
            if len(test_text) > 4000:
                # Отправка накопленного текста
                if batch_items:
                    send_text = current_text + "\n".join(batch_items)

                    # Первая часть — без клавиатуры
                    await bot_manager.send_message(
                        chat_id=chat_id,
                        text=send_text,
                        message_type=MessageType.COMMAND_ACTION,
                        delete_by_type=None,
                        parse_mode="HTML",
                        reply_markup=None,
                    )

                    # Удаляем заголовок для следующих частей
                    current_text = ""

                # Начало новой части
                batch_items = [formatted_item]
            else:
                batch_items.append(formatted_item)

        # Отправка последней части с клавиатурой
        if batch_items:
            send_text = current_text + "\n".join(batch_items)
            keyboard = await self._build_keyboard(
                current_page=0,
                total_pages=1,
                total=0,
                parent_item_id=parent_item_id,
                group_id=group_id,
                state=state,
            )

            await bot_manager.send_message(
                chat_id=chat_id,
                text=send_text,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=None,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

    async def _build_keyboard(
        self,
        current_page: int,
        total_pages: int,
        total: int,
        parent_item_id: int | None,
        group_id: int | None,
        state: FSMContext,
    ) -> InlineKeyboardMarkup:
        """Построение клавиатуры для маршрута.

        Args:
            current_page: Текущая страница
            total_pages: Всего страниц
            total: Общее количество точек
            parent_item_id: ID родительского элемента
            group_id: ID группы действий
            state: Состояние FSM

        Returns:
            InlineKeyboardMarkup: Клавиатура
        """
        keyboard = []

        # 1. Пагинация
        if total_pages > 1:
            page_row = self._build_pagination_row(current_page, total_pages)
            if page_row:
                keyboard.append(page_row)

        # 2. Кнопка "Загрузить еще"
        if current_page < total_pages - 1:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=f"📥 Загрузить еще {self.PAGE_SIZE} точек",
                        callback_data=f"route_points_load_more_{current_page + 1}",
                    )
                ]
            )

        # 3. Кнопка "К последним"
        if current_page < total_pages - 1:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text="⚡ К последним точкам",
                        callback_data=f"route_points_goto_last_{total_pages - 1}",
                    )
                ]
            )

        # 4. Информационная кнопка
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"📊 {current_page + 1}/{total_pages} • {total} точек",
                    callback_data="route_points_info",
                )
            ]
        )

        # 5. Навигационные кнопки
        nav_row = []

        # Кнопка "Назад к перевозкам" (изменено с "Назад к заказам")
        if parent_item_id is not None:
            nav_row.append(
                InlineKeyboardButton(
                    text="🔙 Назад к перевозкам",
                    callback_data=f"action_back_{parent_item_id}",
                )
            )
        else:
            nav_row.append(
                InlineKeyboardButton(
                    text="🔙 Назад к перевозкам",
                    callback_data="carrier_orders_back",
                )
            )

        # Кнопка "В главное меню"
        if group_id:
            nav_row.append(
                InlineKeyboardButton(
                    text="🏠 В главное меню",
                    callback_data="action_home",
                )
            )

        keyboard.append(nav_row)

        # 6. Кнопка закрытия
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="❌ Закрыть",
                    callback_data="route_points_close",
                )
            ]
        )

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def _build_pagination_row(self, current_page: int, total_pages: int) -> list[InlineKeyboardButton] | None:
        """Построение компактной строки пагинации.

        Args:
            current_page: Текущая страница
            total_pages: Всего страниц

        Returns:
            list[InlineKeyboardButton] | None: Строка кнопок пагинации
        """
        row: list[InlineKeyboardButton] = []

        # Кнопка "Назад"
        if current_page > 0:
            row.append(
                InlineKeyboardButton(
                    text="◀️",
                    callback_data=f"route_points_page_{current_page - 1}",
                )
            )

        # Номера страниц
        page_numbers = self._get_page_numbers(current_page, total_pages)
        for p in page_numbers:
            if p == current_page:
                row.append(
                    InlineKeyboardButton(
                        text=f"📍{p + 1}",
                        callback_data=f"route_points_page_{p}",
                    )
                )
            elif p is None:
                row.append(
                    InlineKeyboardButton(
                        text="…",
                        callback_data="route_points_info",
                    )
                )
            else:
                row.append(
                    InlineKeyboardButton(
                        text=f"{p + 1}",
                        callback_data=f"route_points_page_{p}",
                    )
                )

        # Кнопка "Вперед"
        if current_page < total_pages - 1:
            row.append(
                InlineKeyboardButton(
                    text="▶️",
                    callback_data=f"route_points_page_{current_page + 1}",
                )
            )

        return row if row else None

    @staticmethod
    def _get_page_numbers(current: int, total: int) -> list[int | None]:
        """Получение списка номеров страниц для отображения.

        Args:
            current: Текущая страница (0-based)
            total: Общее количество страниц

        Returns:
            list[int | None]: Список номеров страниц (None для разделителя)
        """
        if total <= 7:
            return list(range(total))

        result: list[int | None] = (
            [0]
            + ([None] if current > 2 else [])
            + [p for p in range(max(1, current - 1), min(total - 2, current + 2) + 1) if p != 0 and p != total - 1]
            + ([None] if current < total - 3 else [])
            + ([total - 1] if total - 1 not in [0] else [])
        )

        return list(dict.fromkeys(result))

    async def on_select(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        item_id: int,
        **kwargs: Any,
    ) -> None:
        """Обработка выбора точки маршрута.

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

        # Получение детальной информации о точке
        try:
            async with db_manager.get_session() as session:
                point_data = await _avanpost_user_repo.get_mission_item_details(
                    session=session,
                    item_id=item_id,
                )

            if not point_data:
                await bot_manager.send_toast(
                    text="❌ Информация о точке не найдена.",
                    event=callback,
                    show_alert=True,
                )
                return

            # Формирование текста с детальной информацией
            text = self._format_point_details(point_data)

            # Клавиатура для возврата
            state_data = await state.get_data()
            parent_item_id = state_data.get("parent_item_id")
            group_id = state_data.get("group_id")

            keyboard = self._build_details_keyboard(
                point_id=item_id,
                parent_item_id=parent_item_id,
                group_id=group_id,
            )

            # Отправка сообщения с деталями
            await bot_manager.send_message(
                chat_id=callback.message.chat.id,
                text=text,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        except Exception as e:
            bot_logger.error(f"❌ Failed to get point details: {e}", exc_info=True)
            await bot_manager.send_toast(
                text=f"❌ Ошибка загрузки информации: {str(e)[:100]}",
                event=callback,
                show_alert=True,
            )

    @staticmethod
    def _build_details_keyboard(
        point_id: int,
        parent_item_id: int | None,
        group_id: int | None,
    ) -> InlineKeyboardMarkup:
        """Построение клавиатуры для деталей точки.

        Args:
            point_id: ID точки
            parent_item_id: ID родительского элемента
            group_id: ID группы действий

        Returns:
            InlineKeyboardMarkup: Клавиатура
        """
        buttons = [
            InlineKeyboardButton(
                text="🔙 Назад к маршруту",
                callback_data=f"route_points_back_to_list_{point_id}",
            )
        ]

        if parent_item_id is not None:
            buttons.append(
                InlineKeyboardButton(
                    text="🔙 Назад к перевозкам",  # <-- ИЗМЕНЕНО
                    callback_data=f"action_back_{parent_item_id}",
                )
            )

        if group_id:
            buttons.append(
                InlineKeyboardButton(
                    text="🏠 В главное меню",
                    callback_data="action_home",
                )
            )

        buttons.append(
            InlineKeyboardButton(
                text="❌ Закрыть",
                callback_data="route_points_close",
            )
        )

        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    @staticmethod
    def _format_point_details(point_data: dict[str, Any]) -> str:
        """Форматирование детальной информации о точке.

        Args:
            point_data: Словарь с данными точки

        Returns:
            str: Отформатированный текст
        """
        name = point_data.get("name", "Точка маршрута")
        description = point_data.get("description", "")
        position = point_data.get("position")
        point_id = point_data.get("id")

        text = "📍 <b>Точка маршрута</b>\n\n"

        if position is not None:
            text += f"<b>Номер:</b> {position}\n"

        text += f"<b>Название:</b> {name}\n"

        if description:
            text += f"\n<b>Описание:</b>\n{description}\n"

        if point_id:
            text += f"\n🆔 ID: <code>{point_id}</code>"

        return text

    async def get_state_keys(self) -> dict[str, str]:
        """Получение ключей для хранения состояния.

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
    async def get_back_keyboard(state: FSMContext) -> InlineKeyboardMarkup:
        """Создание клавиатуры с кнопкой 'Назад'."""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        state_data = await state.get_data()
        group_id = state_data.get("group_id")
        parent_item_id = state_data.get("parent_item_id")
        return_to_carrier_orders = state_data.get("_return_to_carrier_orders", False)

        buttons = []

        # Кнопка "Назад к перевозкам"
        if return_to_carrier_orders:
            buttons.append(
                InlineKeyboardButton(
                    text="🔙 Назад к перевозкам",
                    callback_data="carrier_orders_back",
                )
            )
        elif parent_item_id is not None:
            buttons.append(
                InlineKeyboardButton(
                    text="🔙 Назад к перевозкам",
                    callback_data=f"action_back_{parent_item_id}",
                )
            )
        else:
            buttons.append(
                InlineKeyboardButton(
                    text="🔙 Назад к перевозкам",
                    callback_data="carrier_orders_back",
                )
            )

        if group_id:
            buttons.append(
                InlineKeyboardButton(
                    text="🏠 В главное меню",
                    callback_data="action_home",
                )
            )

        if not buttons:
            buttons.append(
                InlineKeyboardButton(
                    text="❌ Закрыть",
                    callback_data="route_points_close",
                )
            )

        return InlineKeyboardMarkup(inline_keyboard=[buttons])


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
    """Внешняя функция для отображения списка точек маршрута.

    Используется для вызова из других модулей.

    Args:
        event: Событие (Message или CallbackQuery)
        state: Состояние FSM
        page: Номер страницы
        search_query: Поисковый запрос
        **kwargs: Дополнительные параметры (avanpost_user_id, mission_id)
    """
    await route_points_handler.show_list(event, state, page, search_query, **kwargs)


# ============================================================
# ОБРАБОТЧИКИ КОЛБЭКОВ
# ============================================================


@router.callback_query(lambda c: c.data.startswith("route_points_"))
async def handle_route_points_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик всех callback-запросов, начинающихся с "route_points_".

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


@router.callback_query(lambda c: c.data == "route_points_close")
async def handle_route_points_close(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик закрытия списка точек маршрута."""
    bot_manager = get_bot_manager()
    await bot_manager.send_toast(text="❌ Список закрыт.", event=callback)

    state_data = await state.get_data()
    chat_id = callback.message.chat.id if callback.message else None
    message_ids = state_data.get("route_points_message_ids", [])

    if chat_id and message_ids:
        for msg_id in message_ids:
            try:
                await bot_manager.delete_message_by_id(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                bot_logger.debug(f"ℹ️ Could not delete message {msg_id}: {e}")

    await state.update_data(
        selected_mission_id=None,
        route_points_total=0,
        route_points_message_ids=[],
    )
    await state.set_state(None)

    if callback.message:
        try:
            await callback.message.delete()
        except Exception as e:
            bot_logger.warning(f"⚠️ Could not delete message: {e}")


@router.callback_query(lambda c: c.data.startswith("route_points_page_"))
async def handle_page_navigation(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка навигации по страницам."""
    try:
        page = int(callback.data.split("_")[-1])
        await route_points_handler.show_list(event=callback, state=state, page=page)
    except ValueError:
        await callback.answer("❌ Неверный номер страницы")


@router.callback_query(lambda c: c.data.startswith("route_points_load_more_"))
async def handle_load_more(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка кнопки 'Загрузить еще'."""
    try:
        page = int(callback.data.split("_")[-1])
        await callback.answer(f"📥 Загружаем страницу {page + 1}...")
        await route_points_handler.show_list(event=callback, state=state, page=page)
    except ValueError:
        await callback.answer("❌ Ошибка загрузки")


@router.callback_query(lambda c: c.data.startswith("route_points_goto_last_"))
async def handle_goto_last(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка кнопки 'К последним точкам'."""
    try:
        page = int(callback.data.split("_")[-1])
        await callback.answer("⚡ Переход к последним точкам...")
        await route_points_handler.show_list(event=callback, state=state, page=page)
    except ValueError:
        await callback.answer("❌ Ошибка перехода")


@router.callback_query(lambda c: c.data == "route_points_info")
async def handle_info(callback: CallbackQuery) -> None:
    """Информационная кнопка (неактивная)."""
    await callback.answer("ℹ️ Информация о странице")


@router.callback_query(lambda c: c.data.startswith("route_points_back_to_list_"))
async def handle_back_to_list(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к списку точек маршрута."""
    try:
        await callback.answer("🔙 Возврат к списку...")

        state_data = await state.get_data()
        mission_id = state_data.get("selected_mission_id")
        avanpost_user_id = state_data.get("avanpost_user_id")

        if not mission_id or not avanpost_user_id:
            await callback.answer("❌ Не удалось определить миссию.")
            return

        await route_points_handler.show_list(
            event=callback,
            state=state,
            avanpost_user_id=avanpost_user_id,
            mission_id=mission_id,
            page=state_data.get("route_points_page", 0),
        )
    except ValueError:
        await callback.answer("❌ Ошибка возврата")


# Регистрация обработчика поисковых запросов
@router.message(RoutePointsStates.searching_route_points)
async def handle_route_points_search(message: Message, state: FSMContext) -> None:
    """Обработчик текстовых сообщений в режиме поиска точек маршрута.

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
