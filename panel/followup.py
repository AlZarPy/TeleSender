"""Ответы на входящие: аккаунт не молчит, если ему ответили.

Задача — не изображать живого человека, а не терять диалог: на уточняющий
вопрос объяснить, на «интересно» — прислать анонс с постером, на отказ —
пометить получателя и больше не писать. Один ответ на одно сообщение.
"""
from __future__ import annotations

import asyncio
import os
import random
import re
from datetime import datetime
from pathlib import Path

from telethon.tl.types import User

from . import db, salesperson, stages

POSTER = Path("media/poster-terra.jpg")

# Пауза перед ответом: человек не отвечает через секунду. Ровный интервал тоже
# подозрителен, поэтому разброс большой, а иногда ответ «задерживается».
REPLY_DELAY = (20, 90)
LONG_DELAY = (120, 300)
LONG_CHANCE = 0.08


def reply_delay(rng: random.Random | None = None) -> int:
    rng = rng or random.Random()
    delay = rng.randint(*REPLY_DELAY)
    if rng.random() < LONG_CHANCE:
        delay = rng.randint(*LONG_DELAY)
    cap = int(os.getenv("SENDERX_REPLY_DELAY_MAX", "300"))
    return max(0, min(delay, cap))


async def mark_read(client, peer, account: str, username: str) -> None:
    """Отмечает входящее прочитанным: у собеседника появляются две галочки.

    Без этого человек видит одну галочку и решает, что его сообщение не дошло
    или что на той стороне никого нет.
    """
    try:
        await client.send_read_acknowledge(peer)
    except Exception as exc:  # noqa: BLE001
        db.event("read_ack_error", account, f"{type(exc).__name__}: {str(exc)[:60]}")


async def ready_to_reply(client, peer, account: str, username: str) -> int:
    """Человеческий порядок: сначала прочитал, потом подумал, потом написал."""
    await mark_read(client, peer, account, username)
    return await pause_before_reply(account, username)


async def pause_before_reply(account: str, username: str) -> int:
    delay = reply_delay()
    if delay:
        await asyncio.sleep(delay)
    db.event("reply_delay", account, f"@{username}: пауза {delay} с")
    return delay

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
NICHE_WORD = re.compile(
    r"(опт|розниц|услуг|стройк|строит|ремонт|производств|завод|логистик|доставк|"
    r"общепит|кафе|ресторан|бар|медицин|клиник|стоматолог|образовани|школ|курс|"
    r"недвижим|агентств|маркетплейс|wildberries|ozon|магазин|айти|софт|сайт|"
    r"маркетинг|реклам|юрист|бухгалтер|финанс|груз|автосервис|авто|мебель|одежд|"
    r"обувь|косметик|красот|салон|фитнес|спорт|туризм|отел|гостиниц|сельск|агро|"
    r"монтаж|отделк|франшиз|дистрибуц|импорт|экспорт|вэд|b2b|b2c)", re.I)
OBJECTION = re.compile(r"далек|не\s*могу|нет\s*врем|дорого|позже|не\s*в\s*москв|"
                       r"другой\s*город|онлайн|не\s*получится|занят", re.I)
SOFT = re.compile(r"(?<![а-яa-z])(спасибо|благодарю|окей|ок|понял[аи]?|понятно|ясно|хорошо|принял[аи]?|договорились)(?![а-яa-z])", re.I)
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
    if SOFT.search(t) and len(t) <= 45:
        return "silence"
    if OBJECTION.search(t):
        return "chat"
    if len(t) <= 40 and len(t.split()) <= 4 and "?" not in t and NICHE_WORD.search(t):
        return "niche"
    if len(t) >= 3:
        return "chat"
    return "silence"


