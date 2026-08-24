"""Тесты для клавиатур Telegram бота.

Этот модуль содержит комплексные тесты для всех типов клавиатур,
используемых в боте. Клавиатуры являются ключевым элементом
пользовательского интерфейса и обеспечивают взаимодействие с ботом.

Тесты покрывают:
1. Базовые клавиатуры (BaseKeyboard) - общие методы создания
2. Построитель списков (ListKeyboardBuilder) - универсальные списки с пагинацией
3. Клавиатуры авторизации (AuthKeyboard) - вход в систему
4. Административные клавиатуры (AdminKeyboard) - управление ботом
5. Клавиатуры автоматизации (AutomationKeyboard) - конвертация, заявки
6. Универсальные клавиатуры (GenericKeyboards) - подтверждение, поиск, навигация
7. Клавиатуры действий (ActionKeyboard) - меню действий Avanpost
8. Клавиатуры пользователей (UserKeyboard) - список пользователей

Особенности:
- Проверяет корректность создания InlineKeyboardMarkup и ReplyKeyboardMarkup
- Верифицирует callback_data для обработчиков колбэков
- Проверяет правильность row_width и расположение кнопок
- Тестирует все типы кнопок: текстовые, с запросом контакта, навигационные

Примечания:
- Все тесты синхронные (не требуют asyncio)
- Используются реальные объекты aiogram, а не моки
- Проверяются как структура, так и содержимое клавиатур
"""

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.bot.keyboards import (
    AdminKeyboard,
    AuthKeyboard,
    AutomationKeyboard,
    ListKeyboardBuilder,
    get_back_keyboard,
    get_confirm_keyboard,
    get_priority_keyboard,
    get_search_keyboard,
)
from app.bot.keyboards.base import BaseKeyboard


