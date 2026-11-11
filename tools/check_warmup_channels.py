"""Проверка каналов прогрева: какие из списка реально существуют."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import load_config_from_txt  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402
from telethon import TelegramClient  # noqa: E402

CANDIDATES = [
    "telegram", "durov", "telegramtips", "premium", "telegramnews",
    "vcnews", "habr_com", "neurohive", "openai", "nvidia", "nplus1",
    "tproger", "forbes", "rbctrends", "secretmag", "rusbase",
    "ainowadays", "robotrends", "neuro_news", "ai_newz",
]


def proxies() -> dict[str, str]:
    out = {}
    for line in (ROOT / "proxies.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ";" in line:
            name, url = line.split(";", 1)
            out[name] = url
    return out


async def main() -> int:
    cfg = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    px = proxies()
    name = "pechkin01"
    _k, host, port, rdns, user, pwd = parse_proxy(px[name])
    client = TelegramClient(name, cfg[name]["api_id"], cfg[name]["api_hash"],
                            proxy=("socks5", host, int(port), rdns, user, pwd),
                            connection_retries=1, request_retries=1, timeout=30)
    await client.connect()
    alive: list[str] = []
    try:
        for username in CANDIDATES:
            try:
                entity = await client.get_entity(username)
                if getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False):
                    alive.append(username)
                    print(f"  ок  @{username}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  нет @{username}: {type(exc).__name__}", flush=True)
            await asyncio.sleep(1.3)
    finally:
        await client.disconnect()

    print(f"\nсуществуют: {len(alive)} из {len(CANDIDATES)}")
    print(" ".join("@" + a for a in alive))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