def announced_before(username: str) -> bool:
    """Анонс с постером в этом диалоге уже отправляли — второй раз нельзя."""
    return bool(db.q1(
        "SELECT 1 FROM events WHERE kind IN ('followup','sales_reply') "
        "AND detail LIKE ? AND detail LIKE '%announce%'", (f"%@{username}%",)))


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
        stage = stages.update(username, msg.text or "")

        if action != "silence" and not allowed(username):
            _mark(account, msg.id, "skipped")
            continue
        if action != "silence" and cooling(username):
            _mark(account, msg.id, "cooling")
            db.event("followup_cooling", account, f"@{username} — недавно отвечали")
            continue

        if stage == "end":
            _mark(account, msg.id, "stage_end")
            continue

        if action == "refuse":
            db.block_recipient(username, True)
            _mark(account, msg.id, action)
            lines.append(f"{account}: отказ от @{username} — больше не пишем")
            continue

        if action == "silence":
            await mark_read(client, sender, account, username)
            _mark(account, msg.id, action)
            continue

        if action == "chat":
            if salesperson.replies_so_far(username) >= salesperson.MAX_REPLIES:
                _mark(account, msg.id, "limit")
                continue

            if salesperson.needs_human(msg.text or ""):
                db.event("human_needed", account, f"@{username}: {(msg.text or '')[:120]}")
                await ready_to_reply(client, sender, account, username)
                try:
                    await client.send_message(
                        sender, "Тут лучше голосом — передаю куратору, он вам наберёт.")
                except Exception as exc:  # noqa: BLE001
                    db.event("followup_error", account, f"{type(exc).__name__}")
                _mark(account, msg.id, "human")
                mark_cooling(username)
                lines.append(f"{account}: передал человеку @{username}")
                continue

            history = []
            try:
                async for m in client.iter_messages(sender, limit=salesperson.MEMORY_TURNS):
                    who = "us" if m.out else "them"
                    if m.text:
                        history.append({"who": who, "text": m.text})
                history.reverse()
            except Exception:  # noqa: BLE001
                history = [{"who": "them", "text": msg.text or ""}]

            reply = salesperson.compose(history, account, stage=stage)
            if not reply:  # модель не ответила — держим диалог простой фразой
                reply = salesperson.CHAT_FALLBACK + f"https://t.me/+{INVITE.get(account, '')}"
            await ready_to_reply(client, sender, account, username)
            try:
                await client.send_message(sender, reply)
            except Exception as exc:  # noqa: BLE001
                db.event("followup_error", account, f"{type(exc).__name__}: {str(exc)[:60]}")
                continue
            _mark(account, msg.id, action)
            mark_cooling(username)
            db.event("sales_reply", account, f"@{username}")
            lines.append(f"{account}: ответил живьём @{username}")
            continue

        if action == "announce" and announced_before(username):
            _mark(account, msg.id, "announce_dup")
            db.event("announce_skipped", account, f"@{username} — анонс уже отправляли")
            continue

        if action == "niche":
            await ready_to_reply(client, sender, account, username)
            try:
                await client.send_message(
                    sender,
                    f"Принял: {(msg.text or '').strip().lower()}. "
                    "Соберу 3 сценария под эту сферу и пришлю следом. "
                    "Пока — что будет 13 ноября: " + announce_text(account),
                    parse_mode="md", link_preview=False)
            except Exception as exc:  # noqa: BLE001
                db.event("followup_error", account, f"{type(exc).__name__}: {str(exc)[:80]}")
                continue
            _mark(account, msg.id, action)
            db.event("followup", account, f"{action} → @{username}")
            lines.append(f"{account}: ответ {action} для @{username}")
            continue

        await ready_to_reply(client, sender, account, username)
        try:
            if action == "announce" and POSTER.exists():
                await client.send_file(sender, str(POSTER), caption=announce_text(account),
                                       parse_mode="md", link_preview=False)
            else:
                await client.send_message(sender, explain_text())
        except Exception as exc:  # noqa: BLE001
            db.event("followup_error", account, f"{type(exc).__name__}: {str(exc)[:80]}")
            continue

        _mark(account, msg.id, action)
        mark_cooling(username)
        if action in ("announce", "niche"):
            stages.mark(username, "solution")
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
