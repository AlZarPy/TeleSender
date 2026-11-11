"""Opt-in: воркер берёт только тех, кто дал согласие."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_optin_test.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db  # noqa: E402


def _seed():
    db.init()
    db.execute("DELETE FROM campaign_targets")
    db.execute("DELETE FROM campaigns")
    db.execute("DELETE FROM recipients")
    db.execute("""INSERT INTO recipients(username, first_name, status, consent)
                  VALUES('agreed_user','Иван','active',1),
                        ('cold_user','Пётр','active',0)""", )
    db.execute("""INSERT INTO campaigns(name, template, status, requires_consent)
                  VALUES('C opt-in','текст','draft',1),
                        ('B обычная','текст','draft',0)""")
    cid_opt = db.q1("SELECT id FROM campaigns WHERE name='C opt-in'")["id"]
    cid_flat = db.q1("SELECT id FROM campaigns WHERE name='B обычная'")["id"]
    for r in db.q("SELECT id FROM recipients"):
        db.execute("INSERT INTO campaign_targets(campaign_id, recipient_id, state) VALUES(?,?,'pending')",
                   (cid_opt, r["id"]))
        db.execute("INSERT INTO campaign_targets(campaign_id, recipient_id, state) VALUES(?,?,'pending')",
                   (cid_flat, r["id"]))
    return cid_opt, cid_flat


def test_optin_campaign_skips_without_consent():
    cid_opt, _ = _seed()
    seen = set()
    for _ in range(5):
        t = db.next_target(cid_opt)
        if not t:
            break
        seen.add(t["username"])
        db.execute("UPDATE campaign_targets SET state='done' WHERE campaign_id=? AND recipient_id=?",
                   (cid_opt, t["recipient_id"]))
    assert seen == {"agreed_user"}, seen


def test_regular_campaign_takes_everyone():
    _, cid_flat = _seed()
    seen = set()
    for _ in range(5):
        t = db.next_target(cid_flat)
        if not t:
            break
        seen.add(t["username"])
        db.execute("UPDATE campaign_targets SET state='done' WHERE campaign_id=? AND recipient_id=?",
                   (cid_flat, t["recipient_id"]))
    assert seen == {"agreed_user", "cold_user"}, seen


def test_set_consent_and_stats():
    _seed()
    assert db.set_consent("cold_user", True) is True
    s = db.consent_stats()
    assert s["total"] == 2, s
    assert s["agreed"] == 2, s
    assert db.set_consent("нет_такого", True) is False


def test_consent_flag_survives_status_change():
    _seed()
    db.set_consent("cold_user", True)
    db.execute("UPDATE recipients SET status='blocked' WHERE username='cold_user'")
    cid_opt = db.q1("SELECT id FROM campaigns WHERE name='C opt-in'")["id"]
    t = db.next_target(cid_opt)
    assert t is None or t["username"] == "agreed_user", t


def test_template_from_docs_is_ready():
    from tools.make_optin import load_first_text

    text = load_first_text()
    assert "<МоёИмя>" in text or "{" in text, "текст должен быть из optin-text.md"
    assert "стоп" in text.lower(), "в тексте должна быть отписка"
    assert "{Алексей|Мария}" not in text, "имя не должно быть спинтаксисом"


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
    try:
        TMP_DB.unlink(missing_ok=True)
    except OSError:
        pass
    print(f"\nПройдено: {passed}, провалено: {len(failures)}")
    if failures:
        print("Провалы: " + "; ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
