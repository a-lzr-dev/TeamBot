# app/bot/handlers/aiogram/lists/orders.py

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
from ..states import CarrierOrderStates, SubMenuStates

# Создание роутера
router = Router(name="aiogram_orders_list")

# Репозиторий
_avanpost_user_repo = AvanpostUserRepository()


class OrdersListHandler(GenericListCallbackHandler):
    """Обработчик списка заказов"""

    def __init__(self) -> None:
        super().__init__(prefix="orders", list_type="orders")
        self.PAGE_SIZE = 10
        self.STATE_VIEWING = SubMenuStates.viewing_orders
        self.STATE_SEARCHING = SubMenuStates.searching_orders

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Загрузка данных заказов"""
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
            data = await _avanpost_user_repo.get_user_orders_page(
                session=session,
                avanpost_user_id=avanpost_user_id,
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
            bot_logger.error(f"❌ Failed to load orders: {e}", exc_info=True)
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
        """Отображение списка заказов"""
        bot_manager = get_bot_manager()

        if isinstance(event, CallbackQuery):
            await event.answer()

        chat_id = self._get_chat_id(event)
        if not chat_id:
            return

        # Получение avanpost_user_id из состояния
        state_data = await state.get_data()
        avanpost_user_id = state_data.get("avanpost_user_id") or kwargs.get("avanpost_user_id")
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
            async with db_manager.get_session() as session:
                data = await self.load_data(session, page, search_query, avanpost_user_id=avanpost_user_id)

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

            if total == 0:
                empty_text = "📋 **Мои заказы**\n\n"
                if search_query:
                    empty_text += f"🔍 По запросу `{search_query}` заказы не найдены."
                else:
                    empty_text += "Нет заказов."

                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=self.get_back_keyboard(state),
                )
                return

            # Формирование текста
            start_item = current_page * self.PAGE_SIZE + 1
            end_item = min(start_item + self.PAGE_SIZE - 1, total)

            text = "📋 **Мои заказы**\n\n"
            if search_query:
                text += f"🔍 **Поиск:** `{search_query}`\n"
            text += f"📊 Показаны: {start_item}-{end_item} из {total}\n"
            text += f"📄 Страница {current_page + 1} из {total_pages}\n\n"

            # Создание клавиатуры через ListKeyboardBuilder
            builder = ListKeyboardBuilder(
                callback_prefix="orders",
                buttons_per_row=2,
                item_icon="📦",
                max_name_length=30,
            )

            parent_item_id = state_data.get("parent_item_id")
            extra_buttons = []

            # Кнопка "Назад к действиям"
            if parent_item_id:
                extra_buttons.append(("🔙 Назад к действиям", f"action_back_{parent_item_id}"))

            # Кнопка "В главное меню" - всегда показываем, если есть group_id
            group_id = state_data.get("group_id")
            if group_id:
                extra_buttons.append(("🏠 В главное меню", "action_home"))

            keyboard = builder.build(
                items=items,
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
                }
            )

            await bot_manager.send_message(
                chat_id=chat_id,
                text=text,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

        except Exception as e:
            bot_logger.error(f"❌ Failed to show orders: {e}", exc_info=True)
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
        """Обработка выбора заказа заказчика - открываем заказы перевозчика"""
        bot_manager = get_bot_manager()

        # Получение ID пользователя из состояния
        state_data = await state.get_data()
        bot_logger.debug(f"🔍 [orders.on_select] state_data keys: {list(state_data.keys())}")
        bot_logger.debug(f"🔍 [orders.on_select] parent_item_id: {state_data.get('parent_item_id')}")

        avanpost_user_id = state_data.get("avanpost_user_id") or kwargs.get("avanpost_user_id")
        parent_item_id = state_data.get("parent_item_id")
        group_id = state_data.get("group_id")
        selected_user_id = state_data.get("selected_user_id")
        selected_user_name = state_data.get("selected_user_name")

        if not avanpost_user_id:
            await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
            return

        # Сохранение ID заказа заказчика в состоянии
        selected_order_id = item_id
        await state.update_data(
            selected_order_id=selected_order_id,
            selected_user_id=selected_user_id,
            selected_user_name=selected_user_name,
            group_id=group_id,
        )

        await bot_manager.send_toast(
            text=f"🚚 Загрузка заказов перевозчика для заказа #{selected_order_id}...",
            event=callback,
        )

        # Переключение состояния на просмотр заказов перевозчика
        await state.set_state(CarrierOrderStates.viewing_orders)
        await state.update_data(
            carrier_orders_page=0,
            carrier_orders_search_query=None,
            parent_item_id=parent_item_id,
            avanpost_user_id=avanpost_user_id,
            group_id=group_id,
            selected_user_id=selected_user_id,
            selected_user_name=selected_user_name,
        )

        # Отображение заказов перевозчика
        from .carrier_orders import show_carrier_orders_list

        await show_carrier_orders_list(
            event=callback,
            state=state,
            avanpost_user_id=avanpost_user_id,
            order_id=selected_order_id,
            page=0,
        )

    async def get_state_keys(self) -> dict[str, str]:
        """Получение ключей для состояния"""
        return {
            "page": "orders_page",
            "search_query": "orders_search_query",
            "page_before_search": "orders_page_before_search",
            "search_message_id": "orders_search_message_id",
            "total": "orders_total",
            "total_pages": "orders_total_pages",
        }

    @staticmethod
    def _get_chat_id(event: Message | CallbackQuery) -> int | None:
        """Получение ID чата из события"""
        if isinstance(event, Message):
            chat_id = event.chat.id
            return int(chat_id) if chat_id is not None else None
        if isinstance(event, CallbackQuery) and event.message:
            chat_id = event.message.chat.id
            return int(chat_id) if chat_id is not None else None
        return None

    @staticmethod
    def get_back_keyboard(state: FSMContext) -> Any:
        """Клавиатура с кнопкой назад"""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        state_data = state.get_data()
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
            buttons.append(InlineKeyboardButton(text="❌ Закрыть", callback_data="orders_close"))

        return InlineKeyboardMarkup(inline_keyboard=[buttons])


orders_handler = OrdersListHandler()
orders_search_handler = GenericSearchHandler(orders_handler)


async def show_orders_list(
    event: Message | CallbackQuery,
    state: FSMContext,
    page: int = 0,
    search_query: str | None = None,
    **kwargs: Any,
) -> None:
    """Внешняя функция для отображения списка заказов"""
    await orders_handler.show_list(event, state, page, search_query, **kwargs)


# Регистрация обработчиков в роутере
@router.callback_query(lambda c: c.data == "orders_back")
async def handle_orders_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к списку заказов."""
    bot_manager = get_bot_manager()
    await bot_manager.send_toast(text="🔙 Возврат к заказам...", event=callback)

    # Получение данных из состояния
    state_data = await state.get_data()
    avanpost_user_id = state_data.get("avanpost_user_id")
    #    group_id = state_data.get("group_id")

    if not avanpost_user_id:
        await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
        return

    # Возврат к списку заказов
    await show_orders_list(event=callback, state=state, avanpost_user_id=avanpost_user_id, page=0)


