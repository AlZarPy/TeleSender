"""Поиск аккаунта Telegram по номеру телефона и отправка сообщения.

Telegram не даёт «поиск по номеру» напрямую: номер нужно добавить в контакты
(ImportContactsRequest), и только тогда сервер вернёт пользователя, если
он разрешил находить себя по номеру. После отправки контакт можно удалить,
чтобы не засорять записную книжку и не «залипали» старые имена.

Запуск:
    python tools/resolve_phones.py --account pechkin02 --phones phones.txt --dry-run
    python tools/resolve_phones.py --account pechkin02 --phones phones.txt --text "…"

Формат файла: по одному номеру в строке, в международном виде (+351…).

Ограничения, которые заложены:
  • пауза между номерами (по умолчанию 40–90 с) — Telegram считает частые
    импорты контактов подозрительными и отвечает FloodWait;
  • после каждого номера контакт удаляется;
  • отправка только тем, кто нашёлся, и только если передан --text.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import load_config_from_txt  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402
from telethon import TelegramClient  # noqa: E402
from telethon.tl.functions.contacts import (  # noqa: E402
    DeleteContactsRequest,
    ImportContactsRequest,
)
from telethon.tl.types import InputPhoneContact  # noqa: E402


def load_proxies(path: str = "proxies.txt") -> dict[str, str]:
    out: dict[str, str] = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and ";" in line:
                name, url = line.split(";", 1)
                out[name.strip()] = url.strip()
    return out


async def resolve(client, phone: str) -> tuple[bool, object | None]:
    """Пробует найти пользователя по номеру. Возвращает (найден, пользователь)."""
    try:
        res = await client(ImportContactsRequest([
            InputPhoneContact(client_id=0, phone=phone, first_name="Контакт", last_name="")
        ]))
    except Exception as exc:  # noqa: BLE001
        print(f"  {phone}: ошибка импорта — {type(exc).__name__}: {str(exc)[:80]}")
        return False, None
    if not res.users:
        return False, None
    user = res.users[0]
    # сразу убираем контакт и перечитываем профиль: сервер в ответе на импорт
    # отдаёт то имя, которое мы сами прислали («Контакт»), а не настоящее
    try:
        await client(DeleteContactsRequest(id=[user]))
        user = await client.get_entity(user.id)
    except Exception:  # noqa: BLE001
        pass
    return True, user


async def drop(client, user) -> None:
    try:
        await client(DeleteContactsRequest(id=[user]))
    except Exception:  # noqa: BLE001
        pass


async def main() -> int:
    ap = argparse.ArgumentParser(description="Номер → аккаунт → сообщение")
    ap.add_argument("--account", required=True, help="с какого аккаунта работать")
    ap.add_argument("--phones", required=True, help="файл с номерами")
    ap.add_argument("--text", default="", help="текст сообщения (если нужно отправить)")
    ap.add_argument("--dry-run", action="store_true", help="только найти, не отправлять")
    ap.add_argument("--min-gap", type=int, default=40)
    ap.add_argument("--max-gap", type=int, default=90)
    args = ap.parse_args()

    numbers = [ln.strip() for ln in Path(args.phones).read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.strip().startswith("#")]
    print(f"номеров в файле: {len(numbers)}")

    accs = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    if args.account not in accs:
        print(f"аккаунт {args.account} не найден в config.txt")
        return 2
    acc = accs[args.account]
    url = load_proxies().get(args.account) or acc.get("proxy")
    if not url:
        print("у аккаунта нет прокси — работа запрещена")
        return 2
    kind, host, port, rdns, user, pwd = parse_proxy(url)

    client = TelegramClient(args.account, acc["api_id"], acc["api_hash"],
                            proxy=("socks5", host, int(port), rdns, user, pwd), timeout=30)
    await client.connect()

    found, missing, sent = [], [], 0
    for phone in numbers:
        ok, person = await resolve(client, phone)
        if not ok:
            missing.append(phone)
            print(f"  {phone}: не найден (номер не зарегистрирован или скрыт)")
        else:
            name = " ".join(x for x in (getattr(person, "first_name", ""),
                                        getattr(person, "last_name", "")) if x).strip()
            username = getattr(person, "username", None)
            found.append((phone, name, username))
            print(f"  {phone}: найден — {name}" + (f" @{username}" if username else ""))
            if args.text and not args.dry_run:
                try:
                    await client.send_message(person, args.text)
                    sent += 1
                    print("     сообщение отправлено")
                except Exception as exc:  # noqa: BLE001
                    print(f"     отправка не удалась: {type(exc).__name__}: {str(exc)[:80]}")
        if ok:
            await drop(client, person)
        await asyncio.sleep(random.uniform(args.min_gap, args.max_gap))

    await client.disconnect()
    print(f"\nитого: найдено {len(found)}, не найдено {len(missing)}, отправлено {sent}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
