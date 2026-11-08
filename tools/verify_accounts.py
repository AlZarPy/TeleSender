"""Проверка аккаунтов через их прокси: кто это, жив ли, есть ли ограничения.

Правила безопасности (почему скрипт такой осторожный):
    • каждый аккаунт подключается только через свой прокси из proxies.txt;
    • никаких сообщений, кроме одного /start в @SpamBot при --spam;
    • между аккаунтами пауза, чтобы не было залповой активности;
    • при ошибке прокси аккаунт пропускается, а не пробуется напрямую.

Запуск:
    python tools/verify_accounts.py                    # только опознание
    python tools/verify_accounts.py --spam             # ещё и @SpamBot
    python tools/verify_accounts.py --only acc_br1
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient  # noqa: E402

from config_loader import load_config_from_txt, load_proxies  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402

PAUSE = 12  # секунд между аккаунтами

def worker_running() -> bool:
    """Защита от второго подключения: два процесса с одной сессией убивают её.

    Telegram выдаёт AuthKeyDuplicated и аннулирует ключ навсегда, если видел
    один и тот же auth_key из двух разных мест. Поэтому инструменты проверки
    отказываются работать, пока воркер держит сессии.
    """
    from panel import db

    alive, _ = db.worker_alive()
    return bool(alive)



async def check(account: dict, proxy_value: str, spam: bool) -> dict:
    name = account["session_name"]
    result = {"name": name, "ok": False, "who": "", "phone": "", "country": "",
              "spam": ""}
    proxy = parse_proxy(proxy_value)
    client = TelegramClient(name, account["api_id"], account["api_hash"],
                            proxy=proxy, connection_retries=2, timeout=30)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            result["spam"] = "не авторизован"
            return result
        me = await client.get_me()
        result["ok"] = True
        result["who"] = (me.first_name or "") + (" @" + me.username if me.username else "")
        result["phone"] = me.phone or ""
        result["country"] = getattr(getattr(me, "phone", None), "country_code", "") or ""

        if spam:
            await client.send_message("SpamBot", "/start")
            await asyncio.sleep(6)
            messages = await client.get_messages("SpamBot", limit=4)
            text = ""
            for msg in messages:
                if not msg.out:
                    text = (msg.text or "").lower()
                    break
            if any(m in text for m in ("good news", "no limits", "nenhum limite", "boas not",
                                       "aucune limite", "keine einschr")):
                result["spam"] = "чистый"
            elif any(m in text for m in ("limited", "restricted", "limitado")):
                result["spam"] = "ОГРАНИЧЕН"
            else:
                result["spam"] = text.replace("\n", " ")[:70] or "ответа нет"
    except Exception as exc:  # noqa: BLE001
        result["spam"] = f"ошибка: {str(exc)[:70]}"
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return result


async def main_async(args) -> int:
    if worker_running() and not args.force:
        print("воркер сейчас держит сессии — остановите его, иначе Telegram аннулирует ключ")
        return 3

    accounts = load_config_from_txt(None, quiet=True)
    proxies = load_proxies()

    wanted = [a for a in accounts if a["session_name"].startswith("acc_")]
    if args.only:
        wanted = [a for a in wanted if a["session_name"] == args.only]
    if not wanted:
        print("нет аккаунтов acc_* в config.txt")
        return 2

    clean = 0
    for index, account in enumerate(wanted, 1):
        name = account["session_name"]
        proxy_value = proxies.get(name.lower())
        if not proxy_value:
            print(f"{name:10} — нет прокси, пропуск (через домашний IP не подключаем)")
            continue
        res = await check(account, proxy_value, args.spam)
        if res["ok"]:
            clean += 1
            print(f"{name:10} ✓ {res['who'][:24]:24} +{res['phone']:14} {res['spam']}")
        else:
            print(f"{name:10} ✕ {res['spam']}")
        if index < len(wanted):
            await asyncio.sleep(PAUSE)
    print(f"\nподключилось: {clean} из {len(wanted)}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Опознание аккаунтов через их прокси")
    ap.add_argument("--spam", action="store_true", help="проверить @SpamBot")
    ap.add_argument("--only", default="", help="только один аккаунт")
    ap.add_argument("--force", action="store_true", help="работать, даже если воркер запущен")
    raise SystemExit(asyncio.run(main_async(ap.parse_args())))
