"""
Модуль с тестами для менеджера локализации (LocaleManager).

Содержит набор тестов для проверки корректности работы системы локализации:
- синглтон-паттерн (единственный экземпляр менеджера);
- поддерживаемые языки и язык по умолчанию;
- получение переводов (существующих и отсутствующих);
- fallback-механизм при отсутствии перевода;
- получение названий языков;
- перезагрузка переводов;
- вспомогательная функция t() для быстрого доступа к переводам.

Тесты проверяют как прямые методы LocaleManager, так и глобальный экземпляр locale_manager.
"""

from app.locales.manager import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, LocaleManager, locale_manager, t


class TestLocaleManager:
    """
    Набор тестов для проверки корректности работы менеджера локализации.

    Тестируются:
    - синглтон-паттерн;
    - конфигурация языков (поддерживаемые, язык по умолчанию);
    - получение переводов с учётом fallback;
    - служебные методы (название языка, перезагрузка);
    - глобальная функция t().
    """

    def test_singleton(self):
        """
        Проверяет, что LocaleManager реализует паттерн синглтон.

        Два вызова конструктора должны возвращать один и тот же объект.
        """
        manager1 = LocaleManager()
        manager2 = LocaleManager()
        assert manager1 is manager2

    def test_supported_languages(self):
        """
        Проверяет, что словарь SUPPORTED_LANGUAGES содержит русский и английский
        с корректными названиями.
        """
        assert "RU" in SUPPORTED_LANGUAGES
        assert "EN" in SUPPORTED_LANGUAGES
        assert SUPPORTED_LANGUAGES["RU"] == "Русский"

    def test_default_language(self):
        """Проверяет, что языком по умолчанию является русский (RU)."""
        assert DEFAULT_LANGUAGE == "RU"

    def test_get_translation_exists(self):
        """
        Проверяет, что у LocaleManager есть метод get() для получения переводов.
        """
        assert hasattr(locale_manager, "get")

    def test_get_translation_missing(self):
        """
        Проверяет поведение при запросе отсутствующего ключа перевода.

        Ожидается, что метод вернёт сам ключ в качестве fallback.
        """
        result = locale_manager.get("nonexistent.key")
        assert result == "nonexistent.key"

    def test_get_with_fallback(self):
        """
        Проверяет получение перевода с явным указанием языка fallback.

        При отсутствии перевода должен возвращаться сам ключ.
        """
        result = locale_manager.get("nonexistent.key", "EN")
        assert result == "nonexistent.key"

    def test_get_language_name(self):
        """
        Проверяет получение названия языка по его коду.

        Для RU должен возвращаться "Русский", для EN — "English",
        для неизвестного кода — сам код.
        """
        assert LocaleManager.get_language_name("RU") == "Русский"
        assert LocaleManager.get_language_name("EN") == "English"
        assert LocaleManager.get_language_name("XX") == "XX"

    def test_get_supported_languages(self):
        """
        Проверяет, что метод возвращает список кодов поддерживаемых языков.
        """
        langs = LocaleManager.get_supported_languages()
        assert "RU" in langs
        assert "EN" in langs

    def test_reload(self):
        """
        Проверяет, что метод перезагрузки переводов выполняется без ошибок.
        """
        locale_manager.reload()

    def test_t_function(self):
        """
        Проверяет работу глобальной функции t() для быстрого доступа к переводам.

        При отсутствии ключа должна возвращаться строка с ключом.
        """
        result = t("nonexistent.key")
        assert result == "nonexistent.key"

    def test_t_with_lang(self):
        """
        Проверяет работу функции t() с явным указанием языка.

        При отсутствии перевода должен возвращаться сам ключ.
        """
        result = t("nonexistent.key", "EN")
        assert result == "nonexistent.key"
