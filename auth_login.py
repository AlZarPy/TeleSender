"""Интерактивная авторизация аккаунтов Telegram (выполняется один раз на аккаунт).

Запускайте сами в своём терминале: телефон, код из Telegram и пароль 2FA
вводятся здесь и никуда не отправляются, кроме api.telegram.org.
Создаёт файлы <session_name>.session (они в .gitignore).
"""
from __future__ import annotations

import asyncio
import getpass
import os
import sys
import time

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
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


def log(message: str) -> None:
    """Пишем ход входа в login.log (без телефона, кода и пароля)."""
    try:
        with open("login.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n")
    except OSError:
        pass


DRY_RUN = "--dry-run" in sys.argv
QR_MODE = "--qr" in sys.argv


async def login(account: dict) -> bool:
    tag = f"{account['my_name']}/{account['session_name']}"
    proxy = parse_proxy(account.get("proxy"))
    log(f"старт: аккаунт={account['session_name']} сеть={describe(proxy)} api_id={account['api_id']}")
    print(f"\n{tag}: сеть {describe(proxy)}")
    client = TelegramClient(account["session_name"], account["api_id"], account["api_hash"], proxy=proxy)
    try:
        await client.connect()
        log("подключение к Telegram: ок")
        if await client.is_user_authorized():
            me = await client.get_me()
            log(f"уже авторизован: @{me.username} id={me.id}")
            print(f"✓ {tag}: уже авторизован как @{me.username or me.id}")
            return True

        print(f"\n🔐 {tag}: требуется вход")
        preset = account.get("phone") or ""
        if preset:
            masked = preset[:4] + "…" + preset[-2:]
            print(f"  номер из config.txt: {masked}")
            phone = preset
        else:
            phone = input("  номер телефона (+7…): ").strip()
            phone = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        log(f"номер: {'из конфига' if preset else 'введён вручную'}, длина {len(phone)}")
        if len(phone) < 8:
            log("отмена: номер слишком короткий")
            print("  ❌ номер не введён или слишком короткий — вход отменён")
            return False

        if DRY_RUN:
            log("dry-run: код не запрашивался")
            print("  🔎 проверка без отправки кода: номер принят, всё готово к входу")
            print("     запустите без --dry-run, чтобы получить код в Telegram")
            return False

        try:
            await client.send_code_request(phone)
            log("код запрошен у Telegram")
        except PhoneNumberInvalidError:
            log("ошибка: PHONE_NUMBER_INVALID")
            print("  ❌ Telegram не принял номер (проверьте формат +<код страны><номер>)")
            return False
        except FloodWaitError as exc:
            log(f"ошибка: FLOOD_WAIT {exc.seconds}s")
            print(f"  ⏳ Telegram просит подождать {exc.seconds} с перед новым кодом")
            return False

        code = getpass.getpass("  код из Telegram (ввод скрыт): ").strip()
        log(f"код введён, длина {len(code)}")
        if not code:
            log("отмена: пустой код")
            print("  ❌ код не введён — вход отменён")
            return False

        try:
            await client.sign_in(phone, code)
            log("sign_in: ок")
        except SessionPasswordNeededError:
            log("требуется облачный пароль (2FA)")
            password = getpass.getpass("  пароль 2FA (ввод скрыт): ")
            if not password:
                log("отмена: пустой пароль 2FA")
                print("  ❌ пароль не введён — вход отменён")
                return False
            try:
                await client.sign_in(password=password)
                log("sign_in с паролем 2FA: ок")
            except Exception as exc:  # noqa: BLE001
                log(f"ошибка 2FA: {type(exc).__name__}: {exc}")
                print(f"  ❌ пароль не подошёл ({type(exc).__name__})")
                return False
        except PhoneCodeInvalidError:
            log("ошибка: PHONE_CODE_INVALID")
            print("  ❌ неверный код")
            return False
        except PhoneCodeExpiredError:
            log("ошибка: PHONE_CODE_EXPIRED")
            print("  ❌ код истёк, запустите снова")
            return False
        except AuthKeyUnregisteredError:
            log("ошибка: AUTH_KEY_UNREGISTERED")
            print("  ❌ сессия отозвана, удалите .session и повторите")
            return False

        me = await client.get_me()
        log(f"вход завершён: @{me.username} id={me.id}")
        print(f"  ✅ вошли как @{me.username or me.id} ({me.first_name or ''})")
        return True
    except (ConnectionError, OSError) as exc:
        log(f"сеть: {type(exc).__name__}: {exc}")
        print(f"  ❌ Telegram недоступен ({type(exc).__name__}). "
              f"Если сеть блокирует DC — добавьте proxy=socks5://host:port в config.txt")
        return False
    except Exception as exc:  # noqa: BLE001
        log(f"неожиданная ошибка: {type(exc).__name__}: {exc}")
        print(f"  ❌ Неожиданная ошибка: {type(exc).__name__}: {exc}")
        print("     подробности в login.log")
        return False
    finally:
        await client.disconnect()


async def login_qr(account: dict) -> bool:
    """Вход по QR/ссылке: пользователь подтверждает вход в своём Telegram, код не нужен."""
    tag = f"{account['my_name']}/{account['session_name']}"
    proxy = parse_proxy(account.get("proxy"))
    log(f"qr-вход: аккаунт={account['session_name']} сеть={describe(proxy)}")
    client = TelegramClient(account["session_name"], account["api_id"], account["api_hash"], proxy=proxy)
    try:
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"✓ {tag}: уже авторизован как @{me.username or me.id}")
            log(f"qr: уже авторизован @{me.username}")
            return True

        for attempt in range(1, int(os.environ.get("SENDERX_QR_ATTEMPTS", "6")) + 1):
            qr = await client.qr_login()
            print(f"\n{tag}: откройте ссылку в Telegram и подтвердите вход (попытка {attempt}/5):")
            print(f"  {qr.url}")
            print("  Ссылка живёт ~30 секунд. После подтверждения окно закроется само.")
            log(f"qr: выдана ссылка, попытка {attempt}")
            try:
                await qr.wait(timeout=35)
            except asyncio.TimeoutError:
                print("  …ссылка истекла, генерирую новую")
                log("qr: таймаут, обновляю ссылку")
                continue
            me = await client.get_me()
            print(f"  ✅ вошли как @{me.username or me.id} ({me.first_name or ''})")
            log(f"qr: вход завершён @{me.username} id={me.id}")
            return True
        print("  ❌ ссылки истекли — запустите снова")
        return False
    except (ConnectionError, OSError) as exc:
        log(f"qr сеть: {type(exc).__name__}: {exc}")
        print(f"  ❌ Telegram недоступен: {type(exc).__name__}")
        return False
    except Exception as exc:  # noqa: BLE001
        log(f"qr ошибка: {type(exc).__name__}: {exc}")
        print(f"  ❌ Ошибка: {type(exc).__name__}: {exc}")
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
        try:
            if QR_MODE:
                results.append(await login_qr(account))
            else:
                results.append(await login(account))
        except (EOFError, KeyboardInterrupt):
            print("\n⏹ вход прерван (окно закрыто или нажали Ctrl+C)")
            results.append(False)

    print("\n" + "=" * 46)
    print(f"Готовы к работе: {sum(results)} из {len(results)}")
    if DRY_RUN:
        print("(режим --dry-run: Telegram не тревожили)")
        return 0
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
