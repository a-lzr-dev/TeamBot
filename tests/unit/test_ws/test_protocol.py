from datetime import UTC, datetime

from app.ws.protocol import (
    deleted_payload,
    extract_drafty_text,
    message_payload,
    utc_iso,
)


def test_utc_iso():
    dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert utc_iso(dt) == "2026-01-01T12:00:00Z"


def test_message_payload():
    p = message_payload(
        topic="grpX",
        seq=1,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        from_user="usrA",
        body="hello",
    )
    assert p == {
        "type": "message",
        "topic": "grpX",
        "seq": 1,
        "ts": "2026-01-01T00:00:00Z",
        "from": "usrA",
        "title": "grpX",
        "body": "hello",
    }


def test_extract_drafty_text():
    assert extract_drafty_text({"txt": "hi"}) == "hi"
    assert extract_drafty_text('{"txt": "hi"}') == "hi"
    assert extract_drafty_text(None) == ""
    assert extract_drafty_text({}) == ""


def test_deleted_payload():
    p = deleted_payload(topic="grpX", seq=2, ts=None)
    assert p["type"] == "message_deleted"
    assert p["seq"] == 2
