from aiogram import Bot, Router
from aiogram.types import ChatMemberUpdated

from ....core import chat_type_from_aiogram, chat_type_to_str, user_info_from_aiogram
from ....db import ChatRepository, UserRepository, db_manager
from ....exceptions import log_exceptions
from ....logger import tg_logger

router = Router(name="aiogram_chat")


@router.my_chat_member()
@log_exceptions(tg_logger)
async def bot_added_or_removed(event: ChatMemberUpdated, bot: Bot) -> None:
    """Обработка событий добавления/удаления бота в чат"""
    tg_logger.debug(f"🔄 Bot chat member event: {event.chat.id}")

    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status

    if new_status == old_status:
        return

    chat = event.chat
    chat_title = chat.title or str(chat.id)

    # Проверка, что событие относится к нашему боту
    bot_user = event.new_chat_member.user
    if bot_user.id != bot.id:
        return

    # Преобразование статуса в строку
    new_status_str = new_status.value if hasattr(new_status, "value") else str(new_status)

    # Используем новый конвертер для типа чата
    chat_type = chat_type_from_aiogram(chat)
    chat_type_str = chat_type_to_str(chat_type)

    async with db_manager.get_session() as session:
        # Сохранение бота как пользователя
        bot_user_info = user_info_from_aiogram(bot_user)
        await UserRepository.save_user(
            session=session,
            user_id=bot_user_info["user_id"],
            is_bot=bot_user_info["is_bot"],
            first_name=bot_user_info["first_name"],
            last_name=bot_user_info["last_name"],
            username=bot_user_info["username"],
        )

        if new_status_str in ["member", "administrator", "creator"]:
            tg_logger.info(f"✅ Bot added to chat: {chat_title} (ID: {chat.id})")

            await ChatRepository.save_chat(
                session=session, chat_id=chat.id, chat_type=chat_type_str, title=chat.title, is_active=True
            )

            await ChatRepository.save_chat_member(
                session=session,
                user_id=bot_user_info["user_id"],
                chat_id=chat.id,
                status=new_status_str,
                is_active=True,
            )

        elif new_status_str in ["left", "kicked"]:
            tg_logger.info(f"❌ Bot removed from chat: {chat_title} (ID: {chat.id})")

            await ChatRepository.save_chat(
                session=session, chat_id=chat.id, chat_type=chat_type_str, title=chat.title, is_active=False
            )

            await ChatRepository.save_chat_member(
                session=session,
                user_id=bot_user_info["user_id"],
                chat_id=chat.id,
                status=new_status_str,
                is_active=False,
            )

        await session.commit()
        tg_logger.info(f"✅ Chat member event processed for {chat.id}")


@router.chat_member()
@log_exceptions(tg_logger)
async def chat_member_update(event: ChatMemberUpdated) -> None:
    """Обработка изменений участников чата"""
    # Игнорирование изменения, связанные с ботом
    bot = event.bot
    if event.new_chat_member.user.id == (await bot.get_me()).id:
        return

    tg_logger.debug(f"🔄 Chat member update: {event.chat.id}")

    user = event.new_chat_member.user
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    if old_status == new_status:
        return

    async with db_manager.get_session() as session:
        user_info = user_info_from_aiogram(user)
        await UserRepository.save_user(
            session=session,
            user_id=user_info["user_id"],
            is_bot=user_info["is_bot"],
            first_name=user_info["first_name"],
            last_name=user_info["last_name"],
            username=user_info["username"],
        )

        # Проверка наличия чата в БД
        chats = await ChatRepository.get_chats(session, chat_id=event.chat.id)
        if not chats:
            tg_logger.warning(f"⚠️ Chat {event.chat.id} not found in DB, creating...")
            chat_type = chat_type_from_aiogram(event.chat)
            chat_type_str = chat_type_to_str(chat_type)

            await ChatRepository.save_chat(
                session=session, chat_id=event.chat.id, chat_type=chat_type_str, title=event.chat.title, is_active=True
            )

        # Обновление статуса участника
        new_status_str = new_status.value if hasattr(new_status, "value") else str(new_status)
        is_active = new_status_str not in ["left", "kicked"]

        await ChatRepository.save_chat_member(
            session=session,
            user_id=user_info["user_id"],
            chat_id=event.chat.id,
            status=new_status_str,
            is_active=is_active,
        )

        await session.commit()
        tg_logger.debug(f"✅ Chat member {user_info['user_id']} status updated to {new_status_str}")


__all__ = [
    "router",
]
