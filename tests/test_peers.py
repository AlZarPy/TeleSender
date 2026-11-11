"""Кэш собеседников: не искать юзернейм заново на каждую отправку."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_peers.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)


class FakeUser:
    def __init__(self, uid: int, access_hash: int):
        self.id = uid
        self.access_hash = access_hash
        self.first_name = "Тест"


def test_remember_and_lookup():
    from panel import db, peers

    db.init()
    db.execute("DELETE FROM peers")
    peers.remember("acc1", "@Target_User", FakeUser(555, 777))
    found = peers.peer("acc1", "target_user")
    assert found is not None, "после запоминания должен находиться"
    assert found.user_id == 555 and found.access_hash == 777, found


def test_unknown_returns_none():
    from panel import db, peers

    db.init()
    db.execute("DELETE FROM peers")
    assert peers.peer("acc1", "nobody") is None


def test_cache_is_per_account():
    from panel import db, peers

    db.init()
    db.execute("DELETE FROM peers")
    peers.remember("acc1", "shared_user", FakeUser(10, 100))
    assert peers.peer("acc1", "shared_user") is not None
    assert peers.peer("acc2", "shared_user") is None, "access_hash у каждого аккаунта свой"


def test_describe_counts_accounts():
    from panel import db, peers

    db.init()
    db.execute("DELETE FROM peers")
    peers.remember("acc1", "popular", FakeUser(1, 11))
    peers.remember("acc2", "popular", FakeUser(1, 22))
    assert peers.describe("popular")["known_by"] == 2, peers.describe("popular")


def test_sender_uses_cache_first():
    src = (ROOT / "sender.py").read_text(encoding="utf-8")
    assert "peers.peer(" in src and "peers.remember(" in src, "sender должен смотреть в кэш"


def test_campaign_send_uses_cache():
    src = (ROOT / "tools" / "send_test_to_self.py").read_text(encoding="utf-8")
    assert "peers.peer(" in src, "тестовая отправка тоже должна использовать кэш"
    assert "resolve_flood" in src, "флуд на поиске не должен исключать аккаунт"


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
