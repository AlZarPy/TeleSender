"""Разделение аккаунтов по группам кампаний: A не пишет текст B."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_groups.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db  # noqa: E402


def _seed():
    db.init()
    for table in ("campaigns", "accounts", "campaign_targets", "recipients"):
        db.execute(f"DELETE FROM {table}")
    for name, grp, limit in (("acct_a1", "a", 20), ("acct_a2", "a", 20),
                             ("pechkin01", "b", 30), ("pechkin02", "b", 30)):
        db.execute("""INSERT INTO accounts(session_name, status, daily_limit, warmup_start, grp)
                      VALUES(?, 'active', ?, '2026-11-10', ?)""", (name, limit, grp))
    db.execute("INSERT INTO campaigns(name, template, status, account_group) VALUES('A','x','active','a')")
    db.execute("INSERT INTO campaigns(name, template, status, account_group) VALUES('B','y','active','b')")
    return (db.q1("SELECT id FROM campaigns WHERE name='A'")["id"],
            db.q1("SELECT id FROM campaigns WHERE name='B'")["id"])


def _accounts_for(campaign_id: int) -> list[str]:
    """Повторяет фильтр, который делает воркер перед run_batch."""
    camp = dict(db.q1("SELECT * FROM campaigns WHERE id=?", (campaign_id,)))
    all_accs = db.accounts_with_config([{"session_name": r["session_name"]}
                                        for r in db.q("SELECT session_name FROM accounts")])
    need = (camp.get("account_group") or "").lower()
    if not need:
        return [a["session_name"] for a in all_accs]
    return [a["session_name"] for a in all_accs
            if (db.account_group(a["session_name"]) or "").lower() == need]


def test_campaign_a_uses_only_group_a():
    cid_a, _ = _seed()
    assert _accounts_for(cid_a) == ["acct_a1", "acct_a2"], _accounts_for(cid_a)


def test_campaign_b_uses_only_group_b():
    _, cid_b = _seed()
    assert _accounts_for(cid_b) == ["pechkin01", "pechkin02"], _accounts_for(cid_b)


def test_no_group_means_all_accounts():
    cid_a, _ = _seed()
    db.execute("UPDATE campaigns SET account_group='' WHERE id=?", (cid_a,))
    assert len(_accounts_for(cid_a)) == 4, _accounts_for(cid_a)


def test_paused_account_is_not_picked():
    """Пауза отсекается не фильтром групп, а pick_account — проверяем именно его."""
    from panel.worker import pick_account

    paused = {"session_name": "acct_a1", "status": "paused", "paused_until": 0,
              "daily_limit": 20, "effective_limit": 15}
    active = dict(paused, status="active")
    assert pick_account([paused]) is None
    assert pick_account([active]) is not None


def test_worker_filters_before_batch():
    src = (ROOT / "panel" / "worker.py").read_text(encoding="utf-8")
    assert "account_group" in src, "воркер должен учитывать группу кампании"
    assert "нужна группа" in src or "need_group" in src


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
