"""Безопасность панели и чистота очереди."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_panel_sec.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)
os.environ.setdefault("PANEL_SECRET", "test-secret-for-tests")
os.environ.setdefault("PANEL_PASSWORD", "test-password")

from panel import app as panel_app, db  # noqa: E402


def test_session_cookie_roundtrip():
    db.init()
    cookie = panel_app.new_session()
    assert panel_app.cookie_valid(cookie) is True, cookie


def test_session_revoked_after_logout():
    db.init()
    cookie = panel_app.new_session()
    db.drop_sessions()
    assert panel_app.cookie_valid(cookie) is False, "после выхода кука должна умереть"


def test_tampered_cookie_rejected():
    db.init()
    cookie = panel_app.new_session()
    broken = cookie[:-3] + "abc"
    assert panel_app.cookie_valid(broken) is False


def test_expired_session_rejected():
    db.init()
    sid = "expired123"
    db.set_session(sid, int(time.time()) - 10)
    assert db.session_alive(sid) is False


def test_login_rate_limit():
    panel_app.LOGIN_FAILS.clear()
    ip = "10.0.0.1"
    for _ in range(panel_app.LOGIN_LIMIT):
        assert panel_app.login_allowed(ip) is True
        panel_app.login_note_fail(ip)
    assert panel_app.login_allowed(ip) is False, "после лимита вход должен блокироваться"
    panel_app.LOGIN_FAILS.clear()


def test_other_ip_not_blocked():
    panel_app.LOGIN_FAILS.clear()
    for _ in range(panel_app.LOGIN_LIMIT):
        panel_app.login_note_fail("10.0.0.2")
    assert panel_app.login_allowed("10.0.0.3") is True


def test_queue_skips_already_messaged():
    db.init()
    db.execute("DELETE FROM sends")
    db.execute("DELETE FROM campaign_targets")
    db.execute("DELETE FROM recipients")
    db.execute("DELETE FROM campaigns")
    db.upsert_recipients([("fresh_user", "", ""), ("old_user", "", "")])
    db.execute("""INSERT INTO sends(campaign_id, recipient, account, ok)
                  VALUES(1,'old_user','acc',1)""")
    db.execute("""INSERT INTO campaigns(id, name, template, status, allow_repeat)
                  VALUES(7,'t','x','draft',0)""")
    added = db.add_targets(7, exclude_sent=True)
    assert added == 1, f"добавлено {added}, ожидался только новый"


def test_queue_includes_everyone_when_repeat_allowed():
    db.init()
    db.execute("DELETE FROM campaign_targets")
    db.execute("DELETE FROM recipients")
    db.upsert_recipients([("a1", "", ""), ("a2", "", "")])
    db.execute("""INSERT INTO sends(campaign_id, recipient, account, ok)
                  VALUES(1,'a1','acc',1)""")
    db.execute("""INSERT INTO campaigns(id, name, template, status, allow_repeat)
                  VALUES(8,'t','x','draft',1)""")
    added = db.add_targets(8, exclude_sent=False)
    assert added == 2, f"добавлено {added}, ожидалось 2"


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
