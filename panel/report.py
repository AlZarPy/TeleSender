"""Сводка за сутки: что доставлено, что сломалось, кто ответил."""
from __future__ import annotations

from panel import brand, db

DAY_SQL = "date(ts)=date('now')"


def numbers() -> dict:
    row = db.q1(f"""SELECT
                      SUM(ok=1) ok, SUM(ok=0) fail, COUNT(*) total
                    FROM sends WHERE {DAY_SQL}""")
    replies = db.q1("SELECT COUNT(*) c FROM recipients WHERE replied=1")
    running = db.q1("SELECT COUNT(*) c FROM campaigns WHERE status='running'")
    waiting = db.q1("SELECT COUNT(*) c FROM campaigns WHERE status IN ('draft','paused')")
    return {
        "ok": int(row["ok"] or 0) if row else 0,
        "fail": int(row["fail"] or 0) if row else 0,
        "total": int(row["total"] or 0) if row else 0,
        "replies": int(replies["c"] or 0) if replies else 0,
        "running": int(running["c"] or 0) if running else 0,
        "waiting": int(waiting["c"] or 0) if waiting else 0,
    }


def build(accounts: list[dict]) -> str:
    """Текст сводки. Без эмодзи-мусора: только цифры, которые нужны для решения."""
    n = numbers()
    alive, state = db.worker_alive()
    lines = [
        f"Почтамт · сводка за сутки",
        f"доставлено: {n['ok']} · ошибок: {n['fail']} · попыток: {n['total']}",
        f"ответили: {n['replies']} · кампаний в работе: {n['running']} · ждут: {n['waiting']}",
        f"воркер: {'работает' if alive else 'остановлен'}"
        + (f" ({state.get('detail')})" if alive and state.get("detail") else ""),
    ]

    if accounts:
        lines.append("")
        for acc in accounts:
            flags = []
            if acc.get("status") != "active":
                flags.append("пауза")
            if acc.get("paused_now"):
                flags.append("flood")
            if acc.get("warmup_day") and acc["warmup_day"] <= acc.get("warmup_days", 0):
                flags.append(f"прогрев {acc['warmup_day']}/{acc['warmup_days']}")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"{acc['session_name']}: {acc['sent_today']}/{acc['effective_limit']}"
                         f" · осталось {acc['left_today']}{suffix}")

    errors = db.q(f"""SELECT reason, COUNT(*) c FROM sends
                      WHERE {DAY_SQL} AND ok=0 GROUP BY reason ORDER BY c DESC LIMIT 3""")
    if errors:
        lines.append("")
        lines.append("ошибки: " + ", ".join(
            f"{brand.reason_label(row['reason']) or 'без причины'} ×{row['c']}" for row in errors))

    stopped = db.q("""SELECT name, stopped_reason FROM campaigns
                      WHERE status='stopped' AND date(finished_at)=date('now') LIMIT 3""")
    if stopped:
        lines.append("")
        for row in stopped:
            lines.append(f"остановлен «{row['name']}»: {row['stopped_reason'] or 'вручную'}")

    return "\n".join(lines)
