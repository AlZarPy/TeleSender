"""Интерактивная авторизация аккаунтов Telegram (выполняется один раз на аккаунт).

Запускайте сами в своём терминале: телефон, код из Telegram и пароль 2FA
вводятся здесь и никуда не отправляются, кроме api.telegram.org.
Создаёт файлы <session_name>.session (они в .gitignore).
"""
from __future__ import annotations

import asyncio
import getpass
import sys

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyUnregisteredError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from config_loader import ConfigError, load_config_from_txt
from io_utils import force_utf8
from proxy_config import describe, parse_proxy


def _utf8_stdout() -> None:
    force_utf8()


async def login(account: dict) -> bool:
    tag = f"{account['my_name']}/{account['session_name']}"
    proxy = parse_proxy(account.get("proxy"))
    print(f"\n{tag}: сеть {describe(proxy)}")
    client = TelegramClient(account["session_name"], account["api_id"], account["api_hash"], proxy=proxy)
    try:
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"✓ {tag}: уже авторизован как @{me.username or me.id}")
            return True

        print(f"\n🔐 {tag}: требуется вход")
        phone = input("  номер телефона (+7…): ").strip()
        try:
            await client.send_code_request(phone)
        except PhoneNumberInvalidError:
            print("  ❌ Telegram не принял номер")
            return False

        code = getpass.getpass("  код из Telegram (ввод скрыт): ").strip()
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            password = getpass.getpass("  пароль 2FA (ввод скрыт): ")
            await client.sign_in(password=password)
        except PhoneCodeInvalidError:
            print("  ❌ неверный код")
            return False
        except PhoneCodeExpiredError:
            print("  ❌ код истёк, запустите снова")
            return False
        except AuthKeyUnregisteredError:
            print("  ❌ сессия отозвана, удалите .session и повторите")
            return False

        me = await client.get_me()
        print(f"  ✅ вошли как @{me.username or me.id} ({me.first_name or ''})")
        return True
    except (ConnectionError, OSError) as exc:
        print(f"  ❌ Telegram недоступен ({type(exc).__name__}). "
              f"Если сеть блокирует DC — добавьте proxy=socks5://host:port в config.txt")
        return False
    finally:
        await client.disconnect()


async def main() -> int:
    _utf8_stdout()
    try:
        accounts = load_config_from_txt()
    except ConfigError as exc:
        print(f"❌ {exc}")
        return 2
    if not accounts:
        print("❌ в config.txt нет валидных аккаунтов")
        return 2

    results = []
    for account in accounts:
        results.append(await login(account))

    print("\n" + "=" * 46)
    print(f"Готовы к работе: {sum(results)} из {len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
