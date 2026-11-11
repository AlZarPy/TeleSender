"""Аудит купленного аккаунта: подписки, профиль, ограничения.

Обязательный шаг после покупки и импорта. Купленные аккаунты часто приходят
с мусором: порно-каналы, казино, чужие юзернеймы, пустые профили. Такой аккаунт
нельзя ставить на прогрев — он уже помечен и тянет за собой репутацию пула.

Использование:
    python tools/audit_accounts.py --group c                # только посмотреть
    python tools/audit_accounts.py --group c --fix          # отписаться от мусора
    python tools/audit_accounts.py --accounts acct_a1,acct_a2 --fix
    python tools/audit_accounts.py --all --fix
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import load_config_from_txt  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402
from telethon import TelegramClient  # noqa: E402
from telethon.tl.functions.channels import LeaveChannelRequest  # noqa: E402
from telethon.tl.functions.messages import DeleteHistoryRequest  # noqa: E402
from telethon.tl.types import Channel, Chat  # noqa: E402

from panel import db  # noqa: E402

# Порно, казино, знакомства, ставки — всё, что делает профиль «не рабочим».
BAD = re.compile(
    r"porn|sex|xxx|nude|naked|onlyfans|escort|hookup|dating|18\+|casino|betting|slots?"
    r"|порн|эрот|интим|знакомств|секс|ставк|казино|букмекер|слот|разврат|гол(ая|ые)"
    r"|кредит|займ|микрозайм|crypto ?signal|сигнал",
    re.I,
)

BAD_USERNAME = re.compile(r"[_\d]{2,}|[a-z]{5,}\d{2,}", re.I)  # фабричные ники вроде shirley_butler28


def proxy_map() -> dict[str, str]:
    out = {}
    for line in (ROOT / "proxies.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ";" in line:
            name, url = line.split(";", 1)
            out[name] = url
    return out


async def audit_one(name: str, cfg: dict, px: dict, fix: bool) -> dict:
    result = {"account": name, "channels": [], "bad": [], "left": [], "errors": [],
              "profile": {}, "spambot": ""}
    if name not in px:
        result["errors"].append("нет прокси")
        return result
    _k, host, port, rdns, user, pwd = parse_proxy(px[name])
    client = TelegramClient(name, cfg[name]["api_id"], cfg[name]["api_hash"],
                            proxy=("socks5", host, int(port), rdns, user, pwd),
                            connection_retries=1, request_retries=1, timeout=30)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            result["errors"].append("не авторизован")
            return result

        me = await client.get_me()
        result["profile"] = {
            "id": me.id, "first_name": me.first_name or "", "last_name": me.last_name or "",
            "username": me.username or "", "phone": me.phone or "",
            "photo": bool(getattr(me, "photo", None)),
        }

        dialogs = await client.get_dialogs(limit=None)
        for d in dialogs:
            entity = d.entity
            if not isinstance(entity, (Channel, Chat)):
                continue
            title = d.name or ""
            username = getattr(entity, "username", None) or ""
            if isinstance(entity, Channel):
                result["channels"].append(title)
            if BAD.search(title) or (username and BAD.search(username)):
                result["bad"].append(title)
                if fix:
                    try:
                        if isinstance(entity, Channel) and getattr(entity, "megagroup", False) is False:
                            await client(LeaveChannelRequest(entity))
                        else:
                            await client(LeaveChannelRequest(entity))
                        result["left"].append(title)
                        await asyncio.sleep(2)
                    except Exception as exc:  # noqa: BLE001
                        result["errors"].append(f"не вышло выйти из «{title}»: {type(exc).__name__}")

        try:
            bot = await client.get_entity("SpamBot")
            await client.send_message(bot, "/start")
            await asyncio.sleep(4)
            msgs = await client.get_messages(bot, limit=1)
            result["spambot"] = (msgs[0].message or "")[:80].replace("\n", " ") if msgs else "?"
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"SpamBot: {type(exc).__name__}")
        return result
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"{type(exc).__name__}: {str(exc)[:70]}")
        return result
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def pick_accounts(args) -> list[str]:
    db.init()
    if args.accounts:
        return [a.strip() for a in args.accounts.split(",") if a.strip()]
    if args.all:
        return [r["session_name"] for r in
                db.q("SELECT session_name FROM accounts WHERE status='active' ORDER BY session_name")]
    return [r["session_name"] for r in
            db.q("SELECT session_name FROM accounts WHERE status='active' AND grp=? ORDER BY session_name",
                 (args.group,))]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", help="список через запятую")
    ap.add_argument("--group", default="", help="группа аккаунтов: a, b, c")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--fix", action="store_true", help="выйти из мусорных каналов")
    args = ap.parse_args()

    names = pick_accounts(args)
    if not names:
        print("аккаунтов не найдено")
        return 1

    cfg = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    px = proxy_map()

    total_bad = total_left = 0
    for name in names:
        r = await audit_one(name, cfg, px, args.fix)
        total_bad += len(r["bad"])
        total_left += len(r["left"])
        p = r["profile"]
        head = (f"{name}: каналов {len(r['channels'])}, мусора {len(r['bad'])}"
                + (f", вышел из {len(r['left'])}" if args.fix else ""))
        print(head)
        if p:
            print(f"   профиль: {p.get('first_name','')} {p.get('last_name','')}".rstrip()
                  + f" | @{p.get('username') or '—'} | фото {'есть' if p.get('photo') else 'нет'}"
                  + f" | {p.get('phone') or '—'}")
        if r["spambot"]:
            print(f"   SpamBot: {r['spambot']}")
        if r["bad"]:
            print("   мусор: " + "; ".join(r["bad"][:6]))
        for err in r["errors"]:
            print(f"   ! {err}")
        await asyncio.sleep(3)

    print(f"\nитого: аккаунтов {len(names)}, мусорных каналов {total_bad}"
          + (f", отписались от {total_left}" if args.fix else " (запустите с --fix, чтобы отписаться)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
