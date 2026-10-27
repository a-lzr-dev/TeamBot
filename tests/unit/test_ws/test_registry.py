from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ws.registry import ConnectionRegistry


@pytest.mark.asyncio
async def test_register_and_broadcast():
    reg = ConnectionRegistry()
    ws = MagicMock()
    ws.send_json = AsyncMock()

    assert await reg.register("usrA", ws) is True
    sent = await reg.broadcast_to_user("usrA", {"type": "message"})
    assert sent == 1
    ws.send_json.assert_awaited_once_with({"type": "message"})


@pytest.mark.asyncio
async def test_unregister_removes_user():
    reg = ConnectionRegistry()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    await reg.register("usrA", ws)
    await reg.unregister("usrA", ws)
    assert await reg.broadcast_to_user("usrA", {}) == 0


@pytest.mark.asyncio
async def test_max_connections():
    reg = ConnectionRegistry()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    from app.config import settings

    limit = settings.WS_NOTIFY_MAX_CONNECTIONS_PER_USER
    for _ in range(limit):
        assert await reg.register("usrA", ws) is True
    assert await reg.register("usrA", ws) is False