@router.callback_query(lambda c: c.data == "orders_back_to_list")
async def handle_orders_back_to_list(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик для кнопки 'Назад к заказам'"""
    bot_manager = get_bot_manager()
    bot_logger.debug("🔍 [handle_orders_back_to_list] START")

    await bot_manager.send_toast(text="🔙 Возврат к заказам...", event=callback)

    state_data = await state.get_data()
    avanpost_user_id = state_data.get("avanpost_user_id")
    parent_item_id = state_data.get("parent_item_id")
    group_id = state_data.get("group_id")
    selected_user_id = state_data.get("selected_user_id")
    selected_user_name = state_data.get("selected_user_name")

    bot_logger.debug(f"🔍 [handle_orders_back_to_list] parent_item_id={parent_item_id}")

    if not avanpost_user_id:
        await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
        return

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

    await show_orders_list(
        event=callback,
        state=state,
        avanpost_user_id=avanpost_user_id,
        page=0,
    )


@router.callback_query(lambda c: c.data.startswith("orders_"))
async def handle_orders_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка колбэков для заказов"""
    await orders_handler.handle(callback, state)


@router.message(SubMenuStates.searching_orders)
async def handle_orders_search(message: Message, state: FSMContext) -> None:
    """Обработка поискового запроса для заказов"""
    await orders_search_handler.handle_search_query(message, state)


__all__ = [
    "router",
    "show_orders_list",
    "orders_handler",
]
