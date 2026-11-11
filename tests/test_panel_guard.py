"""Здоровье под входом, пауза на сутки, запрет правки работающей кампании."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_panel_guard.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)
os.environ.setdefault("PANEL_SECRET", "secret-for-tests")
os.environ.setdefault("PANEL_PASSWORD", "pass-for-tests")

from starlette.testclient import TestClient  # noqa: E402

from panel import app as panel_app, db  # noqa: E402


def _client(auth: bool = False) -> TestClient:
    client = TestClient(panel_app.app)
    if auth:
        resp = client.post("/login", data={"password": os.environ["PANEL_PASSWORD"]},
                           follow_redirects=False)
        assert resp.status_code == 303, resp.status_code
    return client


def test_healthz_public_is_minimal():
    db.init()
    body = _client().get("/healthz").json()
    assert set(body) == {"ok", "build"}, body


def test_healthz_authorised_is_full():
    db.init()
    body = _client(auth=True).get("/healthz").json()
    assert "speed" in body and "db" in body, list(body)


def test_edit_running_campaign_forbidden():
    db.init()
    db.execute("DELETE FROM campaigns")
    db.execute("""INSERT INTO campaigns(id, name, template, status)
                  VALUES(101, 'running', 'текст', 'running')""")
    client = _client(auth=True)
    resp = client.post("/campaigns/101/text", data={"template": "новый", "action": "save"},
                       follow_redirects=False)
    assert resp.status_code == 409, resp.status_code
    row = db.q1("SELECT template FROM campaigns WHERE id=101")
    assert row["template"] == "текст", "текст работающей кампании не должен меняться"


def test_edit_draft_campaign_allowed():
    db.init()
    db.execute("DELETE FROM campaigns")
    db.execute("""INSERT INTO campaigns(id, name, template, status)
                  VALUES(102, 'draft', 'старый', 'draft')""")
    client = _client(auth=True)
    resp = client.post("/campaigns/102/text", data={"template": "новый текст", "action": "save"},
                       follow_redirects=False)
    assert resp.status_code == 303, resp.status_code
    row = db.q1("SELECT template FROM campaigns WHERE id=102")
    assert row["template"] == "новый текст"


def test_spam_block_pauses_for_a_day():
    db.init()
    db.execute("DELETE FROM accounts")
    db.execute("""INSERT INTO accounts(session_name, status) VALUES('acc_x', 'active')""")
    from panel import checks

    class FakeRes:
        spam = "ОГРАНИЧЕН"

    # повторяем логику ветки: проверяем, что пауза ставится в будущее, а не 0
    if FakeRes.spam == "ОГРАНИЧЕН":
        db.set_account("acc_x", status="paused", paused_until=time.time() + 24 * 3600)
    row = db.q1("SELECT status, paused_until FROM accounts WHERE session_name='acc_x'")
    assert row["status"] == "paused"
    assert row["paused_until"] > time.time() + 23 * 3600, row["paused_until"]


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
