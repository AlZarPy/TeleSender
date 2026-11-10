"""Ответы на входящие: аккаунт не молчит, если ему ответили.

Задача — не изображать живого человека, а не терять диалог: на уточняющий
вопрос объяснить, на «интересно» — прислать анонс с постером, на отказ —
пометить получателя и больше не писать. Один ответ на одно сообщение.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from telethon.tl.types import User

from . import db

POSTER = Path("media/poster-terra.jpg")

# инвайт-ссылка на аккаунт: та же, что стоит в описании
INVITE = {
    "pechkin01": "6lOUlnEV6-s0MTcy", "pechkin02": "D1mV6dYXKQI1NzIy",
    "pechkin03": "nw29HFPrftxkOTEy", "pechkin04": "Xc2CjPP06FgyYmIy",
    "pechkin05": "-S6K_9plXSllZTYy", "pechkin06": "mhzhl8EhSBQ0MzYy",
    "pechkin07": "aAoFNmfbAH9lNzIy", "pechkin08": "0xMVJYXk2v1kNDMy",
    "pechkin09": "QJp69xWR-7c3YTEy", "pechkin10": "rB1fO7CvTHsxMTky",
    "pechkin11": "ewD7xEaauHs3NGUy",
}

TICKET = "https://zapuskterra.ru/"
GROUP = "https://t.me/+6lOUlnEV6-s0MTcy"

REFUSE = re.compile(r"не\s*интерес|не\s*надо|не\s*нужно|не\s*пиш|отстань|хватит\s*писать|это\s*спам|отпиши|уберите|удали\s*меня|заблок", re.I)
CONFUSED = re.compile(r"чем\s*(я\s*)?занима|в\s*смысле|не\s*пон(ял|ятно)|что\s*значит|поясни|о\s*ч[её]м\s*вы|какой\s*ниш", re.I)
AGREE = re.compile(r"интересн|давай|да,|пришли|скин|присылай|хочу|расскаж|подробн|"
                   r"что\s*там|по\s*ии|про\s*ии|программ|расписан|да\b", re.I)
NICHE_OK = re.compile(r"[а-яa-z]", re.I)
SOFT = re.compile(r"^\s*(спасибо|благодарю|ок(?![а-яa-z])|окей|понял[аи]?(?![а-яa-z])|ясно|хорошо|принято|нет[, ]+спасибо)", re.I)
ASK = re.compile(r"сколько|цена|стоит|бесплатн|где\s|адрес|во\s*сколько|регистрац", re.I)


def explain_text() -> str:
    return ("Имел в виду сферу, в которой вы работаете — опт, услуги, стройка, "
            "маркетплейсы, общепит, любое. Напишите одно слово, и пришлю 3 сценария, "
            "где ИИ снимает рутину: продажи, маркетинг, автоматизация.")


def announce_text(account: str) -> str:
    invite = INVITE.get(account, "")
    tail = f"\nГруппа школы: https://t.me/+{invite}" if invite else ""
    return ("**13 ноября, 15:00** · Конгресс-центр ЦМТ, 4-й подъезд, Москва, "
            "Краснопресненская наб., 12 · участие бесплатное\n\n"
            "Что будет: 39 мастер-классов в 5 залах, школа «Нейросети», "
            "две смены живых разборов с наставниками.\n\n"
            f"Билет по регистрации: {TICKET}{tail}")


def decided(text: str) -> str:
    """'refuse' | 'explain' | 'announce' | 'niche' | 'silence'."""
    t = (text or "").strip()
    if not t:
        return "silence"
    if REFUSE.search(t):
        return "refuse"
    if CONFUSED.search(t):
        return "explain"
    if AGREE.search(t) or ASK.search(t):
        return "announce"
    if SOFT.match(t) and len(t) <= 30:
        return "silence"
    if len(t) <= 40 and "?" not in t and NICHE_OK.search(t):
        return "niche"
    return "silence"


def cooling(username: str, hours: float | None = None) -> bool:
    """Не отвечали ли этому человеку только что. По умолчанию — сутки покоя."""
    import os
    import time

    limit = hours if hours is not None else float(os.getenv("SENDERX_FOLLOWUP_COOLDOWN_H", "12"))
    row = db.q1("SELECT last_at FROM followup_cooldown WHERE username=?", (username,))
    return bool(row) and (time.time() - float(row["last_at"])) < limit * 3600


def mark_cooling(username: str) -> None:
    import time

    db.execute("""INSERT INTO followup_cooldown(username, last_at) VALUES(?,?)
                  ON CONFLICT(username) DO UPDATE SET last_at=excluded.last_at""",
               (username, time.time()))


def allowed(username: str) -> bool:
    """Отвечаем только тем, кому писали мы, и тем, кого явно указали в белом списке.

    Без этого автоответчик влезал бы в прогрев — чужие переписки пула между собой.
    """
    import os

    extra = {u.strip().lower() for u in os.getenv("SENDERX_FOLLOWUP_WHITELIST", "").split(",") if u.strip()}
    if username.lower() in extra:
        return True
    if db.q1("SELECT 1 FROM recipients WHERE username=?", (username,)):
        return True
    return False


def _seen(account: str, msg_id: int) -> bool:
    return bool(db.q1("SELECT 1 FROM followup_seen WHERE account=? AND msg_id=?",
                      (account, msg_id)))


def _mark(account: str, msg_id: int, action: str) -> None:
    db.execute('INSERT OR IGNORE INTO followup_seen(account, msg_id, action, "when") '
               'VALUES(?,?,?,?)',
               (account, msg_id, action, datetime.now().isoformat(timespec="seconds")))


async def scan_client(client, account: str, limit: int = 15) -> list[str]:
    lines: list[str] = []
    me = await client.get_me()
    async for msg in client.iter_messages(None, limit=limit):
        if not msg.is_private or msg.out:
            continue
        sender = msg.sender
        if not isinstance(sender, User) or sender.id == me.id:
            continue
        if _seen(account, msg.id):
            continue
        action = decided(msg.text or "")
        username = (sender.username or f"id{sender.id}").lower()
        if action != "silence" and not allowed(username):
            _mark(account, msg.id, "skipped")
            continue
        if action != "silence" and cooling(username):
            _mark(account, msg.id, "cooling")
            db.event("followup_cooling", account, f"@{username} — недавно отвечали")
            continue

        if action == "refuse":
            db.block_recipient(username, True)
            _mark(account, msg.id, action)
            lines.append(f"{account}: отказ от @{username} — больше не пишем")
            continue

        if action == "silence":
            _mark(account, msg.id, action)
            continue

        if action == "niche":
            try:
                await client.send_message(
                    sender,
                    f"Принял: {(msg.text or '').strip().lower()}. "
                    "Соберу 3 сценария под эту сферу и пришлю следом. "
                    "Пока — что будет 13 ноября: " + announce_text(account),
                    parse_mode="md")
            except Exception as exc:  # noqa: BLE001
                db.event("followup_error", account, f"{type(exc).__name__}: {str(exc)[:80]}")
                continue
            _mark(account, msg.id, action)
            db.event("followup", account, f"{action} → @{username}")
            lines.append(f"{account}: ответ {action} для @{username}")
            continue

        try:
            if action == "announce" and POSTER.exists():
                await client.send_file(sender, str(POSTER), caption=announce_text(account),
                                       parse_mode="md")
            else:
                await client.send_message(sender, explain_text())
        except Exception as exc:  # noqa: BLE001
            db.event("followup_error", account, f"{type(exc).__name__}: {str(exc)[:80]}")
            continue

        _mark(account, msg.id, action)
        mark_cooling(username)
        db.event("followup", account, f"{action} → @{username}")
        lines.append(f"{account}: ответ {action} для @{username}")
    return lines


async def tick(pool, accounts: list[dict], limit: int = 15) -> list[str]:
    out: list[str] = []
    for acc in accounts:
        name = acc["session_name"]
        try:
            client = await pool.get(name)
            out += await scan_client(client, name, limit)
        except Exception as exc:  # noqa: BLE001
            db.event("followup_error", name, str(exc)[:120])
    return out
