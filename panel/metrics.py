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


# Нормы, по которым судят о работе рассылки: (метрика, границы, что значит)
NORMS = {
    "delivery": (0.95, "доставка"),
    "read": (0.40, "прочтение"),
    "reply": (0.08, "ответ"),
    "complaints": (0.01, "жалобы", True),   # True = чем меньше, тем лучше
    "survival": (0.80, "выживание пула"),
}


def quality(days: int = 7) -> list[dict]:
    """Пять цифр рядом с нормой: доставка, прочтение, ответ, жалобы, выживание."""
    sent_row = db.q1("""SELECT COUNT(*) total, SUM(ok) ok FROM sends
                        WHERE ts >= datetime('now','localtime', ?)""",
                     (f"-{days} days",))
    total = int(sent_row["total"] or 0) if sent_row else 0
    ok = int(sent_row["ok"] or 0) if sent_row else 0

    # COALESCE: если колонка NULL, сравнение read_at<>'' даёт NULL и прочтения исчезают
    read_row = db.q1("""SELECT COUNT(*) c FROM sends
                        WHERE ts >= datetime('now','localtime', ?)
                          AND COALESCE(read_at,'')<>''""",
                     (f"-{days} days",))
    read = int(read_row["c"] if read_row else 0)

    # считаем людей, а не строки: один человек не должен давать N «ответов»
    replied_row = db.q1("""SELECT COUNT(DISTINCT LOWER(s.recipient)) c
                           FROM sends s JOIN recipients r
                             ON LOWER(r.username)=LOWER(s.recipient)
                           WHERE s.ts >= datetime('now','localtime', ?) AND r.replied=1""",
                        (f"-{days} days",))
    replied = int(replied_row["c"] if replied_row else 0)

    # жалобы — это события за период: отписки по просьбе и спам-блоки аккаунтов.
    # Раньше считались все заблокированные за всё время и делились на отправки —
    # цифра врала в обе стороны.
    blocked_row = db.q1("""SELECT COUNT(*) c FROM events
                           WHERE kind IN ('recipient_blocked','spam_block')
                             AND ts >= datetime('now','localtime', ?)""",
                        (f"-{days} days",))
    blocked = int(blocked_row["c"] if blocked_row else 0)

    people_row = db.q1("""SELECT COUNT(DISTINCT LOWER(recipient)) c FROM sends
                          WHERE ts >= datetime('now','localtime', ?)""",
                       (f"-{days} days",))
    people = int(people_row["c"] if people_row else 0)

    # «Выживание» — доля рабочих аккаунтов, которые за 30 дней не ушли в ограничение.
    # Просто active/total не годится: в базе лежат старые BR/US-аккаунты, снятые с работы
    # руками, и они портят цифру, не будучи потерянными.
    acc_row = db.q1("SELECT COUNT(*) total FROM accounts WHERE status='active'")
    acc_total = int(acc_row["total"] or 0) if acc_row else 0
    lost_row = db.q1("""SELECT COUNT(DISTINCT account) c FROM events
                        WHERE kind='spam_block' AND ts >= datetime('now','localtime','-30 days')""")
    lost = int(lost_row["c"] if lost_row else 0)
    acc_active = max(0, acc_total - lost)

    def share(a: int, b: int) -> float:
        return round(a / b, 3) if b else 0.0

    values = {
        "delivery": share(ok, total),
        "read": share(read, total),
        "reply": share(replied, max(people, 1)),
        "complaints": share(blocked, max(people, 1)),
        "survival": share(acc_active, acc_total),
    }

    out = []
    for key, spec in NORMS.items():
        norm = spec[0]
        label = spec[1]
        inverse = len(spec) > 2 and spec[2]
        value = values[key]
        if key in ("delivery", "read", "reply", "complaints") and total < 20:
            level = "pending"      # мало данных — вывод делать нельзя
        elif inverse:
            level = "ok" if value <= norm else "bad"
        else:
            level = "ok" if value >= norm else ("pending" if value == 0 else "bad")
        out.append({"key": key, "label": label, "value": value, "norm": norm,
                    "level": level, "inverse": inverse,
                    "text": f"{value:.0%}" if key != "complaints" else f"{value:.1%}"})
    return out


def summary() -> dict:
    hour = window(60)
    return {
        "hour": hour,
        "queue": queue(),
        "eta_minutes": eta_minutes(hour["per_minute"]),
        "pacing": pacing_state(),
        "accounts": by_account(60),
        "quality": quality(7),
    }


def next_allowed(account: str) -> int:
    return pacing.wait_left(account)
