from typing import Any

from ..locales.manager import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, locale_manager

# Временное хранилище предпочтений пользователей
_user_language_cache: dict[int, str] = {}


def get_user_language(user_id: int) -> str:
    """Получение языка пользователя"""
    return _user_language_cache.get(user_id, DEFAULT_LANGUAGE)


def set_user_language(user_id: int, lang_code: str) -> bool:
    """Установка языка пользователя"""
    if lang_code not in SUPPORTED_LANGUAGES:
        return False

    _user_language_cache[user_id] = lang_code
    return True


def get_current_language(data: dict) -> str:
    """Получение текущего языка из данных"""
    return data.get("lang", DEFAULT_LANGUAGE)  # type: ignore[no-any-return]


def get_localized_text(key: str, lang_code: str | None = None, **kwargs: Any) -> str:
    """Удобная функция для получения локализованного текста"""
    return locale_manager.get(key, lang_code, **kwargs)


# Короткий алиас
def t(key: str, lang_code: str | None = None, **kwargs: Any) -> str:
    """Сокращение для get_localized_text"""
    return get_localized_text(key, lang_code, **kwargs)


__all__ = [
    "get_user_language",
    "set_user_language",
    "get_current_language",
    "get_localized_text",
    "t",
]
