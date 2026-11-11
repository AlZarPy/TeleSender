"""Тестовая отправка первого сообщения на свой аккаунт.

Берёт переписанный под каждый аккаунт текст (не шаблон!), подставляет имя
получателя и имя куратора, отправляет с паузами и пишет результат в журнал.

    python tools/send_test_to_self.py --target r2605s
    python tools/send_test_to_self.py --target r2605s --group b --campaign 19
    python tools/send_test_to_self.py --target r2605s --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import load_config_from_txt  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402
from telethon import TelegramClient  # noqa: E402
from telethon.errors import FloodWaitError  # noqa: E402

from panel import db, message, peers  # noqa: E402


def proxies() -> dict[str, str]:
    out = {}
    for line in (ROOT / "proxies.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ";" in line:
            name, url = line.split(";", 1)
            out[name] = url
    return out


async def send_one(account: str, text: str, target: str, cfg: dict, px: dict,
                   dry: bool, force: bool = False) -> str:
    _k, host, port, rdns, user, pwd = parse_proxy(px[account])
    client = TelegramClient(account, cfg[account]["api_id"], cfg[account]["api_hash"],
                            proxy=("socks5", host, int(port), rdns, user, pwd),
                            connection_retries=1, request_retries=1, timeout=40)
    try:
        await client.connect()
        me = await client.get_me()
        entity = peers.peer(account, target)
        if entity is None:
            entity = await client.get_entity(target)
            if getattr(entity, "access_hash", None):
                peers.remember(account, target, entity)
        his = getattr(entity, "first_name", "") or ""
        expanded = message.expand_spintax(text, random.Random())
        body = message.personalise(expanded, me.first_name or "", his)
        if dry:
            return f"{account} ({me.first_name}): [dry] {body[:80]}…"
        if db.sent_same_recently(target, body, hours=24) and not force:
            return f"{account}: этот текст уже уходил @{target} — не отправляю"
        sent = await client.send_message(entity, body, parse_mode="md", link_preview=False)
        db.log_send(0, target, account, True, "test_to_self", sent.id,
                    variant=1000, text=body)
        head = (sent.message or body).splitlines()[0][:70]
        return f"{account} ({me.first_name}): отправлено · «{head}…»"
    except FloodWaitError as exc:
        # не исключаем аккаунт: ограничение на поиск временное, вернётся сам
        db.event("resolve_flood", account, f"поиск @{target}: пауза {exc.seconds} с")
        return f"{account}: пауза поиска {exc.seconds} с — вернётся после"
    except Exception as exc:  # noqa: BLE001
        db.log_send(0, target, account, False, f"{type(exc).__name__}: {str(exc)[:60]}")
        return f"{account}: ОШИБКА {type(exc).__name__}: {str(exc)[:80]}"
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="r2605s")
    ap.add_argument("--campaign", type=int, default=19)
    ap.add_argument("--group", default="b")
    ap.add_argument("--stage", type=int, default=1)
    ap.add_argument("--gap", type=float, default=30.0, help="базовая пауза между отправками")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--exclude", default="", help="аккаунты через запятую, которые пропустить")
    ap.add_argument("--force", action="store_true", help="слать даже тем, кому уже уходило")
    args = ap.parse_args()

    db.init()
    cfg = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    px = proxies()

    names = [r["session_name"] for r in
             db.q("""SELECT session_name FROM accounts
                     WHERE status='active' AND grp=? ORDER BY session_name""", (args.group,))]
    names = [n for n in names if n in px]
    excluded = {x.strip() for x in args.exclude.split(",") if x.strip()}
    if excluded:
        names = [n for n in names if n not in excluded]
    if not args.force:
        done = {r["account"] for r in db.q(
            "SELECT DISTINCT account FROM sends WHERE reason='test_to_self' AND ok=1")}
        skipped = [n for n in names if n in done]
        names = [n for n in names if n not in done]
        if skipped:
            print("уже получали, пропускаю:", ", ".join(skipped))
    if not names:
        print("нет аккаунтов группы", args.group)
        return 1

    print(f"цель @{args.target} · аккаунтов {len(names)} · кампания {args.campaign} "
          f"· этап {args.stage} · пауза ~{args.gap} с")
    sent = failed = 0
    for i, name in enumerate(names, 1):
        rows = db.account_texts_get(name, args.campaign, args.stage)
        if not rows:
            print(f"{name}: нет переписанного текста — пропуск")
            continue
        variant = rows[(i - 1) % len(rows)]
        line = await send_one(name, variant["text"], args.target, cfg, px,
                              args.dry_run, force=args.force)
        print(f"{i}/{len(names)} {line}", flush=True)
        if "ОШИБКА" in line:
            failed += 1
        else:
            sent += 1
        if i < len(names):
            await asyncio.sleep(args.gap + random.uniform(0, 15))
    print(f"\nитого: отправлено {sent}, ошибок {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
