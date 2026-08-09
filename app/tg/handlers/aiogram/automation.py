from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Document, Message

from ....db import db_manager
from ....exceptions import log_exceptions
from ....logger import tg_logger
from ....models import MessageActionType, MessageType
from ....services.automation_service import automation_service
from ....tg.dependencies import get_tg_manager
from ...keyboards import AutomationKeyboard
from .auth import is_user_authenticated

router = Router(name="aiogram_automation")


# ============ Состояния ============


class AutomationStates(StatesGroup):
    """Состояния для автоматизации"""

    waiting_for_file = State()
    waiting_for_request_title = State()
    waiting_for_request_description = State()
    waiting_for_request_priority = State()
    waiting_for_request_confirm = State()


# ============ Хранилище временных данных ============

_temp_data: dict[int, dict[str, Any]] = {}


def get_temp_data(user_id: int) -> dict[str, Any]:
    """Получение временных данных пользователя"""
    if user_id not in _temp_data:
        _temp_data[user_id] = {}
    return _temp_data[user_id]


def clear_temp_data(user_id: int) -> None:
    """Очистка временных данных пользователя"""
    _temp_data.pop(user_id, None)


# ============ Команды ============


@router.message(Command("automation"))
@log_exceptions(tg_logger)
async def cmd_automation(message: Message, **_kwargs: Any) -> None:
    """Команда для вызова меню автоматизации"""
    tg_manager = get_tg_manager()
    user_id = message.from_user.id

    # Проверка авторизации
    if not await is_user_authenticated(user_id):
        await tg_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\n"
            "Для использования автоматизации необходимо авторизоваться.\n"
            "Используйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    # Очистка временных данных
    clear_temp_data(user_id)

    # Отправка меню
    keyboard = AutomationKeyboard.get_main_menu_keyboard()
    result = await tg_manager.send_answer(
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
@log_exceptions(tg_logger)
async def handle_automation_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка колбэков автоматизации"""
    tg_manager = get_tg_manager()
    user_id = callback.from_user.id
    data = callback.data

    await tg_manager.send_toast(event=callback)

    # --- Главное меню ---
    if data == "automation_menu":
        await show_automation_menu(callback, state)

    # --- Конвертация ---
    elif data == "automation_convert":
        await tg_manager.edit_callback_message(
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
        temp_data = get_temp_data(user_id)
        doc_content = temp_data.get("doc_content")
        filename = temp_data.get("filename")

        if not doc_content or not filename:
            await tg_manager.edit_callback_message(
                callback,
                "❌ **Файл не найден**\n\nПожалуйста, отправьте файл заново.",
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )
            return

        # Конвертация
        await tg_manager.edit_callback_message(
            callback,
            "🔄 **Конвертация...**\n\nПожалуйста, подождите, идет преобразование документа.",
            parse_mode="Markdown",
        )

        try:
            result = await automation_service.convert_doc_to_pdf(
                doc_content=doc_content, filename=filename, user_id=user_id
            )

            if not result["success"]:
                await tg_manager.edit_callback_message(
                    callback,
                    f"❌ **Ошибка конвертации**\n\n{result['error']}",
                    parse_mode="Markdown",
                    reply_markup=AutomationKeyboard.get_back_keyboard(),
                )
                return

            # Отправка PDF-файла
            pdf_file = BufferedInputFile(file=result["pdf_content"], filename=result["pdf_filename"])

            await tg_manager.send_answer(
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

            # Отправка самого PDF-файла через бота
            await callback.message.answer_document(document=pdf_file, caption=f"📄 {result['pdf_filename']}")

            # Очистка временных данных
            clear_temp_data(user_id)

            # Возврат в меню
            await show_automation_menu(callback, state)

        except Exception as e:
            tg_logger.error(f"❌ Conversion error: {e}", exc_info=True)
            await tg_manager.edit_callback_message(
                text=f"❌ **Ошибка конвертации**\n\n{str(e)}",
                callback=callback,
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )

    # --- Заявка ---
    elif data == "automation_request":
        await tg_manager.edit_callback_message(
            callback,
            "📝 **Новая заявка на автоматизацию**\n\n"
            "Введите **название** заявки (краткое описание того, что нужно автоматизировать):",
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_back_keyboard(),
        )
        await state.set_state(AutomationStates.waiting_for_request_title)

    elif data == "automation_request_confirm":
        temp_data = get_temp_data(user_id)
        title = temp_data.get("request_title")
        description = temp_data.get("request_description")
        priority = temp_data.get("request_priority", "medium")

        if not title or not description:
            await tg_manager.edit_callback_message(
                callback,
                "❌ **Недостаточно данных**\n\nПожалуйста, начните создание заявки заново.",
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )
            return

        # Создание заявки
        async with db_manager.get_session() as session:
            result = await automation_service.create_automation_request(
                user_id=user_id,
                title=title,
                description=description,
                priority=priority,
                chat_id=callback.message.chat.id,
                session=session,
            )

        if not result["success"]:
            await tg_manager.edit_callback_message(
                callback,
                f"❌ **Ошибка создания заявки**\n\n{result['error']}",
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )
            return

        # Успех
        priority_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(priority, "🟡")

        await tg_manager.edit_callback_message(
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
        # Возврат к редактированию
        await tg_manager.edit_callback_message(
            callback,
            "✏️ **Редактирование заявки**\n\nВведите новое **название** заявки:",
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_back_keyboard(),
        )
        await state.set_state(AutomationStates.waiting_for_request_title)

    # --- Приоритет ---
    elif data.startswith("automation_priority_"):
        priority = data.replace("automation_priority_", "")
        valid_priorities = ["low", "medium", "high", "critical"]

        if priority in valid_priorities:
            temp_data = get_temp_data(user_id)
            temp_data["request_priority"] = priority

            title = temp_data.get("request_title")
            description = temp_data.get("request_description")

            # Проверка на None
            title_str = title or "Без названия"
            description_str = description or ""

            priority_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(priority, "🟡")

            # Безопасное обрезание описания
            description_preview = description_str[:300] + "..." if len(description_str) > 300 else description_str

            await tg_manager.edit_callback_message(
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

    # --- Мои заявки ---
    elif data == "automation_my_requests":
        async with db_manager.get_session() as session:
            requests = await automation_service.get_requests(user_id=user_id, session=session)

        if not requests:
            await tg_manager.edit_callback_message(
                callback,
                "📋 **Ваши заявки**\n\n"
                "У вас пока нет заявок на автоматизацию.\n\n"
                "Используйте 'Оставить заявку' чтобы создать новую.",
                parse_mode="Markdown",
                reply_markup=AutomationKeyboard.get_back_keyboard(),
            )
            return

        status_emoji = {"new": "🆕", "in_progress": "🔄", "completed": "✅", "cancelled": "❌", "rejected": "⛔"}

        text = "📋 **Ваши заявки на автоматизацию**\n\n"
        for req in requests[-5:]:  # Последние 5
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

        await tg_manager.edit_callback_message(
            callback,
            text,
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_back_keyboard(),
        )

    # --- Отмена ---
    elif data == "automation_cancel":
        clear_temp_data(user_id)
        await state.clear()
        await show_automation_menu(callback, state)

    # --- Назад ---
    elif data == "automation_back":
        await state.clear()
        await show_automation_menu(callback, state)


# ============ Обработчики сообщений ============


@router.message(AutomationStates.waiting_for_file, F.document)
@log_exceptions(tg_logger)
async def handle_document_for_convert(message: Message, **_kwargs: Any) -> None:
    """Обработка документа для конвертации"""
    tg_manager = get_tg_manager()
    user_id = message.from_user.id
    document: Document = message.document

    # Проверка типа файла
    allowed_extensions = [".doc", ".docx"]
    file_ext = f".{document.file_name.split('.')[-1].lower()}" if document.file_name else ""

    if file_ext not in allowed_extensions:
        await tg_manager.send_answer(
            text=f"❌ **Неподдерживаемый формат**\n\n"
            f"Разрешены: {', '.join(allowed_extensions)}\n"
            f"Ваш файл: `{document.file_name}`",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # Проверка размера
    if document.file_size > 50 * 1024 * 1024:  # 50 MB
        await tg_manager.send_answer(
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
    await tg_manager.send_toast(text="🔄 Загрузка файла...", message=message)

    try:
        file = await message.bot.get_file(document.file_id)
        doc_content = await message.bot.download_file(file.file_path)

        # Сохранение во временные данные
        temp_data = get_temp_data(user_id)
        temp_data["doc_content"] = doc_content
        temp_data["filename"] = document.file_name

        # Подтверждение
        await tg_manager.send_answer(
            text=f"✅ **Файл загружен**\n\n"
            f"📄 `{document.file_name}`\n"
            f"📊 Размер: `{document.file_size // 1024} KB`\n\n"
            f"Начать конвертацию?",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
            reply_markup=AutomationKeyboard.get_convert_confirm_keyboard(),
        )

    except Exception as e:
        tg_logger.error(f"❌ File download error: {e}", exc_info=True)
        await tg_manager.send_answer(
            text=f"❌ **Ошибка загрузки файла**\n\n{str(e)}",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
            parse_mode="Markdown",
        )


@router.message(AutomationStates.waiting_for_file)
@log_exceptions(tg_logger)
async def handle_invalid_document(message: Message) -> None:
    """Обработка невалидного ввода для документа"""
    tg_manager = get_tg_manager()

    await tg_manager.send_answer(
        text="📄 **Пожалуйста, отправьте DOC или DOCX файл**\n\n"
        "Используйте кнопку 'Прикрепить' и выберите файл.\n"
        "Для отмены используйте /cancel",
        event=message,
        message_type=MessageType.COMMAND_AUTOMATION,
        delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
    )


@router.message(AutomationStates.waiting_for_request_title)
@log_exceptions(tg_logger)
async def handle_request_title(message: Message, state: FSMContext) -> None:
    """Обработка названия заявки"""
    tg_manager = get_tg_manager()
    user_id = message.from_user.id
    title = message.text

    if not title or len(title.strip()) < 3:
        await tg_manager.send_answer(
            text="❌ **Название слишком короткое**\n\nПожалуйста, введите название заявки (минимум 3 символа):",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    if len(title) > 200:
        await tg_manager.send_answer(
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
    await tg_manager.send_answer(
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
@log_exceptions(tg_logger)
async def handle_request_description(message: Message, state: FSMContext) -> None:
    """Обработка описания заявки"""
    tg_manager = get_tg_manager()
    user_id = message.from_user.id
    description = message.text

    if not description or len(description.strip()) < 10:
        await tg_manager.send_answer(
            text="❌ **Описание слишком короткое**\n\nПожалуйста, опишите заявку подробнее (минимум 10 символов):",
            event=message,
            message_type=MessageType.COMMAND_AUTOMATION,
            delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        )
        return

    if len(description) > 5000:
        await tg_manager.send_answer(
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
    await tg_manager.send_answer(
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
@log_exceptions(tg_logger)
async def handle_request_priority_text(message: Message) -> None:
    """Обработка текстового ввода приоритета (если не используется клавиатура)"""
    tg_manager = get_tg_manager()

    await tg_manager.send_answer(
        text="📊 **Пожалуйста, выберите приоритет**\n\nИспользуйте кнопки ниже для выбора приоритета.",
        event=message,
        message_type=MessageType.COMMAND_AUTOMATION,
        delete_by_type=MessageActionType.COMMAND_AUTOMATION_CLEANUP,
        reply_markup=AutomationKeyboard.get_priority_keyboard(),
    )


# ============ Вспомогательные функции ============


async def show_automation_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Отображение главного меню автоматизации"""
    tg_manager = get_tg_manager()
    await state.clear()

    keyboard = AutomationKeyboard.get_main_menu_keyboard()
    await tg_manager.edit_callback_message(
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
