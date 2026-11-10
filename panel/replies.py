"""Обратная почта: отмечает получателей, которые ответили.

Зачем: тот, кто ответил, — «тёплый». Ему можно писать повторно, и это не спам.
Тот, кто молчит или заблокировал, второй раз не получает ничего.

Сканируем только последние диалоги аккаунта (не всю переписку) и только те,
где последнее сообщение — входящее. Дорого по лимитам, поэтому вызываем редко:
из воркера раз в 10 минут и вручную командой `python -m panel.replies`.
"""
from __future__ import annotations

import asyncio
import sys

from panel import db


async def scan_client(client, limit: int = 30) -> list[tuple[str, str]]:
    """Возвращает [(username, когда ответил)] по последним диалогам аккаунта."""
    found: list[tuple[str, str]] = []
    async for dialog in client.iter_dialogs(limit=limit):
        if not dialog.is_user:
            continue
        entity = dialog.entity
        username = getattr(entity, "username", None)
        if not username:
            continue
        last = dialog.message
        if last is None or getattr(last, "out", False):
            continue  # последним писали мы — ответа нет
        when = last.date.astimezone().strftime("%Y-%m-%d %H:%M:%S") if last.date else ""
        found.append((username, when))
    return found


def remember(found: list[tuple[str, str]], account: str = "") -> list[str]:
    """Пишет ответы в базу. Возвращает имена тех, кто ответил впервые."""
    fresh = []
    for username, when in found:
        if db.mark_replied(username, when):
            fresh.append(username)
            db.event("reply", account, f"@{username} ответил {when}")
    return fresh


async def scan_pool(pool, accounts: list[dict], limit: int = 30) -> list[str]:
    """Обходит все аккаунты пула и собирает новые ответы."""
    fresh: list[str] = []
    for acc in accounts:
        if acc["status"] != "active":
            continue
        if not acc.get("proxy"):
            # без прокси подключение запрещено — молча пропускаем, чтобы не засорять журнал
            continue
        try:
            client = await pool.get(acc["session_name"])
            found = await scan_client(client, limit)
        except Exception as exc:  # noqa: BLE001 — один аккаунт не должен ронять скан
            db.event("reply_scan_error", acc["session_name"], str(exc)[:120])
            continue
        fresh += remember(found, acc["session_name"])
    return fresh


async def _main_async() -> int:
    from config_loader import load_config_from_txt
    from io_utils import force_utf8
    from panel.worker import Pool

    force_utf8()
    accounts = db.accounts_with_config(load_config_from_txt("config.txt", quiet=True))
    pool = Pool(accounts)
    try:
        fresh = await scan_pool(pool, accounts)
    finally:
        await pool.close_all()
    print(f"новых ответов: {len(fresh)}" + (f" — {', '.join('@' + u for u in fresh)}" if fresh else ""))
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    sys.exit(main())
