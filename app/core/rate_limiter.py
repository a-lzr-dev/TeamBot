import asyncio
import contextlib
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from typing import Any, Optional

from ..logger import app_logger


class RateLimitStrategy(StrEnum):
    """Стратегии ограничения скорости"""

    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"


@dataclass
class RateLimitEntry:
    """Запись о запросах для rate limiting"""

    requests: list[float] = field(default_factory=list)
    last_reset: float = field(default_factory=time.time)
    warnings_count: int = 0
    blocked_until: float | None = None
    tokens: float = 0.0
    last_token_refill: float = field(default_factory=time.time)

    def is_blocked(self) -> bool:
        """Проверка, заблокирован ли пользователь"""
        if self.blocked_until is None:
            return False
        return time.time() < self.blocked_until


class RateLimiter:
    """Базовый класс для ограничения скорости запросов"""

    def __init__(
        self,
        limit: int = 10,
        period: int = 60,
        strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW,
        block_duration: int = 300,
        max_warnings: int = 3,
        name: str = "default",
    ) -> None:
        self.limit = limit
        self.period = period
        self.strategy = strategy
        self.block_duration = block_duration
        self.max_warnings = max_warnings
        self.name = name

        self._entries: dict[str, RateLimitEntry] = defaultdict(RateLimitEntry)
        self._token_refill_rate = limit / period

        self._stats = {
            "total_requests": 0,
            "blocked_requests": 0,
            "warnings": 0,
        }

    def is_allowed(self, key: str) -> bool:
        """Проверка, разрешен ли запрос для ключа"""
        current_time = time.time()
        entry = self._entries[key]

        if entry.is_blocked():
            self._stats["blocked_requests"] += 1
            return False

        if self.strategy == RateLimitStrategy.FIXED_WINDOW:
            allowed = self._check_fixed_window(entry, current_time)
        elif self.strategy == RateLimitStrategy.SLIDING_WINDOW:
            allowed = self._check_sliding_window(entry, current_time)
        elif self.strategy == RateLimitStrategy.TOKEN_BUCKET:
            allowed = self._check_token_bucket(entry, current_time)
        else:
            allowed = self._check_sliding_window(entry, current_time)

        if allowed:
            self._stats["total_requests"] += 1
            entry.warnings_count = 0
        else:
            entry.warnings_count += 1
            self._stats["warnings"] += 1

            if entry.warnings_count >= self.max_warnings:
                entry.blocked_until = current_time + self.block_duration
                app_logger.warning(
                    f"Rate limit exceeded, blocked key {key} for {self.block_duration}s", component=self.name
                )

        return allowed

    def _check_fixed_window(self, entry: RateLimitEntry, current_time: float) -> bool:
        """Проверка в фиксированном окне"""
        if current_time - entry.last_reset >= self.period:
            entry.requests = []
            entry.last_reset = current_time

        if len(entry.requests) >= self.limit:
            return False

        entry.requests.append(current_time)
        return True

    def _check_sliding_window(self, entry: RateLimitEntry, current_time: float) -> bool:
        """Проверка в скользящем окне"""
        window_start = current_time - self.period
        entry.requests = [t for t in entry.requests if t > window_start]

        if len(entry.requests) >= self.limit:
            return False

        entry.requests.append(current_time)
        return True

    def _check_token_bucket(self, entry: RateLimitEntry, current_time: float) -> bool:
        """Проверка в корзине токенов"""
        elapsed = current_time - entry.last_token_refill
        tokens_to_add = elapsed * self._token_refill_rate
        entry.tokens = min(entry.tokens + tokens_to_add, self.limit)
        entry.last_token_refill = current_time

        if entry.tokens < 1:
            return False

        entry.tokens -= 1
        return True

    def get_remaining(self, key: str) -> int:
        """Получение оставшегося количества разрешенных запросов"""
        if key not in self._entries:
            return self.limit

        entry = self._entries[key]
        current_time = time.time()

        if entry.is_blocked():
            return 0

        if self.strategy == RateLimitStrategy.FIXED_WINDOW:
            if current_time - entry.last_reset >= self.period:
                return self.limit
            return max(0, self.limit - len(entry.requests))

        elif self.strategy == RateLimitStrategy.SLIDING_WINDOW:
            window_start = current_time - self.period
            valid_requests = [t for t in entry.requests if t > window_start]
            return max(0, self.limit - len(valid_requests))

        elif self.strategy == RateLimitStrategy.TOKEN_BUCKET:
            elapsed = current_time - entry.last_token_refill
            tokens_to_add = elapsed * self._token_refill_rate
            entry.tokens = min(entry.tokens + tokens_to_add, self.limit)
            entry.last_token_refill = current_time
            return int(entry.tokens)

        return max(0, self.limit - len(entry.requests))

    def get_reset_time(self, key: str) -> float | None:
        """Получение времени сброса ограничений"""
        if key not in self._entries:
            return None

        entry = self._entries[key]
        current_time = time.time()

        if entry.is_blocked():
            return entry.blocked_until

        if self.strategy == RateLimitStrategy.FIXED_WINDOW:
            return entry.last_reset + self.period

        elif self.strategy == RateLimitStrategy.SLIDING_WINDOW:
            if not entry.requests:
                return current_time + self.period
            return min(entry.requests) + self.period

        return None

    def reset_key(self, key: str) -> None:
        """Сброс ограничений для ключа"""
        if key in self._entries:
            del self._entries[key]
            app_logger.debug(f"Rate limit reset for key {key}", component=self.name)

    def reset_all(self) -> None:
        """Сброс всех ограничений"""
        self._entries.clear()
        self._stats = {
            "total_requests": 0,
            "blocked_requests": 0,
            "warnings": 0,
        }
        app_logger.info("All rate limits reset", component=self.name)

    def get_stats(self) -> dict[str, Any]:
        """Получение статистики ограничителя"""
        blocked_count = sum(1 for e in self._entries.values() if e.is_blocked())

        return {
            "name": self.name,
            "strategy": self.strategy.value,
            "limit": self.limit,
            "period": self.period,
            "total_entries": len(self._entries),
            "blocked_keys": blocked_count,
            "total_requests": self._stats["total_requests"],
            "blocked_requests": self._stats["blocked_requests"],
            "warnings": self._stats["warnings"],
        }

    def get_entry_info(self, key: str) -> dict[str, Any] | None:
        """Получение информации о записи"""
        if key not in self._entries:
            return None

        entry = self._entries[key]

        return {
            "key": key,
            "requests_count": len(entry.requests),
            "warnings_count": entry.warnings_count,
            "is_blocked": entry.is_blocked(),
            "remaining": self.get_remaining(key),
            "reset_at": self.get_reset_time(key),
            "blocked_until": entry.blocked_until,
        }


