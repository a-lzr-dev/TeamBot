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
from ..actions import SubMenuStates

router = Router(name="aiogram_vehicles_list")

_avanpost_user_repo = AvanpostUserRepository()


class VehiclesListHandler(GenericListCallbackHandler):
    """Обработчик списка транспорта"""

    def __init__(self) -> None:
        super().__init__(prefix="vehicles", list_type="vehicles")
        self.PAGE_SIZE = 10
        self.STATE_VIEWING = SubMenuStates.viewing_vehicles
        self.STATE_SEARCHING = SubMenuStates.searching_vehicles

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
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
            data = await _avanpost_user_repo.get_user_vehicles_page(
                session=session,
                avanpost_user_id=avanpost_user_id,
                page=page,
                page_size=self.PAGE_SIZE,
                search_query=search_query,
            )

            return {
                "items": data.get("vehicles", []),
                "total": data.get("total", 0),
                "page": data.get("page", 0),
                "total_pages": data.get("total_pages", 0),
                "has_prev": data.get("has_prev", False),
                "has_next": data.get("has_next", False),
                "search_query": data.get("search_query"),
            }
        except Exception as e:
            bot_logger.error(f"❌ Failed to load vehicles: {e}", exc_info=True)
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
        bot_manager = get_bot_manager()

        if isinstance(event, CallbackQuery):
            await event.answer()

        chat_id = self._get_chat_id(event)
        if not chat_id:
            return

        state_data = await state.get_data()
        avanpost_user_id = state_data.get("avanpost_user_id") or kwargs.get("avanpost_user_id")

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
                    text=f"❌ Ошибка загрузки транспорта: {data['error']}",
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
                empty_text = "🚗 **Мой транспорт**\n\n"
                if search_query:
                    empty_text += f"🔍 По запросу `{search_query}` транспорт не найден."
                else:
                    empty_text += "Нет транспорта."

                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=self.get_back_keyboard(state),
                )
                return

            start_item = current_page * self.PAGE_SIZE + 1
            end_item = min(start_item + self.PAGE_SIZE - 1, total)

            text = "🚗 **Мой транспорт**\n\n"
            if search_query:
                text += f"🔍 **Поиск:** `{search_query}`\n"
            text += f"📊 Показаны: {start_item}-{end_item} из {total}\n"
            text += f"📄 Страница {current_page + 1} из {total_pages}\n\n"

            builder = ListKeyboardBuilder(
                callback_prefix="vehicles",
                buttons_per_row=2,
                item_icon="🚗",
                max_name_length=30,
            )

            parent_item_id = state_data.get("parent_item_id")
            extra_buttons = []
            if parent_item_id:
                extra_buttons.append(("🔙 Назад к действиям", f"action_back_{parent_item_id}"))

            keyboard = builder.build(
                items=items,
                current_page=current_page,
                total_pages=total_pages,
                search_query=search_query,
                extra_buttons=extra_buttons if extra_buttons else None,
            )

            state_keys = await self.get_state_keys()
            await state.update_data(
                **{
                    state_keys["page"]: current_page,
                    state_keys["search_query"]: search_query,
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
            bot_logger.error(f"❌ Failed to show vehicles: {e}", exc_info=True)
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Произошла ошибка при загрузке транспорта. Попробуйте позже.",
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
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(
            text=f"🚗 Выбран транспорт #{item_id}",
            event=callback,
        )

    async def get_state_keys(self) -> dict[str, str]:
        return {
            "page": "vehicles_page",
            "search_query": "vehicles_search_query",
            "page_before_search": "vehicles_page_before_search",
            "search_message_id": "vehicles_search_message_id",
            "total": "vehicles_total",
            "total_pages": "vehicles_total_pages",
        }

    @staticmethod
    def _get_chat_id(event: Message | CallbackQuery) -> int | None:
        if isinstance(event, Message):
            chat_id = event.chat.id
            return int(chat_id) if chat_id is not None else None
        if isinstance(event, CallbackQuery) and event.message:
            chat_id = event.message.chat.id
            return int(chat_id) if chat_id is not None else None
        return None

    @staticmethod
    def get_back_keyboard(state: FSMContext) -> Any:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="vehicles_back")]]
        )


vehicles_handler = VehiclesListHandler()
vehicles_search_handler = GenericSearchHandler(vehicles_handler)


async def show_vehicles_list(
    event: Message | CallbackQuery,
    state: FSMContext,
    page: int = 0,
    search_query: str | None = None,
    **kwargs: Any,
) -> None:
    await vehicles_handler.show_list(event, state, page, search_query, **kwargs)


@router.callback_query(lambda c: c.data.startswith("vehicles_"))
async def handle_vehicles_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await vehicles_handler.handle(callback, state)


@router.message(SubMenuStates.searching_vehicles)
async def handle_vehicles_search(message: Message, state: FSMContext) -> None:
    await vehicles_search_handler.handle_search_query(message, state)


__all__ = [
    "router",
    "show_vehicles_list",
    "vehicles_handler",
]
