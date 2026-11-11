"""База фактов: загрузка карточек и проверка ответа по ним."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_facts_test.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db, facts  # noqa: E402


def test_seed_fills_cards():
    n = facts.seed()
    assert n >= 15, n
    assert db.q1("SELECT COUNT(*) n FROM facts")["n"] == n


def test_search_finds_by_question():
    facts.seed()
    assert db.fact_search("во сколько начало")[0]["id"] == "event_when"
    assert db.fact_search("сколько стоит участие")[0]["id"] == "event_price"
    assert db.fact_search("далеко ехать")[0]["id"] == "obj_far"


def test_search_falls_back_on_typos():
    facts.seed()
    rows = db.fact_search("скока стоит")
    assert rows, "поиск должен находить по частичному совпадению"


def test_context_block_has_facts_only():
    facts.seed()
    block = facts.context_for("где проходит", limit=3)
    assert "Краснопресненская" in block
    assert sum(1 for line in block.splitlines() if line.startswith("— ")) <= 3


def test_correct_numbers_pass():
    facts.seed()
    assert facts.check_numbers("13 ноября в 15:00, Краснопресненская наб., 12") == []


def test_wrong_time_caught():
    facts.seed()
    codes = [i["code"] for i in facts.check_numbers("начало в 16:00")]
    assert "fact_time" in codes


def test_wrong_date_caught():
    facts.seed()
    codes = [i["code"] for i in facts.check_numbers("14 ноября ждём вас")]
    assert "fact_date" in codes


def test_no_masterclasses_in_base():
    """Мастер-классы, школы и наставники сознательно не включены."""
    facts.seed()
    titles = " ".join(r["title"] for r in db.q("SELECT title FROM facts")).lower()
    # расписания мастер-классов и списка наставников в базе нет — только формат курса
    assert "мастер-класс" not in titles
    assert "расписание" not in titles


def test_salesperson_prompt_includes_facts(monkeypatch=None):
    src = (ROOT / "panel" / "salesperson.py").read_text(encoding="utf-8")
    assert "facts.context_for" in src, "продавец должен подтягивать карточки"
    assert "чего нет в фактах" in src


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
