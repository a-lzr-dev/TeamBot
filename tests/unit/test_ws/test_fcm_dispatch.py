"""Тесты для FCM-логики в PushNotificationService.

Проверяем, что:
  - FCM_SEND_MODE=always → FCM отправляется всегда (msg), кроме read/silent;
  - FCM_SEND_MODE=fallback → FCM только если WS не доставил (msg),
                             но для sub — всегда;
  - FCM_SEND_MODE=never → FCM не отправляется никогда;
  - push.silent → FCM только при NO_CONNECTIONS;
  - push.type=read → FCM не отправляется;
  - push.type=sub → FCM отправляется всегда (кроме never).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ws import push_notification_service as svc_mod
from app.ws.models import RelayPush

# ============================================================
# Хелперы
# ============================================================


class _FakeFcm:
    """Фейковый FCM-клиент, запоминающий вызовы send()."""

    def __init__(self, available: bool = True, return_value: bool = True) -> None:
        self.available = available
        self._return_value = return_value
        self.calls: list[dict[str, Any]] = []

    async def send(
        self,
        fids: list[str],
        *,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
        silent: bool = False,
    ) -> bool:
        self.calls.append(
            {
                "fids": list(fids),
                "title": title,
                "body": body,
                "data": dict(data or {}),
                "silent": silent,
            }
        )
        return self._return_value


def _make_push(**overrides: Any) -> RelayPush:
    """Собрать RelayPush с разумными дефолтами."""
    base: dict[str, Any] = {
        "userId": "usrAAAAAA",
        "type": "msg",
        "topic": "usrBBBBBB",
        "seq": 5,
        "ts": "2026-01-01T00:00:00Z",
        "content": {"txt": "hello"},
    }
    base.update(overrides)
    return RelayPush(**base)


def _patch_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
    mode: str = "always",
) -> None:
    """Подменить FCM-настройки в модуле push_notification_service."""
    monkeypatch.setattr(svc_mod.settings, "FCM_ENABLED", enabled, raising=False)
    monkeypatch.setattr(svc_mod.settings, "FCM_SEND_MODE", mode, raising=False)


async def _service_with_fid(
    fcm: _FakeFcm,
    user_id: str = "usrAAAAAA",
    fid: str = "fid1234567890",
) -> svc_mod.PushNotificationService:
    """Создать сервис, зарегистрировать FID и подменить FCM-клиент."""
    svc = svc_mod.PushNotificationService()
    svc.fcm = fcm  # type: ignore[assignment]
    await svc.update_fid(user_id, fid)
    return svc


# ============================================================
# Режим "always"
# ============================================================


@pytest.mark.asyncio
async def test_always_sends_fcm_even_if_ws_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FCM_SEND_MODE=always → FCM отправляется даже если WS доставил."""
    _patch_settings(monkeypatch, enabled=True, mode="always")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.DELIVERED

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.DELIVERED
    assert len(fcm.calls) == 1, "FCM must be sent in 'always' mode even if WS delivered"
    call = fcm.calls[0]
    assert call["fids"] == ["fid1234567890"]
    assert call["title"] == "New message"
    assert call["body"] == "hello"
    assert call["data"]["type"] == "message"
    assert call["data"]["topic"] == "usrBBBBBB"
    assert call["data"]["seq"] == "5"
    assert call["silent"] is False


@pytest.mark.asyncio
async def test_always_sends_fcm_if_ws_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FCM_SEND_MODE=always → FCM отправляется и при NO_CONNECTIONS."""
    _patch_settings(monkeypatch, enabled=True, mode="always")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.NO_CONNECTIONS

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.NO_CONNECTIONS
    assert len(fcm.calls) == 1


# ============================================================
# Режим "fallback"
# ============================================================


@pytest.mark.asyncio
async def test_fallback_skips_fcm_if_ws_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FCM_SEND_MODE=fallback + WS доставил → FCM НЕ отправляется."""
    _patch_settings(monkeypatch, enabled=True, mode="fallback")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.DELIVERED

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.DELIVERED
    assert fcm.calls == [], "FCM must not be sent in 'fallback' mode if WS delivered"


@pytest.mark.asyncio
async def test_fallback_sends_fcm_if_ws_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FCM_SEND_MODE=fallback + WS офлайн → FCM отправляется."""
    _patch_settings(monkeypatch, enabled=True, mode="fallback")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.NO_CONNECTIONS

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.NO_CONNECTIONS
    assert len(fcm.calls) == 1
    assert fcm.calls[0]["body"] == "hello"


@pytest.mark.asyncio
async def test_fallback_sends_fcm_on_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FCM_SEND_MODE=fallback + PARTIAL (часть WS-сокетов умерла) → FCM отправляется."""
    _patch_settings(monkeypatch, enabled=True, mode="fallback")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.PARTIAL

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.PARTIAL
    assert len(fcm.calls) == 1


