"""Тесты для утилит бота.

Этот модуль содержит тесты для:
1. Конвертеров данных (преобразование между форматами)
2. UserConverter - работа с пользователями
3. Validator - базовые проверки данных
4. TextValidator - валидация и обработка текста
5. CommandValidator - работа с командами
6. DataValidator - проверка структур данных
7. RateLimitValidator - ограничение частоты запросов
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

# Импортируем функции и классы для тестирования из app.bot.utils
from app.bot.utils import (
    CommandValidator,
    DataValidator,
    RateLimitValidator,
    TextValidator,
    UserConverter,
    Validator,
    chat_info_from_aiogram,
    chat_info_from_telethon,
    dict_to_chat_model,
    dict_to_user_model,
    message_info_from_aiogram,
    message_info_from_telethon,
    save_media_info_to_model,
)

# Импортируем типы из models
from app.models import ChatMessageModel, ChatModel, ChatType, UserModel

# ============================================================
# 1. ТЕСТЫ ДЛЯ КОНВЕРТЕРОВ
# ============================================================


class TestConverters:
    """Тесты для функций-конвертеров данных.

    Проверяет преобразование данных между различными форматами:
    - Словарь -> Модель пользователя
    - Telethon объект -> Информация о чате
    - Aiogram объект -> Информация о чате
    - Словарь -> Модель чата
    - Telethon объект -> Информация о сообщении
    - Aiogram объект -> Информация о сообщении
    - Сохранение медиа-информации в модель
    """

    def test_dict_to_user_model(self):
        """Тест преобразования словаря в модель UserModel.

        Проверяет:
        - Корректное заполнение всех полей
        - Обработку отсутствующих ключей с значениями по умолчанию
        """
        data = {
            "user_id": 123,
            "username": "test_user",
            "first_name": "Test",
            "last_name": "User",
            "is_bot": False,
        }
        user = dict_to_user_model(data)
        assert isinstance(user, UserModel)
        assert user.FID == 123
        assert user.FUserName == "test_user"
        assert user.FFirstName == "Test"
        assert user.FLastName == "User"
        assert user.FFlagBot is False

        # Проверка с отсутствующими ключами
        data_missing = {"user_id": 456}
        user = dict_to_user_model(data_missing)
        assert user.FID == 456
        assert user.FUserName == ""  # Значение по умолчанию
        assert user.FFirstName == ""

    def test_chat_info_from_telethon(self):
        """Тест извлечения информации о чате из объекта Telethon.

        Проверяет:
        - Корректное извлечение ID, названия, username, количества участников
        - Преобразование типа чата в строковое представление
        - Обработку ошибок при извлечении данных
        - Обработку None значения
        """
        # Мок-объект чата Telethon
        mock_chat = MagicMock()
        mock_chat.id = 123456789
        mock_chat.title = "Test Group"
        mock_chat.username = "test_group"
        mock_chat.participants_count = 100

        # Мокаем функцию определения типа, чтобы вернуть ChatType.GROUP
        with patch("app.bot.utils.chat_type_from_telethon", return_value=ChatType.GROUP):
            info = chat_info_from_telethon(mock_chat)
            assert info["chat_id"] == 123456789
            assert info["title"] == "Test Group"
            assert info["type"] == "group"
            assert info["username"] == "test_group"
            assert info["participants_count"] == 100

        # Обработка ошибок при извлечении типа
        with patch("app.bot.utils.chat_type_from_telethon", side_effect=Exception("Test error")):
            info = chat_info_from_telethon(mock_chat)
            assert info["chat_id"] == 123456789
            assert info["type"] == "private"  # Значение по умолчанию при ошибке

        # Проверка с None - должен вернуть словарь с значениями по умолчанию
        info = chat_info_from_telethon(None)
        assert info == {
            "chat_id": 0,
            "title": None,
            "type": "private",
            "username": None,
            "participants_count": None,
        }

    def test_chat_info_from_aiogram(self):
        """Тест извлечения информации о чате из объекта Aiogram.

        Проверяет:
        - Корректное извлечение ID, названия, username
        - Преобразование типа чата в строковое представление
        - Обработку None значения
        """
        mock_chat = MagicMock()
        mock_chat.id = 987654321
        mock_chat.title = "Test Private"
        mock_chat.username = "test_private"

        with patch("app.bot.utils.chat_type_from_aiogram", return_value=ChatType.PRIVATE):
            info = chat_info_from_aiogram(mock_chat)
            assert info["chat_id"] == 987654321
            assert info["title"] == "Test Private"
            assert info["type"] == "private"
            assert info["username"] == "test_private"

        # Проверка с None
        info = chat_info_from_aiogram(None)
        assert info == {"chat_id": 0, "title": None, "type": "private", "username": None}

    def test_dict_to_chat_model(self):
        """Тест создания модели чата из словаря.

        Проверяет:
        - Корректное создание модели ChatModel из словаря
        - Преобразование строкового типа в ChatType enum
        - Обработку невалидных типов с fallback на PRIVATE
        """
        data = {
            "chat_id": -100123456,
            "title": "Supergroup",
            "type": "supergroup",
            "participants_count": 50,
            "is_active": True,
        }
        chat = dict_to_chat_model(data)
        assert isinstance(chat, ChatModel)
        assert chat.FID == -100123456
        assert chat.FTitle == "Supergroup"
        assert chat.FType == ChatType.SUPERGROUP
        assert chat.FCountMembers == 50
        assert chat.FFlagActive is True

        # Проверка с типом чата из ChatType (уже enum)
        data["type"] = ChatType.CHANNEL
        chat = dict_to_chat_model(data)
        assert chat.FType == ChatType.CHANNEL

        # Проверка с невалидным типом - должен использовать PRIVATE
        data["type"] = "invalid_type"
        chat = dict_to_chat_model(data)
        assert chat.FType == ChatType.PRIVATE

    def test_message_info_from_telethon(self):
        """Тест извлечения информации о сообщении из объекта Telethon.

        Проверяет:
        - Корректное извлечение ID, chat_id, sender_id, текста
        - Преобразование дат
        - Определение флагов is_reply, is_forwarded
        - Определение типа медиа
        - Обработку caption как альтернативы text
        - Обработку None значения
        """
        mock_message = MagicMock()
        mock_message.id = 123
        mock_message.chat_id = 456
        mock_message.sender_id = 789
        mock_message.text = "Hello from Telethon"
        mock_message.date = datetime(2024, 1, 1, 12, 0, 0)
        mock_message.edit_date = None
        mock_message.reply_to = MagicMock()  # Для is_reply
        mock_message.forward = None
        mock_message.photo = None

        with patch("app.bot.utils._get_telethon_media_type", return_value="text"):
            info = message_info_from_telethon(mock_message)
            assert info["message_id"] == 123
            assert info["chat_id"] == 456
            assert info["sender_id"] == 789
            assert info["text"] == "Hello from Telethon"
            assert info["date"] is not None
            assert info["edit_date"] is None
            assert info["is_reply"] is True
            assert info["is_forwarded"] is False
            assert info["media_type"] == "text"

        # Проверка с caption (когда text отсутствует)
        mock_message.text = None
        mock_message.caption = "Image caption"
        info = message_info_from_telethon(mock_message)
        assert info["text"] == "Image caption"

        # Проверка с None
        info = message_info_from_telethon(None)
        assert info["message_id"] == 0
        assert info["chat_id"] == 0
        assert info["sender_id"] is None

    def test_message_info_from_aiogram(self):
        """Тест извлечения информации о сообщении из объекта Aiogram.

        Проверяет:
        - Корректное извлечение ID, chat_id, sender_id, текста
        - Преобразование дат
        - Определение флагов is_reply, is_forwarded
        - Определение типа медиа
        - Обработку caption как альтернативы text
        """
        mock_message = MagicMock()
        mock_message.message_id = 456
        mock_message.chat.id = 789
        mock_message.from_user.id = 101
        mock_message.text = "Hello from Aiogram"
        mock_message.date = datetime(2024, 1, 1, 13, 0, 0)
        mock_message.edit_date = None
        mock_message.reply_to_message = MagicMock()
        mock_message.forward_from = None
        mock_message.forward_origin = None
        mock_message.forward_from_chat = None
        mock_message.photo = None

        with patch("app.bot.utils._get_aiogram_media_type", return_value="text"):
            info = message_info_from_aiogram(mock_message)
            assert info["message_id"] == 456
            assert info["chat_id"] == 789
            assert info["sender_id"] == 101
            assert info["text"] == "Hello from Aiogram"
            assert info["is_reply"] is True
            assert info["is_forwarded"] is False

        # Проверка с caption
        mock_message.text = None
        mock_message.caption = "Another caption"
        info = message_info_from_aiogram(mock_message)
        assert info["text"] == "Another caption"

    def test_save_media_info_to_model(self):
        """Тест сохранения медиа-информации в модель сообщения.

        Проверяет:
        - Сохранение информации о фото (file_id, file_unique_id, file_size)
        - Сохранение информации о документе (включая mime_type)
        - Обработку случаев без медиа
        - Обработку None значения для сообщения
        """
        # Создаем модель сообщения
        chat_message = ChatMessageModel()

        # Мок-объект Telethon сообщения с фото
        mock_message = MagicMock()
        mock_photo = MagicMock()
        mock_photo.file_id = "photo_id_123"
        mock_photo.file_unique_id = "unique_id_456"
        mock_photo.file_size = 1024
        mock_message.photo = [mock_photo]

        save_media_info_to_model(chat_message, mock_message)
        assert chat_message.FK_File == "photo_id_123"
        assert chat_message.FK_FileUnique == "unique_id_456"
        assert chat_message.FFileSize == 1024

        # Проверка с документом
        mock_message.photo = None
        mock_message.document = MagicMock()
        mock_message.document.file_id = "doc_id"
        mock_message.document.file_unique_id = "doc_unique"
        mock_message.document.file_size = 2048
        mock_message.document.mime_type = "application/pdf"

        save_media_info_to_model(chat_message, mock_message)
        assert chat_message.FK_File == "doc_id"
        assert chat_message.FMimeType == "application/pdf"

        # Проверка с None - не должно вызвать ошибку
        save_media_info_to_model(chat_message, None)


# ============================================================
# 2. ТЕСТЫ ДЛЯ USERCONVERTER
# ============================================================


class TestUserConverter:
    """Тесты для класса UserConverter.

    Проверяет методы работы с пользователями:
    - get_full_name: получение полного имени из частей
    - get_display_name: получение отображаемого имени
    - get_mention: создание упоминания для Telegram
    """

    def test_get_full_name(self):
        """Тест получения полного имени пользователя.

        Проверяет различные комбинации:
        - Имя + фамилия -> "John Doe"
        - Только имя -> "John"
        - Только фамилия -> "Doe"
        - Ничего -> "Unknown User"
        - Username вместо имени -> используется username
        """
        assert UserConverter.get_full_name("John", "Doe") == "John Doe"
        assert UserConverter.get_full_name("John", None) == "John"
        assert UserConverter.get_full_name(None, "Doe") == "Doe"
        assert UserConverter.get_full_name(None, None) == "Unknown User"
        assert UserConverter.get_full_name(None, None, "john_doe") == "john_doe"
        assert UserConverter.get_full_name("John", None, "john_doe") == "John"

    def test_get_display_name(self):
        """Тест получения отображаемого имени пользователя.

        Проверяет приоритеты:
        1. Полное имя (если есть)
        2. Username с @ (если есть)
        3. User {id} (если есть)
        4. "Unknown User" (по умолчанию)
        """
        assert UserConverter.get_display_name("John", "Doe") == "John Doe"
        assert UserConverter.get_display_name(None, None, "john_doe") == "@john_doe"
        assert UserConverter.get_display_name(None, None, None, 123) == "User 123"
        assert UserConverter.get_display_name(None, None, None, None) == "Unknown User"
        assert UserConverter.get_display_name("John", None, "john_doe", 123) == "John"

    def test_get_mention(self):
        """Тест создания упоминания пользователя в формате Markdown.

        Проверяет:
        - Формат [имя](tg://user?id=id)
        - Использование полного имени при наличии
        - Использование username с @ при отсутствии имени
        - Использование "User {id}" при отсутствии имени и username
        """
        mention = UserConverter.get_mention(123, "John", "Doe", "john_doe")
        assert mention == "[John Doe](tg://user?id=123)"

        # Когда есть username, но нет имени
        mention = UserConverter.get_mention(123, None, None, "john_doe")
        assert mention == "[@john_doe](tg://user?id=123)"

        # Когда нет имени и username
        mention = UserConverter.get_mention(123, None, None, None)
        assert mention == "[User 123](tg://user?id=123)"


# ============================================================
# 3. ТЕСТЫ ДЛЯ VALIDATOR
# ============================================================


class TestValidator:
    """Тесты для класса Validator.

    Проверяет базовые валидаторы:
    - validate_not_empty: проверка на пустые значения
    - validate_length: проверка длины строки
    - validate_positive_int: проверка положительного числа
    - validate_chat_id: валидация ID чата
    - validate_user_id: валидация ID пользователя
    - validate_message_id: валидация ID сообщения
    """

    def test_validate_not_empty(self):
        """Тест проверки значения на пустоту.

        Должен возвращать True для:
        - Непустых строк, чисел, списков, словарей
        Должен возвращать False для:
        - None, пустых строк, пустых коллекций
        """
        assert Validator.validate_not_empty("text", "field") is True
        assert Validator.validate_not_empty(123, "field") is True
        assert Validator.validate_not_empty([1, 2], "field") is True
        assert Validator.validate_not_empty({"a": 1}, "field") is True

        assert Validator.validate_not_empty(None, "field") is False
        assert Validator.validate_not_empty("", "field") is False
        assert Validator.validate_not_empty([], "field") is False
        assert Validator.validate_not_empty({}, "field") is False

    def test_validate_length(self):
        """Тест проверки длины строки.

        Проверяет:
        - Допустимые длины (в пределах min-max)
        - Слишком короткие строки (< min)
        - Слишком длинные строки (> max)
        - Пустые строки (fail)
        """
        assert Validator.validate_length("test", "field", 2, 10) is True
        assert Validator.validate_length("a", "field", 2, 10) is False
        assert Validator.validate_length("a" * 20, "field", 2, 10) is False
        assert Validator.validate_length("", "field", 2, 10) is False

    def test_validate_positive_int(self):
        """Тест проверки положительного целого числа.

        Должен возвращать True для чисел > 0
        Должен возвращать False для 0 и отрицательных чисел
        """
        assert Validator.validate_positive_int(1, "field") is True
        assert Validator.validate_positive_int(100, "field") is True
        assert Validator.validate_positive_int(0, "field") is False
        assert Validator.validate_positive_int(-1, "field") is False

    def test_validate_chat_id(self):
        """Тест валидации ID чата.

        ID чата может быть положительным (приватный чат)
        или отрицательным (супергруппа, канал)
        """
        assert Validator.validate_chat_id(123) is True
        assert Validator.validate_chat_id(-100123) is True  # Супергруппа
        assert Validator.validate_chat_id(0) is False

    def test_validate_user_id(self):
        """Тест валидации ID пользователя.

        ID пользователя всегда должен быть положительным числом.
        """
        assert Validator.validate_user_id(123) is True
        assert Validator.validate_user_id(0) is False
        assert Validator.validate_user_id(-1) is False

    def test_validate_message_id(self):
        """Тест валидации ID сообщения.

        ID сообщения всегда должен быть положительным числом.
        """
        assert Validator.validate_message_id(123) is True
        assert Validator.validate_message_id(0) is False
        assert Validator.validate_message_id(-1) is False


# ============================================================
# 4. ТЕСТЫ ДЛЯ TEXTVALIDATOR
# ============================================================


class TestTextValidator:
    """Тесты для класса TextValidator.

    Проверяет:
    - sanitize_text: очистка и экранирование текста
    - validate_parse_mode: валидация режима парсинга
    - extract_mentions: извлечение упоминаний @username
    - extract_hashtags: извлечение хэштегов #tag
    - extract_links: извлечение ссылок
    - truncate_text: обрезание текста до указанной длины
    """

    def test_sanitize_text(self):
        """Тест очистки и экранирования текста.

        Проверяет:
        - Экранирование HTML-спецсимволов: < > & " '
        - Обрезание текста до максимальной длины
        - Обработку пустого текста
        """
        text = "Hello <World> & Friends"
        sanitized = TextValidator.sanitize_text(text)
        assert sanitized == "Hello &lt;World&gt; &amp; Friends"
        assert "&quot;" in TextValidator.sanitize_text('Hello "World"')

        # Обрезание длины
        long_text = "a" * 5000
        truncated = TextValidator.sanitize_text(long_text, 100)
        assert len(truncated) == 100

        # Пустой текст
        assert TextValidator.sanitize_text("") == ""

    def test_validate_parse_mode(self):
        """Тест валидации режима парсинга Telegram.

        Поддерживает: HTML, MARKDOWN, MARKDOWN_V2
        При невалидном значении возвращает HTML как fallback
        """
        assert TextValidator.validate_parse_mode("HTML") == "HTML"
        assert TextValidator.validate_parse_mode("MARKDOWN") == "MARKDOWN"
        assert TextValidator.validate_parse_mode("MARKDOWN_V2") == "MARKDOWN_V2"
        assert TextValidator.validate_parse_mode("html") == "HTML"
        assert TextValidator.validate_parse_mode(None) is None
        assert TextValidator.validate_parse_mode("INVALID") == "HTML"  # Fallback

    def test_extract_mentions(self):
        """Тест извлечения упоминаний (@username) из текста.

        Использует регулярное выражение для поиска @username
        """
        text = "Hello @john_doe and @jane_doe"
        mentions = TextValidator.extract_mentions(text)
        assert mentions == ["@john_doe", "@jane_doe"]

        assert TextValidator.extract_mentions("No mentions here") == []

    def test_extract_hashtags(self):
        """Тест извлечения хэштегов (#tag) из текста.

        Использует регулярное выражение для поиска #tag
        """
        text = "#test #hello_world #123"
        hashtags = TextValidator.extract_hashtags(text)
        assert hashtags == ["#test", "#hello_world", "#123"]

        assert TextValidator.extract_hashtags("No hashtags") == []

    def test_extract_links(self):
        """Тест извлечения ссылок (http://, https://) из текста.

        Использует регулярное выражение для поиска URL
        """
        text = "Visit https://example.com and http://test.org"
        links = TextValidator.extract_links(text)
        assert links == ["https://example.com", "http://test.org"]

        assert TextValidator.extract_links("No links here") == []

    def test_truncate_text(self):
        """Тест обрезания текста до указанной длины.

        Особенности:
        - Добавляет "..." в конце обрезанного текста
        - Старается не разрывать слова (обрезает по пробелу)
        - Возвращает оригинальный текст, если он короче max_length
        """
        text = "This is a long text that needs to be truncated."
        truncated = TextValidator.truncate_text(text, 20)
        assert truncated.startswith("This is a long")
        assert truncated.endswith("...")

        # Если текст короче лимита - возвращается без изменений
        truncated = TextValidator.truncate_text(text, 100)
        assert truncated == text

        # Пустой текст
        assert TextValidator.truncate_text("", 10) == ""


# ============================================================
# 5. ТЕСТЫ ДЛЯ COMMANDVALIDATOR
# ============================================================


class TestCommandValidator:
    """Тесты для класса CommandValidator.

    Проверяет:
    - validate_command: валидация формата команды
    - parse_command: парсинг команды и аргументов
    - is_admin_command: проверка административной команды
    """

    def test_validate_command(self):
        """Тест валидации формата команды.

        Команда должна:
        - Начинаться с "/"
        - Содержать только буквы, цифры и подчеркивания
        """
        assert CommandValidator.validate_command("/start") is True
        assert CommandValidator.validate_command("/help") is True
        assert CommandValidator.validate_command("/command_123") is True
        assert CommandValidator.validate_command("/") is False  # Пустая команда
        assert CommandValidator.validate_command("start") is False  # Без /
        assert CommandValidator.validate_command("") is False

    def test_parse_command(self):
        """Тест парсинга команды и аргументов.

        Возвращает словарь с:
        - command: полная команда
        - args: список аргументов
        - args_text: строка аргументов
        - full_text: исходный текст
        """
        result = CommandValidator.parse_command("/start")
        assert result["command"] == "/start"
        assert result["args"] == []
        assert result["args_text"] == ""

        result = CommandValidator.parse_command("/send 123 hello world")
        assert result["command"] == "/send"
        assert result["args"] == ["123", "hello", "world"]
        assert result["args_text"] == "123 hello world"

        # Пустой текст
        assert CommandValidator.parse_command("") == {}

    def test_is_admin_command(self):
        """Тест проверки, является ли команда административной.

        По умолчанию административные команды: /sync, /stats, /broadcast
        Можно передать свой список для проверки
        """
        admin_cmds = ["/sync", "/stats", "/broadcast"]
        assert CommandValidator.is_admin_command("/sync", admin_cmds) is True
        assert CommandValidator.is_admin_command("/stats", admin_cmds) is True
        assert CommandValidator.is_admin_command("/help", admin_cmds) is False

        # Использование default списка
        assert CommandValidator.is_admin_command("/sync") is True
        assert CommandValidator.is_admin_command("/help") is False


# ============================================================
# 6. ТЕСТЫ ДЛЯ DATAVALIDATOR
# ============================================================


class TestDataValidator:
    """Тесты для класса DataValidator.

    Проверяет:
    - validate_dict_keys: наличие обязательных ключей в словаре
    - validate_dict_types: соответствие типов значений
    - validate_phone_number: валидация номера телефона
    - validate_email: валидация email
    - validate_username: валидация username Telegram
    """

    def test_validate_dict_keys(self):
        """Тест проверки наличия обязательных ключей в словаре.

        Возвращает True только если все указанные ключи присутствуют
        """
        data = {"name": "John", "age": 30}
        assert DataValidator.validate_dict_keys(data, ["name", "age"]) is True
        assert DataValidator.validate_dict_keys(data, ["name", "email"]) is False
        assert DataValidator.validate_dict_keys({}, ["name"]) is False

    def test_validate_dict_types(self):
        """Тест проверки соответствия типов значений в словаре.

        Проверяет, что значения имеют ожидаемые типы
        Отсутствующие ключи не считаются ошибкой
        """
        data = {"id": 1, "name": "John", "active": True}
        type_map = {"id": int, "name": str, "active": bool}
        assert DataValidator.validate_dict_types(data, type_map) is True

        type_map_wrong = {"id": str, "name": str}
        assert DataValidator.validate_dict_types(data, type_map_wrong) is False

        # Отсутствие ключа в словаре не считается ошибкой
        assert DataValidator.validate_dict_types(data, {"email": str}) is True

    def test_validate_phone_number(self):
        """Тест валидации номера телефона.

        Требования:
        - Только цифры и знак '+'
        - Длина от 10 до 15 символов
        - Может начинаться с '+'
        """
        assert DataValidator.validate_phone_number("+1234567890") is True
        assert DataValidator.validate_phone_number("+375291234567") is True
        assert DataValidator.validate_phone_number("1234567890") is True
        assert DataValidator.validate_phone_number("+123") is False  # Слишком короткий
        assert DataValidator.validate_phone_number("") is False
        assert DataValidator.validate_phone_number("abc") is False

    def test_validate_email(self):
        """Тест валидации email адреса.

        Проверяет формат: user@domain.tld
        """
        assert DataValidator.validate_email("test@example.com") is True
        assert DataValidator.validate_email("user.name@domain.co") is True
        assert DataValidator.validate_email("invalid-email") is False
        assert DataValidator.validate_email("missing@tld") is False
        assert DataValidator.validate_email("") is False

    def test_validate_username(self):
        """Тест валидации username Telegram.

        Требования:
        - Длина от 3 до 32 символов
        - Только буквы, цифры и подчеркивание
        - Может начинаться с @ (удаляется при проверке)
        """
        assert DataValidator.validate_username("john_doe") is True
        assert DataValidator.validate_username("john123") is True
        assert DataValidator.validate_username("@john_doe") is True  # Убирает @
        assert DataValidator.validate_username("jo") is False  # Слишком короткий (мин 3)

        # Исправленная строка: ровно 33 символа (превышает максимум 32)
        long_username = "this_is_a_very_long_username_1234"  # ← 33 символа
        assert len(long_username) == 33
        assert DataValidator.validate_username(long_username) is False

        # Недопустимые символы
        assert DataValidator.validate_username("user-name") is False  # Символ -
        assert DataValidator.validate_username("") is False


# ============================================================
# 7. ТЕСТЫ ДЛЯ RATELIMITVALIDATOR
# ============================================================


class TestRateLimitValidator:
    """Тесты для класса RateLimitValidator.

    Проверяет ограничение частоты запросов:
    - is_allowed: разрешен ли запрос
    - get_remaining: оставшееся количество запросов
    - get_reset_time: время сброса лимита
    """

    def test_is_allowed(self):
        """Тест проверки разрешения запроса.

        После достижения лимита запросы отклоняются
        Каждый пользователь имеет свой независимый лимит
        """
        limiter = RateLimitValidator(limit=2, period=60)

        # Первые два запроса разрешены
        assert limiter.is_allowed("user1") is True
        assert limiter.is_allowed("user1") is True
        # Третий запрос отклонен
        assert limiter.is_allowed("user1") is False

        # Другой пользователь имеет свой лимит
        assert limiter.is_allowed("user2") is True

    def test_get_remaining(self):
        """Тест получения оставшегося количества запросов.

        Возвращает:
        - limit для новых пользователей
        - limit - использовано для активных
        - 0 при достижении лимита
        """
        limiter = RateLimitValidator(limit=3, period=60)
        assert limiter.get_remaining("user1") == 3

        limiter.is_allowed("user1")
        assert limiter.get_remaining("user1") == 2

        limiter.is_allowed("user1")
        limiter.is_allowed("user1")
        assert limiter.get_remaining("user1") == 0

    def test_get_reset_time(self):
        """Тест получения времени сброса лимита.

        Возвращает:
        - datetime сброса для активных пользователей
        - None для новых пользователей
        """
        from datetime import datetime

        limiter = RateLimitValidator(limit=2, period=10)
        limiter.is_allowed("user1")
        reset_time = limiter.get_reset_time("user1")
        assert reset_time is not None
        assert reset_time > datetime.now()

        # Для нового пользователя
        assert limiter.get_reset_time("user2") is None
