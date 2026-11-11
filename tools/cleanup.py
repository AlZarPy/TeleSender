"""Политика хранения: что удаляем, что оставляем.

Принцип: доказательства отправок храним долго, персональные данные — минимально.
Удаление только по явной команде; без --apply ничего не меняется.

    python tools/cleanup.py                 # посмотреть, что попадёт под очистку
    python tools/cleanup.py --apply         # выполнить
    python tools/cleanup.py --apply --dialogs-days 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import db  # noqa: E402

KEEP = {
    "sends": 0,          # 0 = не удалять: это доказательства отправок
    "events": 180,       # события старше полугода не нужны для работы
    "followup_seen": 90,  # техническая память автоответчика
    "recipients_reply": 60,  # тексты чужих реплик — персональные данные
}


def counts() -> dict:
    db.init()
    return {
        "sends": db.q1("SELECT COUNT(*) n FROM sends")["n"],
        "events": db.q1("SELECT COUNT(*) n FROM events")["n"],
        "followup_seen": db.q1("SELECT COUNT(*) n FROM followup_seen")["n"],
        "recipients_with_reply": db.q1(
            "SELECT COUNT(*) n FROM recipients WHERE last_reply<>''")["n"],
    }


def plan(dialogs_days: int) -> list[tuple[str, str, int]]:
    db.init()
    steps = []
    n = db.q1("""SELECT COUNT(*) n FROM events
                 WHERE ts < datetime('now','localtime', ?)""", (f"-{KEEP['events']} days",))["n"]
    steps.append(("events", f"старше {KEEP['events']} дней", n))

    n = db.q1("""SELECT COUNT(*) n FROM followup_seen
                 WHERE ts < datetime('now','localtime', ?)""",
              (f"-{KEEP['followup_seen']} days",))["n"] if _has_ts("followup_seen") else 0
    steps.append(("followup_seen", f"старше {KEEP['followup_seen']} дней", n))

    n = db.q1("""SELECT COUNT(*) n FROM recipients
                 WHERE last_reply<>'' AND last_reply_at < datetime('now','localtime', ?)""",
              (f"-{dialogs_days} days",))["n"] if _has_col("recipients", "last_reply_at") else 0
    steps.append(("recipients.last_reply", f"старше {dialogs_days} дней", n))
    return steps


def _has_col(table: str, col: str) -> bool:
    return col in [r["name"] for r in db.q(f"PRAGMA table_info({table})")]


def _has_ts(table: str) -> bool:
    return _has_col(table, "ts")


def apply(dialogs_days: int) -> None:
    db.init()
    db.execute("DELETE FROM events WHERE ts < datetime('now','localtime', ?)",
               (f"-{KEEP['events']} days",))
    if _has_ts("followup_seen"):
        db.execute("DELETE FROM followup_seen WHERE ts < datetime('now','localtime', ?)",
                   (f"-{KEEP['followup_seen']} days",))
    if _has_col("recipients", "last_reply_at"):
        db.execute("""UPDATE recipients SET last_reply='', last_reply_at=''
                      WHERE last_reply<>'' AND last_reply_at < datetime('now','localtime', ?)""",
                   (f"-{dialogs_days} days",))
    db.execute("VACUUM")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dialogs-days", type=int, default=KEEP["recipients_reply"])
    args = ap.parse_args()

    before = counts()
    print("сейчас:", before)
    print("\nплан:")
    for table, rule, n in plan(args.dialogs_days):
        print(f"  {table:22s} {rule:24s} под удаление: {n}")

    if not args.apply:
        print("\nэто предпросмотр. для выполнения: --apply")
        return 0

    apply(args.dialogs_days)
    print("\nпосле:", counts())
    print("подтверждения отправок (sends) не тронуты")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
