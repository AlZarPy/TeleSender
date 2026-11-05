"""Здоровье аккаунта: одна цифра и понятные причины.

Идея взята из TMMS (health-score), но считается по нашим данным:
сессия, статус, свежие флуды, доля ошибок, отказы «закрыт для сообщений»,
давность последней успешной отправки.

Шкала: 90+ можно работать, 75–89 следить, 50–74 готовиться к замене, ниже 50 — не гнать.
"""
from __future__ import annotations

from panel import db


def _clamp(value: float) -> int:
    return int(max(0, min(100, round(value))))


def level(score: int) -> str:
    if score >= 90:
        return "ok"
    if score >= 75:
        return "warn"
    return "bad"


def label(score: int) -> str:
    if score >= 90:
        return "здоров"
    if score >= 75:
        return "следить"
    if score >= 50:
        return "риск"
    return "менять"


def account_health(account: dict) -> dict:
    """Возвращает {score, level, label, reasons: [(уровень, текст)]}."""
    name = account["session_name"]
    score = 100.0
    reasons: list[tuple[str, str]] = []

    if not account.get("session_exists"):
        return {"score": 0, "level": "bad", "label": "менять",
                "reasons": [("bad", "нет файла сессии — вход не выполнен")]}

    if account.get("status") != "active":
        score -= 45
        reasons.append(("bad", "аккаунт на паузе"))

    floods = db.q1("""SELECT COUNT(*) c FROM events
                      WHERE account=? AND kind='flood' AND ts >= datetime('now','localtime','-1 day')""",
                   (name,))
    flood_count = int(floods["c"]) if floods else 0
    if flood_count:
        score -= min(25, 8 * flood_count)
        reasons.append(("warn", f"флуд за сутки: {flood_count}"))

    recent = db.q("SELECT ok FROM sends WHERE account=? ORDER BY id DESC LIMIT 30", (name,))
    if len(recent) >= 5:
        errors = sum(1 for row in recent if not row["ok"])
        share = errors / len(recent)
        if share >= 0.4:
            score -= 30
            reasons.append(("bad", f"ошибок {share:.0%} из последних {len(recent)}"))
        elif share >= 0.2:
            score -= 15
            reasons.append(("warn", f"ошибок {share:.0%} из последних {len(recent)}"))

    streak = db.privacy_streak(name)
    if streak >= 2:
        score -= 12
        reasons.append(("warn", f"отказов «закрыт для сообщений» подряд: {streak}"))

    if account.get("warmup_day") and account["warmup_day"] <= account.get("warmup_days", 0):
        reasons.append(("ok", f"прогрев: день {account['warmup_day']} из {account['warmup_days']}"))

    left = account.get("left_today", 0)
    if account.get("status") == "active" and left == 0:
        score -= 5
        reasons.append(("warn", "дневная квота выбрана"))

    if not reasons:
        reasons.append(("ok", "без замечаний"))

    total = _clamp(score)
    return {"score": total, "level": level(total), "label": label(total), "reasons": reasons}


def with_health(accounts: list[dict]) -> list[dict]:
    """Добавляет к каждому аккаунту поле health."""
    out = []
    for acc in accounts:
        item = dict(acc)
        item["health"] = account_health(acc)
        out.append(item)
    return out
