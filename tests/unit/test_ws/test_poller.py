from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws.sources.poller import TinodePoller


@pytest.mark.asyncio
async def test_dispatch_skips_duplicate_seq():
    poller = TinodePoller()
    row = MagicMock()
    row.__getitem__.side_effect = lambda k: {
        "topic": "grpA",
        "seqid": 5,
        "createdat": None,
        "from_user": "usrX",
        "content": {"txt": "hi"},
    }[k]

    with (
        patch.object(TinodePoller, "_get_recipients", AsyncMock(return_value=["usrY"])),
        patch("app.ws.sources.poller.connection_registry") as reg,
    ):
        reg.broadcast_to_user = AsyncMock(return_value=1)

        await poller._dispatch(row)
        await poller._dispatch(row)  # тот же seq — должен быть пропущен

        assert reg.broadcast_to_user.await_count == 1
        assert poller._stats["skipped_dup"] == 1
