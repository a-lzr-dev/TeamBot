"""
Модуль обработчиков для автоматизации.

Этот модуль предоставляет функциональность автоматизации в Telegram боте:
- Конвертация DOC/DOCX в PDF
- Создание заявок на автоматизацию
- Просмотр статуса заявок

Основные компоненты:
    - Команда /automation для вызова меню автоматизации
    - Обработчики колбэков для навигации по меню
    - Обработчики файлов для конвертации
    - Обработчики текстовых сообщений для создания заявок

Состояния FSM:
    - waiting_for_file: Ожидание файла для конвертации
    - waiting_for_request_title: Ожидание названия заявки
    - waiting_for_request_description: Ожидание описания заявки
    - waiting_for_request_priority: Ожидание выбора приоритета
    - waiting_for_request_confirm: Ожидание подтверждения заявки
"""

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from ....bot.dependencies import get_bot_manager
from ....bot.keyboards import AutomationKeyboard
from ....db import db_manager
from ....logger import bot_logger
from ....models import MessageActionType, MessageType
from ....services.automation_service import automation_service
from ....utils.decorators import log_exceptions
from .auth import is_user_authenticated

# Создание роутера для автоматизации
router = Router(name="aiogram_automation")


# ============ Состояния FSM ============


class AutomationStates(StatesGroup):
    """Состояния для процесса автоматизации."""

    waiting_for_file = State()  # Ожидание файла для конвертации
    waiting_for_request_title = State()  # Ожидание названия заявки
    waiting_for_request_description = State()  # Ожидание описания заявки
    waiting_for_request_priority = State()  # Ожидание выбора приоритета
    waiting_for_request_confirm = State()  # Ожидание подтверждения заявки


# ============ Хранилище временных данных ============

_temp_data: dict[int, dict[str, Any]] = {}


def get_temp_data(user_id: int) -> dict[str, Any]:
    """
    Получение временных данных пользователя.

    Args:
        user_id: ID пользователя Telegram

    Returns:
        dict: Словарь с временными данными
    """
    if user_id not in _temp_data:
        _temp_data[user_id] = {}
    return _temp_data[user_id]


def clear_temp_data(user_id: int) -> None:
    """
    Очистка временных данных пользователя.

    Args:
        user_id: ID пользователя Telegram
    """
    _temp_data.pop(user_id, None)


# ============ Команды ============


