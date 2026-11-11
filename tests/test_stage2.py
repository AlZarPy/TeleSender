"""Второе сообщение: переписанный вариант на аккаунт, иначе шаблон."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_stage2.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db, followup  # noqa: E402


def _camp() -> int:
    db.init()
    db.execute("DELETE FROM campaigns")
    db.execute("""INSERT INTO campaigns(id, name, template, status)
                  VALUES(55, 'stage2', 'шаблон второго сообщения', 'draft')""")
    return 55


def test_rewritten_stage2_used_first():
    cid = _camp()
    db.execute("DELETE FROM account_texts")
    db.account_texts_put("acc_s", cid, 2, ["Переписанный текст для этого аккаунта"])
    text = followup.stage2_text("acc_s", cid)
    assert text == "Переписанный текст для этого аккаунта", text


def test_second_call_falls_back_when_variant_used():
    cid = _camp()
    db.execute("DELETE FROM account_texts")
    db.execute("DELETE FROM used_variants")
    db.account_texts_put("acc_s2", cid, 2, ["Единственный переписанный вариант"])
    first = followup.stage2_text("acc_s2", cid)
    second = followup.stage2_text("acc_s2", cid)
    assert first == "Единственный переписанный вариант", first
    assert second != first, "повторно тот же вариант уходить не должен"
    assert "13 ноября" in second or "Группа школы" in second or "t.me" in second, second


def test_without_rewrites_uses_template():
    cid = _camp()
    db.execute("DELETE FROM account_texts")
    text = followup.stage2_text("acc_no_rewrites", cid)
    assert "13 ноября" in text, text


def test_variant_marked_used():
    cid = _camp()
    db.execute("DELETE FROM account_texts")
    db.execute("DELETE FROM used_variants")
    db.account_texts_put("acc_s3", cid, 2, ["Текст номер один"])
    followup.stage2_text("acc_s3", cid)
    rows = db.account_texts_get("acc_s3", cid, 2)
    taken = [db.variant_taken("acc_s3", cid, int(r["variant"])) for r in rows]
    assert any(taken), "вариант должен быть помечен использованным"


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
