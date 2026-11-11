"""Тесты механизма sync-load / sync-edit (мобильный клиент).

Покрывают:
  * пустой ответ sync-load (is_empty=true, sync_time=null);
  * lmt=null → SYNC_BASE_DEFAULT_LIMIT из настроек;
  * sync-edit отклоняет ts, которого не было в sync-load;
  * sync-edit отклоняет dtp, которого не выдавали;
  * sync-edit успешно применяет пакет и сбрасывает реестр.

Зависимости:
  * app/api/routers/client.py — эндпоинты;
  * app/services/sync_session_registry.py — in-memory реестр;
  * app/db/repositories/teamdroid.py — TeamdroidProcedureRepository;
  * app/ws/token_crypto.py — WsTokenData;
  * app/config.py — Settings (поля SYNC_BASE_*).

Подмена SQL-вызовов:
  monkeypatch.setattr(TeamdroidProcedureRepository, "<method>", fake)
  — PyCharm видит реальные методы класса, нет Unresolved reference.

Подмена настроек:
  monkeypatch.setattr(real_settings, "<field>", value)
  — client.py импортирует тот же объект settings через
    `from ...config import settings`, изменения видны.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.client import router as client_router
from app.config import settings as real_settings
from app.db.repositories.teamdroid import TeamdroidProcedureRepository
from app.services.sync_session_registry import sync_session_registry
from app.ws.token_crypto import WsTokenData

# ---------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    """Сброс реестра между тестами (sync-версия, без pytest-asyncio).

    autouse=True — чтобы каждый тест начинал с чистого реестра,
    даже если предыдущий упал и не дошёл до reset.
    """
    # до теста — на всякий случай
    sync_session_registry.reset_sync("usrTESTUSER01")
    sync_session_registry.reset_sync("usrTESTUSER02")
    yield
    # после теста — обязательно
    sync_session_registry.reset_sync("usrTESTUSER01")
    sync_session_registry.reset_sync("usrTESTUSER02")


@pytest.fixture
def client() -> TestClient:
    """FastAPI-приложение с одним роутером client (без middleware).

    middleware не подключаем: AuthMiddleware проверяет X-API-Key,
    но в тестах sync-логика не зависит от него. Если нужно
    проверить и middleware — вынести в отдельный тест.
    """
    app = FastAPI()
    app.include_router(client_router, prefix="/api/v1")
    return TestClient(app)


@pytest.fixture
def valid_token_payload() -> dict:
    """Валидная нагрузка для WsTokenData (без AES-шифрования)."""
    return {
        "user_id": "usrTESTUSER01",
        "fcm_id": "test_fid_1234567890",
        "app_version": "1.0.0",
        "app_version_code": 1,
        "date": "251109",
    }


def _make_token(monkeypatch, payload: dict) -> str:
    """Подменяем decrypt_ws_token, чтобы не возиться с AES.

    Патчим по строковому пути — это единственный способ, потому что
    client.py импортирует decrypt_ws_token как имя (`from ... import`),
    а не как атрибут модуля. PyCharm ругается на строку — это ок,
    ошибка не влияет на runtime.
    """

    def fake_decrypt(_token: str) -> WsTokenData:
        return WsTokenData(**payload)

    monkeypatch.setattr(
        "app.api.routers.client.decrypt_ws_token",
        fake_decrypt,
    )
    return "ignored_token"


# ---------------------------------------------------------------
# sync-load: пустой ответ
# ---------------------------------------------------------------


def test_sync_load_empty(client, monkeypatch, valid_token_payload):
    """sync-load при пустом результате:
    * HTTP 200;
    * is_empty=true;
    * sync_time=null;
    * server_time присутствует (клиент отличает «пусто» от «упало»).
    """
    token = _make_token(monkeypatch, valid_token_payload)

    async def fake_load(**_kw):
        return []

    # patch по реальному классу — PyCharm видит атрибут
    monkeypatch.setattr(TeamdroidProcedureRepository, "load_base_data", fake_load)

    resp = client.post(
        "/api/v1/client/sync-load",
        json={"token": token, "lmt": 1000},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_empty"] is True
    assert data["sync_time"] is None
    assert "server_time" in data
    assert data["rows"] == []


# ---------------------------------------------------------------
# sync-load: lmt=None → default из настроек
# ---------------------------------------------------------------


def test_sync_load_lmt_none_uses_config_default(client, monkeypatch, valid_token_payload):
    """Если клиент не передал lmt — берётся SYNC_BASE_DEFAULT_LIMIT.

    Подменяем поля реального Settings-объекта: client.py импортирует
    тот же объект через `from ...config import settings`, поэтому
    изменения видны. PyCharm видит реальные поля — нет подсветки.
    """
    token = _make_token(monkeypatch, valid_token_payload)

    captured: dict = {}

    async def fake_load(**kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(TeamdroidProcedureRepository, "load_base_data", fake_load)

    # Подменяем атрибуты реального Settings — client.py видит их
    # через импорт того же объекта.
    monkeypatch.setattr(real_settings, "TEAMDROID_APP_ID", 18)
    monkeypatch.setattr(real_settings, "SYNC_BASE_DEFAULT_LIMIT", 777)
    monkeypatch.setattr(real_settings, "SYNC_BASE_MAX_LIMIT", 50_000)
    monkeypatch.setattr(real_settings, "SYNC_BASE_LOAD_TIMEOUT_SEC", 30)

    resp = client.post(
        "/api/v1/client/sync-load",
        json={"token": token},  # lmt не передан
    )
    assert resp.status_code == 200
    assert captured["limit"] == 777


# ---------------------------------------------------------------
# sync-load: lmt больше SYNC_BASE_MAX_LIMIT → 400
# ---------------------------------------------------------------


def test_sync_load_lmt_exceeds_max(client, monkeypatch, valid_token_payload):
    """lmt > SYNC_BASE_MAX_LIMIT → 400, до SQL не доходим."""
    token = _make_token(monkeypatch, valid_token_payload)

    called = {"n": 0}

    async def fake_load(**_kw):
        called["n"] += 1
        return []

    monkeypatch.setattr(TeamdroidProcedureRepository, "load_base_data", fake_load)

    monkeypatch.setattr(real_settings, "TEAMDROID_APP_ID", 18)
    monkeypatch.setattr(real_settings, "SYNC_BASE_MAX_LIMIT", 50_000)
    monkeypatch.setattr(real_settings, "SYNC_BASE_DEFAULT_LIMIT", 1000)

    resp = client.post(
        "/api/v1/client/sync-load",
        json={"token": token, "lmt": 999_999},
    )
    assert resp.status_code == 400
    assert called["n"] == 0
    data = resp.json()
    assert "lmt exceeds maximum" in data["error"]


# ---------------------------------------------------------------
# sync-edit: отклоняет ts, которого не было в sync-load
# ---------------------------------------------------------------


def test_sync_edit_rejects_unknown_ts(client, monkeypatch, valid_token_payload):
    """ts не совпадает с sync_time из последнего sync-load → 400.

    SQL-вызов не должен произойти: реестр блокирует до SQL.
    """
    token = _make_token(monkeypatch, valid_token_payload)

    # имитируем, что был выдан пакет с sync_time=T1
    asyncio.run(
        sync_session_registry.record_load(
            user_id="usrTESTUSER01",
            sync_time="2026-11-09T12:00:00Z",
            data_types={1, 2},
        )
    )

    called = {"n": 0}

    async def fake_edit(_items):
        called["n"] += 1

    monkeypatch.setattr(TeamdroidProcedureRepository, "edit_base_data", fake_edit)

    resp = client.post(
        "/api/v1/client/sync-edit",
        json={
            "items": [
                {
                    "token": token,
                    "dtp": [1],
                    "ts": "2026-11-09T13:00:00Z",  # ← не совпадает
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert called["n"] == 0  # до SQL не дошли
    data = resp.json()
    assert data["error"] == "invalid_edit"
    assert len(data["issues"]) == 1
    assert data["issues"][0]["reason"].startswith("ts mismatch")


# ---------------------------------------------------------------
# sync-edit: отклоняет dtp, которого не выдавали
# ---------------------------------------------------------------


def test_sync_edit_rejects_unknown_dtp(client, monkeypatch, valid_token_payload):
    """dtp содержит тип, которого не было в sync-load → 400."""
    token = _make_token(monkeypatch, valid_token_payload)

    asyncio.run(
        sync_session_registry.record_load(
            user_id="usrTESTUSER01",
            sync_time="2026-11-09T12:00:00Z",
            data_types={1, 2},
        )
    )

    async def fake_edit(_items):
        pass

    monkeypatch.setattr(TeamdroidProcedureRepository, "edit_base_data", fake_edit)

    resp = client.post(
        "/api/v1/client/sync-edit",
        json={
            "items": [
                {
                    "token": token,
                    "dtp": [1, 999],  # 999 не выдавался
                    "ts": "2026-11-09T12:00:00Z",
                }
            ]
        },
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "invalid_edit"
    assert len(data["issues"]) == 1
    assert "dtp not issued" in data["issues"][0]["reason"]


# ---------------------------------------------------------------
# sync-edit: успех
# ---------------------------------------------------------------


def test_sync_edit_ok(client, monkeypatch, valid_token_payload):
    """Валидный sync-edit:
    * HTTP 200;
    * edit_base_data вызван с корректными items;
    * реестр сброшен после успеха.
    """
    token = _make_token(monkeypatch, valid_token_payload)

    asyncio.run(
        sync_session_registry.record_load(
            user_id="usrTESTUSER01",
            sync_time="2026-11-09T12:00:00Z",
            data_types={1, 2},
        )
    )

    captured: dict = {}

    async def fake_edit(items):
        captured["items"] = items

    monkeypatch.setattr(TeamdroidProcedureRepository, "edit_base_data", fake_edit)

    resp = client.post(
        "/api/v1/client/sync-edit",
        json={
            "items": [
                {
                    "token": token,
                    "dtp": [1, 2],
                    "ts": "2026-11-09T12:00:00Z",
                }
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["committed_items"] == 1
    assert data["committed_types"] == 2

    assert len(captured["items"]) == 1
    assert captured["items"][0]["dtp"] == [1, 2]
    assert captured["items"][0]["ts"] == "2026-11-09T12:00:00Z"
    assert captured["items"][0]["usi"] == "usrTESTUSER01"
    assert captured["items"][0]["api"] == 18
    assert captured["items"][0]["dvc"] == "test_fid_1234567890"

    # реестр сброшен после успеха
    assert sync_session_registry.snapshot() == {}


# ---------------------------------------------------------------
# sync-load: два вызова с разными dtp — оба попадают в реестр
# ---------------------------------------------------------------


def test_sync_load_two_calls_second_overwrites_registry(client, monkeypatch, valid_token_payload):
    """Повторный sync-load перезаписывает sync_time и data_types.

    Клиент должен подтверждать только последний пакет (по текущему
    sync_time). Предыдущий пакет считается «поглощённым».
    """
    token = _make_token(monkeypatch, valid_token_payload)

    responses = [
        [
            {
                "DataTypeId": 1,
                "FlagExpire": None,
                "RecordData": "[]",
                "HasMore": 0,
                "SyncTime": "2026-11-09T12:00:00Z",
            }
        ],
        [
            {
                "DataTypeId": 1,
                "FlagExpire": None,
                "RecordData": "[]",
                "HasMore": 0,
                "SyncTime": "2026-11-09T12:05:00Z",
            }
        ],
    ]
    call_idx = {"i": 0}

    async def fake_load(**_kw):
        i = call_idx["i"]
        call_idx["i"] += 1
        return responses[i]

    monkeypatch.setattr(TeamdroidProcedureRepository, "load_base_data", fake_load)
    monkeypatch.setattr(real_settings, "TEAMDROID_APP_ID", 18)
    monkeypatch.setattr(real_settings, "SYNC_BASE_DEFAULT_LIMIT", 1000)
    monkeypatch.setattr(real_settings, "SYNC_BASE_MAX_LIMIT", 50_000)
    monkeypatch.setattr(real_settings, "SYNC_BASE_LOAD_TIMEOUT_SEC", 30)

    r1 = client.post(
        "/api/v1/client/sync-load",
        json={"token": token, "dtp": [1]},
    )
    assert r1.status_code == 200
    assert r1.json()["sync_time"] == "2026-11-09T12:00:00Z"

    r2 = client.post(
        "/api/v1/client/sync-load",
        json={"token": token, "dtp": [1]},
    )
    assert r2.status_code == 200
    assert r2.json()["sync_time"] == "2026-11-09T12:05:00Z"

    # в реестре — только последний пакет
    snap = sync_session_registry.snapshot()
    assert "usrTESTUSER01" in snap
    assert snap["usrTESTUSER01"]["sync_time"] == "2026-11-09T12:05:00Z"
