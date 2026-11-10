"""Прочитано ли наше сообщение — факт с сервера, а не догадка.

В Telegram за это отвечает `read_outbox_max_id` у диалога: id последнего нашего
сообщения, которое собеседник открыл. Если он не меньше id отправленного, значит
прочитано. Проверено на живом диалоге: `read_outbox_max_id = 42` при последнем
отправленном `42` — то есть информация доступна, и «Telegram не отдаёт прочтения»
относится только к счётчикам в интерфейсе, а не к API.
"""
from __future__ import annotations

import asyncio

from . import db

MAX_DIALOGS = 40          # сколько диалогов смотреть за проход


async def scan_client(client, account: str) -> list[str]:
    from telethon.tl.functions.messages import GetPeerDialogsRequest

    marked = 0
    checked = 0
    async for dialog in client.iter_dialogs(limit=MAX_DIALOGS):
        if not dialog.is_user:
            continue
        peer = dialog.entity
        username = (getattr(peer, "username", "") or f"id{peer.id}").lower()
        try:
            res = await client(GetPeerDialogsRequest(peers=[peer]))
        except Exception as exc:  # noqa: BLE001
            db.event("read_scan_error", account, f"{type(exc).__name__}: {str(exc)[:60]}")
            continue
        if not res.dialogs:
            continue
        read_up_to = res.dialogs[0].read_outbox_max_id or 0
        if not read_up_to:
            continue
        rows = db.q("""SELECT msg_id FROM sends
                       WHERE account=? AND recipient=? AND msg_id>0 AND read_at=''
                         AND msg_id<=?""", (account, username, read_up_to))
        if not rows:
            continue
        ids = [int(r["msg_id"]) for r in rows]
        marked += db.mark_read({username: ids}, account)
        checked += 1

    if marked:
        return [f"{account}: прочитано {marked} сообщ."]
    return []


async def tick(pool, accounts: list[dict]) -> list[str]:
    out: list[str] = []
    for acc in accounts:
        name = acc["session_name"]
        try:
            client = await pool.get(name)
            out += await scan_client(client, name)
        except Exception as exc:  # noqa: BLE001
            db.event("read_scan_error", name, f"{type(exc).__name__}: {str(exc)[:80]}")
        await asyncio.sleep(2)
    return out
