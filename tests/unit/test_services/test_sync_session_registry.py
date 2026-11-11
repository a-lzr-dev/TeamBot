"""Тесты SyncSessionRegistry (P0.1, P0.2, P1.1)."""

from __future__ import annotations

import time

import pytest

from app.services.sync_session_registry import (
    SyncSessionRegistry,
)


@pytest.fixture()
def registry() -> SyncSessionRegistry:
    return SyncSessionRegistry()


@pytest.mark.asyncio
async def test_record_load_with_none_ts_is_noop(registry: SyncSessionRegistry) -> None:
    await registry.record_load("usrX", None, {1, 2})
    assert registry.snapshot() == {}


@pytest.mark.asyncio
async def test_record_load_with_empty_types_is_noop(registry: SyncSessionRegistry) -> None:
    await registry.record_load("usrX", "2026-11-09T12:00:00", set())
    assert registry.snapshot() == {}


@pytest.mark.asyncio
async def test_record_load_appends_packets(registry: SyncSessionRegistry) -> None:
    await registry.record_load("usrX", "T1", {1, 2})
    await registry.record_load("usrX", "T2", {3})
    snap = registry.snapshot()
    assert "usrX" in snap
    assert len(snap["usrX"]) == 2
    assert snap["usrX"][0]["sync_time"] == "T1"
    assert snap["usrX"][0]["data_types"] == [1, 2]
    assert snap["usrX"][1]["sync_time"] == "T2"


@pytest.mark.asyncio
async def test_validate_edit_accepts_both_ts(registry: SyncSessionRegistry) -> None:
    await registry.record_load("usrX", "T1", {1, 2})
    await registry.record_load("usrX", "T2", {3})

    ok, reason = await registry.validate_edit("usrX", "T1", {1})
    assert ok is True, reason
    assert reason is None

    ok, reason = await registry.validate_edit("usrX", "T2", {3})
    assert ok is True, reason


@pytest.mark.asyncio
async def test_validate_edit_rejects_unknown_ts(registry: SyncSessionRegistry) -> None:
    await registry.record_load("usrX", "T1", {1})
    ok, reason = await registry.validate_edit("usrX", "T999", {1})
    assert ok is False
    assert "ts not issued" in (reason or "")


@pytest.mark.asyncio
async def test_validate_edit_rejects_extra_dtp(registry: SyncSessionRegistry) -> None:
    await registry.record_load("usrX", "T1", {1, 2})
    ok, reason = await registry.validate_edit("usrX", "T1", {1, 2, 99})
    assert ok is False
    assert "dtp not issued" in (reason or "")
    assert "99" in (reason or "")


@pytest.mark.asyncio
async def test_validate_edit_fail_open_when_no_packets(registry: SyncSessionRegistry) -> None:
    ok, reason = await registry.validate_edit("usrX", "any", {1, 2})
    assert ok is True
    assert reason is None


@pytest.mark.asyncio
async def test_validate_edit_fail_open_after_ttl(
    registry: SyncSessionRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    await registry.record_load("usrX", "T1", {1})
    # «состарим» пакет
    for p in registry._by_user["usrX"]:
        p.expires_at = time.time() - 1
    ok, reason = await registry.validate_edit("usrX", "T1", {1})
    assert ok is True, reason


@pytest.mark.asyncio
async def test_reset_specific_ts_keeps_other(registry: SyncSessionRegistry) -> None:
    await registry.record_load("usrX", "T1", {1})
    await registry.record_load("usrX", "T2", {2})

    await registry.reset("usrX", sync_time="T1")
    snap = registry.snapshot()
    assert len(snap["usrX"]) == 1
    assert snap["usrX"][0]["sync_time"] == "T2"


@pytest.mark.asyncio
async def test_reset_all(registry: SyncSessionRegistry) -> None:
    await registry.record_load("usrX", "T1", {1})
    await registry.reset("usrX")
    assert registry.snapshot() == {}


@pytest.mark.asyncio
async def test_iterations_accumulate_and_reset(registry: SyncSessionRegistry) -> None:
    for _ in range(3):
        await registry.bump_iteration("usrX")
    ok, n = await registry.check_iterations("usrX")
    assert ok is True
    assert n == 3
    await registry.reset("usrX")
    ok, n = await registry.check_iterations("usrX")
    assert ok is True
    assert n == 0


@pytest.mark.asyncio
async def test_iterations_limit(registry: SyncSessionRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_MAX_ITERATIONS", 3, raising=False)

    for _ in range(3):
        await registry.bump_iteration("usrX")
    ok, n = await registry.check_iterations("usrX")
    assert ok is True

    await registry.bump_iteration("usrX")
    ok, n = await registry.check_iterations("usrX")
    assert ok is False
    assert n == 4
