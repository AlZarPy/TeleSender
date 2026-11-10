"""Стадии диалога: переходы и запреты.

Проверяем то, из-за чего были жалобы: повтор анонса, объяснение понятого,
возврат в презентацию после того, как человек уже получил анонс.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "stages_test.db"
if TMP_DB.exists():
    TMP_DB.unlink()
os.environ["SENDERX_DB"] = str(TMP_DB)

passed = 0
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failures.append(name)
        print(f"  ✗ {name} {detail}")


def main() -> int:
    from panel import db, stages

    db.init()

    print("переходы")
    cases = [
        ("не пишите мне больше", "intro", False, "end"),
        ("я из Казани, далеко", "value", True, "objection"),
        ("во сколько и где проходит?", "value", True, "close"),
        ("не успеваем, всё вручную", "qualify", False, "needs"),
        ("у нас опт стройматериалов", "qualify", False, "value"),
        ("а что там по программе?", "intro", False, "qualify"),
        ("хорошо", "close", True, "close"),
        ("а есть онлайн?", "objection", False, "value"),
    ]
    for text, prev, announced, want in cases:
        got = stages.decide(text, prev, announced=announced)
        check(f"«{text}»: {prev} → {want}", got == want, f"получилось {got}")

    print("\nанонс не возвращает разговор назад")
    check("после анонса стадия solution", stages.decide("наш опт", "solution", announced=True) == "solution")
    check("«спасибо» после анонса не откатывает",
          stages.decide("спасибо", "solution", announced=True) == "solution")
    check("отказ всегда end", stages.decide("не надо", "close", announced=True) == "end")

    print("\nзапреты стадии попадают в промпт")
    intro = stages.block("intro")
    check("на intro запрещены ссылки", "ссылки" in intro, intro)
    solution = stages.block("solution")
    check("на solution запрещён повторный анонс", "повторный анонс" in solution, solution)
    close = stages.block("close")
    check("на close один шаг", "один следующий шаг" in close, close)

    print("\nсостояние диалога хранится и не откатывается")
    db.upsert_recipients([("client", "Клиент", "")])
    first = stages.update("client", "здравствуйте")
    check("первая реплика → qualify", first == "qualify", first)
    stages.mark("client", "solution")
    again = stages.update("client", "наш опт")
    check("«наш опт» не откатывает solution", again == "solution", again)
    check("стадия читается из базы", stages.current("client") == "solution")
    check("застой виден", stages.stalled("client", limit_minutes=-1) is True)

    try:
        TMP_DB.unlink(missing_ok=True)
    except OSError:
        pass

    print(f"\nПройдено: {passed}, провалено: {len(failures)}")
    if failures:
        print("Провалы: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
