"""Проверка аккаунта: живой ли он и есть ли ограничения.

Смысл не в отчёте, а в том, чтобы аккаунт жил долго: ограничение нужно увидеть
в первый день, а не через неделю, когда половина пула уже в спам-блоке.

Две вещи, которые проверяются без отправки сообщений людям:
    • online — статус сессии из get_me (был в сети / когда заходил);
    • spam   — ответ @SpamBot на «/start»: «Good news, no limits» или «limited».
"""
from __future__ import annotations

import asyncio
import time
import re
from datetime import datetime

from . import db

SPAM_CLEAN = re.compile(r"no limits|nenhum limite|нет ограничени|sin l[ií]mites|good news", re.I)
SPAM_LIMITED = re.compile(r"limited|restricted|ограничен|limitad|restringid", re.I)
SPAM_TIME = re.compile(r"(\d+)\s*(day|days|hour|hours|дн|час)", re.I)


def online_status(user) -> tuple[str, str]:
    """'онлайн' / 'был(а) <когда>' по статусу из get_me."""
    status = getattr(user, "status", None)
    name = type(status).__name__ if status else "None"
    if name == "UserStatusOnline":
        return "онлайн", name
    if name == "UserStatusOffline":
        was = getattr(status, "was_online", None)
        if was:
            if isinstance(was, datetime):
                return "не в сети", was.strftime("%d.%m %H:%M")
            return "не в сети", str(was)[:16]
    if name == "UserStatusRecently":
        return "недавно", name
    if name == "UserStatusLastWeek":
        return "на этой неделе", name
    if name == "UserStatusLastMonth":
        return "в этом месяце", name
    return "неизвестно", name


async def ask_spambot(client) -> tuple[str, str]:
    """Спрашивает @SpamBot про ограничения. Возвращает (статус, текст ответа)."""
    try:
        bot = await client.get_entity("SpamBot")
    except Exception as exc:  # noqa: BLE001
        return "нет доступа", f"{type(exc).__name__}: {str(exc)[:60]}"

    try:
        await client.send_message(bot, "/start")
    except Exception as exc:  # noqa: BLE001
        return "нет доступа", f"{type(exc).__name__}: {str(exc)[:60]}"

    await asyncio.sleep(4)          # бот отвечает не мгновенно
    text = ""
    try:
        async for msg in client.iter_messages(bot, limit=5):
            if msg.out:
                continue
            text = msg.message or ""
            if text:
                break
    except Exception as exc:  # noqa: BLE001
        return "ошибка", f"{type(exc).__name__}: {str(exc)[:60]}"

    if not text:
        return "нет ответа", ""
    if SPAM_LIMITED.search(text) and not SPAM_CLEAN.search(text):
        left = SPAM_TIME.search(text)
        return "ОГРАНИЧЕН", (f"до {left.group(1)} {left.group(2)}" if left else text[:80])
    if SPAM_CLEAN.search(text):
        return "чисто", "no limits"
    return "непонятно", text[:80]


async def check(client, account: str, *, spam: bool = True) -> dict:
    me = await client.get_me()
    on_status, on_detail = online_status(me)
    db.check_set(account, "online", on_status, on_detail)

    result = {"account": account, "online": on_status}
    if spam:
        spam_status, spam_detail = await ask_spambot(client)
        db.check_set(account, "spam", spam_status, spam_detail)
        result["spam"] = spam_status
        if spam_status == "ОГРАНИЧЕН":
            db.event("spam_block", account, spam_detail)
    return result


async def tick(pool, accounts: list[dict], hours: float = 20.0) -> list[str]:
    """По одному аккаунту за проход: чаще, чем раз в сутки, проверять незачем."""
    lines: list[str] = []
    for acc in accounts:
        name = acc["session_name"]
        if db.checks_fresh(name, "spam", hours):
            continue
        try:
            client = await pool.get(name)
            res = await check(client, name)
            lines.append(f"{name}: {res['online']} / @SpamBot {res.get('spam', '—')}")
            if res.get("spam") == "ОГРАНИЧЕН":
                # paused_until=0 читался как «пауза истекла» и аккаунт возвращался
                # в работу на следующем проходе — ставим сутки
                db.set_account(name, status="paused", paused_until=time.time() + 24 * 3600)
        except Exception as exc:  # noqa: BLE001
            db.event("check_error", name, f"{type(exc).__name__}: {str(exc)[:80]}")
        await asyncio.sleep(3)
    return lines


def summary(accounts: list[dict]) -> list[dict]:
    """Данные для панели: онлайн и спам-статус рядом с аккаунтом."""
    out = []
    for acc in accounts:
        name = acc["session_name"]
        on = db.check_get(name, "online")
        spam = db.check_get(name, "spam")
        acc = dict(acc)
        acc["online"] = on["status"] if on else ""
        acc["online_at"] = (on["checked_at"] or "")[11:16] if on else ""
        acc["spam"] = spam["status"] if spam else ""
        acc["spam_note"] = spam["detail"] if spam else ""
        acc["spam_at"] = (spam["checked_at"] or "")[:10] if spam else ""
        out.append(acc)
    return out
