"""Поиск каналов для прогрева по темам, с проверкой существования.

Использует поиск Telegram (contacts.Search), а не резолв имён: резолв пачкой
ловит FloodWait быстрее. Результат печатается списком с подписчиками.

    python tools/find_warmup_channels.py --account acct_c1
    python tools/find_warmup_channels.py --account acct_c1 --write
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import load_config_from_txt  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402
from telethon import TelegramClient, functions  # noqa: E402
from telethon.tl.types import Channel  # noqa: E402

QUERIES = [
    "нейросети", "искусственный интеллект", "бизнес", "предприниматель",
    "маркетинг", "продажи", "малый бизнес",
]

BAD = re.compile(
    r"porn|sex|xxx|nude|casino|bet|ставк|казино|порн|интим|знакомств"
    r"|кредит|займ|микрозайм|крипт[ао]|crypto|трейд|сигнал|18\+",
    re.I,
)

MIN_SUBS = 5_000
MAX_SUBS = 2_000_000


def proxies() -> dict[str, str]:
    out = {}
    for line in (ROOT / "proxies.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ";" in line:
            name, url = line.split(";", 1)
            out[name] = url
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="acct_c1")
    ap.add_argument("--write", action="store_true", help="записать найденное в warmup_channels.txt")
    args = ap.parse_args()

    cfg = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    px = proxies()
    name = args.account
    if name not in px:
        print(f"{name}: нет прокси")
        return 1

    _k, host, port, rdns, user, pwd = parse_proxy(px[name])
    client = TelegramClient(name, cfg[name]["api_id"], cfg[name]["api_hash"],
                            proxy=("socks5", host, int(port), rdns, user, pwd),
                            connection_retries=1, request_retries=1, timeout=40)
    await client.connect()

    found: dict[str, dict] = {}
    try:
        for query in QUERIES:
            try:
                res = await client(functions.contacts.SearchRequest(q=query, limit=30))
            except Exception as exc:  # noqa: BLE001
                print(f"«{query}»: поиск не удался ({type(exc).__name__})")
                await asyncio.sleep(10)
                continue
            added = 0
            for chat in res.chats:
                if not isinstance(chat, Channel) or not getattr(chat, "username", None):
                    continue
                if not getattr(chat, "broadcast", False):
                    continue                      # нужны каналы, а не группы
                title = chat.title or ""
                if BAD.search(title) or BAD.search(chat.username):
                    continue
                subs = getattr(chat, "participants_count", 0) or 0
                if not (MIN_SUBS <= subs <= MAX_SUBS):
                    continue
                if not re.search(r"[А-Яа-яЁё]", title):
                    continue                      # русскоязычные
                found.setdefault(chat.username, {"title": title, "subs": subs,
                                                 "topic": query})["subs"] = max(
                    found.get(chat.username, {}).get("subs", 0), subs)
                added += 1
            print(f"«{query}»: +{added}, всего {len(found)}", flush=True)
            await asyncio.sleep(8)
    finally:
        await client.disconnect()

    rows = sorted(found.items(), key=lambda kv: -kv[1]["subs"])
    print("\nкандидаты:")
    for username, info in rows:
        print(f"  @{username:24s} {info['subs']:>9,} — {info['title'][:44]} ({info['topic']})")

    if args.write and rows:
        path = ROOT / "warmup_channels.txt"
        header = ("# Каналы для прогрева: по одному в строке.\n"
                  "# Собраны поиском по темам, проверены на существование и тематику.\n")
        body = "\n".join("@" + u for u, _ in rows)
        path.write_text(header + body + "\n", encoding="utf-8")
        print(f"\nзаписано в {path}: {len(rows)} каналов")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