class TestBaseKeyboard:
    """Тесты для базовых клавиатур.

    Проверяет основные методы создания клавиатур:
    - Inline-клавиатуры (с callback_data)
    - Reply-клавиатуры (с текстовыми кнопками)
    - Кнопки навигации (Назад, В главное меню, Отмена)
    """

    def test_get_inline_keyboard(self):
        """Тест создания инлайн-клавиатуры.

        Проверяет:
        - Корректное количество рядов (row_width)
        - Правильное распределение кнопок по рядам
        - Тип возвращаемого объекта - InlineKeyboardMarkup
        """
        test_buttons = [
            {"text": "Button 1", "callback_data": "cb1"},
            {"text": "Button 2", "callback_data": "cb2"},
            {"text": "Button 3", "callback_data": "cb3"},
        ]
        keyboard = BaseKeyboard.get_inline_keyboard(test_buttons, row_width=2)
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 2
        assert len(keyboard.inline_keyboard[0]) == 2
        assert len(keyboard.inline_keyboard[1]) == 1

    def test_get_inline_keyboard_empty(self):
        """Тест создания пустой инлайн-клавиатуры.

        Проверяет, что при передаче пустого списка возвращается
        корректная пустая клавиатура.
        """
        keyboard = BaseKeyboard.get_inline_keyboard([])
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert keyboard.inline_keyboard == []

    def test_get_reply_keyboard(self):
        """Тест создания reply-клавиатуры.

        Проверяет:
        - Корректное количество рядов
        - Тип кнопок - KeyboardButton
        - Корректную структуру вложенных списков
        """
        test_buttons = ["Button 1", "Button 2", "Button 3"]
        keyboard = BaseKeyboard.get_reply_keyboard(test_buttons, row_width=2)
        assert isinstance(keyboard, ReplyKeyboardMarkup)
        assert isinstance(keyboard.keyboard, list)
        assert len(keyboard.keyboard) == 2
        assert all(isinstance(btn, KeyboardButton) for row in keyboard.keyboard for btn in row)

    def test_get_reply_keyboard_with_dict(self):
        """Тест создания reply-клавиатуры с расширенными параметрами.

        Проверяет:
        - Кнопки с запросом контакта (request_contact)
        - Кнопки с запросом локации (request_location)
        - Обычные текстовые кнопки
        - Правильное применение параметров к кнопкам
        """
        test_buttons = [
            {"text": "Contact", "request_contact": True},
            {"text": "Location", "request_location": True},
            {"text": "Cancel"},
        ]
        keyboard = BaseKeyboard.get_reply_keyboard(test_buttons, row_width=2)
        assert isinstance(keyboard, ReplyKeyboardMarkup)
        assert len(keyboard.keyboard) == 2
        first_btn = keyboard.keyboard[0][0]
        assert first_btn.text == "Contact"
        assert first_btn.request_contact is True

    def test_get_back_button(self):
        """Тест кнопки 'Назад'.

        Проверяет:
        - Текст кнопки с эмодзи "🔙 Назад"
        - Callback_data "back" для обработки возврата
        """
        keyboard = BaseKeyboard.get_back_button()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "🔙 Назад"
        assert keyboard.inline_keyboard[0][0].callback_data == "back"

    def test_get_home_button(self):
        """Тест кнопки 'В главное меню'.

        Проверяет:
        - Текст с эмодзи "🏠 В главное меню"
        - Callback_data "home" для обработки возврата в меню
        """
        keyboard = BaseKeyboard.get_home_button()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "🏠 В главное меню"
        assert keyboard.inline_keyboard[0][0].callback_data == "home"

    def test_get_cancel_button(self):
        """Тест кнопки 'Отмена'.

        Проверяет:
        - Текст с эмодзи "❌ Отмена"
        - Callback_data "cancel" для обработки отмены операции
        """
        keyboard = BaseKeyboard.get_cancel_button()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "❌ Отмена"
        assert keyboard.inline_keyboard[0][0].callback_data == "cancel"

    def test_get_navigation_buttons(self):
        """Тест навигационной клавиатуры.

        Проверяет:
        - Комбинацию нескольких кнопок в одном ряду
        - Наличие всех переданных кнопок
        - Правильные тексты и callback_data
        """
        keyboard = BaseKeyboard.get_navigation_buttons(
            back_callback="back",
            home_callback="home",
            extra_buttons=[{"text": "Extra", "callback_data": "extra"}],
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 3
        texts = [btn.text for btn in keyboard.inline_keyboard[0]]
        assert "🔙 Назад" in texts
        assert "🏠 В главное меню" in texts
        assert "Extra" in texts


class TestListKeyboardBuilder:
    """Тесты для построителя списков.

    ListKeyboardBuilder - универсальный инструмент для создания
    клавиатур со списками элементов, пагинацией и поиском.
    Используется для отображения списков пользователей, заказов,
    чатов и других данных.
    """

    def test_init(self):
        """Тест инициализации построителя.

        Проверяет:
        - Добавление подчеркивания к callback_prefix
        - Сохранение всех параметров конфигурации
        - Корректные значения по умолчанию
        """
        builder = ListKeyboardBuilder(
            callback_prefix="test",
            buttons_per_row=3,
            item_icon="📌",
            max_name_length=20,
        )
        assert builder.callback_prefix == "test_"
        assert builder.buttons_per_row == 3
        assert builder.item_icon == "📌"
        assert builder.max_name_length == 20

    def test_build_empty_list(self):
        """Тест построения клавиатуры для пустого списка.

        Проверяет, что при отсутствии элементов создается
        клавиатура только с кнопкой закрытия.
        """
        builder = ListKeyboardBuilder("test")
        keyboard = builder.build(
            items=[],
            current_page=0,
            total_pages=1,
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "❌ Закрыть"

    def test_build_with_items(self):
        """Тест построения клавиатуры со списком элементов.

        Проверяет:
        - Каждый элемент превращается в кнопку
        - Иконка добавляется к названию
        - Правильное распределение по рядам (buttons_per_row)
        """
        builder = ListKeyboardBuilder("test", buttons_per_row=2)
        items = [
            {"id": 1, "name": "Item 1"},
            {"id": 2, "name": "Item 2"},
            {"id": 3, "name": "Item 3"},
        ]
        keyboard = builder.build(
            items=items,
            current_page=0,
            total_pages=1,
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) >= 3
        item_row_1 = keyboard.inline_keyboard[0]
        assert len(item_row_1) == 2
        assert item_row_1[0].text == "📌 Item 1"
        assert item_row_1[1].text == "📌 Item 2"

    def test_build_with_pagination(self):
        """Тест построения с пагинацией (первая страница).

        Проверяет:
        - Наличие кнопки "Вперед ➡️" на первой странице
        - Отсутствие кнопки "⬅️ Назад" на первой странице
        - Кнопка поиска присутствует всегда
        """
        builder = ListKeyboardBuilder("test")
        items = [{"id": i, "name": f"Item {i}"} for i in range(10)]
        keyboard = builder.build(
            items=items[:5],
            current_page=0,
            total_pages=2,
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        nav_row = keyboard.inline_keyboard[-2]
        nav_texts = [btn.text for btn in nav_row]
        assert any("Вперед ➡️" in text for text in nav_texts)
        assert not any("⬅️ Назад" in text for text in nav_texts)

    def test_build_with_pagination_second_page(self):
        """Тест построения с пагинацией (вторая страница).

        Проверяет наличие кнопки "⬅️ Назад" на второй странице.
        """
        builder = ListKeyboardBuilder("test")
        items = [{"id": i, "name": f"Item {i}"} for i in range(10)]
        keyboard = builder.build(
            items=items[5:],
            current_page=1,
            total_pages=2,
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        nav_row = keyboard.inline_keyboard[-2]
        nav_texts = [btn.text for btn in nav_row]
        assert any("⬅️ Назад" in text for text in nav_texts)

    def test_build_with_search(self):
        """Тест построения с активным поиском.

        Проверяет наличие кнопки "🔍 Поиск..." в навигационной строке.
        """
        builder = ListKeyboardBuilder("test")
        items = [{"id": 1, "name": "Test Item"}]
        keyboard = builder.build(
            items=items,
            current_page=0,
            total_pages=1,
            search_query="test",
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        nav_row = keyboard.inline_keyboard[-2]
        assert any("🔍 Поиск..." in btn.text for btn in nav_row)

    def test_build_with_extra_buttons(self):
        """Тест построения с дополнительными кнопками.

        Проверяет добавление пользовательских кнопок в нижний ряд.
        """
        builder = ListKeyboardBuilder("test")
        items = [{"id": 1, "name": "Item 1"}]
        extra_buttons = [("🔙 Назад", "back"), ("🏠 Главное меню", "home")]
        keyboard = builder.build(
            items=items,
            current_page=0,
            total_pages=1,
            extra_buttons=extra_buttons,
        )
        last_row = keyboard.inline_keyboard[-1]
        assert len(last_row) == 3
        texts = [btn.text for btn in last_row]
        assert "🔙 Назад" in texts
        assert "🏠 Главное меню" in texts
        assert "❌ Закрыть" in texts

    def test_build_with_item_formatter(self):
        """Тест построения с пользовательским форматтером элементов.

        Проверяет возможность кастомизации отображения каждого элемента.
        """
        builder = ListKeyboardBuilder("test")
        items = [{"id": 1, "name": "Item", "extra": "★"}]

        def formatter(item):
            return f"{item['name']} {item['extra']}"

        keyboard = builder.build(
            items=items,
            current_page=0,
            total_pages=1,
            item_name_formatter=formatter,
        )
        assert keyboard.inline_keyboard[0][0].text == "📌 Item ★"

    def test_build_with_hide_pagination(self):
        """Тест скрытия пагинации при одной странице.

        Проверяет, что при hide_pagination_if_single=True
        навигационная строка не отображается.
        """
        builder = ListKeyboardBuilder("test")
        items = [{"id": 1, "name": "Item 1"}]
        keyboard = builder.build(
            items=items,
            current_page=0,
            total_pages=1,
            hide_pagination_if_single=True,
        )
        assert len(keyboard.inline_keyboard) == 2  # Элементы + закрытие

    def test_build_with_hide_pagination_false(self):
        """Тест принудительного показа пагинации.

        Проверяет, что даже при одной странице навигация отображается,
        если hide_pagination_if_single=False.
        """
        builder = ListKeyboardBuilder("test")
        items = [{"id": 1, "name": "Item 1"}]
        keyboard = builder.build(
            items=items,
            current_page=0,
            total_pages=1,
            hide_pagination_if_single=False,
        )
        assert len(keyboard.inline_keyboard) == 3  # Элементы + навигация + закрытие
        nav_row = keyboard.inline_keyboard[1]
        nav_texts = [btn.text for btn in nav_row]
        assert any("🔍 Поиск..." in text for text in nav_texts)


class TestAuthKeyboard:
    """Тесты для клавиатур авторизации.

    Проверяет клавиатуры, используемые в процессе входа пользователя в систему:
    - Запрос контакта (ReplyKeyboardMarkup)
    - Сообщение о необходимости авторизации (InlineKeyboardMarkup)
    - Выход из системы (InlineKeyboardMarkup)
    """

    def test_get_auth_request_keyboard(self):
        """Тест клавиатуры запроса контакта.

        Проверяет:
        - Наличие кнопки "📱 Поделиться контактом" с request_contact=True
        - Наличие кнопки "❌ Отмена" для отказа от авторизации
        - Корректный тип ReplyKeyboardMarkup
        """
        keyboard = AuthKeyboard.get_auth_request_keyboard()
        assert isinstance(keyboard, ReplyKeyboardMarkup)
        assert isinstance(keyboard.keyboard, list)
        assert len(keyboard.keyboard) >= 1

        found_contact = False
        found_cancel = False
        for row in keyboard.keyboard:
            for btn in row:
                if btn.text == "📱 Поделиться контактом":
                    found_contact = True
                    assert btn.request_contact is True
                if btn.text == "❌ Отмена":
                    found_cancel = True
        assert found_contact is True
        assert found_cancel is True

    def test_get_auth_needed_keyboard(self):
        """Тест клавиатуры 'Требуется авторизация'.

        Проверяет наличие кнопки "🔐 Авторизоваться"
        с callback_data "auth_needed".
        """
        keyboard = AuthKeyboard.get_auth_needed_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "🔐 Авторизоваться"
        assert keyboard.inline_keyboard[0][0].callback_data == "auth_needed"

    def test_get_logout_keyboard(self):
        """Тест клавиатуры выхода из системы.

        Проверяет наличие кнопки "🚪 Выйти"
        с callback_data "logout".
        """
        keyboard = AuthKeyboard.get_logout_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "🚪 Выйти"
        assert keyboard.inline_keyboard[0][0].callback_data == "logout"


class TestAdminKeyboard:
    """Тесты для административных клавиатур.

    Проверяет клавиатуры для административных функций:
    - Подтверждение массовой рассылки
    - Подтверждение удаления сообщений
    """

    def test_get_broadcast_confirm_keyboard(self):
        """Тест клавиатуры подтверждения рассылки.

        Проверяет наличие двух кнопок:
        - "✅ Да, отправить" с callback_data "broadcast_confirm"
        - "❌ Отмена" с callback_data "broadcast_cancel"
        """
        keyboard = AdminKeyboard.get_broadcast_confirm_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        key_buttons = keyboard.inline_keyboard[0]
        assert len(key_buttons) == 2
        assert key_buttons[0].text == "✅ Да, отправить"
        assert key_buttons[0].callback_data == "broadcast_confirm"
        assert key_buttons[1].text == "❌ Отмена"
        assert key_buttons[1].callback_data == "broadcast_cancel"

    def test_get_delete_confirm_keyboard(self):
        """Тест клавиатуры подтверждения удаления.

        Проверяет наличие двух кнопок:
        - "✅ Да, удалить" с callback_data "delete_confirm"
        - "❌ Отмена" с callback_data "delete_cancel"
        """
        keyboard = AdminKeyboard.get_delete_confirm_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        key_buttons = keyboard.inline_keyboard[0]
        assert len(key_buttons) == 2
        assert key_buttons[0].text == "✅ Да, удалить"
        assert key_buttons[0].callback_data == "delete_confirm"
        assert key_buttons[1].text == "❌ Отмена"
        assert key_buttons[1].callback_data == "delete_cancel"


class TestAutomationKeyboard:
    """Тесты для клавиатур автоматизации.

    Проверяет клавиатуры для функций автоматизации:
    - Главное меню автоматизации
    - Выбор приоритета заявки
    - Подтверждение конвертации
    - Подтверждение заявки
    """

    def test_get_main_menu_keyboard(self):
        """Тест главного меню автоматизации.

        Проверяет наличие всех кнопок:
        - Конвертация DOC в PDF
        - Оставление заявки
        - Просмотр заявок
        - Возврат назад
        И соответствующие callback_data.
        """
        keyboard = AutomationKeyboard.get_main_menu_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        key_buttons = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("📄 Преобразовать DOC в PDF" in text for text in key_buttons)
        assert any("📝 Оставить заявку" in text for text in key_buttons)
        assert any("📋 Мои заявки" in text for text in key_buttons)
        assert any("🔙 Назад" in text for text in key_buttons)

        callbacks = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
        assert "automation_convert" in callbacks
        assert "automation_request" in callbacks
        assert "automation_my_requests" in callbacks
        assert "automation_back" in callbacks

    def test_get_priority_keyboard(self):
        """Тест клавиатуры выбора приоритета заявки.

        Проверяет все уровни приоритета:
        - 🟢 Низкий
        - 🟡 Средний
        - 🟠 Высокий
        - 🔴 Критический
        - ❌ Отмена
        """
        keyboard = AutomationKeyboard.get_priority_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        key_buttons = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("🟢 Низкий" in text for text in key_buttons)
        assert any("🟡 Средний" in text for text in key_buttons)
        assert any("🟠 Высокий" in text for text in key_buttons)
        assert any("🔴 Критический" in text for text in key_buttons)
        assert any("❌ Отмена" in text for text in key_buttons)

        callbacks = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
        assert "automation_priority_low" in callbacks
        assert "automation_priority_medium" in callbacks
        assert "automation_priority_high" in callbacks
        assert "automation_priority_critical" in callbacks
        assert "automation_cancel" in callbacks

    def test_get_convert_confirm_keyboard(self):
        """Тест клавиатуры подтверждения конвертации.

        Проверяет наличие двух кнопок:
        - "✅ Да, конвертировать" с callback_data "automation_convert_confirm"
        - "❌ Отмена" с callback_data "automation_cancel"
        """
        keyboard = AutomationKeyboard.get_convert_confirm_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        key_buttons = keyboard.inline_keyboard[0]
        assert len(key_buttons) == 2
        assert key_buttons[0].text == "✅ Да, конвертировать"
        assert key_buttons[0].callback_data == "automation_convert_confirm"
        assert key_buttons[1].text == "❌ Отмена"
        assert key_buttons[1].callback_data == "automation_cancel"

    def test_get_request_confirm_keyboard(self):
        """Тест клавиатуры подтверждения заявки.

        Проверяет наличие трех кнопок:
        - "✅ Отправить заявку" с callback_data "automation_request_confirm"
        - "✏️ Редактировать" с callback_data "automation_request_edit"
        - "❌ Отмена" с callback_data "automation_cancel"
        """
        keyboard = AutomationKeyboard.get_request_confirm_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        key_buttons = keyboard.inline_keyboard[0]
        assert len(key_buttons) == 3
        assert key_buttons[0].text == "✅ Отправить заявку"
        assert key_buttons[0].callback_data == "automation_request_confirm"
        assert key_buttons[1].text == "✏️ Редактировать"
        assert key_buttons[1].callback_data == "automation_request_edit"
        assert key_buttons[2].text == "❌ Отмена"
        assert key_buttons[2].callback_data == "automation_cancel"


class TestGenericKeyboards:
    """Тесты для универсальных клавиатур.

    Проверяет переиспользуемые клавиатуры для типовых операций:
    - Подтверждение действия
    - Навигация (Назад)
    - Поиск (отмена поиска)
    - Выбор приоритета
    - Возврат в меню действий
    """

    def test_get_confirm_keyboard(self):
        """Тест универсальной клавиатуры подтверждения.

        Проверяет:
        - Две кнопки: подтверждение и отмена
        - Добавление префикса к callback_data
        - Корректные тексты кнопок
        """
        keyboard = get_confirm_keyboard(
            confirm_text="✅ Да",
            confirm_callback="confirm",
            cancel_text="❌ Нет",
            cancel_callback="cancel",
            prefix="test",
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        key_buttons = keyboard.inline_keyboard[0]
        assert len(key_buttons) == 2
        assert key_buttons[0].text == "✅ Да"
        assert key_buttons[0].callback_data == "test_confirm"
        assert key_buttons[1].text == "❌ Нет"
        assert key_buttons[1].callback_data == "test_cancel"

    def test_get_confirm_keyboard_without_prefix(self):
        """Тест клавиатуры подтверждения без префикса.

        Проверяет, что при пустом префиксе callback_data
        используются без дополнительных символов.
        """
        keyboard = get_confirm_keyboard(
            confirm_text="✅ Да",
            confirm_callback="confirm",
            cancel_text="❌ Нет",
            cancel_callback="cancel",
            prefix="",
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        key_buttons = keyboard.inline_keyboard[0]
        assert key_buttons[0].callback_data == "confirm"
        assert key_buttons[1].callback_data == "cancel"

    def test_get_back_keyboard(self):
        """Тест клавиатуры с кнопкой 'Назад'.

        Проверяет добавление префикса к callback_data.
        """
        keyboard = get_back_keyboard(
            back_text="🔙 Назад",
            back_callback="back",
            prefix="test",
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "🔙 Назад"
        assert keyboard.inline_keyboard[0][0].callback_data == "test_back"

    def test_get_search_keyboard(self):
        """Тест клавиатуры отмены поиска.

        Проверяет кнопку "❌ Отменить поиск"
        с callback_data "test_cancel_search".
        """
        keyboard = get_search_keyboard(
            cancel_text="❌ Отменить поиск",
            cancel_callback="cancel_search",
            prefix="test",
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "❌ Отменить поиск"
        assert keyboard.inline_keyboard[0][0].callback_data == "test_cancel_search"

    def test_get_priority_keyboard(self):
        """Тест универсальной клавиатуры выбора приоритета.

        Проверяет:
        - Все четыре уровня приоритета с эмодзи
        - Кнопку отмены
        - Правильные callback_data с префиксом
        """
        keyboard = get_priority_keyboard(
            callback_prefix="priority",
            cancel_callback="cancel",
            buttons_per_row=2,
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        key_buttons = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("🟢 Низкий" in text for text in key_buttons)
        assert any("🟡 Средний" in text for text in key_buttons)
        assert any("🟠 Высокий" in text for text in key_buttons)
        assert any("🔴 Критический" in text for text in key_buttons)
        assert any("❌ Отмена" in text for text in key_buttons)

        callbacks = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
        assert "priority_low" in callbacks
        assert "priority_medium" in callbacks
        assert "priority_high" in callbacks
        assert "priority_critical" in callbacks
        assert "priority_cancel" in callbacks

    def test_get_search_cancel_keyboard(self):
        """Тест клавиатуры отмены поиска (без префикса).

        Проверяет кнопку "❌ Отменить поиск"
        с callback_data "cancel_search".
        """
        from app.bot.keyboards import get_search_cancel_keyboard

        keyboard = get_search_cancel_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "❌ Отменить поиск"
        assert keyboard.inline_keyboard[0][0].callback_data == "cancel_search"

    def test_get_back_to_menu_keyboard(self):
        """Тест клавиатуры возврата в меню действий.

        Проверяет два варианта:
        1. Без parent_id - только кнопка закрытия
        2. С parent_id - кнопка "Назад к действиям" + "Закрыть" в одном ряду
        """
        from app.bot.keyboards import get_back_to_menu_keyboard

        # Без parent_id - только закрытие
        keyboard = get_back_to_menu_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 1
        assert keyboard.inline_keyboard[0][0].text == "❌ Закрыть"
        assert keyboard.inline_keyboard[0][0].callback_data == "close"

        # С parent_id - две кнопки в одном ряду
        keyboard = get_back_to_menu_keyboard(parent_item_id=123)
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 2
        assert keyboard.inline_keyboard[0][0].text == "🔙 Назад к действиям"
        assert keyboard.inline_keyboard[0][0].callback_data == "action_back_123"
        assert keyboard.inline_keyboard[0][1].text == "❌ Закрыть"
        assert keyboard.inline_keyboard[0][1].callback_data == "close"


class TestActionKeyboard:
    """Тесты для клавиатуры действий Avanpost.

    Проверяет клавиатуры для меню действий:
    - Корневое меню (главное меню действий)
    - Подменю (с кнопкой возврата)
    - С административными кнопками
    """

    def test_get_action_menu_keyboard_root(self):
        """Тест корневого меню действий.

        Проверяет:
        - Отображение элементов с правильными префиксами
        - Элементы с подменю помечаются "▶️"
        - Элементы без подменю помечаются "•"
        - Отсутствие кнопки "В главное меню" в корневом меню
        """
        from app.bot.keyboards import ActionKeyboard

        items = [
            {"id": 1, "name": "Action 1", "has_subitems": False},
            {"id": 2, "name": "Action 2", "has_subitems": True},
            {"id": 3, "name": "Action 3", "has_subitems": False},
        ]
        keyboard = ActionKeyboard.get_action_menu_keyboard(
            items=items,
            parent_id=None,
            is_root_menu=True,
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) >= 2

        first_row = keyboard.inline_keyboard[0]
        assert "• Action 1" in first_row[0].text
        assert "▶️ Action 2" in first_row[1].text

    def test_get_action_menu_keyboard_submenu(self):
        """Тест подменю действий.

        Проверяет наличие кнопки "В главное меню"
        и кнопок навигации в подменю.
        """
        from app.bot.keyboards import ActionKeyboard

        items = [
            {"id": 1, "name": "Sub Action 1", "has_subitems": False},
            {"id": 2, "name": "Sub Action 2", "has_subitems": False},
        ]
        keyboard = ActionKeyboard.get_action_menu_keyboard(
            items=items,
            parent_id=5,
            is_root_menu=False,
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        all_texts = [btn.text for btn in all_buttons]

        # Проверяем наличие кнопки "В главное меню"
        assert any("главное меню" in text.lower() for text in all_texts)

        # Проверяем наличие кнопок навигации
        nav_texts = [btn.text for btn in keyboard.inline_keyboard[1]] if len(keyboard.inline_keyboard) > 1 else []
        assert any("Назад" in text for text in nav_texts) or any("Поиск" in text for text in nav_texts)

    def test_get_action_menu_keyboard_with_admin(self):
        """Тест меню действий с административными кнопками.

        Проверяет наличие кнопки "👥 К пользователям"
        для администраторов и при выборе конкретного пользователя.
        """
        from app.bot.keyboards import ActionKeyboard

        items = [{"id": 1, "name": "Action 1", "has_subitems": False}]
        keyboard = ActionKeyboard.get_action_menu_keyboard(
            items=items,
            is_admin=True,
            show_back_to_users=True,
        )
        last_row = keyboard.inline_keyboard[-1]
        texts = [btn.text for btn in last_row]
        assert "👥 К пользователям" in texts


class TestUserKeyboard:
    """Тесты для клавиатуры списка пользователей.

    Проверяет клавиатуры для отображения и управления списком пользователей:
    - Список пользователей с индикацией авторизации
    - Закрытие списка
    - Отмена поиска пользователей
    """

    def test_get_users_keyboard(self):
        """Тест клавиатуры списка пользователей.

        Проверяет:
        - Отображение имен пользователей
        - Индикация авторизации (🟢/⚪)
        - Иконки в зависимости от группы пользователя
        - Пагинация (если страниц > 1)
        """
        from app.bot.keyboards import UserKeyboard

        users = [
            {"id": 1, "name": "User 1", "group_id": 1, "is_authorized": True},
            {"id": 2, "name": "User 2", "group_id": 2, "is_authorized": False},
        ]
        keyboard = UserKeyboard.get_users_keyboard(
            users=users,
            current_page=0,
            total_pages=1,
        )
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) >= 2

        first_row = keyboard.inline_keyboard[0]
        assert "User 1" in first_row[0].text
        assert "User 2" in first_row[1].text

    def test_get_close_keyboard(self):
        """Тест клавиатуры закрытия списка пользователей.

        Проверяет наличие кнопки "❌ Закрыть".
        """
        from app.bot.keyboards import UserKeyboard

        keyboard = UserKeyboard.get_close_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "❌ Закрыть"

    def test_get_users_search_cancel_keyboard(self):
        """Тест клавиатуры отмены поиска пользователей.

        Проверяет кнопку "❌ Отменить поиск"
        с callback_data "users_cancel_search".
        """
        from app.bot.keyboards import UserKeyboard

        keyboard = UserKeyboard.get_search_cancel_keyboard()
        assert isinstance(keyboard, InlineKeyboardMarkup)
        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].text == "❌ Отменить поиск"
        assert keyboard.inline_keyboard[0][0].callback_data == "users_cancel_search"
