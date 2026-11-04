"""Загрузка и валидация отправителей из config.txt.

Формат строки (обратная совместимость с исходным TeleSender):
    session_name=sender1;api_id=123456;api_hash=<hash>;my_name=Александр

Необязательные поля:
    min_delay=20        — минимальная пауза между отправками, сек
    max_delay=60        — максимальная пауза, сек
    max_per_account=50  — сколько сообщений отправлять с одного аккаунта за прогон
"""
from __future__ import annotations

import os

CONFIG_PATH = "config.txt"
REQUIRED = ("session_name", "api_id", "api_hash", "my_name")
DEFAULTS = {"min_delay": 20, "max_delay": 60, "max_per_account": 50}
OPTIONAL_STR = ("proxy", "my_name", "session_name")


class ConfigError(RuntimeError):
    pass


def mask(value: str) -> str:
    return value[:4] + "…" + value[-2:] if len(value) > 8 else "…"


def parse_account(line: str) -> dict:
    """Разбирает одну строку config.txt. Бросает ValueError с понятной причиной."""
    account: dict[str, object] = {}
    for part in line.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"фрагмент без '=': {part!r}")
        key, _, value = part.partition("=")
        account[key.strip()] = value.strip()

    missing = [k for k in REQUIRED if k not in account]
    if missing:
        raise ValueError("нет обязательных полей: " + ", ".join(missing))

    try:
        api_id = int(str(account["api_id"]))
    except ValueError as exc:
        raise ValueError(f"api_id должен быть числом, получено {account['api_id']!r}") from exc
    if not 1 <= api_id < 2**31:
        raise ValueError(f"api_id вне допустимого диапазона: {api_id}")

    limits: dict[str, int] = {}
    for key, default in DEFAULTS.items():
        try:
            limits[key] = int(str(account.get(key, default)))
        except ValueError as exc:
            raise ValueError(f"{key} должен быть числом, получено {account.get(key)!r}") from exc

    if limits["max_delay"] < limits["min_delay"]:
        raise ValueError("max_delay меньше min_delay")
    if limits["max_per_account"] < 1:
        raise ValueError("max_per_account должен быть >= 1")

    account["api_id"] = api_id
    account.update(limits)

    for key in ("api_hash", "my_name", "session_name"):
        account[key] = str(account[key])
    account.setdefault("proxy", "")
    if account["proxy"]:
        from proxy_config import parse_proxy  # локальный импорт: нужен только при наличии прокси
        parse_proxy(str(account["proxy"]))  # валидируем сразу, а не в момент отправки

    phone = str(account.get("phone", "")).strip()
    phone = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if phone and (len(phone) < 8 or not phone.startswith("+")):
        raise ValueError(f"phone должен быть в формате +<код страны><номер>, получено {len(phone)} цифр")
    account["phone"] = phone
    return account


PROXIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxies.txt")


def load_proxies(path: str | None = None, *, quiet: bool = True) -> dict[str, str]:
    """Отдельный файл прокси: строка «аккаунт;прокси».

    Нужен, чтобы менять прокси, не трогая config.txt с api_hash.
    Пустой/отсутствующий файл — просто нет переопределений.
    """
    file = path or os.environ.get("SENDERX_PROXIES", PROXIES_PATH)
    overrides: dict[str, str] = {}
    if not os.path.exists(file):
        return overrides
    with open(file, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if ";" not in line:
                if not quiet:
                    print(f"⚠️ proxies.txt строка {lineno}: нужен формат «аккаунт;прокси»")
                continue
            name, proxy = (part.strip() for part in line.split(";", 1))
            if not name or not proxy:
                continue
            try:
                from proxy_config import parse_proxy  # локальный импорт: нужен только здесь
                parse_proxy(proxy)
            except Exception as exc:  # noqa: BLE001 — прокси проверяем сразу
                if not quiet:
                    print(f"⚠️ proxies.txt строка {lineno} пропущена: {exc}")
                continue
            overrides[name.lower()] = proxy
    return overrides


def load_config_from_txt(path: str | None = None, *, quiet: bool = False) -> list[dict]:
    config_path = path or os.environ.get("SENDERX_CONFIG", CONFIG_PATH)
    if not os.path.exists(config_path):
        raise ConfigError(
            f"Файл {config_path} не найден. Скопируйте example_config.txt в config.txt "
            "и впишите api_id/api_hash с https://my.telegram.org"
        )

    accounts: list[dict] = []
    with open(config_path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                accounts.append(parse_account(line))
            except ValueError as exc:
                print(f"⚠️ строка {lineno} пропущена: {exc}")

    names = [a["session_name"] for a in accounts]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ConfigError("повторяются session_name: " + ", ".join(sorted(duplicates)))

    # прокси из отдельного файла главнее, чем из config.txt
    overrides = load_proxies(quiet=quiet)
    for acc in accounts:
        key = acc["session_name"].lower()
        if key in overrides:
            acc["proxy"] = overrides[key]
            acc["proxy_source"] = "proxies.txt"
        else:
            acc["proxy_source"] = "config.txt" if acc.get("proxy") else ""

    if not quiet:
        for acc in accounts:
            print(
                f"  • {acc['session_name']}: api_id={acc['api_id']} "
                f"api_hash={mask(acc['api_hash'])} имя={acc['my_name']} "
                f"лимит={acc['max_per_account']} пауза={acc['min_delay']}-{acc['max_delay']}с"
            )
    return accounts
