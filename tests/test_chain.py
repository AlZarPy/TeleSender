"""Регрессия автоответчика: цепочка А → ответ → Б не должна молча ломаться."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_chain.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db, followup  # noqa: E402


def test_announced_before_respects_last_touch():
    db.init()
    db.execute("DELETE FROM events")
    db.execute("""INSERT INTO events(kind, account, detail, ts)
                  VALUES('followup','acc','announce → @user1','2026-11-11 17:00:00')""")
    # старый анонс не должен блокировать новое касание
    since = 1794408000.0   # позже 17:00
    assert followup.announced_before("user1", since=since) is False
    # а вот тот же анонс, если он был позже касания — блокирует
    assert followup.announced_before("user1", since=0) is True


def test_announced_before_scoped_to_user():
    db.init()
    db.execute("DELETE FROM events")
    db.execute("""INSERT INTO events(kind, account, detail, ts)
                  VALUES('followup','acc','announce → @other','2026-11-11 17:00:00')""")
    assert followup.announced_before("user1", since=0) is False, "чужой анонс не считается"


def test_guard_uses_username_before_last_send():
    """Статическая проверка: обращение к username не должно идти раньше присваивания."""
    src = (ROOT / "panel" / "followup.py").read_text(encoding="utf-8")
    assign = src.index('username = (sender.username')
    guard = src.index("last_out = db.last_send_at(account, username)")
    assert assign < guard, "проверка стоит до вычисления username — будет UnboundLocalError"


def test_last_send_at_used_in_scan():
    src = (ROOT / "panel" / "followup.py").read_text(encoding="utf-8")
    assert "msg_ts <= last_out" in src, "старые входящие должны отбрасываться"


def test_delay_cap_is_twenty_seconds():
    src = (ROOT / "panel" / "followup.py").read_text(encoding="utf-8")
    assert 'SENDERX_REPLY_DELAY_MAX", "20"' in src, "потолок паузы должен быть 20 секунд"


def test_quick_scan_is_twenty_five_seconds():
    src = (ROOT / "panel" / "worker.py").read_text(encoding="utf-8")
    assert 'SENDERX_FOLLOWUP_SCAN", "25"' in src, "быстрый опрос — 25 секунд"


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