@router.message(Command("automation"))
@log_exceptions(bot_logger)
async def cmd_automation(message: Message, **_kwargs: Any) -> None:
    """
    Команда для вызова меню автоматизации.

    Args:
        message: Сообщение от пользователя
        **_kwargs: Дополнительные аргументы
    """
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    user_id = message.from_user.id

    # Проверка авторизации пользователя
    if not await is_user_authenticated(user_id):
        await bot_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\n"
            "Для использования автоматизации необходимо авторизоваться.\n"
            "Используйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    # Очистка временных данных при входе в меню
    clear_temp_data(user_id)

    # Отправка главного меню
    keyboard = AutomationKeyboard.get_main_menu_keyboard()
    result = await bot_manager.send_answer(
        text="🤖 **Меню автоматизации**\n\n"
        "Выберите действие:\n"
        "• 📄 **Преобразовать DOC в PDF** - конвертация документа\n"
        "• 📝 **Оставить заявку** - заявка на автоматизацию\n"
        "• 📋 **Мои заявки** - просмотр ваших заявок",
        event=message,
        message_type=MessageType.COMMAND_AUTOMATION,
        delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    # Сохранение ID сообщения для последующего удаления
    if result.get("success"):
        data = get_temp_data(user_id)
        data["menu_message_id"] = result.get("message_id")


# ============ Обработчики колбэков ============


@router.callback_query(F.data.startswith("automation_"))
@log_exceptions(bot_logger)
async def handle_automation_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка колбэков автоматизации.

    Обрабатывает все колбэки с префиксом "automation_":
    - Навигация по меню
    - Конвертация документов
    - Создание заявок
    - Просмотр заявок
    - Управление состояниями

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    if not callback.from_user:
        await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
        return

    user_id = callback.from_user.id
    data = callback.data

    await bot_manager.send_toast(event=callback)

    # --- 1. Главное меню ---
    if data == "automation_menu":
        await show_automation_menu(callback, state)

    # --- 2. Конвертация DOC в PDF ---
    elif data == "automation_convert":
        # Переход в режим ожидания файла
        await bot_manager.edit_callback_message(
            callback,
            "📄 **Преобразование DOC в PDF**\n\n"
            "Отправьте мне DOC или DOCX файл для конвертации.\n"
            "Максимальный размер файла: 50MB\n\n"
            "Для отмены используйте /cancel",
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_back_keyboard(),
        )
        await state.set_state(AutomationStates.waiting_for_file)

    elif data == "automation_convert_confirm":
        # Подтверждение конвертации
        temp_data = get_temp_data(user_id)
        doc_content = temp_data.get("doc_content")
        filename = temp_data.get("filename")

        if not doc_content or not filename:
            await bot_manager.edit_callback_message(
                callback,
                "❌ **Файл не найден**\n\nПожалуйста, отправьте файл заново.",
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )
            return

        # Начало конвертации
        await bot_manager.edit_callback_message(
            callback,
            "🔄 **Конвертация...**\n\nПожалуйста, подождите, идет преобразование документа.",
            parse_mode="Markdown",
        )

        try:
            result = await automation_service.convert_doc_to_pdf(
                doc_content=doc_content, filename=filename, user_id=user_id
            )

            if not result["success"]:
                await bot_manager.edit_callback_message(
                    callback,
                    f"❌ **Ошибка конвертации**\n\n{result['error']}",
                    parse_mode="Markdown",
                    reply_markup=AutomationKeyboard.get_back_keyboard(),
                )
                return

            # Отправка PDF-файла пользователю
            pdf_file = BufferedInputFile(file=result["pdf_content"], filename=result["pdf_filename"])

            await bot_manager.send_answer(
                text=f"✅ **Конвертация завершена!**\n\n"
                f"📄 Исходный файл: `{filename}`\n"
                f"📄 PDF: `{result['pdf_filename']}`\n"
                f"📊 Размер: `{result['file_size'] // 1024} KB`\n"
                f"⚙️ Метод: `{result.get('conversion_method', 'unknown')}`",
                event=callback,
                message_type=MessageType.COMMAND_AUTOMATION,
                delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
                parse_mode="Markdown",
            )

            if callback.message:
                await callback.message.answer_document(document=pdf_file, caption=f"📄 {result['pdf_filename']}")

            # Очистка временных данных
            clear_temp_data(user_id)

            # Возврат в главное меню
            await show_automation_menu(callback, state)

        except Exception as e:
            bot_logger.error(f"❌ Conversion error: {e}", exc_info=True)
            await bot_manager.edit_callback_message(
                text=f"❌ **Ошибка конвертации**\n\n{str(e)}",
                callback=callback,
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )

    # --- 3. Создание заявки ---
    elif data == "automation_request":
        # Начало создания заявки - запрос названия
        await bot_manager.edit_callback_message(
            callback,
            "📝 **Новая заявка на автоматизацию**\n\n"
            "Введите **название** заявки (краткое описание того, что нужно автоматизировать):",
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_back_keyboard(),
        )
        await state.set_state(AutomationStates.waiting_for_request_title)

    elif data == "automation_request_confirm":
        # Подтверждение создания заявки
        temp_data = get_temp_data(user_id)
        title = temp_data.get("request_title")
        description = temp_data.get("request_description")
        priority = temp_data.get("request_priority", "medium")

        if not title or not description:
            await bot_manager.edit_callback_message(
                callback,
                "❌ **Недостаточно данных**\n\nПожалуйста, начните создание заявки заново.",
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )
            return

        # Создание заявки в базе данных
        async with db_manager.get_session() as session:
            result = await automation_service.create_automation_request(
                user_id=user_id,
                title=title,
                description=description,
                priority=priority,
                chat_id=callback.message.chat.id if callback.message else None,
                session=session,
            )

        if not result["success"]:
            await bot_manager.edit_callback_message(
                callback,
                f"❌ **Ошибка создания заявки**\n\n{result['error']}",
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )
            return

        # Успешное создание заявки
        priority_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(priority, "🟡")

        await bot_manager.edit_callback_message(
            callback,
            f"✅ **Заявка успешно создана!**\n\n"
            f"📋 **#{result['request_id']}** {priority_emoji} {title}\n\n"
            f"📝 **Описание:**\n{description[:200]}{'...' if len(description) > 200 else ''}\n\n"
            f"📊 **Приоритет:** {priority.upper()}\n"
            f"📅 **Создана:** {result['request']['created_at']}\n\n"
            f"Статус: 🆕 Новая\n\n"
            f"Администратор рассмотрит вашу заявку в ближайшее время.",
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_back_keyboard(),
        )

        # Очистка временных данных
        clear_temp_data(user_id)

    elif data == "automation_request_edit":
        # Возврат к редактированию названия заявки
        await bot_manager.edit_callback_message(
            callback,
            "✏️ **Редактирование заявки**\n\nВведите новое **название** заявки:",
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_back_keyboard(),
        )
        await state.set_state(AutomationStates.waiting_for_request_title)

    # --- 4. Выбор приоритета ---
    elif data and data.startswith("automation_priority_"):
        priority = data.replace("automation_priority_", "")
        valid_priorities = ["low", "medium", "high", "critical"]

        if priority in valid_priorities:
            temp_data = get_temp_data(user_id)
            temp_data["request_priority"] = priority

            title = temp_data.get("request_title")
            description = temp_data.get("request_description")

            # Безопасное получение строк
            title_str = title or "Без названия"
            description_str = description or ""

            priority_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(priority, "🟡")

            description_preview = description_str[:300] + "..." if len(description_str) > 300 else description_str

            # Отображение подтверждения с выбранным приоритетом
            await bot_manager.edit_callback_message(
                callback,
                f"📝 **Подтверждение заявки**\n\n"
                f"📋 **Название:** {title_str}\n"
                f"📝 **Описание:**\n{description_preview}\n\n"
                f"📊 **Приоритет:** {priority_emoji} {priority.upper()}\n\n"
                f"✅ Отправить заявку?",
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_request_confirm_keyboard(),
            )
            await state.set_state(AutomationStates.waiting_for_request_confirm)

    # --- 5. Просмотр заявок ---
    elif data == "automation_my_requests":
        # Получение списка заявок пользователя
        async with db_manager.get_session() as session:
            requests = await automation_service.get_requests(user_id=user_id, session=session)

        if not requests:
            await bot_manager.edit_callback_message(
                callback,
                "📋 **Ваши заявки**\n\n"
                "У вас пока нет заявок на автоматизацию.\n\n"
                "Используйте 'Оставить заявку' чтобы создать новую.",
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )
            return

        # Формирование списка заявок
        status_emoji = {"new": "🆕", "in_progress": "🔄", "completed": "✅", "cancelled": "❌", "rejected": "⛔"}

        text = "📋 **Ваши заявки на автоматизацию**\n\n"
        for req in requests[-5:]:  # Последние 5 заявок
            emoji = status_emoji.get(req["status"], "📌")
            priority_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(
                req.get("priority", "medium"), "🟡"
            )
            text += (
                f"**#{req['id']}** {priority_emoji} {req['title'][:40]}\n"
                f"  {emoji} {req['status'].upper()}\n"
                f"  📅 {req['created_at'][:10]}\n\n"
            )

        if len(requests) > 5:
            text += f"\n... и еще {len(requests) - 5} заявок"

        await bot_manager.edit_callback_message(
            callback,
            text,
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_back_keyboard(),
        )

    # --- 6. Отмена и возврат ---
    elif data == "automation_cancel":
        # Полная отмена операции
        clear_temp_data(user_id)
        await state.clear()
        await show_automation_menu(callback, state)

    elif data == "automation_back":
        # Возврат в главное меню
        await state.clear()
        await show_automation_menu(callback, state)


# ============ Обработчики сообщений ============


@router.message(AutomationStates.waiting_for_file, F.document)
@log_exceptions(bot_logger)
async def handle_document_for_convert(message: Message, **_kwargs: Any) -> None:
    """
    Обработка документа для конвертации.

    Принимает DOC или DOCX файл, проверяет его и сохраняет
    для последующей конвертации.

    Args:
        message: Сообщение с документом
        **_kwargs: Дополнительные аргументы
    """
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    user_id = message.from_user.id

    document = message.document
    if not document:
        await bot_manager.send_answer(
            text="❌ **Файл не найден**\n\nПожалуйста, отправьте DOC или DOCX файл.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # Проверка типа файла
    allowed_extensions = [".doc", ".docx"]
    file_name = document.file_name or ""
    file_ext = f".{file_name.split('.')[-1].lower()}" if file_name else ""

    if not file_name:
        await bot_manager.send_answer(
            text="❌ **Имя файла не определено**\n\nПожалуйста, отправьте файл с корректным именем.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    if file_ext not in allowed_extensions:
        await bot_manager.send_answer(
            text=f"❌ **Неподдерживаемый формат**\n\n"
            f"Разрешены: {', '.join(allowed_extensions)}\n"
            f"Ваш файл: `{file_name}`",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # Проверка размера файла
    file_size = document.file_size
    if file_size is None:
        await bot_manager.send_answer(
            text="❌ **Не удалось определить размер файла**",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    if file_size > 50 * 1024 * 1024:  # 50 MB
        await bot_manager.send_answer(
            text="❌ **Файл слишком большой**\n\n"
            "Максимальный размер: 50MB\n"
            "Пожалуйста, уменьшите файл или используйте другой.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # Загрузка файла
    await bot_manager.send_toast(text="🔄 Загрузка файла...", message=message)

    try:
        bot = message.bot
        if not bot:
            await bot_manager.send_answer(
                text="❌ **Бот не инициализирован**",
                event=message,
                message_type=MessageType.COMMAND_AUTOMATION,
                delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
                parse_mode="Markdown",
            )
            return

        # Скачивание файла
        file = await bot.get_file(document.file_id)
        if file.file_path is None:
            await bot_manager.send_answer(
                text="❌ **Не удалось получить содержимое файла**\n\nПожалуйста, попробуйте еще раз.",
                event=message,
                message_type=MessageType.COMMAND_AUTOMATION,
                delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
                parse_mode="Markdown",
            )
            return

        doc_content = await bot.download_file(file.file_path)

        # Сохранение во временные данные
        temp_data = get_temp_data(user_id)
        temp_data["doc_content"] = doc_content
        temp_data["filename"] = document.file_name

        # Подтверждение загрузки
        file_size_kb = document.file_size // 1024 if document.file_size else 0
        await bot_manager.send_answer(
            text=f"✅ **Файл загружен**\n\n"
            f"📄 `{document.file_name}`\n"
            f"📊 Размер: `{file_size_kb} KB`\n\n"
            f"Начать конвертацию?",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_convert_confirm_keyboard(),
        )

    except Exception as e:
        bot_logger.error(f"❌ File download error: {e}", exc_info=True)
        await bot_manager.send_answer(
            text=f"❌ **Ошибка загрузки файла**\n\n{str(e)}",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
        )


@router.message(AutomationStates.waiting_for_file)
@log_exceptions(bot_logger)
async def handle_invalid_document(message: Message) -> None:
    """
    Обработка невалидного ввода для документа.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    await bot_manager.send_answer(
        text="📄 **Пожалуйста, отправьте DOC или DOCX файл**\n\n"
        "Используйте кнопку 'Прикрепить' и выберите файл.\n"
        "Для отмены используйте /cancel",
        event=message,
        message_type=MessageType.COMMAND_AUTOMATION,
        delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
    )


@router.message(AutomationStates.waiting_for_request_title)
@log_exceptions(bot_logger)
async def handle_request_title(message: Message, state: FSMContext) -> None:
    """
    Обработка названия заявки.

    Args:
        message: Сообщение с названием
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    user_id = message.from_user.id
    title = message.text

    # Валидация названия
    if not title or len(title.strip()) < 3:
        await bot_manager.send_answer(
            text="❌ **Название слишком короткое**\n\nПожалуйста, введите название заявки (минимум 3 символа):",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    if len(title) > 200:
        await bot_manager.send_answer(
            text="❌ **Название слишком длинное**\n\nМаксимум 200 символов. Пожалуйста, сократите.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    # Сохранение названия
    temp_data = get_temp_data(user_id)
    temp_data["request_title"] = title

    # Запрос описания
    await bot_manager.send_answer(
        text=f"✅ **Название сохранено**\n\n"
        f"📋 `{title}`\n\n"
        f"Теперь введите **описание** заявки:\n"
        f"Опишите, что нужно автоматизировать, какие проблемы решить.",
        event=message,
        message_type=MessageType.COMMAND_AUTOMATION,
        delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        parse_mode="Markdown",
    )
    await state.set_state(AutomationStates.waiting_for_request_description)


@router.message(AutomationStates.waiting_for_request_description)
@log_exceptions(bot_logger)
async def handle_request_description(message: Message, state: FSMContext) -> None:
    """
    Обработка описания заявки.

    Args:
        message: Сообщение с описанием
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    user_id = message.from_user.id
    description = message.text

    # Валидация описания
    if not description or len(description.strip()) < 10:
        await bot_manager.send_answer(
            text="❌ **Описание слишком короткое**\n\nПожалуйста, опишите заявку подробнее (минимум 10 символов):",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    if len(description) > 5000:
        await bot_manager.send_answer(
            text="❌ **Описание слишком длинное**\n\nМаксимум 5000 символов. Пожалуйста, сократите.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    # Сохранение описания
    temp_data = get_temp_data(user_id)
    temp_data["request_description"] = description

    # Выбор приоритета
    await bot_manager.send_answer(
        text=f"✅ **Описание сохранено**\n\n"
        f"📝 `{description[:100]}{'...' if len(description) > 100 else ''}`\n\n"
        f"Выберите **приоритет** заявки:",
        event=message,
        message_type=MessageType.COMMAND_AUTOMATION,
        delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        parse_mode="Markdown",
        reply_markup=AutomationKeyboard.get_priority_keyboard(),
    )
    await state.set_state(AutomationStates.waiting_for_request_priority)


@router.message(AutomationStates.waiting_for_request_priority)
@log_exceptions(bot_logger)
async def handle_request_priority_text(message: Message) -> None:
    """
    Обработка текстового ввода приоритета.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    await bot_manager.send_answer(
        text="📊 **Пожалуйста, выберите приоритет**\n\nИспользуйте кнопки ниже для выбора приоритета.",
        event=message,
        message_type=MessageType.COMMAND_AUTOMATION,
        delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        reply_markup=AutomationKeyboard.get_priority_keyboard(),
    )


# ============ Вспомогательные функции ============


async def show_automation_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Отображение главного меню автоматизации.

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()
    await state.clear()

    keyboard = AutomationKeyboard.get_main_menu_keyboard()
    await bot_manager.edit_callback_message(
        text="🤖 **Меню автоматизации**\n\n"
        "Выберите действие:\n"
        "• 📄 **Преобразовать DOC в PDF** - конвертация документа\n"
        "• 📝 **Оставить заявку** - заявка на автоматизацию\n"
        "• 📋 **Мои заявки** - просмотр ваших заявок",
        callback=callback,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


__all__ = [
    "router",
    "cmd_automation",
    "show_automation_menu",
    "AutomationStates",
]
