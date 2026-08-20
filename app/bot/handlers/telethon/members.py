from telethon import TelegramClient, events
from telethon.tl.types import MessageActionChatAddUser

from ....core.converters import (
    chat_type_from_telethon,
    chat_type_to_str,
    user_info_from_telethon,
)
from ....db.manager import db_manager
from ....db.repositories import ChatRepository, UserRepository
from ....exceptions import log_exceptions
from ....logger import bot_logger
from ....models import ChatMemberStatus, datetime_now

# Репозитории (создаем один раз на уровне модуля)
_user_repo = UserRepository()
_chat_repo = ChatRepository()


@log_exceptions(bot_logger)
async def handle_chat_action(event: events.ChatAction.Event, client: TelegramClient) -> None:
    """Обработка действий в чате (присоединение/выход участников)"""
    # Игнорирование действий нашего бота
    try:
        me = await client.get_me()
        if event.user_id == me.id:
            return
    except Exception as err:
        bot_logger.warning(f"⚠️ Failed to get me: {err}")
        return

    bot_logger.debug(f"🔄 Chat action in {event.chat_id}: {event}")

    async with db_manager.get_session() as session:
        try:
            # Получение информации о пользователе
            try:
                user = await client.get_entity(event.user_id)
                user_info = user_info_from_telethon(user)

                await _user_repo.save_user(
                    session=session,
                    user_id=user_info["user_id"],
                    is_bot=user_info["is_bot"],
                    first_name=user_info["first_name"],
                    last_name=user_info["last_name"],
                    username=user_info["username"],
                )
            except Exception as err:
                bot_logger.warning(f"⚠️ Failed to get user {event.user_id}: {err}")
                return

            # Получение информации о чате
            try:
                chat = await client.get_entity(event.chat_id)
                chat_type = chat_type_from_telethon(chat)

                await _chat_repo.save_chat(
                    session=session,
                    chat_id=chat.id,
                    chat_type=chat_type_to_str(chat_type),
                    title=getattr(chat, "title", None),
                    is_active=True,
                )
            except Exception as err:
                bot_logger.warning(f"⚠️ Failed to get chat {event.chat_id}: {err}")
                return

            # Обработка разных типов действий
            if event.user_joined:
                # Присоединение пользователя к чату
                bot_logger.info(f"👤 User {event.user_id} joined chat {event.chat_id}")

                await _chat_repo.save_chat_member(
                    session=session,
                    user_id=event.user_id,
                    chat_id=event.chat_id,
                    status=ChatMemberStatus.MEMBER.value,
                    is_active=True,
                )

                # Обновление времени синхронизации участника
                await _chat_repo.update_member_sync_time(
                    session=session,
                    user_id=event.user_id,
                    chat_id=event.chat_id,
                )

                # Отправка приветствия
                try:
                    await client.send_message(
                        event.chat_id, f"👋 Добро пожаловать, {user_info['first_name'] or 'пользователь'}!"
                    )
                except Exception as err:
                    bot_logger.warning(f"⚠️ Failed to send welcome message: {err}")

            elif event.user_left:
                # Выход пользователя из чата
                bot_logger.info(f"👤 User {event.user_id} left chat {event.chat_id}")

                await _chat_repo.remove_chat_member(
                    session=session,
                    user_id=event.user_id,
                    chat_id=event.chat_id,
                )

            elif event.user_kicked:
                # Удаление пользователя из чата
                bot_logger.info(f"👤 User {event.user_id} kicked from chat {event.chat_id}")

                await _chat_repo.remove_chat_member(
                    session=session,
                    user_id=event.user_id,
                    chat_id=event.chat_id,
                )

            elif hasattr(event, "action") and isinstance(event.action, MessageActionChatAddUser):
                # Добавление нескольких пользователей в чат
                added_users = []
                for user_id in event.action.users:
                    try:
                        user = await client.get_entity(user_id)
                        user_info = user_info_from_telethon(user)

                        if user_info["user_id"] != me.id:
                            await _user_repo.save_user(
                                session=session,
                                user_id=user_info["user_id"],
                                is_bot=user_info["is_bot"],
                                first_name=user_info["first_name"],
                                last_name=user_info["last_name"],
                                username=user_info["username"],
                            )

                            await _chat_repo.save_chat_member(
                                session=session,
                                user_id=user_info["user_id"],
                                chat_id=event.chat_id,
                                status=ChatMemberStatus.MEMBER.value,
                                is_active=True,
                            )
                            added_users.append(user_info["user_id"])
                    except Exception as err:
                        bot_logger.warning(f"⚠️ Failed to process added user {user_id}: {err}")

                # Массовое обновление времени синхронизации для добавленных пользователей
                if added_users:
                    for user_id in added_users:
                        await _chat_repo.update_member_sync_time(
                            session=session,
                            user_id=user_id,
                            chat_id=event.chat_id,
                        )
                    bot_logger.debug(f"✅ Updated sync time for {len(added_users)} added users")

            await session.commit()
            bot_logger.debug(f"✅ Chat action processed for {event.chat_id}")

        except Exception as err:
            bot_logger.error(f"❌ Failed to handle chat action: {err}", exc_info=True)
            await session.rollback()


@log_exceptions(bot_logger)
async def handle_user_update(event: events.UserUpdate.Event) -> None:
    """Обработка обновлений пользователя (статус, активность)"""
    bot_logger.debug(f"🔄 User update: {event.user_id}")

    # Здесь можно добавить логику обновления пользователя в БД
    # Например, обновление времени последней активности
    async with db_manager.get_session() as session:
        try:
            user = await _user_repo.get_user_by_id(session, event.user_id)
            if user:
                user.FDateUpdated = datetime_now()
                await session.commit()
                bot_logger.debug(f"✅ Updated user {event.user_id} activity time")
        except Exception as err:
            bot_logger.warning(f"⚠️ Failed to update user {event.user_id}: {err}")


__all__ = [
    "handle_chat_action",
    "handle_user_update",
]
