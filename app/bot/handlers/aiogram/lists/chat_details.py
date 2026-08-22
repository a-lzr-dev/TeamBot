"""
Обработчик деталей чата - список сообщений в чате.

Поддерживает:
- Гибридную навигацию (пагинация + "Загрузить еще" + "К последним")
- Отображение форматированных сообщений в стиле Telegram с визуализацией направления
- Фильтрацию сообщений с FK_Direction = 3
- Контекстное меню через команду /msg
- Навигацию между страницами
- Переход из списка чатов
"""

import asyncio
from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .....bot.callbacks.generic import GenericListCallbackHandler
from .....bot.dependencies import get_bot_manager
from .....config import settings
from .....db import db_manager
from .....db.repositories import AvanpostUserRepository
from .....logger import bot_logger
from .....models import MessageActionType, MessageType

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

    Поддерживает гибридную навигацию:
    - Пагинация для быстрого перехода между страницами
    - Кнопка "Загрузить еще" для последовательного чтения
    - Кнопка "К последним" для перехода к свежим сообщениям
    - Фильтрация сообщений с FK_Direction = 3
    - Визуализация направления сообщений (входящие/исходящие)
    - Контекстное меню для каждого сообщения через команду /msg
    """

    def __init__(self) -> None:
        """Инициализация обработчика деталей чата."""
        super().__init__(prefix="chat_details", list_type="chat_details")
        self.PAGE_SIZE = 30
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
        Загрузка данных сообщений чата из БД с фильтрацией FK_Direction = 3.

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
            # Получение данных через репозиторий с исключением контрольных сообщений (FK_Direction = 3)
            data = await _avanpost_user_repo.get_chat_messages_page(
                session=session,
                avanpost_user_id=avanpost_user_id,
                chat_id=chat_id,
                page=page,
                page_size=self.PAGE_SIZE,
                exclude_direction=3,
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
        Отображение сообщений чата с гибридной навигацией.
        """
        bot_manager = get_bot_manager()

        if isinstance(event, CallbackQuery):
            await event.answer()

        chat_id = self._get_chat_id(event)
        if not chat_id:
            return

        state_data = await state.get_data()
        avanpost_user_id = state_data.get("avanpost_user_id") or kwargs.get("avanpost_user_id")
        chat_id_value = state_data.get("selected_chat_id") or kwargs.get("chat_id")
        group_id = state_data.get("group_id")
        selected_user_id = state_data.get("selected_user_id")
        selected_user_name = state_data.get("selected_user_name")
        parent_item_id = state_data.get("parent_item_id")

        # Удаление старых сообщений
        old_message_ids = state_data.get("chat_details_message_ids", [])
        if old_message_ids:
            for msg_id in old_message_ids:
                try:
                    await bot_manager.delete_message_by_id(chat_id=chat_id, message_id=msg_id)
                except Exception as e:
                    bot_logger.debug(f"ℹ️ Could not delete old message {msg_id}: {e}")
            await state.update_data(chat_details_message_ids=[])

        if not avanpost_user_id or not chat_id_value:
            result = await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Не удалось определить пользователя или чат.",
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=None,
                parse_mode="Markdown",
            )
            if result.get("success"):
                await state.update_data(chat_details_message_ids=[result.get("message_id")])
            return

        try:
            async with db_manager.get_session() as session:
                data = await self.load_data(
                    session, page, search_query, avanpost_user_id=avanpost_user_id, chat_id=chat_id_value
                )

            if data.get("error"):
                result = await bot_manager.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка загрузки сообщений: {data['error']}",
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=None,
                    parse_mode="Markdown",
                )
                if result.get("success"):
                    await state.update_data(chat_details_message_ids=[result.get("message_id")])
                return

            items = data["items"]
            total = data["total"]
            current_page = data["page"]
            total_pages = data["total_pages"]

            if total == 0:
                empty_text = "💬 **Сообщения чата**\n\nВ этом чате пока нет сообщений."
                keyboard = self._build_hybrid_keyboard(
                    current_page=0,
                    total_pages=1,
                    total=0,
                    parent_item_id=parent_item_id,
                    group_id=group_id,
                    state=state,
                )
                result = await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=None,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                if result.get("success"):
                    await state.update_data(chat_details_message_ids=[result.get("message_id")])
                return

            # Формированием заголовка
            start_item = current_page * self.PAGE_SIZE + 1
            end_item = min(start_item + self.PAGE_SIZE - 1, total)

            header = (
                "💬 **Сообщения чата**\n\n"
                f"📊 Показаны: {start_item}-{end_item} из {total}\n"
                f"📄 Страница {current_page + 1} из {total_pages}\n\n"
            )

            # Форматирование всех сообщений
            formatted_messages = [self._format_message(item) for item in items]

            # Проверка, есть ли вообще сообщения для отображения
            if not formatted_messages:
                empty_text = "💬 **Сообщения чата**\n\nВ этом чате пока нет сообщений."
                keyboard = self._build_hybrid_keyboard(
                    current_page=0,
                    total_pages=1,
                    total=0,
                    parent_item_id=parent_item_id,
                    group_id=group_id,
                    state=state,
                )
                result = await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=None,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                if result.get("success"):
                    await state.update_data(chat_details_message_ids=[result.get("message_id")])
                return

            new_message_ids = []

            # Проверка, помещается ли всё в одно сообщение
            full_text = header + "".join(formatted_messages)

            if len(full_text) <= 4000:
                # Отправка одним сообщением с клавиатурой
                keyboard = self._build_hybrid_keyboard(
                    current_page=current_page,
                    total_pages=total_pages,
                    total=total,
                    parent_item_id=parent_item_id,
                    group_id=group_id,
                    state=state,
                )
                result = await bot_manager.send_message(
                    chat_id=chat_id,
                    text=full_text,
                    message_type=MessageType.COMMAND_ACTION,
                    delete_by_type=None,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                if result.get("success"):
                    new_message_ids.append(result.get("message_id"))
            else:
                # =========== Разбиваем на части ===========
                # Первая часть — заголовок + сообщения
                current_text = header
                batch_messages: list[str] = []

                for formatted in formatted_messages:
                    # Проверка, поместится ли сообщение с этим элементом
                    test_text = current_text + "".join(batch_messages) + formatted
                    if len(test_text) > 4000:
                        # Отправление текущего накопленный текста
                        if batch_messages:
                            send_text = current_text + "".join(batch_messages)

                            # Первая часть — без клавиатуры
                            result = await bot_manager.send_message(
                                chat_id=chat_id,
                                text=send_text,
                                message_type=MessageType.COMMAND_ACTION,
                                delete_by_type=None,
                                parse_mode="Markdown",
                                reply_markup=None,
                            )
                            if result.get("success"):
                                new_message_ids.append(result.get("message_id"))
                            await asyncio.sleep(0.05)

                            # Удаление заголовка для следующих частей
                            current_text = ""

                        # Начало новой части
                        batch_messages = [formatted]
                    else:
                        batch_messages.append(formatted)

                # Отправка последней части с клавиатурой
                if batch_messages:
                    send_text = current_text + "".join(batch_messages)
                    keyboard = self._build_hybrid_keyboard(
                        current_page=current_page,
                        total_pages=total_pages,
                        total=total,
                        parent_item_id=parent_item_id,
                        group_id=group_id,
                        state=state,
                    )
                    result = await bot_manager.send_message(
                        chat_id=chat_id,
                        text=send_text,
                        message_type=MessageType.COMMAND_ACTION,
                        delete_by_type=None,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
                    if result.get("success"):
                        new_message_ids.append(result.get("message_id"))

            # Сохранение ID новых сообщений
            await state.update_data(chat_details_message_ids=new_message_ids)

            # Сохранение состояния
            state_keys = await self.get_state_keys()
            await state.update_data(
                **{
                    state_keys["page"]: current_page,
                    state_keys["search_query"]: search_query,
                    "selected_user_id": selected_user_id,
                    "selected_user_name": selected_user_name,
                    "group_id": group_id,
                    "chat_details_total": total,
                }
            )

        except Exception as e:
            bot_logger.error(f"❌ Failed to show chat messages: {e}", exc_info=True)
            result = await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Произошла ошибка при загрузке сообщений. Попробуйте позже.",
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=None,
                parse_mode="Markdown",
            )
            if result.get("success"):
                await state.update_data(chat_details_message_ids=[result.get("message_id")])

    def _build_hybrid_keyboard(
        self,
        current_page: int,
        total_pages: int,
        total: int,
        parent_item_id: int | None,
        group_id: int | None,
        state: FSMContext,
    ) -> InlineKeyboardMarkup:
        """
        Построение гибридной клавиатуры навигации.

        Включает:
        - Компактную пагинацию (для быстрого перехода)
        - Кнопку "Загрузить еще" (для последовательного чтения)
        - Кнопку "К последним" (для перехода к свежим сообщениям)
        - Навигационные кнопки (назад, главное меню, закрыть)
        """
        keyboard = []

        # 1. Пагинация (компактная)
        if total_pages > 1:
            page_row = self._build_pagination_row(current_page, total_pages)
            if page_row:
                keyboard.append(page_row)

        # 2. Кнопка "Загрузить еще" (если есть следующая страница)
        if current_page < total_pages - 1:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=f"📥 Загрузить еще {self.PAGE_SIZE} сообщений",
                        callback_data=f"chat_details_load_more_{current_page + 1}",
                    )
                ]
            )

        # 3. Кнопка "К последним" (если не на последней странице)
        if current_page < total_pages - 1:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text="⚡ К последним сообщениям",
                        callback_data=f"chat_details_goto_last_{total_pages - 1}",
                    )
                ]
            )

        # 4. Информационная кнопка (неактивная)
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"📊 {current_page + 1}/{total_pages} • {total} сообщений",
                    callback_data="chat_details_info",
                )
            ]
        )

        # 5. Навигационные кнопки
        nav_row = []

        if parent_item_id:
            nav_row.append(
                InlineKeyboardButton(
                    text="🔙 Назад к чатам",
                    callback_data=f"action_back_{parent_item_id}",
                )
            )

        if group_id:
            nav_row.append(
                InlineKeyboardButton(
                    text="🏠 В главное меню",
                    callback_data="action_home",
                )
            )

        if nav_row:
            keyboard.append(nav_row)

        # 6. Кнопка закрытия
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="❌ Закрыть",
                    callback_data="chat_details_close",
                )
            ]
        )

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def _build_pagination_row(self, current_page: int, total_pages: int) -> list[InlineKeyboardButton] | None:
        """
        Построение компактной строки пагинации.

        Показывает:
        - Назад/Вперед
        - Номера страниц с текущей выделенной
        - Сокращение для больших диапазонов (...)
        """
        row: list[InlineKeyboardButton] = []

        # Кнопка "Назад"
        if current_page > 0:
            row.append(
                InlineKeyboardButton(
                    text="◀️",
                    callback_data=f"chat_details_page_{current_page - 1}",
                )
            )

        # Номера страниц
        page_numbers = self._get_page_numbers(current_page, total_pages)
        for p in page_numbers:
            if p == current_page:
                row.append(
                    InlineKeyboardButton(
                        text=f"📍{p + 1}",
                        callback_data=f"chat_details_page_{p}",
                    )
                )
            elif p is None:
                row.append(
                    InlineKeyboardButton(
                        text="…",
                        callback_data="chat_details_info",
                    )
                )
            else:
                row.append(
                    InlineKeyboardButton(
                        text=f"{p + 1}",
                        callback_data=f"chat_details_page_{p}",
                    )
                )

        # Кнопка "Вперед"
        if current_page < total_pages - 1:
            row.append(
                InlineKeyboardButton(
                    text="▶️",
                    callback_data=f"chat_details_page_{current_page + 1}",
                )
            )

        return row if row else None

    @staticmethod
    def _get_page_numbers(current: int, total: int) -> list[int | None]:
        """
        Получение списка номеров страниц для отображения.

        Args:
            current: Текущая страница (0-based)
            total: Общее количество страниц

        Returns:
            list[int | None]: Список номеров страниц (None для разделителя)
        """
        if total <= 7:
            return list(range(total))

        # Формирование списка страниц с разделителями
        result: list[int | None] = (
            [0]
            + ([None] if current > 2 else [])
            + [p for p in range(max(1, current - 1), min(total - 2, current + 2) + 1) if p != 0 and p != total - 1]
            + ([None] if current < total - 3 else [])
            + ([total - 1] if total - 1 not in [0] else [])
        )

        # Удаление дубликатов с сохранением порядка
        return list(dict.fromkeys(result))

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
            # Открытие меню для ответа
            from ..chat_message_menu import show_message_context_menu

            await show_message_context_menu(
                event=callback,
                state=state,
                message_id=item_id,
                chat_id=callback.message.chat.id if callback.message else 0,
            )

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
            dict: Словарь с ключами состояния
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
    async def get_back_keyboard(state: FSMContext) -> InlineKeyboardMarkup:
        """
        Создание клавиатуры с кнопкой "Назад к чатам".

        Args:
            state: Состояние FSM

        Returns:
            InlineKeyboardMarkup: Клавиатура с кнопкой назад
        """
        state_data = await state.get_data()
        group_id = state_data.get("group_id")
        parent_item_id = state_data.get("parent_item_id")

        buttons = []

        if parent_item_id:
            buttons.append(
                InlineKeyboardButton(
                    text="🔙 Назад к чатам",
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

        if not buttons:
            buttons.append(
                InlineKeyboardButton(
                    text="❌ Закрыть",
                    callback_data="chat_details_close",
                )
            )

        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    @staticmethod
    def format_single_message(item: dict[str, Any]) -> str:
        """
        Форматирование одного сообщения для отображения (без разделителя).

        Используется для deep linking и других случаев,
        когда нужно показать одно сообщение без лишних элементов.

        Args:
            item: Словарь с данными сообщения

        Returns:
            str: Отформатированное сообщение
        """
        date = item.get("date", "")
        author = item.get("author_name") or f"Контакт #{item.get('author_contact_id')}"
        text = item.get("text") or ""
        msg_id = item.get("id")
        direction = item.get("direction")

        # Обрезка длинного текста
        if text and len(text) > 500:
            text = text[:500] + "..."

        # Определение иконки и текста направления
        direction_icon = "❓"
        direction_text = "UNKNOWN"
        if direction == 1:
            direction_icon = "⬅️"
            direction_text = "Входящее"
        elif direction == 2:
            direction_icon = "➡️"
            direction_text = "Исходящее"

        # Формирование строки с автором и направлением
        result = f"👤 **{author}**"
        if direction:
            result += f" {direction_icon} [{direction_text}]"

        if date:
            try:
                dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                date_str = dt.strftime("%d.%m.%Y %H:%M")
                result += f" 🕐 {date_str}"
            except (ValueError, TypeError, AttributeError):
                pass
        result += "\n"

        if text:
            result += f"📝 {text}\n"

        if msg_id:
            result += f"🆔 `{msg_id}`\n"

        return result

    @staticmethod
    def _format_message(item: dict[str, Any]) -> str:
        """
        Форматирование сообщения с визуализацией направления (входящее/исходящее).

        Отображает:
        - Автора сообщения
        - Направление (входящее/исходящее) с иконкой
        - Время отправки (в формате ДД.ММ.ГГГГ ЧЧ:ММ)
        - Текст сообщения (обрезается до 500 символов)
        - ID сообщения для использования в команде /msg
        - Разделитель между сообщениями

        Args:
            item: Словарь с данными сообщения

        Returns:
            str: Отформатированное сообщение
        """
        date = item.get("date", "")
        author = item.get("author_name") or f"Контакт #{item.get('author_contact_id')}"
        text = item.get("text") or ""
        msg_id = item.get("id")
        direction = item.get("direction")

        # Обрезка длинного текста
        if text and len(text) > 500:
            text = text[:500] + "..."

        # Определение иконки и текста направления
        direction_icon = "❓"
        direction_text = "UNKNOWN"
        if direction == 1:
            direction_icon = "⬅️"
            direction_text = "Входящее"
        elif direction == 2:
            direction_icon = "➡️"
            direction_text = "Исходящее"

        # Формирование строки с автором и направлением
        result = f"👤 **{author}**"
        if direction:
            result += f" {direction_icon} [{direction_text}]"

        if date:
            try:
                dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                date_str = dt.strftime("%d.%m.%Y %H:%M")
                result += f" 🕐 {date_str}"
            except (ValueError, TypeError, AttributeError):
                pass
        result += "\n"

        if text:
            result += f"📝 {text}\n"

        # Deep Linking с параметром start
        if msg_id:
            bot_username = settings.BOT_USERNAME
            deep_link = f"https://t.me/{bot_username}?start=msg_{msg_id}"

            result += f"🆔 `{msg_id}`"
            result += "  •  "
            # Кликабельная ссылка для перехода к сообщению
            result += f"[💬 Перейти к сообщению]({deep_link})\n"
            # Текстовая команда для тех, кто привык к старому формату
            result += f"   ⚙️ `/msg {msg_id}`\n"

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


# ============================================================
# ОБРАБОТЧИКИ КОЛБЭКОВ ДЛЯ ГИБРИДНОЙ НАВИГАЦИИ
# ============================================================


@router.callback_query(F.data.startswith("chat_details_page_"))
async def handle_page_navigation(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка навигации по страницам."""
    try:
        page = int(callback.data.split("_")[-1])
        await chat_details_handler.show_list(event=callback, state=state, page=page)
    except ValueError:
        await callback.answer("❌ Неверный номер страницы")


@router.callback_query(F.data.startswith("chat_details_load_more_"))
async def handle_load_more(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка кнопки 'Загрузить еще'."""
    try:
        page = int(callback.data.split("_")[-1])
        await callback.answer(f"📥 Загружаем страницу {page + 1}...")
        await chat_details_handler.show_list(event=callback, state=state, page=page)
    except ValueError:
        await callback.answer("❌ Ошибка загрузки")


@router.callback_query(F.data.startswith("chat_details_goto_last_"))
async def handle_goto_last(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка кнопки 'К последним сообщениям'."""
    try:
        page = int(callback.data.split("_")[-1])
        await callback.answer("⚡ Переход к последним сообщениям...")
        await chat_details_handler.show_list(event=callback, state=state, page=page)
    except ValueError:
        await callback.answer("❌ Ошибка перехода")


@router.callback_query(F.data == "chat_details_info")
async def handle_info(callback: CallbackQuery) -> None:
    """Информационная кнопка (неактивная)."""
    await callback.answer("ℹ️ Информация о странице")


@router.callback_query(F.data == "chat_details_close")
async def handle_close(callback: CallbackQuery, state: FSMContext) -> None:
    """Закрытие списка сообщений."""
    bot_manager = get_bot_manager()
    await bot_manager.send_toast(text="❌ Список сообщений закрыт.", event=callback)

    # Удаление всех сообщений чата
    state_data = await state.get_data()
    chat_id = callback.message.chat.id if callback.message else None
    message_ids = state_data.get("chat_details_message_ids", [])

    if chat_id and message_ids:
        for msg_id in message_ids:
            try:
                await bot_manager.delete_message_by_id(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                bot_logger.debug(f"ℹ️ Could not delete message {msg_id}: {e}")

    # Очистка состояния
    state_keys = await chat_details_handler.get_state_keys()
    await state.update_data(
        **{
            state_keys["page"]: 0,
            state_keys["search_query"]: None,
            "selected_chat_id": None,
            "chat_details_total": 0,
        }
    )
    await state.set_state(None)

    # Удаление сообщения
    if callback.message:
        try:
            await callback.message.delete()
        except Exception as e:
            bot_logger.warning(f"⚠️ Could not delete message: {e}")


@router.callback_query(F.data.startswith("chat_details_reply_"))
async def handle_reply_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка ответа на сообщение через callback."""
    try:
        message_id = int(callback.data.split("_")[-1])
        from ..chat_message_menu import show_message_context_menu

        await show_message_context_menu(
            event=callback,
            state=state,
            message_id=message_id,
            chat_id=callback.message.chat.id if callback.message else 0,
        )
    except ValueError:
        await callback.answer("❌ Неверный ID сообщения")


@router.callback_query(F.data.startswith("chat_details_attachments_"))
async def handle_attachments_callback(callback: CallbackQuery) -> None:
    """Обработка просмотра вложений."""
    try:
        message_id = int(callback.data.split("_")[-1])
        await callback.answer(f"📎 Вложения сообщения #{message_id} (в разработке)")
    except ValueError:
        await callback.answer("❌ Неверный ID сообщения")


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

    # Проверка, не является ли это ответом на сообщение
    state_data = await state.get_data()
    reply_to_message_id = state_data.get("reply_to_message_id")

    if reply_to_message_id:
        # Это ответ на сообщение
        from ..chat_message_menu import handle_reply_text

        await handle_reply_text(message, state)
    else:
        # Обычное сообщение в режиме просмотра
        await bot_manager.send_answer(
            text="💬 Введите текст для ответа на сообщение или используйте /msg <id>",
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
