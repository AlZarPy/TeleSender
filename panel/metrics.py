"""Цифры о работе рассылки: скорость, ошибки, сколько ждать до конца очереди.

Без этого «быстро и точно» — вопрос веры. Считаем по таблице sends и по pacing.
"""
from __future__ import annotations

import time

from . import db, pacing


def window(minutes: int = 60) -> dict:
    row = db.q1("""SELECT COUNT(*) total,
                          SUM(ok) ok,
                          SUM(1 - ok) failed
                   FROM sends WHERE ts >= datetime('now','localtime', ?)""",
                (f"-{minutes} minutes",))
    total = int(row["total"] or 0) if row else 0
    ok = int(row["ok"] or 0) if row else 0
    failed = int(row["failed"] or 0) if row else 0
    return {
        "minutes": minutes,
        "total": total,
        "ok": ok,
        "failed": failed,
        "per_minute": round(total / minutes, 2) if minutes else 0.0,
        "error_share": round(failed / total, 3) if total else 0.0,
    }


def by_account(minutes: int = 60) -> list[dict]:
    rows = db.q("""SELECT account,
                          COUNT(*) total,
                          SUM(ok) ok,
                          SUM(1 - ok) failed,
                          MAX(ts) last_at
                   FROM sends WHERE ts >= datetime('now','localtime', ?)
                   GROUP BY account ORDER BY total DESC""",
                (f"-{minutes} minutes",))
    return [{"account": r["account"], "total": int(r["total"] or 0),
             "ok": int(r["ok"] or 0), "failed": int(r["failed"] or 0),
             "last_at": r["last_at"]} for r in rows]


def queue() -> dict:
    pending = db.q1("SELECT COUNT(*) c FROM campaign_targets WHERE state='pending'")
    sending = db.q1("SELECT COUNT(*) c FROM campaign_targets WHERE state='sending'")
    return {"pending": int(pending["c"] if pending else 0),
            "sending": int(sending["c"] if sending else 0)}


def pacing_state(accounts: list[str] | None = None) -> dict:
    now = time.time()
    names = accounts or [r["session_name"] for r in db.q("SELECT session_name FROM accounts")]
    waiting = []
    for name in names:
        left = int(db.pacing_next_at(name) - now)
        if left > 0:
            waiting.append({"account": name, "wait_sec": left})
    waiting.sort(key=lambda item: item["wait_sec"])
    return {"waiting": len(waiting), "next_in": waiting[0]["wait_sec"] if waiting else 0,
            "detail": waiting[:5]}


def eta_minutes(per_minute: float | None = None) -> float | None:
    rate = per_minute if per_minute is not None else window(60)["per_minute"]
    left = queue()["pending"]
    if not left:
        return 0.0
    if not rate:
        return None
    return round(left / rate, 1)


def summary() -> dict:
    hour = window(60)
    return {
        "hour": hour,
        "queue": queue(),
        "eta_minutes": eta_minutes(hour["per_minute"]),
        "pacing": pacing_state(),
        "accounts": by_account(60),
    }


def next_allowed(account: str) -> int:
    return pacing.wait_left(account)
