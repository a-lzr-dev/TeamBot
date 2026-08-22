"""
Обработчик деталей контакта - список контактной информации (FK_Type=7).

Поддерживает:
- Отображение списка контактной информации (телефоны, email, и т.д.)
- Переход из списка контактов
- Навигацию (назад к контактам, закрыть)
"""

import contextlib
from typing import Any

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .....bot.dependencies import get_bot_manager
from .....db import db_manager
from .....db.repositories import AvanpostUserRepository
from .....logger import bot_logger
from ..states import SubMenuStates
from .base import BaseDetailsHandler

# Создание роутера для обработки callback-запросов
router = Router(name="aiogram_contact_details")

# Репозиторий для работы с данными пользователей Avanpost
_avanpost_user_repo = AvanpostUserRepository()


class ContactDetailsStates(StatesGroup):
    """Состояния для деталей контакта"""

    viewing_details = State()


class ContactDetailsHandler(BaseDetailsHandler):
    """
    Обработчик деталей контакта - отображение контактной информации.

    Особенности:
    - Загружает данные через get_contact_details
    - Отображает список контактной информации (телефоны, email, и т.д.)
    - Простая навигация без пагинации
    """

    def __init__(self) -> None:
        """Инициализация обработчика деталей контакта."""
        super().__init__(prefix="contact_details", list_type="contact_details", page_size=10)
        self.STATE_VIEWING = ContactDetailsStates.viewing_details

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Загрузка данных контактной информации из БД.

        Args:
            session: Сессия БД
            page: Номер страницы (начиная с 0)
            search_query: Поисковый запрос (не используется)
            **kwargs: Дополнительные параметры (avanpost_user_id, contact_id)

        Returns:
            dict: Словарь с данными:
                - items: Список контактной информации
                - total: Общее количество
                - page: Текущая страница
                - total_pages: Всего страниц
                - has_prev: Есть ли предыдущая страница
                - has_next: Есть ли следующая страница
                - error: Сообщение об ошибке (если есть)
        """
        avanpost_user_id = kwargs.get("avanpost_user_id")
        contact_id = kwargs.get("contact_id")

        if not avanpost_user_id or not contact_id:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "error": "User ID or Contact ID not provided",
            }

        try:
            data = await _avanpost_user_repo.get_contact_details_page(
                session=session,
                avanpost_user_id=avanpost_user_id,
                contact_id=contact_id,
                page=page,
                page_size=self.PAGE_SIZE,
            )

            return {
                "items": data.get("details", []),
                "total": data.get("total", 0),
                "page": data.get("page", 0),
                "total_pages": data.get("total_pages", 0),
                "has_prev": data.get("has_prev", False),
                "has_next": data.get("has_next", False),
            }
        except Exception as e:
            bot_logger.error(f"❌ Failed to load contact details: {e}", exc_info=True)
            return {
                "items": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
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
        Отображение контактной информации.
        """
        # bot_manager = get_bot_manager()

        if isinstance(event, CallbackQuery):
            await event.answer()

        chat_id = self._get_chat_id(event)
        if not chat_id:
            return

        state_data = await state.get_data()
        avanpost_user_id = state_data.get("avanpost_user_id") or kwargs.get("avanpost_user_id")
        contact_id = state_data.get("selected_contact_id") or kwargs.get("contact_id")
        parent_item_id = state_data.get("parent_item_id")
        group_id = state_data.get("group_id")
        selected_user_id = state_data.get("selected_user_id")
        selected_user_name = state_data.get("selected_user_name")

        if not avanpost_user_id or not contact_id:
            await self.send_details_message(
                event=event,
                state=state,
                text="❌ Не удалось определить пользователя или контакт.",
                keyboard=None,
            )
            return

        try:
            async with db_manager.get_session() as session:
                data = await self.load_data(
                    session, page, search_query, avanpost_user_id=avanpost_user_id, contact_id=contact_id
                )

            if data.get("error"):
                await self.send_details_message(
                    event=event,
                    state=state,
                    text=f"❌ Ошибка загрузки контактной информации: {data['error']}",
                    keyboard=None,
                )
                return

            items = data["items"]
            total = data["total"]

            if total == 0:
                await self.send_details_message(
                    event=event,
                    state=state,
                    text="📋 **Контактная информация**\n\nНет данных.",
                    keyboard=self._build_keyboard(parent_item_id, group_id),
                )
                return

            # Получение имени контакта
            contact_name = await self._get_contact_name(session, contact_id)

            # Формирование заголовка
            header = f"📋 **Контактная информация**\n👤 {contact_name or f'Контакт #{contact_id}'}\n\n"

            # Форматирование всех записей
            formatted_items = [self._format_detail_item(item) for item in items]
            full_text = header + "".join(formatted_items)

            # Отправка сообщения
            await self.send_details_message(
                event=event,
                state=state,
                text=full_text,
                keyboard=self._build_keyboard(parent_item_id, group_id),
            )

            # Сохранение состояния
            await state.update_data(
                selected_user_id=selected_user_id,
                selected_user_name=selected_user_name,
                group_id=group_id,
                contact_details_total=total,
            )

        except Exception as e:
            bot_logger.error(f"❌ Failed to show contact details: {e}", exc_info=True)
            await self.send_details_message(
                event=event,
                state=state,
                text="❌ Произошла ошибка при загрузке контактной информации. Попробуйте позже.",
                keyboard=None,
            )

    async def on_select(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        item_id: int,
        **kwargs: Any,
    ) -> None:
        """Обработка выбора элемента контактной информации."""
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(
            text=f"ℹ️ Детали контакта #{item_id}",
            event=callback,
        )

    @staticmethod
    def _build_keyboard(parent_item_id: int | None, group_id: int | None) -> InlineKeyboardMarkup:
        """
        Построение клавиатуры для деталей контакта.
        """
        # Кнопка "Назад к контактам"
        buttons = [
            InlineKeyboardButton(
                text="🔙 Назад к контактам",
                callback_data="contact_details_back_to_contacts",
            )
        ]

        if parent_item_id:
            buttons.append(
                InlineKeyboardButton(
                    text="🔙 Назад к действиям",
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
                callback_data="contact_details_close",
            )
        )

        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    @staticmethod
    async def _get_contact_name(session: Any, contact_id: int) -> str | None:
        """Получение имени контакта."""
        try:
            return await _avanpost_user_repo.get_contact_name(session, contact_id, lang_code="RU")  # type: ignore[no-any-return]
        except Exception:
            return None

    @staticmethod
    def _format_detail_item(item: dict[str, Any]) -> str:
        """Форматирование элемента контактной информации."""
        contact_type = item.get("type_name", "Контакт")
        contact_value = item.get("contact", "")
        description = item.get("description", "")

        result = f"📌 **{contact_type}**"
        if contact_value:
            result += f": `{contact_value}`"
        if description:
            result += f"\n   📝 {description}"
        result += "\n"

        return result


