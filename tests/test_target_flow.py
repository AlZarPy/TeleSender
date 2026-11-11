"""Судьба адресата: не терять людей при сбоях и не дублировать отправку."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_target_flow.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db, worker  # noqa: E402


def _seed() -> tuple[dict, dict]:
    db.init()
    for table in ("campaign_targets", "campaigns", "recipients", "events", "accounts"):
        db.execute(f"DELETE FROM {table}")
    db.execute("""INSERT INTO campaigns(id, name, template, status)
                  VALUES(1, 't', 'текст {раз|два}', 'active')""")
    db.execute("""INSERT INTO recipients(id, username, first_name, status)
                  VALUES(10, 'user_one', 'Иван', 'active')""")
    db.execute("""INSERT INTO campaign_targets(campaign_id, recipient_id, state)
                  VALUES(1, 10, 'pending')""")
    campaign = dict(db.q1("SELECT * FROM campaigns WHERE id=1"))
    acc = {"session_name": "t_acc", "my_name": "Ирина", "status": "active",
           "paused_until": 0, "daily_limit": 20, "effective_limit": 15, "warmup_day": 7}
    return campaign, acc


def test_error_returns_target_to_queue():
    campaign, acc = _seed()

    async def boom(*a, **k):
        raise RuntimeError("сеть упала")

    original = worker._send_once_body
    worker._send_once_body = boom  # type: ignore[assignment]
    try:
        try:
            asyncio.run(worker._send_once(None, campaign, [acc], acc))
        except RuntimeError:
            pass
    finally:
        worker._send_once_body = original  # type: ignore[assignment]

    row = db.q1("SELECT state, reason FROM campaign_targets WHERE recipient_id=10")
    assert row["state"] == "pending", dict(row)
    assert row["reason"] == "returned_after_error", dict(row)
    n = db.q1("SELECT COUNT(*) n FROM events WHERE kind='target_returned'")
    assert n["n"] == 1, dict(n)


def test_target_not_lost_after_cancel():
    campaign, acc = _seed()

    async def cancelled(*a, **k):
        raise asyncio.CancelledError()

    original = worker._send_once_body
    worker._send_once_body = cancelled  # type: ignore[assignment]
    try:
        try:
            asyncio.run(worker._send_once(None, campaign, [acc], acc))
        except asyncio.CancelledError:
            pass
    finally:
        worker._send_once_body = original  # type: ignore[assignment]

    row = db.q1("SELECT state FROM campaign_targets WHERE recipient_id=10")
    assert row["state"] == "pending", dict(row)


class _Msg:
    def __init__(self, text: str, out: bool = True, age: int = 0):
        self.message = text
        self.out = out
        self.date = type("D", (), {"timestamp": lambda _self, a=age: time.time() - a})()  # noqa: ARG005


class _Client:
    def __init__(self, msgs):
        self._msgs = msgs

    async def get_messages(self, username, limit=5):
        return self._msgs[:limit]


def test_already_delivered_when_text_present():
    client = _Client([_Msg("Привет, это Ирина", out=True, age=60)])
    ok = asyncio.run(worker._already_delivered(client, "user_one", "Привет, это Ирина"))
    assert ok is True


def test_not_delivered_when_old_message():
    client = _Client([_Msg("Привет, это Ирина", out=True, age=3600)])
    ok = asyncio.run(worker._already_delivered(client, "user_one", "Привет, это Ирина"))
    assert ok is False, "старое сообщение не считается доставленным только что"


def test_not_delivered_when_incoming():
    client = _Client([_Msg("Привет, это Ирина", out=False, age=30)])
    ok = asyncio.run(worker._already_delivered(client, "user_one", "Привет, это Ирина"))
    assert ok is False, "входящее сообщение не наше"


def test_retry_does_not_duplicate_when_delivered():
    campaign, acc = _seed()
    calls = {"n": 0}

    class Client:
        async def get_messages(self, username, limit=5):
            return [_Msg("Привет, это Ирина", out=True, age=5)]

    async def failing(client):
        calls["n"] += 1
        raise asyncio.TimeoutError("timeout")

    async def fake_get(name):
        return Client()

    class FakePool:
        me_ids: dict = {}
        async def get(self, name):
            return await fake_get(name)
        async def reset(self, name):
            return None

    from sender import SendResult

    text = "Привет, это Ирина"

    async def verify(client):
        return await worker._already_delivered(client, "user_one", text)

    result = asyncio.run(worker.send_with_retry(FakePool(), "t_acc",
                                                {"username": "user_one"}, failing, verify=verify))
    assert isinstance(result, SendResult) and result.ok, result
    assert result.reason == "delivered_verified", result.reason
    assert calls["n"] == 1, "повторной отправки быть не должно"


def main() -> int:
    passed, failures = 0, []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"  ок  {name}")
            except AssertionError as exc:
                failures.append(f"{name}: {exc}")
                print(f"  ПРОВАЛ {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
                print(f"  ОШИБКА {name}: {type(exc).__name__}: {exc}")
    print(f"\nПройдено: {passed}, провалено: {len(failures)}")
    if failures:
        print("Провалы: " + "; ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
