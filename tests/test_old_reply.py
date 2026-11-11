"""Ответ считается только если он новее нашего последнего сообщения."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_oldreply.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db  # noqa: E402


def _send(account: str, recipient: str, ts: str) -> None:
    db.execute("""INSERT INTO sends(campaign_id, recipient, account, ok, reason, ts, text)
                  VALUES(0,?,?,1,'test',?, 'текст')""", (recipient, account, ts))


def test_last_send_returns_zero_without_history():
    db.init()
    db.execute("DELETE FROM sends")
    assert db.last_send_at("acc", "user") == 0.0


def test_last_send_returns_latest():
    db.init()
    db.execute("DELETE FROM sends")
    _send("acc1", "user1", "2026-11-11 17:35:00")
    _send("acc1", "user1", "2026-11-11 18:10:00")
    ts = db.last_send_at("acc1", "user1")
    assert ts > 0
    from datetime import datetime

    assert datetime.fromtimestamp(ts).strftime("%H:%M") == "18:10", ts


def test_last_send_is_per_account():
    db.init()
    db.execute("DELETE FROM sends")
    _send("acc1", "user1", "2026-11-11 10:00:00")
    assert db.last_send_at("acc2", "user1") == 0.0, "у другого аккаунта истории нет"


def test_last_send_ignores_failed():
    db.init()
    db.execute("DELETE FROM sends")
    db.execute("""INSERT INTO sends(campaign_id, recipient, account, ok, reason, ts, text)
                  VALUES(0,'user1','acc1',0,'flood','2026-11-11 12:00:00','x')""")
    assert db.last_send_at("acc1", "user1") == 0.0


def test_guard_is_in_followup():
    src = (ROOT / "panel" / "followup.py").read_text(encoding="utf-8")
    assert "last_send_at" in src, "автоответчик должен сверять время"
    assert '"_mark(account, msg.id, \\"old\\")"' in src or '_mark(account, msg.id, "old")' in src


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