def rate_limit(
    limiter: RateLimiter, key_func: Callable | None = None, on_limit_exceeded: Callable | None = None
) -> Callable:
    """Декоратор для ограничения скорости вызовов функций"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            key = f"{func.__name__}"
            if key_func:
                with contextlib.suppress(Exception):
                    key = f"{key}:{key_func(*args, **kwargs)}"

            if not limiter.is_allowed(key):
                if on_limit_exceeded:
                    return await on_limit_exceeded(*args, **kwargs)
                raise ValueError(f"Rate limit exceeded for {key}")

            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            key = f"{func.__name__}"
            if key_func:
                with contextlib.suppress(Exception):
                    key = f"{key}:{key_func(*args, **kwargs)}"

            if not limiter.is_allowed(key):
                if on_limit_exceeded:
                    return on_limit_exceeded(*args, **kwargs)
                raise ValueError(f"Rate limit exceeded for {key}")

            return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class RateLimitScope(StrEnum):
    """Сферы применения rate limiting"""

    API = "api"
    TELEGRAM = "telegram"
    COMMAND = "command"
    GLOBAL = "global"
    CUSTOM = "custom"


@dataclass
class RateLimitConfig:
    """Конфигурация для Rate Limiter"""

    limit: int = 100
    period: int = 60
    strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW
    block_duration: int = 300
    max_warnings: int = 3

    exclude_paths: list[str] = field(default_factory=list)
    whitelist: list[int | str] = field(default_factory=list)
    send_warning: bool = True
    warning_message: str = "Too many requests. Please try again later."


class RateLimitManager:
    """Централизованный менеджер для управления несколькими RateLimiter"""

    _instance: Optional["RateLimitManager"] = None

    def __new__(cls) -> "RateLimitManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return

        self._limiters: dict[RateLimitScope, RateLimiter] = {}
        self._configs: dict[RateLimitScope, RateLimitConfig] = {}
        self._initialized = False

        self._stats: dict[str, Any] = {"total_checks": 0, "allowed": 0, "blocked": 0, "by_scope": {}}

        app_logger.debug("✅ RateLimitManager instance created")
        self._initialized = True

    def register_scope(self, scope: RateLimitScope, config: RateLimitConfig) -> None:
        """Регистрация новой конфигурации для scope"""
        if scope in self._limiters:
            app_logger.warning(f"⚠️ Scope {scope} already registered, updating...")

        self._configs[scope] = config

        self._limiters[scope] = RateLimiter(
            limit=config.limit,
            period=config.period,
            strategy=config.strategy,
            block_duration=config.block_duration,
            max_warnings=config.max_warnings,
            name=f"rate_limiter_{scope.value}",
        )

        self._stats["by_scope"][scope.value] = {
            "config": {"limit": config.limit, "period": config.period, "strategy": config.strategy.value},
            "entries": 0,
            "blocked": 0,
        }

        app_logger.info(f"✅ Scope {scope.value} registered with limit={config.limit}/{config.period}s")

    def is_allowed(self, scope: RateLimitScope, key: str, context: dict[str, Any] | None = None) -> bool:
        """Проверка, разрешен ли запрос"""
        self._stats["total_checks"] += 1

        if scope not in self._limiters:
            app_logger.warning(f"⚠️ Scope {scope} not registered, using default")
            self._register_default_scope(scope)

        limiter = self._limiters[scope]
        config = self._configs.get(scope)

        if config and self._is_whitelisted(key, config):
            self._stats["allowed"] += 1
            return True

        if config and self._is_excluded_path(context, config):
            self._stats["allowed"] += 1
            return True

        allowed = limiter.is_allowed(key)

        if allowed:
            self._stats["allowed"] += 1
            if scope.value in self._stats["by_scope"]:
                self._stats["by_scope"][scope.value]["entries"] += 1
        else:
            self._stats["blocked"] += 1
            if scope.value in self._stats["by_scope"]:
                self._stats["by_scope"][scope.value]["blocked"] += 1

            app_logger.warning(
                f"Rate limit exceeded: scope={scope.value}, key={key}",
                extra={"scope": scope.value, "key": key, "remaining": limiter.get_remaining(key)},
            )

        return allowed

    def _register_default_scope(self, scope: RateLimitScope) -> None:
        """Регистрация дефолтной конфигурации для scope"""
        default_config = RateLimitConfig(limit=100, period=60, strategy=RateLimitStrategy.SLIDING_WINDOW)
        self.register_scope(scope, default_config)

    @staticmethod
    def _is_whitelisted(key: str, config: RateLimitConfig) -> bool:
        """Проверка, находится ли ключ в белом списке"""
        if not config.whitelist:
            return False

        for whitelist_item in config.whitelist:
            if isinstance(whitelist_item, str) and key == whitelist_item:
                return True
            if isinstance(whitelist_item, int):
                if key.startswith("user_"):
                    try:
                        user_id = int(key.split("_")[1])
                        if user_id == whitelist_item:
                            return True
                    except (ValueError, IndexError):
                        pass
                if ":" in key:
                    try:
                        ip = key.split(":")[0]
                        if ip == str(whitelist_item):
                            return True
                    except (ValueError, IndexError):
                        pass

        return False

    @staticmethod
    def _is_excluded_path(context: dict[str, Any] | None, config: RateLimitConfig) -> bool:
        """Проверка, исключен ли путь из rate limiting"""
        if not context or not config.exclude_paths:
            return False

        path = context.get("path", "")
        return any(path.startswith(excluded) for excluded in config.exclude_paths)

    def get_remaining(self, scope: RateLimitScope, key: str) -> int:
        """Получение оставшегося количества запросов"""
        if scope not in self._limiters:
            return 0

        return self._limiters[scope].get_remaining(key)

    def get_reset_time(self, scope: RateLimitScope, key: str) -> float | None:
        """Получение времени сброса"""
        if scope not in self._limiters:
            return None

        return self._limiters[scope].get_reset_time(key)

    def reset_scope(self, scope: RateLimitScope) -> None:
        """Сброс всех лимитов для scope"""
        if scope in self._limiters:
            self._limiters[scope].reset_all()
            app_logger.info(f"✅ Rate limits reset for scope {scope.value}")

    def reset_key(self, scope: RateLimitScope, key: str) -> None:
        """Сброс лимита для конкретного ключа"""
        if scope in self._limiters:
            self._limiters[scope].reset_key(key)
            app_logger.debug(f"✅ Rate limit reset for {scope.value}:{key}")

    def get_stats(self, scope: RateLimitScope | None = None) -> dict[str, Any]:
        """Получение статистики"""
        if scope:
            if scope in self._limiters:
                return {
                    "scope": scope.value,
                    "stats": self._limiters[scope].get_stats(),
                    "config": self._configs.get(scope, {}).__dict__,
                }
            return {}

        stats = self._stats.copy()
        stats["limiters"] = {}

        for scope_name, limiter in self._limiters.items():
            stats["limiters"][scope_name.value] = limiter.get_stats()

        return stats

    def update_config(self, scope: RateLimitScope, **kwargs: Any) -> None:
        """Обновление конфигурации для scope"""
        if scope not in self._configs:
            app_logger.warning(f"⚠️ Scope {scope} not found, registering...")
            self._register_default_scope(scope)

        config = self._configs[scope]

        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)

        self._limiters[scope] = RateLimiter(
            limit=config.limit,
            period=config.period,
            strategy=config.strategy,
            block_duration=config.block_duration,
            max_warnings=config.max_warnings,
            name=f"rate_limiter_{scope.value}",
        )

        app_logger.info(f"✅ Config updated for scope {scope.value}: {kwargs}")

    def get_limiter(self, scope: RateLimitScope) -> RateLimiter | None:
        """Получение экземпляра RateLimiter для scope"""
        return self._limiters.get(scope)

    def get_config(self, scope: RateLimitScope) -> RateLimitConfig | None:
        """Получение конфигурации для scope"""
        return self._configs.get(scope)


rate_limit_manager = RateLimitManager()

__all__ = [
    # Базовые компоненты
    "RateLimiter",
    "RateLimitEntry",
    "RateLimitStrategy",
    # Декоратор
    "rate_limit",
    # Менеджер
    "RateLimitManager",
    "RateLimitScope",
    "RateLimitConfig",
    "rate_limit_manager",
]
