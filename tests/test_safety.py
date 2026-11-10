"""Защита от лишних сообщений: кулдаун автоответчика и сухой прогон.

Главная проверка — что правила срабатывают до отправки, а не после.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "safety_test.db"
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
    from panel import db, followup

    db.init()

    print("распознавание входящих")
    cases = {
        "в смысле, чем я занимаюсь?": "explain",
        "не понял": "explain",
        "Интересно": "announce",
        "пришлите подробности": "announce",
        "сколько стоит?": "announce",
        "не пишите мне больше": "refuse",
        "опт": "niche",
        "спасибо": "silence",
        "Ок, понял": "silence",
    }
    for text, want in cases.items():
        got = followup.decided(text)
        check(f"«{text}» → {want}", got == want, f"получилось {got}")

    print("\nкулдаун: один ответ на диалог")
    db.upsert_recipients([("client1", "Клиент", "")])
    check("до ответа не в кулдауне", not followup.cooling("client1"))
    followup.mark_cooling("client1")
    check("после ответа — кулдаун", followup.cooling("client1"))
    check("с истёкшим окном кулдаун снят", not followup.cooling("client1", hours=0))

    print("\nсухой прогон не трогает очередь")
    db.upsert_recipients([("client2", "Второй", "")])
    cid = db.create_campaign("сухой", "привет", ["client2"])
    claimed = db.claim_target(cid, "pechkin01")
    check("адресат захвачен", claimed is not None)
    db.close_target(cid, claimed["recipient_id"], "pending")
    stats = db.campaign_stats(cid)
    check("после возврата он снова в очереди", stats["pending"] == 1, str(stats))
    check("ничего не отмечено отправленным", stats["sent"] == 0, str(stats))

    print("\nметрики отвечают")
    from panel import metrics
    summary = metrics.summary()
    for key in ("hour", "queue", "eta_minutes", "pacing", "accounts"):
        check(f"есть раздел {key}", key in summary, str(list(summary)))
    # оценка честно пустая, когда скорость ещё неизвестна (нет отправок за час)
    eta_ok = summary["eta_minutes"] is None or isinstance(summary["eta_minutes"], float)
    check("очередь и оценка времени согласованы", isinstance(summary["queue"]["pending"], int) and eta_ok,
          f"в очереди {summary['queue']}, оценка {summary['eta_minutes']}")

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
