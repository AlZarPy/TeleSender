"""Отзыв тестовых сообщений: чистим чаты владельца от прогонов.

Удаляет только СВОИ (out=True) сообщения за сегодня в указанных чатах.
Ничего чужого не трогает.

    python tools/recall_tests.py --target r2605s --keep pechkin06
    python tools/recall_tests.py --target R2606 --accounts pechkin11
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import load_config_from_txt  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402
from telethon import TelegramClient  # noqa: E402

from panel import db  # noqa: E402


def proxies() -> dict[str, str]:
    out = {}
    for line in (ROOT / "proxies.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ";" in line:
            name, url = line.split(";", 1)
            out[name] = url
    return out


async def clean(account: str, target: str, cfg: dict, px: dict, today: str,
                all_days: bool = False) -> int:
    _k, host, port, rdns, user, pwd = parse_proxy(px[account])
    client = TelegramClient(account, cfg[account]["api_id"], cfg[account]["api_hash"],
                            proxy=("socks5", host, int(port), rdns, user, pwd),
                            connection_retries=1, request_retries=1, timeout=40)
    await client.connect()
    removed = 0
    try:
        entity = await client.get_entity(target)
        ids = []
        async for msg in client.iter_messages(entity, limit=50):
            if not msg.out or not msg.date:
                continue
            if all_days or msg.date.astimezone().strftime("%Y-%m-%d") == today:
                ids.append(msg.id)
        if ids:
            await client.delete_messages(entity, ids, revoke=True)
            removed = len(ids)
        return removed
    finally:
        await client.disconnect()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--keep", default="", help="аккаунты через запятую, чьи сообщения оставить")
    ap.add_argument("--accounts", default="", help="только эти аккаунты")
    ap.add_argument("--all-days", action="store_true", help="удалять свои сообщения за любую дату")
    args = ap.parse_args()

    db.init()
    cfg = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    px = proxies()
    keep = {x.strip() for x in args.keep.split(",") if x.strip()}

    if args.accounts:
        names = [x.strip() for x in args.accounts.split(",") if x.strip()]
    else:
        names = [r["session_name"] for r in
                 db.q("""SELECT session_name FROM accounts
                         WHERE status='active' AND COALESCE(grp,'')<>'personal'
                         ORDER BY session_name""")]
    names = [n for n in names if n in px and n in cfg and n not in keep]
    today = date.today().isoformat()
    print(f"чистим @{args.target} за {today} · аккаунтов {len(names)}, оставляем {sorted(keep) or '—'}")

    total = 0
    for name in names:
        try:
            n = await clean(name, args.target, cfg, px, today, all_days=args.all_days)
            total += n
            print(f"  {name}: удалено {n}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: ОШИБКА {type(exc).__name__}: {str(exc)[:60]}")
        await asyncio.sleep(3)
    print(f"\nвсего удалено: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
