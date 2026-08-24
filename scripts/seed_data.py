"""Заполнение БД тестовыми данными для TeamBot.

Использование:
    python scripts/seed_data.py [options]

Опции:
    --clear         Очистить все данные перед заполнением
    --db NAME       База данных для заполнения (main, avanpost) [default: main]
    --count N       Количество сообщений на чат [default: 5]
    --errors N      Количество ошибок для генерации [default: 10]
    --reminders N   Количество напоминаний для генерации [default: 5]
"""

import argparse
import asyncio
import random
import sys
from datetime import timedelta
from pathlib import Path

# Добавление корня проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.manager import db_manager
from app.models import (
    ChatMemberModel,
    ChatMemberStatus,
    ChatMessageModel,
    ChatModel,
    ChatType,
    ErrorCategory,
    ErrorModel,
    ErrorSeverity,
    ErrorStatus,
    MessageSource,
    MessageType,
    UserModel,
    UserReminderModel,
    datetime_now,
)
from app.utils.crypto import encrypt_data


class TestDataGenerator:
    """Генератор тестовых данных."""

    def __init__(self) -> None:
        self.users: list[UserModel] = []
        self.chats: list[ChatModel] = []
        self.messages: list[ChatMessageModel] = []
        self.errors: list[ErrorModel] = []
        self.reminders: list[UserReminderModel] = []

        # Тестовые данные
        self.test_users: list[dict] = [
            {
                "id": 1039799368,
                "username": "admin",
                "first_name": "Admin",
                "last_name": "User",
                "is_bot": False,
                "phone": "+375291234567",
            },
            {
                "id": 1039799369,
                "username": "john_doe",
                "first_name": "John",
                "last_name": "Doe",
                "is_bot": False,
                "phone": "+375292345678",
            },
            {
                "id": 1039799370,
                "username": "jane_smith",
                "first_name": "Jane",
                "last_name": "Smith",
                "is_bot": False,
                "phone": "+375293456789",
            },
            {
                "id": 1039799371,
                "username": "bob_wilson",
                "first_name": "Bob",
                "last_name": "Wilson",
                "is_bot": False,
                "phone": "+375294567890",
            },
            {
                "id": 1039799372,
                "username": "alice_bot",
                "first_name": "Alice",
                "last_name": "Bot",
                "is_bot": True,
                "phone": None,
            },
        ]

        self.test_chats: list[dict] = [
            {"id": -1001234567890, "title": "Team Development", "type": ChatType.SUPERGROUP},
            {"id": -1001234567891, "title": "Design Team", "type": ChatType.GROUP},
            {"id": -1001234567892, "title": "Project Management", "type": ChatType.SUPERGROUP},
            {"id": 123456789, "title": None, "type": ChatType.PRIVATE},
        ]

        self.message_types: list[MessageType] = [
            MessageType.USER_REQUEST,
            MessageType.BOT_RESPONSE,
            MessageType.COMMAND,
            MessageType.SYSTEM_ALERT,
            MessageType.REMINDER,
        ]

        self.error_categories: list[ErrorCategory] = [
            ErrorCategory.ARBITRARY,
            ErrorCategory.PERIODIC_TASK,
            ErrorCategory.TASK_EXECUTION,
            ErrorCategory.SYSTEM,
            ErrorCategory.EXTERNAL,
        ]

        self.error_severities: list[ErrorSeverity] = [
            ErrorSeverity.CRITICAL,
            ErrorSeverity.ERROR,
            ErrorSeverity.WARNING,
            ErrorSeverity.INFO,
        ]

    async def generate_users(self, session: AsyncSession, count: int = 5) -> list[UserModel]:
        """Генерация тестовых пользователей."""
        print("👤 Generating test users...")

        for user_data in self.test_users[:count]:
            # Проверка, существует ли пользователь
            stmt = select(UserModel).where(UserModel.FID == user_data["id"])
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if not existing:
                user = UserModel(
                    FID=user_data["id"],
                    FUserName=user_data["username"],
                    FFirstName=user_data["first_name"],
                    FLastName=user_data["last_name"],
                    FFlagBot=user_data["is_bot"],
                    FPhone=user_data["phone"],
                    FK_Avanpost=random.randint(1000, 9999),
                    FK_AvanpostGroup=random.randint(1, 10),
                    FDateCreated=datetime_now() - timedelta(days=random.randint(1, 30)),
                    FDateUpdated=datetime_now(),
                    FDateLastActivity=datetime_now() - timedelta(hours=random.randint(1, 24)),
                )
                session.add(user)
                self.users.append(user)
                print(f"  ✅ Created user: {user_data['username']} (ID: {user_data['id']})")

        await session.flush()
        return self.users

    async def generate_chats(self, session: AsyncSession) -> list[ChatModel]:
        """Генерация тестовых чатов."""
        print("💬 Generating test chats...")

        for chat_data in self.test_chats:
            # Проверка, существует ли чат
            stmt = select(ChatModel).where(ChatModel.FID == chat_data["id"])
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if not existing:
                chat = ChatModel(
                    FID=chat_data["id"],
                    FTitle=chat_data["title"],
                    FType=chat_data["type"],
                    FFlagActive=True,
                    FCountMembers=random.randint(5, 50),
                    FCountMessages=random.randint(10, 100),
                    FDateCreated=datetime_now() - timedelta(days=random.randint(1, 30)),
                    FDateUpdated=datetime_now(),
                    FDateSynced=datetime_now() - timedelta(hours=random.randint(1, 24)),
                )
                session.add(chat)
                self.chats.append(chat)
                print(f"  ✅ Created chat: {chat_data['title'] or f'Chat {chat_data["id"]}'} (ID: {chat_data['id']})")
            else:
                self.chats.append(existing)
                print(f"  ℹ️ Chat already exists: {chat_data['title'] or f'Chat {chat_data["id"]}'}")

        await session.flush()
        return self.chats

    async def generate_chat_members(self, session: AsyncSession) -> list[ChatMemberModel]:
        """Генерация участников чатов."""
        print("👥 Generating chat members...")

        members: list[ChatMemberModel] = []
        statuses = [ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER]

        for chat in self.chats:
            if chat.FType == ChatType.PRIVATE:
                continue  # Пропуск приватных чатов

            # Добавление всех пользователей в каждый чат
            for user in self.users:
                # Проверяем, существует ли участник
                stmt = select(ChatMemberModel).where(
                    ChatMemberModel.FK_Chat == chat.FID,
                    ChatMemberModel.FK_User == user.FID,
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if not existing:
                    status = random.choice(statuses)
                    member = ChatMemberModel(
                        FK_Chat=chat.FID,
                        FK_User=user.FID,
                        FStatus=status,
                        FFlagActive=True,
                        FDateJoined=datetime_now() - timedelta(days=random.randint(1, 20)),
                        FDateUpdated=datetime_now(),
                    )
                    session.add(member)
                    members.append(member)
                    print(f"  ✅ Added user {user.FUserName} to chat {chat.FTitle or chat.FID} as {status.value}")

        await session.flush()
        return members

    async def generate_messages(self, session: AsyncSession, count_per_chat: int = 5) -> list[ChatMessageModel]:
        """Генерация тестовых сообщений."""
        print(f"💬 Generating {count_per_chat} messages per chat...")

        messages_texts = [
            "Привет всем! Как дела?",
            "Нужна помощь с проектом",
            "Отличная работа, команда!",
            "Когда будет следующее обновление?",
            "Есть идея по улучшению",
            "Прошу утвердить план",
            "Кто сегодня дежурит?",
            "Завтра встреча в 10:00",
            "Спасибо за помощь!",
            "Можно задать вопрос?",
            "Проверьте, пожалуйста, отчет",
            "Внес изменения в код",
            "Тестируем новую фичу",
            "Обновил документацию",
            "Нужно согласовать с заказчиком",
        ]

        for chat in self.chats:
            if chat.FType == ChatType.PRIVATE:
                continue  # Пропуск приватных чатов для массовой генерации

            for _ in range(min(count_per_chat, len(self.users))):
                user = random.choice(self.users)
                message_type = random.choice(self.message_types)
                source = random.choice([MessageSource.USER, MessageSource.BOT, MessageSource.SYSTEM])

                # Проверка, существует ли сообщение с таким ID
                message_id = random.randint(1000000, 9999999)
                stmt = select(ChatMessageModel).where(ChatMessageModel.FID == message_id)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if not existing:
                    text = random.choice(messages_texts)
                    msg = ChatMessageModel(
                        FID=message_id,
                        FK_Chat=chat.FID,
                        FK_User=user.FID,
                        FK_MessageType=message_type,
                        FText=text,
                        FSource=source,
                        FDateSent=datetime_now() - timedelta(hours=random.randint(1, 48)),
                        FFlagReply=random.choice([True, False]),
                        FFlagDeleted=False,
                        FLifetimeSeconds=random.choice([60, 300, 600, None]),
                    )
                    if msg.FLifetimeSeconds:
                        msg.FExpiresAt = datetime_now() + timedelta(seconds=msg.FLifetimeSeconds)
                    session.add(msg)
                    self.messages.append(msg)

        await session.flush()
        print(f"  ✅ Generated {len(self.messages)} messages")
        return self.messages

    async def generate_errors(self, session: AsyncSession, count: int = 10) -> list[ErrorModel]:
        """Генерация тестовых ошибок."""
        print(f"🚨 Generating {count} test errors...")

        error_messages = [
            ("ERR_001", "Database connection timeout"),
            ("ERR_002", "Failed to send message to Telegram"),
            ("ERR_003", "Authentication failed for user"),
            ("ERR_004", "API rate limit exceeded"),
            ("ERR_005", "Invalid request parameters"),
            ("ERR_006", "External service unavailable"),
            ("ERR_007", "Memory allocation failed"),
            ("ERR_008", "File not found in storage"),
            ("ERR_009", "Task execution timeout"),
            ("ERR_010", "Permission denied"),
        ]

        for i in range(count):
            code, message = random.choice(error_messages)
            severity = random.choice(self.error_severities)
            category = random.choice(self.error_categories)
            status = random.choice([ErrorStatus.NEW, ErrorStatus.IN_PROGRESS, ErrorStatus.RESOLVED])

            error = ErrorModel(
                FErrorCode=f"{code}_{i}",
                FErrorMessage=f"{message} (test #{i})",
                FErrorDetails=f"Test error details for {code}",
                FSourceSystem=random.choice(["TeamBot", "Avanpost", "Telegram"]),
                FSourceModule=random.choice(["api", "db", "bot", "services"]),
                FCategory=category,
                FSeverity=severity,
                FStatus=status,
                FUserID=random.choice([u.FID for u in self.users]) if self.users else None,
                FUserLogin=random.choice([u.FUserName for u in self.users]) if self.users else "test_user",
                FCountOccurrences=random.randint(1, 5),
                FFirstOccurrence=datetime_now() - timedelta(days=random.randint(1, 7)),
                FLastOccurrence=datetime_now() - timedelta(hours=random.randint(1, 24)),
                FGroupHash=f"hash_{random.randint(1000, 9999)}",
            )

            if status == ErrorStatus.RESOLVED and random.choice([True, False]):
                error.FResolvedBy = random.choice([u.FID for u in self.users]) if self.users else None
                error.FResolvedAt = datetime_now() - timedelta(hours=random.randint(1, 12))
                error.FResolvedNote = "Resolved by admin"

            session.add(error)
            self.errors.append(error)

        await session.flush()
        print(f"  ✅ Generated {len(self.errors)} errors")
        return self.errors

    async def generate_reminders(self, session: AsyncSession, count: int = 5) -> list[UserReminderModel]:
        """Генерация тестовых напоминаний."""
        print(f"⏰ Generating {count} test reminders...")

        reminder_titles = [
            "Встреча с командой",
            "Сдать отчет",
            "Обновить документацию",
            "Проверить почту",
            "Завершить задачу",
            "Подготовить презентацию",
            "Созвониться с клиентом",
            "Написать пост",
        ]

        for _ in range(count):
            user = random.choice(self.users) if self.users else None
            if not user:
                break

            title = random.choice(reminder_titles)
            remind_at = datetime_now() + timedelta(hours=random.randint(1, 24))
            is_encrypted = random.choice([True, False])

            reminder = UserReminderModel(
                FK_User=user.FID,
                FTitle=title if not is_encrypted else "🔒 Зашифровано",
                FDescription=f"Description for {title}" if not is_encrypted else None,
                FCategory=random.choice(["work", "personal", "urgent"]),
                FRemindAt=remind_at,
                FRemindInterval=random.choice([None, 15, 30, 60]),
                FMaxRemindCount=random.choice([None, 3, 5, 10]),
                FIsCompleted=random.choice([True, False]),
                FIsActive=True,
                FNotificationType=random.choice(["private", "group", "both"]),
                FCodeWord=f"code_{random.randint(100, 999)}",
                FIsEncrypted=is_encrypted,
            )

            if is_encrypted:
                try:
                    encrypted_data = encrypt_data(f'{{"title":"{title}","description":"Secret description"}}')
                    reminder.FEncryptedData = encrypted_data
                except Exception as e:
                    print(f"  ⚠️ Failed to encrypt reminder: {e}")

            if reminder.FIsCompleted:
                reminder.FCompletedAt = datetime_now() - timedelta(hours=random.randint(1, 12))
                reminder.FIsSuccessful = random.choice([True, False])

            session.add(reminder)
            self.reminders.append(reminder)

        await session.flush()
        print(f"  ✅ Generated {len(self.reminders)} reminders")
        return self.reminders

    async def generate_all(self, session: AsyncSession) -> dict[str, int]:
        """Генерация всех тестовых данных."""
        print("\n" + "=" * 50)
        print("  🌱 Seeding TeamBot database with test data...")
        print("=" * 50 + "\n")

        await self.generate_users(session, count=5)
        await self.generate_chats(session)
        await self.generate_chat_members(session)
        await self.generate_messages(session, count_per_chat=5)
        await self.generate_errors(session, count=10)
        await self.generate_reminders(session, count=5)

        await session.commit()

        return {
            "users": len(self.users),
            "chats": len(self.chats),
            "messages": len(self.messages),
            "errors": len(self.errors),
            "reminders": len(self.reminders),
        }

    @staticmethod
    async def clear_data(session: AsyncSession) -> None:
        """Очистка всех данных."""
        print("🗑️  Clearing all data...")

        # Удаление в порядке зависимости (сначала дочерние, потом родительские)
        tables = [
            UserReminderModel,
            ErrorModel,
            ChatMessageModel,
            ChatMemberModel,
            ChatModel,
            UserModel,
        ]

        for table in tables:
            try:
                await session.execute(delete(table))
                print(f"  ✅ Cleared {table.__tablename__}")
            except Exception as e:
                print(f"  ⚠️ Failed to clear {table.__tablename__}: {e}")

        await session.commit()
        print("✅ All data cleared!")


async def main() -> None:
    """Главная функция."""
    parser = argparse.ArgumentParser(
        description="TeamBot Database Seeding Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--clear", action="store_true", help="Clear all data before seeding")
    parser.add_argument("--db", type=str, default="main", help="Database name (main, avanpost)")
    parser.add_argument("--count", type=int, default=5, help="Number of messages per chat")
    parser.add_argument("--errors", type=int, default=10, help="Number of errors to generate")
    parser.add_argument("--reminders", type=int, default=5, help="Number of reminders to generate")

    args = parser.parse_args()

    try:
        # Инициализация БД
        await db_manager.initialize_all()

        generator = TestDataGenerator()

        async with db_manager.get_session(args.db) as session:
            if args.clear:
                await generator.clear_data(session)

            # Генерация данных с учетом переданных параметров
            result = await generator.generate_all(session)

            print("\n" + "=" * 50)
            print("  ✅ Database seeding complete!")
            print("=" * 50)
            print("\n📊 Generated data:")
            for key, value in result.items():
                print(f"  • {key.capitalize()}: {value}")

            print("\n📝 Test credentials:")
            print("  • Admin:  admin / +375291234567")
            print("  • User1:  john_doe / +375292345678")
            print("  • User2:  jane_smith / +375293456789")
            print("\n💡 Use /start in Telegram to authenticate with these phone numbers")

    except Exception as e:
        print(f"❌ Error seeding database: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        # Закрытие соединений
        await db_manager.close_all()


if __name__ == "__main__":
    print("=" * 60)
    print("  🌱 TeamBot Database Seeding Tool")
    print("=" * 60)
    asyncio.run(main())
