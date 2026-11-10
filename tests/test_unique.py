"""Проверки уникализации под аккаунт и аналитики по вариантам/возражениям."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_unique_test.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db, message, unique  # noqa: E402

TPL = "👋 {Здравствуйте|Добрый день}, <ЕгоИмя>! Это <МоёИмя>, куратор школы. {Как дела|Как вы}?"
ACCOUNTS = [f"acct_a{i}" for i in range(1, 6)] + [f"pechkin{i:02d}" for i in range(1, 7)]


def test_variants_list_counts_all_combinations():
    variants = message.variants_list(TPL)
    assert len(variants) == 4, len(variants)
    assert len(set(variants)) == 4
    assert all("<ЕгоИмя>" in v for v in variants), "плейсхолдер должен остаться до персонализации"


def test_pools_do_not_overlap():
    variants = message.variants_list(TPL)
    seen: dict[str, str] = {}
    for acc in ACCOUNTS[:4]:
        for text in unique.pool_for(acc, variants, ACCOUNTS[:4]):
            assert text not in seen, f"{acc} пересекается с {seen[text]}"
            seen[text] = acc
    assert len(seen) == len(variants), "каждый вариант должен иметь владельца"


def test_same_account_never_repeats_text():
    db.init()
    picked: list[str] = []
    for i in range(4):
        text, idx = unique.pick("acct_a1", 77, TPL, ACCOUNTS[:4])
        assert text not in picked, f"повтор на шаге {i}: {text[:40]}"
        picked.append(text)
        db.mark_variant("acct_a1", 77, idx)


def test_different_accounts_start_from_different_texts():
    db.init()
    firsts = {}
    for acc in ACCOUNTS[:4]:
        text, idx = unique.pick(acc, 78, TPL, ACCOUNTS[:4])
        assert idx not in firsts.values(), f"{acc} взял вариант чужого аккаунта"
        firsts[acc] = idx
    assert len(set(firsts.values())) == len(firsts), firsts


def test_variant_is_written_to_sends_and_read_back():
    db.init()
    db.log_send(77, "user_one", "acct_a1", True, "", 0, variant=2)
    db.log_send(77, "user_two", "acct_a1", True, "", 0, variant=2)
    stats = {row["variant"]: row for row in db.variant_stats(77)}
    assert 2 in stats, stats
    assert stats[2]["sent"] == 2, stats[2]


def test_objection_stats_groups_by_meaning():
    db.init()
    db.event("objection", "acct_a1", "Далеко от меня, я в Питере")
    db.event("objection", "acct_a2", "Нет времени, позже")
    db.event("refusal", "acct_a3", "не интересно")
    rows = db.objection_stats(30)
    names = [r["reason"] for r in rows]
    assert "далеко" in names, names
    assert "нет времени" in names, names
    total = sum(r["count"] for r in rows)
    assert total >= 3, total
    assert abs(sum(r["share"] for r in rows) - 1.0) < 0.01


def test_dashboard_shows_new_tables():
    from panel import app  # noqa: F401

    src = (ROOT / "panel" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert "Какие тексты работают" in src
    assert "Почему отказываются" in src
    assert "variant_stats" in (ROOT / "panel" / "app.py").read_text(encoding="utf-8")


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
