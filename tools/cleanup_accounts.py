"""Чистка купленных аккаунтов от «наследства» продавца.

Что делает:
    • выходит из каналов, которые не нужны для прогрева (взрослые, спам-подборки);
    • удаляет диалоги с ботами и посторонними людьми;
    • оставляет переписку внутри нашего пула и официальные каналы.

Зачем: аккаунты приходили с историей взрослой рассылки. Telegram оценивает
аккаунт в том числе по окружению, а старые диалоги с незнакомцами портят картину.

Запуск:
    python tools/cleanup_accounts.py --dry-run     # только показать план
    python tools/cleanup_accounts.py               # выполнить
    python tools/cleanup_accounts.py --only acc_br3
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient  # noqa: E402
from telethon.tl.functions.channels import LeaveChannelRequest  # noqa: E402
from telethon.tl.types import Channel, User  # noqa: E402

from config_loader import load_config_from_txt, load_proxies  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402

KEEP_CHANNELS = {"telegram", "durov", "telegramtips", "premium", "telegrampremium"}
KEEP_USERS = {777000, 178220800}   # служебный аккаунт Telegram и @SpamBot
MAX_ACTIONS = 40               # чтобы не долбить Telegram пачкой
PAUSE = (2.0, 5.0)


async def clean_one(name: str, account: dict, proxy_value: str, pool_ids: set[int],
                    dry: bool) -> dict:
    stats = {"left": 0, "deleted": 0, "kept": 0, "errors": 0}
    client = TelegramClient(name, account["api_id"], account["api_hash"],
                            proxy=parse_proxy(proxy_value), timeout=35, connection_retries=2)
    await client.connect()
    try:
        me = await client.get_me()
        print(f"\n=== {name} ({me.first_name}, +{me.phone}) ===", flush=True)
        actions = 0
        async for dialog in client.iter_dialogs(limit=120):
            if actions >= MAX_ACTIONS:
                break
            entity = dialog.entity
            title = (dialog.name or "")[:40]

            if isinstance(entity, Channel):
                username = (getattr(entity, "username", "") or "").lower()
                if username in KEEP_CHANNELS:
                    stats["kept"] += 1
                    continue
                if dry:
                    print(f"  выйти из канала: {title}")
                else:
                    try:
                        await client(LeaveChannelRequest(entity))
                        await asyncio.sleep(random.uniform(*PAUSE))
                    except Exception as exc:  # noqa: BLE001
                        stats["errors"] += 1
                        print(f"  ! канал {title}: {type(exc).__name__}")
                        continue
                stats["left"] += 1
                actions += 1
                continue

            if isinstance(entity, User):
                if entity.bot or entity.id not in pool_ids:
                    if entity.id in KEEP_USERS:
                        stats["kept"] += 1
                        continue
                    kind = "бота" if entity.bot else "постороннего"
                    if dry:
                        print(f"  удалить диалог с {kind}: {title or entity.id}")
                    else:
                        try:
                            await client.delete_dialog(entity)
                            await asyncio.sleep(random.uniform(*PAUSE))
                        except Exception as exc:  # noqa: BLE001
                            stats["errors"] += 1
                            print(f"  ! диалог {title}: {type(exc).__name__}")
                            continue
                    stats["deleted"] += 1
                    actions += 1
                else:
                    stats["kept"] += 1
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return stats


async def main_async(args) -> int:
    from panel import db

    alive, _ = db.worker_alive()
    if alive and not args.force:
        print("воркер держит сессии — сначала остановите его")
        return 3

    accounts = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    proxies = load_proxies()

    # американские в возврат — их не трогаем, чтобы не тратить действия
    names = [n for n in sorted(accounts) if n.startswith("acc_") and not n.startswith("acc_us")]
    if args.only:
        names = [n for n in names if n == args.only]
    names = [n for n in names if proxies.get(n)]
    if not names:
        print("нет аккаунтов с прокси")
        return 2

    # id всех наших аккаунтов — их диалоги не трогаем
    pool_ids: set[int] = set()
    for name in names:
        client = TelegramClient(name, accounts[name]["api_id"], accounts[name]["api_hash"],
                                proxy=parse_proxy(proxies[name]), timeout=30)
        try:
            await client.connect()
            me = await client.get_me()
            pool_ids.add(me.id)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
    print(f"своих аккаунтов в пуле: {len(pool_ids)}")

    total = {"left": 0, "deleted": 0, "kept": 0, "errors": 0}
    for name in names:
        try:
            stats = await clean_one(name, accounts[name], proxies[name], pool_ids, args.dry_run)
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: не удалось — {type(exc).__name__}: {str(exc)[:60]}")
            continue
        for key in total:
            total[key] += stats[key]
        print(f"  итог {name}: вышёл из {stats['left']} каналов, "
              f"удалил {stats['deleted']} диалогов, ошибок {stats['errors']}")

    print(f"\nВСЕГО: вышли из {total['left']} каналов, удалили {total['deleted']} диалогов, "
          f"оставили {total['kept']}, ошибок {total['errors']}")
    if args.dry_run:
        print("это был пробный прогон — ничего не изменено")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Чистка купленных аккаунтов")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    raise SystemExit(asyncio.run(main_async(ap.parse_args())))
