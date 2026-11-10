"""Темп отправки и атомарный захват адресата.

Проверяем ровно то, из-за чего можно потерять аккаунт или послать дважды:
интервал не сокращается с прогревом до неприличия, и два потока не берут одного человека.
"""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
    # временную базу надо подставить ДО импорта panel.db: путь читается при импорте
    import os
    tmp = Path(tempfile.gettempdir()) / "pacing_test.db"
    if tmp.exists():
        tmp.unlink()
    os.environ["SENDERX_DB"] = str(tmp)

    from panel import pacing

    print("темп по дням прогрева")
    for day in (0, 1, 3, 5, 7, 30):
        delays = [pacing.interval(day, random.Random(seed)) for seed in range(300)]
        low, high = min(delays), max(delays)
        base_low = pacing.BASE.get(day, pacing.MATURE)[0]
        check(f"день {day}: минимум не ниже {base_low} с", low >= base_low, f"было {low}")
        check(f"день {day}: разброс есть", len(set(delays)) > 20, f"уникальных {len(set(delays))}")

    check("молодой аккаунт пишет реже зрелого",
          pacing.interval(0, random.Random(1)) > pacing.interval(30, random.Random(1)),
          "интервалы совпали")

    print("\nзахват адресата")
    tmp = Path(tempfile.gettempdir()) / "pacing_test.db"
    if tmp.exists():
        tmp.unlink()
    import os
    os.environ["SENDERX_DB"] = str(tmp)
    from panel import db
    db.init()
    db.upsert_recipients([("user1", "Иван", ""), ("user2", "Пётр", ""), ("user3", "Анна", "")])
    cid = db.create_campaign("тест", "привет", ["user1", "user2", "user3"])
    first = db.claim_target(cid, "pechkin01")
    second = db.claim_target(cid, "pechkin02")
    check("первый захват вернул адресата", first is not None)
    first_name = first["username"] if first else "—"
    second_name = second["username"] if second else "—"
    check("второй захват вернул другого", second is not None and second_name != first_name,
          f"{first_name} / {second_name}")
    check("третьего хватает третий поток", db.claim_target(cid, "pechkin03") is not None)
    check("четвёртый захват пуст", db.claim_target(cid, "pechkin04") is None)

    released = db.release_stale_targets(0)
    check("зависшие возвращаются в очередь", released == 3, f"вернулось {released}")
    check("после возврата адресат снова доступен", db.claim_target(cid, "pechkin05") is not None)

    print("\nинтервал держится на аккаунте")
    db.pacing_set("pechkin01", 0)
    check("свежий аккаунт готов", pacing.ready("pechkin01"))
    wait = pacing.after_send("pechkin01", 0)
    check("после отправки аккаунт не готов", not pacing.ready("pechkin01"), f"пауза {wait}")
    check("пауза не меньше нижней границы", wait >= pacing.BASE[0][0], f"{wait} с")
    check("время ожидания считается", pacing.wait_left("pechkin01") > 0)

    try:  # sqlite может ещё держать файл — это не ошибка теста
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    print(f"\nПройдено: {passed}, провалено: {len(failures)}")
    if failures:
        print("Провалы: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
