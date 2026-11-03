"""Прокси для Telegram: часть провайдеров/стран блокирует DC по TCP.

Поддерживаемые схемы в поле `proxy=` конфига:

    proxy=socks5://host:1080
    proxy=socks5://user:pass@host:1080
    proxy=mtproxy://host:443/ee00deadbeef...        # секрет из @MTProxybot

Пустая строка/отсутствие поля — прямое подключение.
"""
from __future__ import annotations

from urllib.parse import unquote, urlparse

SUPPORTED = ("socks5", "socks5h", "mtproxy", "http")


def parse_proxy(value: str | None):
    """Возвращает аргумент `proxy=` для TelegramClient или None."""
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    parsed = urlparse(raw if "://" in raw else "socks5://" + raw)
    scheme = parsed.scheme.lower()
    if scheme not in SUPPORTED:
        raise ValueError(f"неизвестная схема прокси {scheme!r}, поддерживаются: {', '.join(SUPPORTED)}")
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"в прокси {raw!r} нет хоста или порта")

    if scheme == "mtproxy":
        secret = unquote(parsed.path.lstrip("/")) or parsed.query
        if not secret:
            raise ValueError("для mtproxy нужен секрет: mtproxy://host:port/<secret>")
        return ("mtproxy", parsed.hostname, int(parsed.port), secret)

    try:
        from python_socks import ProxyType
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError("нужен пакет python-socks: pip install 'python-socks[asyncio]'") from exc

    ptype = ProxyType.SOCKS5 if scheme.startswith("socks5") else ProxyType.HTTP
    user = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    # rdns=True — имя резолвит прокси, а не локальный DNS (важно при отравленном DNS)
    return (ptype, parsed.hostname, int(parsed.port), True, user, password)


def describe(proxy) -> str:
    if proxy is None:
        return "напрямую"
    if proxy[0] == "mtproxy":
        return f"mtproxy {proxy[1]}:{proxy[2]}"
    return f"{str(proxy[0]).split('.')[-1].lower()} {proxy[1]}:{proxy[2]}"
