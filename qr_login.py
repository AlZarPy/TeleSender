"""Один QR для входа: рисует PNG с tg://login-токеном и ждёт подтверждения.

Выводит машинно-читаемые строки, чтобы агент мог подхватить файл:
    QR_READY:<путь к png>
    AUTHORIZED:<@username>
    EXPIRED
    FAILED:<причина>
"""
from __future__ import annotations

import asyncio
import sys
import time

import qrcode

from telethon import TelegramClient
from config_loader import load_config_from_txt
from io_utils import force_utf8
from proxy_config import parse_proxy

OUT = "C:/Users/User/AppData/Local/hermes/cache/scratch/telegram_login_qr.png"


async def main() -> int:
    force_utf8()
    acc = load_config_from_txt("config.txt", quiet=True)[0]
    proxy = parse_proxy(acc.get("proxy"))
    client = TelegramClient(acc["session_name"], acc["api_id"], acc["api_hash"], proxy=proxy)
    try:
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"AUTHORIZED:@{me.username}")
            return 0

        for attempt in range(1, 4):
            qr = await client.qr_login()
            img = qrcode.make(qr.url, box_size=8, border=2)
            img.save(OUT)
            print(f"QR_READY:{OUT}", flush=True)
            try:
                await qr.wait(timeout=40)
            except asyncio.TimeoutError:
                print("EXPIRED", flush=True)
                continue
            me = await client.get_me()
            print(f"AUTHORIZED:@{me.username}", flush=True)
            return 0
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED:{type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