# Создание глобального экземпляра
contact_details_handler = ContactDetailsHandler()


async def show_contact_details(
    event: Message | CallbackQuery,
    state: FSMContext,
    page: int = 0,
    search_query: str | None = None,
    **kwargs: Any,
) -> None:
    """Внешняя функция для отображения контактной информации."""
    await contact_details_handler.show_list(event, state, page, search_query, **kwargs)


# ============================================================
# ОБРАБОТЧИКИ КОЛБЭКОВ
# ============================================================


@router.callback_query(lambda c: c.data == "contact_details_back_to_contacts")
async def handle_back_to_contacts(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка кнопки 'Назад к контактам'."""
    bot_manager = get_bot_manager()
    await bot_manager.send_toast(text="🔙 Возврат к списку контактов...", event=callback)

    state_data = await state.get_data()
    avanpost_user_id = state_data.get("avanpost_user_id")
    parent_item_id = state_data.get("parent_item_id")
    group_id = state_data.get("group_id")
    selected_user_id = state_data.get("selected_user_id")
    selected_user_name = state_data.get("selected_user_name")

    if not avanpost_user_id:
        await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
        return

    await state.set_state(SubMenuStates.viewing_contacts)
    await state.update_data(
        contacts_page=0,
        contacts_search_query=None,
        parent_item_id=parent_item_id,
        avanpost_user_id=avanpost_user_id,
        selected_contact_id=None,
        group_id=group_id,
        selected_user_id=selected_user_id,
        selected_user_name=selected_user_name,
    )

    if callback.message:
        with contextlib.suppress(Exception):
            await callback.message.delete()

    from ..lists.contacts import show_contacts_list

    await show_contacts_list(
        event=callback,
        state=state,
        avanpost_user_id=avanpost_user_id,
        page=0,
    )


@router.callback_query(lambda c: c.data == "contact_details_close")
async def handle_close(callback: CallbackQuery, state: FSMContext) -> None:
    """Закрытие деталей контакта."""
    bot_manager = get_bot_manager()
    await bot_manager.send_toast(text="❌ Контактная информация закрыта.", event=callback)

    chat_id = callback.message.chat.id if callback.message else None
    state_data = await state.get_data()
    message_ids = state_data.get("contact_details_message_ids", [])

    if chat_id and message_ids:
        for msg_id in message_ids:
            with contextlib.suppress(Exception):
                await bot_manager.delete_message_by_id(chat_id=chat_id, message_id=msg_id)

    await state.update_data(
        selected_contact_id=None,
        contact_details_total=0,
        contact_details_message_ids=[],
    )
    await state.set_state(None)

    if callback.message:
        with contextlib.suppress(Exception):
            await callback.message.delete()


__all__ = [
    "router",
    "show_contact_details",
    "contact_details_handler",
    "ContactDetailsStates",
]
