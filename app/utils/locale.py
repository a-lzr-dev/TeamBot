"""
Модуль управления локализацией пользователей.

Назначение:
    Предоставляет функции для управления языковыми предпочтениями пользователей
    и получения локализованных текстов.

Основные функции:
    1. Получение и установка языка пользователя
    2. Получение локализованных текстов через locale_manager
    3. Кеширование языковых предпочтений пользователей
    4. Алиас t() для быстрого доступа к локализации

Технические особенности:
    - In-memory кеш языковых предпочтений
    - Поддержка только поддерживаемых языков (SUPPORTED_LANGUAGES)
    - Fallback на DEFAULT_LANGUAGE при отсутствии языка
    - Интеграция с locale_manager для получения текстов

Архитектура:
    - Модульный подход (функции вместо класса)
    - Использует глобальный кеш _user_language_cache
    - Работает через locale_manager
"""

from typing import Any

from ..locales.manager import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, locale_manager

# ============================================================
# 1. КЕШ ЯЗЫКОВЫХ ПРЕДПОЧТЕНИЙ
# ============================================================

# Временное хранилище предпочтений пользователей
# Ключ: user_id, Значение: код языка (например, "ru", "en")
_user_language_cache: dict[int, str] = {}

# ============================================================
# 2. УПРАВЛЕНИЕ ЯЗЫКОМ ПОЛЬЗОВАТЕЛЯ
# ============================================================


def get_user_language(user_id: int) -> str:
    """
    Получение языка пользователя.

    Args:
        user_id: ID пользователя

    Returns:
        str: Код языка (по умолчанию DEFAULT_LANGUAGE)
    """
    return _user_language_cache.get(user_id, DEFAULT_LANGUAGE)


def set_user_language(user_id: int, lang_code: str) -> bool:
    """
    Установка языка пользователя.

    Args:
        user_id: ID пользователя
        lang_code: Код языка (например, "ru", "en")

    Returns:
        bool: True если язык установлен, False если язык не поддерживается
    """
    if lang_code not in SUPPORTED_LANGUAGES:
        return False

    _user_language_cache[user_id] = lang_code
    return True


def get_current_language(data: dict) -> str:
    """
    Получение текущего языка из данных.

    Обычно используется для извлечения языка из контекста,
    например, из данных состояния FSM или callback_data.

    Args:
        data: Словарь с данными (например, из FSM storage)

    Returns:
        str: Код языка или DEFAULT_LANGUAGE
    """
    return data.get("lang", DEFAULT_LANGUAGE)  # type: ignore[no-any-return]


# ============================================================
# 3. ПОЛУЧЕНИЕ ЛОКАЛИЗОВАННЫХ ТЕКСТОВ
# ============================================================


def get_localized_text(key: str, lang_code: str | None = None, **kwargs: Any) -> str:
    """
    Удобная функция для получения локализованного текста.

    Args:
        key: Ключ текста в файле локализации
        lang_code: Код языка (если None, используется DEFAULT_LANGUAGE)
        **kwargs: Параметры для подстановки в текст (формат {param})

    Returns:
        str: Локализованный текст с подставленными параметрами

    Example:
        >>> get_localized_text("welcome", "ru", name="Иван")
        "Добро пожаловать, Иван!"
    """
    return locale_manager.get(key, lang_code, **kwargs)


def t(key: str, lang_code: str | None = None, **kwargs: Any) -> str:
    """
    Сокращение (алиас) для get_localized_text.

    Предназначен для быстрого доступа к локализации в коде.

    Args:
        key: Ключ текста в файле локализации
        lang_code: Код языка (если None, используется DEFAULT_LANGUAGE)
        **kwargs: Параметры для подстановки в текст

    Returns:
        str: Локализованный текст

    Example:
        >>> t("welcome", "ru", name="Иван")
        "Добро пожаловать, Иван!"
    """
    return get_localized_text(key, lang_code, **kwargs)


# ============================================================
# 4. ЭКСПОРТ
# ============================================================

__all__ = [
    "get_user_language",
    "set_user_language",
    "get_current_language",
    "get_localized_text",
    "t",
]