@pytest.mark.asyncio
async def test_fallback_sends_fcm_on_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FCM_SEND_MODE=fallback + FAILED (все WS-сокеты умерли) → FCM отправляется."""
    _patch_settings(monkeypatch, enabled=True, mode="fallback")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.FAILED

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.FAILED
    assert len(fcm.calls) == 1


# ============================================================
# Режим "never"
# ============================================================


@pytest.mark.asyncio
async def test_never_skips_fcm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FCM_SEND_MODE=never → FCM не отправляется никогда."""
    _patch_settings(monkeypatch, enabled=True, mode="never")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.NO_CONNECTIONS

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.NO_CONNECTIONS
    assert fcm.calls == []


# ============================================================
# FCM отключён глобально (FCM_ENABLED=false)
# ============================================================


@pytest.mark.asyncio
async def test_fcm_disabled_globally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FCM_ENABLED=false → FCM не отправляется, даже если mode=always."""
    _patch_settings(monkeypatch, enabled=False, mode="always")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.DELIVERED

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.DELIVERED
    assert fcm.calls == []


# ============================================================
# silent push
# ============================================================


@pytest.mark.asyncio
async def test_silent_push_sends_fcm_only_if_ws_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """silent=True + WS доставил → FCM НЕ отправляется (нет UI-уведомления)."""
    _patch_settings(monkeypatch, enabled=True, mode="always")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.DELIVERED

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push(silent=True))

    assert status == svc_mod.DeliveryStatus.DELIVERED
    assert fcm.calls == [], "silent push must not be duplicated via FCM if WS delivered"


@pytest.mark.asyncio
async def test_silent_push_sends_fcm_if_ws_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """silent=True + WS офлайн → FCM отправляется (синхронизация в фоне)."""
    _patch_settings(monkeypatch, enabled=True, mode="always")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.NO_CONNECTIONS

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push(silent=True))

    assert status == svc_mod.DeliveryStatus.NO_CONNECTIONS
    assert len(fcm.calls) == 1
    assert fcm.calls[0]["silent"] is True
    assert fcm.calls[0]["title"] == ""
    assert fcm.calls[0]["body"] == ""


# ============================================================
# read (квитанция)
# ============================================================


@pytest.mark.asyncio
async def test_read_push_never_sent_via_fcm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """type=read → FCM не отправляется ни в каком режиме."""
    _patch_settings(monkeypatch, enabled=True, mode="always")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.SKIPPED_TYPE

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push(type="read", seq=7))

    assert status == svc_mod.DeliveryStatus.SKIPPED_TYPE
    assert fcm.calls == []


# ============================================================
# sub (приглашение в чат)
# ============================================================


@pytest.mark.asyncio
async def test_sub_sent_via_fcm_even_if_ws_delivered_in_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """type=sub + fallback + WS доставил → FCM всё равно отправляется."""
    _patch_settings(monkeypatch, enabled=True, mode="fallback")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.DELIVERED

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push(type="sub", topic="grpCCCCCC", seq=0, **{"from": "usrDDDDDD"}))

    assert status == svc_mod.DeliveryStatus.DELIVERED
    assert len(fcm.calls) == 1, "sub must always go through FCM (fallback mode)"
    call = fcm.calls[0]
    assert call["title"] == "New chat"
    assert call["body"] == "usrDDDDDD"
    assert call["data"]["type"] == "subscription"
    assert call["data"]["topic"] == "grpCCCCCC"


@pytest.mark.asyncio
async def test_sub_not_sent_via_fcm_in_never_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """type=sub + mode=never → FCM не отправляется."""
    _patch_settings(monkeypatch, enabled=True, mode="never")

    fcm = _FakeFcm()
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.NO_CONNECTIONS

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    await svc.dispatch(_make_push(type="sub", topic="grpCCCCCC", seq=0, **{"from": "usrDDDDDD"}))

    assert fcm.calls == []


# ============================================================
# Нет FID у пользователя
# ============================================================


@pytest.mark.asyncio
async def test_no_fid_no_fcm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если у пользователя нет FID — FCM.send() не вызывается."""
    _patch_settings(monkeypatch, enabled=True, mode="always")

    fcm = _FakeFcm()
    # Сервис без update_fid: FID не зарегистрирован.
    svc = svc_mod.PushNotificationService()
    svc.fcm = fcm  # type: ignore[assignment]

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.NO_CONNECTIONS

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.NO_CONNECTIONS
    assert fcm.calls == [], "no FID registered → no FCM send"


# ============================================================
# FCM вернул ошибку
# ============================================================


@pytest.mark.asyncio
async def test_fcm_send_failure_increments_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если FCM.send() вернул False — счётчик fcm_failed растёт."""
    _patch_settings(monkeypatch, enabled=True, mode="always")

    fcm = _FakeFcm(available=True, return_value=False)
    svc = await _service_with_fid(fcm)

    async def _fake_ws(push: RelayPush, payload: dict[str, Any]) -> svc_mod.DeliveryStatus:
        return svc_mod.DeliveryStatus.DELIVERED

    svc._dispatch_ws = _fake_ws  # type: ignore[assignment]

    status = await svc.dispatch(_make_push())

    assert status == svc_mod.DeliveryStatus.DELIVERED
    assert len(fcm.calls) == 1
    # Счётчики обновляются внутри _dispatch_fcm.
    assert svc._stats["fcm_failed"] >= 1
