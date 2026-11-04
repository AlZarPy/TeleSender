"""SenderX — рассылка персонализированных сообщений в Telegram с ротацией аккаунтов.

Примеры:
    python main.py --dry-run                       # план без обращения к Telegram
    python main.py --limit 1 --min-delay 0 --max-delay 0   # один тестовый получатель
    python main.py --message "Привет, <ЕгоИмя>! Я <МоёИмя>."

Перед первым запуском: python auth_login.py (ввод телефона и кода — только в вашем терминале).
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import sys
import time
from pathlib import Path

from telethon import TelegramClient

from config_loader import ConfigError, load_config_from_txt
from csv_loader import RecipientsError, load_recipients
from io_utils import force_utf8
from proxy_config import describe, parse_proxy
from sender import FloodDetected, render, send_one

DEFAULT_SENT_LOG = "sent.jsonl"


def _utf8_stdout() -> None:
    force_utf8()


def load_sent(path: str) -> set[str]:
    """Кому уже успешно отправлено в прошлых прогонах (по логу)."""
    done: set[str] = set()
    if not os.path.exists(path):
        return done
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("ok"):
                done.add(str(record.get("username", "")).lower())
    return done


def filter_pending(recipients: list[str], sent: set[str], limit: int | None = None) -> list[str]:
    pending = [name for name in recipients if name.lower() not in sent]
    return pending[:limit] if limit else pending


def record_sent(path: str, account: str, username: str, ok: bool, reason: str = "") -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "account": account,
            "username": username,
            "ok": ok,
            "reason": reason,
        }, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Рассылка сообщений в Telegram с ротацией аккаунтов")
    p.add_argument("--config", default=None,
                   help="файл отправителей (по умолчанию $SENDERX_CONFIG или config.txt)")
    p.add_argument("--recipients", default="recipients.csv", help="CSV с колонкой recipient")
    p.add_argument("--message", help="текст сообщения (иначе спросим интерактивно)")
    p.add_argument("--message-file", help="файл с текстом сообщения")
    p.add_argument("--limit", type=int, help="отправить не более N получателям")
    p.add_argument("--min-delay", type=int, help="переопределить минимальную паузу, сек")
    p.add_argument("--max-delay", type=int, help="переопределить максимальную паузу, сек")
    p.add_argument("--dry-run", action="store_true", help="показать план и выйти, ничего не отправляя")
    p.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    p.add_argument("--sent-log", default=DEFAULT_SENT_LOG, help="журнал отправленных (по умолчанию sent.jsonl)")
    p.add_argument("--ignore-history", action="store_true", help="не пропускать тех, кому уже отправляли")
    p.add_argument("--allow-self", action="store_true",
                   help="разрешить отправку самому себе (тест в «Избранное»), по умолчанию такие получатели пропускаются")
    p.add_argument("--check-net", action="store_true",
                   help="проверить доступность Telegram (учитывая proxy=) и выйти")
    return p


async def check_net(accounts: list[dict]) -> int:
    """Пробует подключиться к Telegram, чтобы отличить блокировку сети от проблем в коде."""
    account = accounts[0]
    proxy = parse_proxy(account.get("proxy"))
    print(f"Проверяю Telegram через: {describe(proxy)}")
    client = TelegramClient(account["session_name"], account["api_id"], account["api_hash"], proxy=proxy)
    started = time.time()
    try:
        await asyncio.wait_for(client.connect(), timeout=25)
    except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
        print(f"❌ Не достучались за {time.time() - started:.1f} с: {type(exc).__name__}")
        print("   Похоже на блокировку DC в этой сети. Добавьте в строку аккаунта proxy=…")
        return 1
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()
    print(f"✅ Telegram отвечает за {time.time() - started:.1f} с")
    return 0


def resolve_message(args) -> str:
    if args.message_file:
        return Path(args.message_file).read_text(encoding="utf-8").strip()
    if args.message:
        return args.message.strip()
    print("Введите текст сообщения. Шаблоны: <МоёИмя>, <ЕгоИмя>. Пустая строка — конец ввода.")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip() and lines:
            break
        lines.append(line)
    return "\n".join(lines).strip()


async def run(args) -> int:
    accounts = load_config_from_txt(args.config)
    if not accounts:
        print("❌ В конфиге нет ни одного валидного отправителя")
        return 2
    print(f"👤 Отправителей: {len(accounts)}")

    if getattr(args, "check_net", False):
        return await check_net(accounts)

    recipients = load_recipients(args.recipients)
    if not recipients:
        print("❌ В списке получателей ничего не осталось после чистки")
        return 2

    sent = set() if args.ignore_history else load_sent(args.sent_log)
    pending = filter_pending(recipients, sent, args.limit)
    print(f"📋 Получателей в файле: {len(recipients)} | уже отправлено ранее: {len(sent)} | к отправке: {len(pending)}")
    if not pending:
        print("✅ Отправлять нечего — все получатели уже обработаны (сбросьте history через --ignore-history)")
        return 0

    template = ""
    if not (args.dry_run and not (args.message or args.message_file)):
        template = resolve_message(args)
        if not template:
            print("❌ Пустой текст сообщения")
            return 2

    if args.dry_run:
        print("\n=== DRY RUN: ничего не отправляется ===")
        for name in pending:
            preview = render(template, accounts[0]["my_name"], "‹имя›") if template else "‹текст не задан›"
            print(f"[{account_tag(accounts[0])}] → {name}: {preview!r}")
        print(f"\nИтого было бы отправлено: {len(pending)}"
              f" (аккаунтов хватит на {sum(a['max_per_account'] for a in accounts)})")
        return 0

    if not args.yes:
        answer = input(f"Отправить {len(pending)} сообщений с {len(accounts)} аккаунтов? [y/N] ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("Отменено")
            return 0

    queue = list(pending)
    stats = {"sent": 0, "failed": 0, "flood": 0}
    failures: dict[str, int] = {}

    for account in accounts:
        if not queue:
            break
        tag = account_tag(account)
        proxy = parse_proxy(account.get("proxy"))
        print(f"\n🚀 Аккаунт {tag} ({account['session_name']}), сеть: {describe(proxy)}")
        client = TelegramClient(account["session_name"], account["api_id"], account["api_hash"], proxy=proxy)
        try:
            try:
                await client.connect()
            except (ConnectionError, OSError) as exc:
                print(f"❌ {tag}: Telegram недоступен ({type(exc).__name__}). "
                      f"Если сеть блокирует DC — добавьте proxy=socks5://host:port в config.txt")
                continue
            if not await client.is_user_authorized():
                print(f"⚠️ {tag}: сессия не авторизована — запустите python auth_login.py")
                continue
            me = await client.get_me()
            me_id = None if args.allow_self else getattr(me, "id", None)
            quota = account["max_per_account"]
            sent_here = 0
            while queue and sent_here < quota:
                username = queue[0]
                try:
                    result = await send_one(client, username, account["my_name"], template, me_id)
                except FloodDetected as exc:
                    stats["flood"] += 1
                    print(f"⛔ {tag}: лимит Telegram, ждать {exc.seconds} с — переключаюсь на следующий аккаунт")
                    break

                queue.pop(0)
                sent_here += 1
                if result.ok:
                    stats["sent"] += 1
                    print(f"  ✅ {username}")
                else:
                    stats["failed"] += 1
                    failures[result.reason] = failures.get(result.reason, 0) + 1
                    print(f"  ❌ {username}: {result.reason}")
                record_sent(args.sent_log, tag, username, result.ok, result.reason)

                if queue and sent_here < quota:
                    lo = args.min_delay if args.min_delay is not None else account["min_delay"]
                    hi = args.max_delay if args.max_delay is not None else account["max_delay"]
                    delay = random.randint(min(lo, hi), max(lo, hi))
                    if delay:
                        print(f"  ⏱ пауза {delay} с…")
                        await asyncio.sleep(delay)
        finally:
            await client.disconnect()

    print("\n" + "=" * 46)
    print(f"Отправлено: {stats['sent']} | ошибок: {stats['failed']} | упёрлись в лимит: {stats['flood']} | осталось: {len(queue)}")
    if failures:
        print("Причины ошибок: " + ", ".join(f"{k}={v}" for k, v in sorted(failures.items())))
    if queue:
        print("Не отправлены: " + ", ".join(queue))
        return 1
    return 0


def account_tag(account: dict) -> str:
    return f"{account['my_name']}/{account['session_name']}"


def main() -> int:
    _utf8_stdout()
    args = build_parser().parse_args()
    try:
        return asyncio.run(run(args))
    except (ConfigError, RecipientsError) as exc:
        print(f"❌ {exc}")
        return 2
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
