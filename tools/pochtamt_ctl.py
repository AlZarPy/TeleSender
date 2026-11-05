"""Управление «Почтамтом» из чата: короткие команды для агента и человека.

Зачем: панель хороша для глазами, но из Telegram удобнее текстом. Скрипт даёт
несколько безопасных операций, которые агент вызывает через терминал.

Примеры:
    python tools/pochtamt_ctl.py status
    python tools/pochtamt_ctl.py campaigns
    python tools/pochtamt_ctl.py start 3
    python tools/pochtamt_ctl.py pause 3
    python tools/pochtamt_ctl.py add 3 --tag клиенты --never
    python tools/pochtamt_ctl.py report
    python tools/pochtamt_ctl.py preview 3
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# те же переменные, что у панели и воркера
os.environ.setdefault("SENDERX_DB", str(Path(os.environ.get("SENDERX_DATA", ROOT)) / "panel.db"))
os.environ.setdefault("SENDERX_CONFIG", str(Path(os.environ.get("SENDERX_DATA", ROOT)) / "config.txt"))

from panel import db, health, message, report  # noqa: E402


def _accounts() -> list[dict]:
    from config_loader import ConfigError, load_config_from_txt

    try:
        return health.with_health(db.accounts_with_config(load_config_from_txt(None, quiet=True)))
    except ConfigError:
        return []


def cmd_status(_args) -> int:
    db.init()
    alive, state = db.worker_alive()
    funnel = db.global_funnel()
    print(f"воркер: {'работает' if alive else 'остановлен'}"
          + (f" · {state.get('detail')}" if alive and state.get("detail") else ""))
    print(f"доставлено всего: {funnel['sent']} · ответили: {funnel['replied']} "
          f"· конверсия {funnel['conversion']}% · в базе {funnel['base']}")
    print("")
    for acc in _accounts():
        h = acc["health"]
        print(f"{acc['session_name']}: {h['score']} {h['label']} · сегодня "
              f"{acc['sent_today']}/{acc['effective_limit']} · осталось {acc['left_today']}")
        for lvl, txt in h["reasons"]:
            if lvl != "ok":
                print(f"   {lvl}: {txt}")
    return 0


def cmd_campaigns(_args) -> int:
    db.init()
    rows = db.q("SELECT * FROM campaigns ORDER BY id DESC LIMIT 20")
    if not rows:
        print("кампаний нет")
        return 0
    for row in rows:
        f = db.campaign_funnel(row["id"])
        sched = f" · старт {row['scheduled_at']}" if row["scheduled_at"] else ""
        print(f"#{row['id']} «{row['name']}» — {row['status']}{sched}")
        print(f"   в маршруте {f['total']} · доставлено {f['sent']} · ответили {f['replied']} "
              f"· конверсия {f['conversion']}% · ошибок {f['failed']}")
    return 0


def _campaign(cid: int):
    row = db.q1("SELECT * FROM campaigns WHERE id=?", (cid,))
    if row is None:
        print(f"кампания #{cid} не найдена")
        raise SystemExit(2)
    return row


def cmd_start(args) -> int:
    db.init()
    row = _campaign(args.cid)
    if row["status"] == "running":
        print(f"«{row['name']}» уже идёт")
        return 0
    db.set_campaign_status(args.cid, "running")
    db.event("campaign_start", "", f"кампания «{row['name']}» запущена из чата")
    print(f"запущено: «{row['name']}» (#{args.cid})")
    return 0


def cmd_pause(args) -> int:
    db.init()
    row = _campaign(args.cid)
    db.set_campaign_status(args.cid, "paused")
    print(f"на паузе: «{row['name']}» (#{args.cid})")
    return 0


def cmd_stop(args) -> int:
    db.init()
    row = _campaign(args.cid)
    db.stop_campaign(args.cid, args.reason or "остановлено из чата")
    print(f"остановлено: «{row['name']}» (#{args.cid})")
    return 0


def cmd_add(args) -> int:
    db.init()
    row = _campaign(args.cid)
    if args.people:
        names = [n.strip().lstrip("@") for n in args.people.replace(",", " ").split() if n.strip()]
        db.upsert_recipients([(n, "", "") for n in names])
        added = db.add_targets(args.cid, names)
    else:
        added = db.add_segment(args.cid, tag=args.tag or "", never_written=args.never,
                               answered_only=args.answered)
    print(f"в «{row['name']}» добавлено: {added}")
    return 0


def cmd_report(_args) -> int:
    db.init()
    print(report.build(_accounts()))
    return 0


def cmd_preview(args) -> int:
    db.init()
    row = _campaign(args.cid)
    rows = db.q("""SELECT r.username, r.first_name FROM campaign_targets t
                   JOIN recipients r ON r.id=t.recipient_id
                   WHERE t.campaign_id=? ORDER BY t.recipient_id LIMIT ?""", (args.cid, args.count))
    if not rows:
        print("в кампании нет получателей")
        return 0
    for target in rows:
        text = message.render(row["template"], row["intro"] or "", "Александр",
                              target["first_name"] or "")
        print(f"--- @{target['username']} ---")
        print(text)
        print("")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Управление Почтамтом из чата")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("campaigns").set_defaults(func=cmd_campaigns)
    sub.add_parser("report").set_defaults(func=cmd_report)

    for name, func in (("start", cmd_start), ("pause", cmd_pause), ("stop", cmd_stop), ("preview", cmd_preview)):
        p = sub.add_parser(name)
        p.add_argument("cid", type=int)
        p.set_defaults(func=func)
        if name == "stop":
            p.add_argument("--reason", default="")
        if name == "preview":
            p.add_argument("--count", type=int, default=3)

    p = sub.add_parser("add")
    p.add_argument("cid", type=int)
    p.add_argument("--people", default="", help="никнеймы через запятую")
    p.add_argument("--tag", default="")
    p.add_argument("--never", action="store_true", help="только тем, кому не писали")
    p.add_argument("--answered", action="store_true", help="только ответившим")
    p.set_defaults(func=cmd_add)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
