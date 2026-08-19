import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    TelegramObject,
    Update,
)

from ...db import DBManager
from ...db.repositories import ChatRepository, UserRepository
from ...logger import bot_logger
from .utils import get_chat_id, get_message_preview, get_user_id


class LoggingMiddleware(BaseMiddleware):
    """Middleware для логирования обновлений Bot-а"""

    def __init__(self, log_requests: bool = True, log_updates: bool = True, component: str = "bot") -> None:
        self.log_requests = log_requests
        self.log_updates = log_updates
        self.component = component
        self._bot_info_cache: dict[str, Any] | None = None
        self._cache_time: float = 0.0
        self._cache_ttl: int = 60  # Кеширование на 60 секунд
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Логирование входящих обновлений"""
        user_id = get_user_id(event)
        chat_id = get_chat_id(event)

        # print(f"log_telegram_event {user_id}{chat_id}")
        #
        # if isinstance(event, Message):
        #     print("✅ Это сообщение")
        #     # message.text, message.chat, message.from_user и т.д.
        #
        # elif isinstance(event, CallbackQuery):
        #     print("✅ Это callback-запрос")
        #     # event.data, event.from_user, event.message
        #
        # elif isinstance(event, Update):
        #     print("✅ Это Update (контейнер)")
        #     # event.message, event.callback_query, event.chat_member и т.д.
        #
        # elif isinstance(event, ChatMemberUpdated):
        #     print("✅ Это обновление участника чата")
        #     # event.chat, event.from_user, event.new_chat_member
        #
        #     # === ДРУГИЕ ТИПЫ ===
        # elif isinstance(event, InlineQuery):
        #     print("✅ Это inline-запрос")
        #
        # elif isinstance(event, ChosenInlineResult):
        #     print("✅ Это выбранный inline-результат")
        #
        # elif isinstance(event, ShippingQuery):
        #     print("✅ Это запрос доставки")
        #
        # elif isinstance(event, PreCheckoutQuery):
        #     print("✅ Это запрос предоплаты")
        #
        # elif isinstance(event, Poll):
        #     print("✅ Это опрос")
        #
        # elif isinstance(event, PollAnswer):
        #     print("✅ Это ответ на опрос")
        #
        # elif isinstance(event, ChatJoinRequest):
        #     print("✅ Это запрос на вступление в чат")
        #
        # # Проверяем, что это Update
        # if isinstance(event, Update):
        #     update: Update = event
        #
        #     # === 1. Обработка Message ===
        #     if update.message:
        #         message: Message = update.message
        #         print(f"📩 Message: {message.text}")
        #         print(f"   Chat ID: {message.chat.id}")
        #         print(f"   User ID: {message.from_user.id if message.from_user else None}")
        #
        #         # Можно получить все данные из сообщения
        #         if message.text:
        #             text = message.text
        #             if text.startswith("/"):
        #                 command = text.split()[0]
        #                 args = text.split()[1:] if len(text.split()) > 1 else []
        #                 print(f"   Command: {command}, Args: {args}")
        #
        #         elif message.photo:
        #             print(f"   Photo: {message.photo[-1].file_id}")
        #
        #         elif message.document:
        #             print(f"   Document: {message.document.file_name}")
        #
        #     # === 2. Обработка edited_message ===
        #     elif update.edited_message:
        #         message: Message = update.edited_message
        #         print(f"📝 Edited message: {message.text}")
        #
        #     # === 3. Обработка CallbackQuery ===
        #     elif update.callback_query:
        #         callback: CallbackQuery = update.callback_query
        #         print(f"🔘 Callback: {callback.data}")
        #         print(f"   User ID: {callback.from_user.id}")
        #
        #         if callback.message:
        #             print(f"   Message ID: {callback.message.message_id}")
        #             print(f"   Chat ID: {callback.message.chat.id}")
        #
        #     # === 4. Обработка ChatMemberUpdated ===
        #     elif update.chat_member:
        #         chat_member: ChatMemberUpdated = update.chat_member
        #         print(f"👤 Chat member update in {chat_member.chat.id}")
        #         print(f"   Old status: {chat_member.old_chat_member.status}")
        #         print(f"   New status: {chat_member.new_chat_member.status}")
        #
        #     # === 5. Обработка MyChatMemberUpdated ===
        #     elif update.my_chat_member:
        #         my_chat_member = update.my_chat_member
        #         print(f"🤖 Bot status changed in {my_chat_member.chat.id}")
        #         print(f"   Old: {my_chat_member.old_chat_member.status}")
        #         print(f"   New: {my_chat_member.new_chat_member.status}")
        #
        #     # === 6. Обработка InlineQuery ===
        #     elif update.inline_query:
        #         inline_query = update.inline_query
        #         print(f"🔍 Inline query: {inline_query.query}")
        #         print(f"   User: {inline_query.from_user.id}")
        #
        #     # === 7. Обработка ChosenInlineResult ===
        #     elif update.chosen_inline_result:
        #         chosen = update.chosen_inline_result
        #         print(f"✅ Chosen inline result: {chosen.result_id}")
        #
        #     # === 8. Обработка ChatJoinRequest ===
        #     elif update.chat_join_request:
        #         join_request = update.chat_join_request
        #         print(f"📨 Join request to {join_request.chat.id}")
        #         print(f"   User: {join_request.from_user.id}")
        #
        #     # === 9. Другие типы ===
        #     elif update.poll:
        #         print(f"📊 Poll: {update.poll.question}")
        #     elif update.poll_answer:
        #         print(f"📊 Poll answer from {update.poll_answer.user.id}")
        #     elif update.shipping_query:
        #         print(f"📦 Shipping query")
        #     elif update.pre_checkout_query:
        #         print(f"💳 Pre-checkout query")
        #
        #     # === Продолжаем обработку ===
        #     return await handler(event, data)
        #
        # # Если это не Update - обрабатываем как обычно
        # else:
        #     return await handler(event, data)

        # Логирование обновления
        if self.log_updates:
            bot_logger.log_telegram_event(
                event_type=self._get_event_type(event),
                user_id=user_id,
                chat_id=chat_id,
                extra={
                    "update_id": self._get_update_id(event),
                    "message_preview": get_message_preview(event) if isinstance(event, Message) else None,
                },
            )

        # Замер времени выполнения
        start_time = time.time()

        try:
            result = await handler(event, data)

            # Логирование успешного выполнения
            if self.log_requests:
                duration_ms = (time.time() - start_time) * 1000
                bot_logger.info(
                    f"Handler completed: {self._get_event_type(event)}",
                    extra={"duration_ms": duration_ms, "user_id": user_id, "chat_id": chat_id},
                    exc_info=True,
                )

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            bot_logger.log_error(
                error=e,
                message=f"Handler failed: {self._get_event_type(event)}",
                extra={
                    "duration_ms": duration_ms,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "event_type": self._get_event_type(event),
                    "update_id": self._get_update_id(event),
                },
                exc_info=True,
            )
            raise

    def _get_event_type(self, event: TelegramObject) -> str:
        """Определение типа события"""
        if isinstance(event, Message):
            if event.text and event.text.startswith("/"):
                return f"command_{event.text.split()[0]}"
            return f"message_{event.content_type.value if hasattr(event.content_type, 'value') else event.content_type}"
        if isinstance(event, CallbackQuery):
            return f"callback_{event.data[:20] if event.data else 'unknown'}"
        if isinstance(event, Update):
            return self._get_update_type(event)
        return type(event).__name__

    @staticmethod
    def _get_update_type(update: Update) -> str:
        """Определение типа обновления"""
        types = {
            "message": update.message,
            "edited_message": update.edited_message,
            "channel_post": update.channel_post,
            "edited_channel_post": update.edited_channel_post,
            "callback_query": update.callback_query,
            "inline_query": update.inline_query,
            "chat_member": update.chat_member,
            "my_chat_member": update.my_chat_member,
            "chat_join_request": update.chat_join_request,
        }
        for name, value in types.items():
            if value:
                return name
        return "unknown"

    @staticmethod
    def _get_update_id(event: TelegramObject) -> int | None:
        """Получение ID обновления"""
        if isinstance(event, Update):
            update_id = event.update_id
            if isinstance(update_id, int):
                return update_id
            return None
        return None

    async def _is_message_for_bot(self, message: Message, bot: Bot) -> bool:
        """Основная проверка адресованности боту"""
        if not bot:
            return False

        # Получаем информацию о боте с кешированием
        bot_info = await self._get_bot_info(bot)
        if not bot_info:
            return False

        bot_id = bot_info.get("id")
        bot_username = bot_info.get("username")

        if not bot_id or not bot_username:
            return False

        # === 1. Личный чат ===
        if message.chat.type == "private":
            return True

        # === 2. Команда ===
        if message.text and message.text.startswith("/"):
            command_parts = message.text.split()
            command = command_parts[0]

            # Проверяем, что команда не для другого бота
            if "@" in command:
                # /command@other_bot
                return bool(command.endswith(f"@{bot_username}"))
            else:
                # /command — для нашего бота
                return True

        # === 3. Reply на сообщение бота ===
        if (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == bot_id
        ):
            return True

        # === 4. Упоминание @username ===
        if message.text and f"@{bot_username}" in message.text:
            return True

        # === 5. Проверка entities ===
        if message.entities:
            for entity in message.entities:
                if entity.type == "mention":
                    text = message.text[entity.offset : entity.offset + entity.length]
                    if text == f"@{bot_username}":
                        return True
                elif entity.type == "text_mention":
                    if entity.user.id == bot_id:
                        return True

        return False

    async def _get_bot_info(self, bot: Bot) -> dict:
        """Кешированное получение информации о боте"""
        import time

        current_time = time.time()
        if self._bot_info_cache and (current_time - self._cache_time) < self._cache_ttl:
            return self._bot_info_cache

        try:
            me = await bot.get_me()
            self._bot_info_cache = {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "is_bot": me.is_bot,
            }
            self._cache_time = current_time
            return self._bot_info_cache
        except Exception as e:
            print(f"⚠️ Не удалось получить информацию о боте: {e}")
            return {}


class ChatActivityMiddleware(BaseMiddleware):
    """Middleware для отслеживания активности в чатах"""

    def __init__(self, db_manager: DBManager, update_interval: int = 60, component: str = "bot") -> None:
        self.db_manager = db_manager
        self.update_interval = update_interval
        self.component = component
        self._last_updates: dict[int, float] = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Обновление времени последней активности"""
        if isinstance(event, Message) and event.from_user and event.chat:
            chat_id = event.chat.id
            user = event.from_user

            current_time = time.time()
            last_update = self._last_updates.get(chat_id, 0)

            if current_time - last_update >= self.update_interval:
                try:
                    await self._update_activity(event, user)
                    self._last_updates[chat_id] = current_time
                except Exception as e:
                    bot_logger.log_error(
                        error=e,
                        message="Failed to update chat activity",
                        extra={"chat_id": chat_id, "user_id": user.id},
                    )

        return await handler(event, data)

    async def _update_activity(self, message: Message, user: Any) -> None:
        """
        Обновление активности пользователя и чата через репозитории.

        Args:
            message: Объект сообщения
            user: Объект пользователя (уже проверен на None)
        """
        from ...models import datetime_now

        now = datetime_now()
        user_id = user.id
        chat_id = message.chat.id

        async with self.db_manager.get_session() as session:
            try:
                # Обновление пользователя через репозиторий
                db_user = await UserRepository.get_user_by_id(session, user_id)
                if db_user:
                    # Обновляем только если данные изменились
                    if db_user.FFirstName != user.first_name:
                        db_user.FFirstName = user.first_name
                    if db_user.FLastName != user.last_name:
                        db_user.FLastName = user.last_name
                    if db_user.FUserName != user.username:
                        db_user.FUserName = user.username

                    # Обновляем время последней активности
                    db_user.FDateLastActivity = now

                    await session.flush()
                    bot_logger.debug(f"✅ User {user_id} activity updated")
                else:
                    # Создание пользователя, если его нет
                    await UserRepository.save_user(
                        session=session,
                        user_id=user_id,
                        chat_id=chat_id,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        username=user.username,
                        is_bot=user.is_bot,
                    )
                    bot_logger.debug(f"✅ New user {user_id} created from activity")

                # Обновление чата через репозиторий
                chat = await ChatRepository.get_chat_by_id(session, chat_id)
                if chat:
                    chat.FDateUpdated = now
                    chat.FCountMessages = (chat.FCountMessages or 0) + 1

                    if message.chat.title and chat.FTitle != message.chat.title:
                        chat.FTitle = message.chat.title

                    await session.flush()
                    bot_logger.debug(f"✅ Chat {chat_id} activity updated")
                else:
                    # Создание чата, если его нет
                    from ...core.converters import chat_type_from_aiogram, chat_type_to_str

                    chat_type = chat_type_from_aiogram(message.chat)
                    chat_type_str = chat_type_to_str(chat_type)

                    await ChatRepository.save_chat(
                        session=session,
                        chat_id=chat_id,
                        chat_type=chat_type_str,
                        title=message.chat.title,
                        is_active=True,
                    )
                    bot_logger.debug(f"✅ New chat {chat_id} created from activity")

                await session.commit()

                bot_logger.debug(
                    f"Chat activity updated: chat={chat_id}, user={user_id}",
                    extra={"chat_id": chat_id, "user_id": user_id},
                )

            except Exception as e:
                bot_logger.error(f"❌ Failed to update activity: {e}", exc_info=True)
                await session.rollback()
                raise


__all__ = [
    "LoggingMiddleware",
    "ChatActivityMiddleware",
]
