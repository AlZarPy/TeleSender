"""Правила прогрева: у каждого аккаунта свой набор каналов, темп растянут."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_warmup_sets.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import warmup  # noqa: E402

CHANNELS = [f"chan{i}" for i in range(1, 21)]


def test_each_account_gets_own_subset():
    a = set(warmup.channels_for("pechkin01", CHANNELS))
    b = set(warmup.channels_for("pechkin02", CHANNELS))
    assert a != b, "наборы не должны совпадать"


def test_subset_is_stable_for_account():
    assert warmup.channels_for("acct_a1", CHANNELS) == warmup.channels_for("acct_a1", CHANNELS)


def test_overlap_not_total():
    a = set(warmup.channels_for("pechkin03", CHANNELS))
    b = set(warmup.channels_for("acct_c2", CHANNELS))
    union = a | b
    share = len(a & b) / len(union)
    assert share < 1.0, "полное совпадение списков — прямой признак фермы"


def test_subset_size_about_60_percent():
    own = warmup.channels_for("pechkin05", CHANNELS)
    assert 0.4 * len(CHANNELS) <= len(own) <= 0.8 * len(CHANNELS), len(own)


def test_empty_list_is_safe():
    assert warmup.channels_for("x", []) == []


def test_next_channel_prefers_own_set():
    from panel import db
    db.init()                       # нужна таблица warmup_actions
    own = set(warmup.channels_for("pechkin07", CHANNELS))
    picked = {warmup.next_channel("pechkin07", CHANNELS) for _ in range(20)}
    assert picked <= own | {None}, picked - own


def test_warmup_rule_in_skill():
    skill = Path.home() / "AppData/Local/hermes/skills/software-development/telegram-pool-ops/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "у каждого аккаунта свой набор" in text.lower()
    assert "channels_for" in text


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
