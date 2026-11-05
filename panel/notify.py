"""Уведомления в Telegram: пишем сами себе в «Избранное».

Зачем именно так: отдельного бота нет, а почтовый аккаунт уже авторизован —
значит тревога уйдёт в тот же мессенджер, где вы и так сидите.

Адресат по умолчанию — «Избранное» (me). Если задать REPORT_CHAT
(например, @username или числовой id), сводка уйдёт туда.
"""
from __future__ import annotations

import os

from panel import db


def target() -> str:
    return os.environ.get("REPORT_CHAT", "me")


async def send(pool, text: str, prefer_account: str = "") -> bool:
    """Отправляет текст через первый доступный аккаунт. Не роняет воркер при сбое."""
    accounts = [prefer_account] if prefer_account else list(pool.accounts)
    for name in accounts:
        if not name:
            continue
        try:
            client = await pool.get(name)
            await client.send_message(target(), text)
            return True
        except Exception as exc:  # noqa: BLE001 — уведомление не должно ломать рассылку
            db.event("notify_error", name, str(exc)[:120])
            continue
    return False
