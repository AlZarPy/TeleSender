"""Новые вопросы без ответа — для уведомления владельцу.

Печатает только то, чего он ещё не видел, и сразу помечает увиденным.
Пустой вывод = новых вопросов нет (в cron это значит «молчим»).

    python tools/unanswered_report.py            # показать новые
    python tools/unanswered_report.py --peek     # показать без пометки
    python tools/unanswered_report.py --all      # за 7 дней, включая просмотренные
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--peek", action="store_true", help="не отмечать просмотренным")
    ap.add_argument("--all", action="store_true", help="включая просмотренные за 7 дней")
    args = ap.parse_args()

    db.init()

    if args.all:
        rows = [dict(r) for r in db.q(
            """SELECT * FROM unanswered WHERE ts >= datetime('now','localtime','-7 days')
               ORDER BY id""")]
    else:
        rows = db.unanswered_pending()

    if not rows:
        return 0

    lines = [f"❓ Вопросы без ответа: {len(rows)}"]
    for r in rows:
        who = f"@{r['username']}" if r["username"] else r["account"] or "—"
        lines.append(f"• {who} ({r['ts'][5:16]}): {r['question'][:160]}")
    print("\n".join(lines))

    if not args.all and not args.peek:
        db.unanswered_mark([int(r["id"]) for r in rows])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
