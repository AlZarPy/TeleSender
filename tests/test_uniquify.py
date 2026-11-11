"""ИИ-уникализация: варианты под аккаунт и гейт перед волной."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_uniquify.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db, unique  # noqa: E402
from panel.worker import copy_gate  # noqa: E402

CLEAN = ("<ЕгоИмя>, здравствуйте! Это <МоёИмя>, куратор школы «Терра». "
         "13 ноября в 15:00 бесплатное открытие 41-го потока. Напишите «да» — пришлю детали.")


def _campaign(name: str, template: str = CLEAN) -> dict:
    db.init()
    db.execute("INSERT INTO campaigns(name, template, status) VALUES(?,?,'active')", (name, template))
    return dict(db.q1("SELECT * FROM campaigns WHERE name=?", (name,)))


def test_rewritten_text_wins_over_spintax():
    camp = _campaign("uniq-1")
    db.account_texts_put("acct_x1", camp["id"], 1, ["Переписанный вариант номер один"])
    text, variant = unique.pick("acct_x1", camp["id"], camp["template"], ["acct_x1"])
    assert text == "Переписанный вариант номер один", text
    assert variant >= 1000, variant


def test_two_accounts_get_different_texts():
    camp = _campaign("uniq-2")
    db.account_texts_put("acct_x1", camp["id"], 1, ["Текст для первого аккаунта"])
    db.account_texts_put("acct_x2", camp["id"], 1, ["Совсем другой текст для второго"])
    t1, _ = unique.pick("acct_x1", camp["id"], camp["template"], ["acct_x1", "acct_x2"])
    t2, _ = unique.pick("acct_x2", camp["id"], camp["template"], ["acct_x1", "acct_x2"])
    assert t1 != t2, (t1, t2)


def test_gate_blocks_campaign_without_rewrites():
    camp = _campaign("uniq-3")
    reason = copy_gate(camp)
    assert reason and "не уникализирован" in reason, reason
    row = db.q1("SELECT status FROM campaigns WHERE id=?", (camp["id"],))
    assert row["status"] == "stopped", dict(row)


def test_gate_allows_campaign_with_rewrites():
    camp = _campaign("uniq-4")
    db.account_texts_put("acct_x1", camp["id"], 1, ["Переписанный текст"])
    assert copy_gate(camp) is None


def test_override_flag_allows_plain_text():
    camp = _campaign("uniq-5")
    os.environ["SENDERX_ALLOW_PLAIN_TEXT"] = "1"
    try:
        assert copy_gate(camp) is None
    finally:
        os.environ.pop("SENDERX_ALLOW_PLAIN_TEXT", None)


def test_variants_are_counted_per_account():
    camp = _campaign("uniq-6")
    db.account_texts_put("acct_x1", camp["id"], 1, ["а", "б"])
    db.account_texts_put("acct_x2", camp["id"], 1, ["в", "г"])
    assert db.account_texts_count(camp["id"]) == 2, db.account_texts_count(camp["id"])


def test_rewrite_tool_checks_placeholders():
    from tools.rewrite_variants import valid

    ok, why = valid("Текст без плейсхолдеров", CLEAN)
    assert not ok and "ЕгоИмя" in why, (ok, why)

    good = ("<ЕгоИмя>, добрый день! Я <МоёИмя>, куратор школы «Терра». "
            "13 ноября в 15:00 бесплатное открытие 41-го потока.")
    ok2, why2 = valid(good, CLEAN)
    assert ok2, why2


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
