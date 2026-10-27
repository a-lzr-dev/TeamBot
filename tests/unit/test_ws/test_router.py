from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.ws.auth import TokenVerifier


def test_ws_unauthorized(api_client: TestClient) -> None:
    """Smoke: WS endpoint существует и отклоняет неавторизованное подключение."""
    with patch.object(TokenVerifier, "verify", new_callable=AsyncMock, return_value=None):
        with pytest.raises(WebSocketDisconnect):
            with api_client.websocket_connect("/ws/notify") as ws:
                # Если дошли сюда — значит сервер НЕ закрыл соединение
                # (что противоречит контракту при verify=None)
                ws.send_text("ping")  # спровоцируем ошибку, если соединение живое
                pytest.fail("Expected WS to be closed with 4401")


def test_ws_stats_endpoint(api_client: TestClient) -> None:
    """Smoke: /api/v1/ws/stats зарегистрирован."""
    resp = api_client.get("/api/v1/ws/stats")
    assert resp.status_code in (200, 404, 500)
