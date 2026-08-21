import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from ..logger import app_logger

# Поддерживаемые языки
SUPPORTED_LANGUAGES = {"RU": "Русский", "EN": "English", "DE": "Deutsch", "ZH": "中文"}

DEFAULT_LANGUAGE = "RU"


class LocaleManager:
    """Менеджер локализации"""

    _instance: Optional["LocaleManager"] = None

    def __new__(cls) -> "LocaleManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return

        self._translations: dict[str, dict[str, str]] = {}
        self._data_dir = Path(__file__).parent / "data"
        self._initialized = False
        self._load_translations()
        self._initialized = True
        app_logger.info(f"✅ LocaleManager initialized with languages: {list(SUPPORTED_LANGUAGES.keys())}")

    def _load_translations(self) -> None:
        """Загрузка всех файлов переводов"""
        if not self._data_dir.exists():
            app_logger.warning(f"⚠️ Data directory not found: {self._data_dir}")
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._create_default_translations()
            return

        for lang_code in SUPPORTED_LANGUAGES:
            lang_file = self._data_dir / f"{lang_code}.json"
            if lang_file.exists():
                try:
                    with open(lang_file, encoding="utf-8") as f:
                        self._translations[lang_code] = json.load(f)
                    app_logger.debug(f"✅ Loaded translations for {lang_code}")
                except Exception as e:
                    app_logger.error(f"❌ Failed to load {lang_code}: {e}")
                    self._translations[lang_code] = {}
            else:
                app_logger.warning(f"⚠️ Language file not found: {lang_file}")
                self._translations[lang_code] = {}

    def _create_default_translations(self) -> None:
        """Создание файлов переводов по умолчанию"""
        for lang_code in SUPPORTED_LANGUAGES:
            lang_file = self._data_dir / f"{lang_code}.json"
            try:
                with open(lang_file, "w", encoding="utf-8") as f:
                    json.dump({}, f, ensure_ascii=False, indent=2)
                app_logger.info(f"✅ Created default translation file: {lang_file}")
            except Exception as e:
                app_logger.error(f"❌ Failed to create {lang_file}: {e}")

    @lru_cache(maxsize=128)  # noqa: B019
    def _get_translation(self, lang_code: str, key: str) -> str | None:
        """Получение перевода по ключу (с кешированием)"""
        if lang_code not in self._translations:
            lang_code = DEFAULT_LANGUAGE

        translations = self._translations.get(lang_code, {})
        return translations.get(key)

    def get(self, key: str, lang_code: str | None = None, **kwargs: Any) -> str:
        """
        Получение перевода с подстановкой параметров
        """
        if lang_code is None:
            lang_code = DEFAULT_LANGUAGE

        if lang_code not in self._translations:
            lang_code = DEFAULT_LANGUAGE

        # Получение перевода по ключу с поддержкой вложенности
        translation = self._get_translation(lang_code, key)

        if translation is None:
            # Попытка найти в английском или русском
            for fallback in ["EN", "RU"]:
                if fallback != lang_code:
                    fallback_trans = self._get_translation(fallback, key)
                    if fallback_trans is not None:
                        translation = fallback_trans
                        break

            if translation is None:
                app_logger.debug(f"⚠️ Translation not found: {key} for {lang_code}")
                return key

        # Подстановка параметров
        if kwargs and translation:
            try:
                return translation.format(**kwargs)
            except KeyError as e:
                app_logger.warning(f"⚠️ Missing format key: {e} in translation {key}")
                return translation

        return translation

    @staticmethod
    def get_language_name(lang_code: str) -> str:
        """Получение названия языка"""
        return SUPPORTED_LANGUAGES.get(lang_code, lang_code)

    @staticmethod
    def get_supported_languages() -> list[str]:
        """Получение списка поддерживаемых языков"""
        return list(SUPPORTED_LANGUAGES.keys())

    def reload(self) -> None:
        """Перезагрузка переводов"""
        self._translations.clear()
        self._get_translation.cache_clear()
        self._load_translations()
        app_logger.info("🔄 Translations reloaded")


locale_manager = LocaleManager()


# Функция для удобного использования
def t(key: str, lang_code: str | None = None, **kwargs: Any) -> str:
    """Сокращение для locale_manager.get()"""
    return locale_manager.get(key, lang_code, **kwargs)


__all__ = [
    "LocaleManager",
    "locale_manager",
    "t",
    "SUPPORTED_LANGUAGES",
    "DEFAULT_LANGUAGE",
]
