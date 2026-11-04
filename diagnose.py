"""Диагностика канала до Telegram: прокси, HTTPS-фронт и — главное — сами DC.

Запуск:  python diagnose.py            (берёт первый аккаунт из config.txt)
         python diagnose.py --config other.txt

Разница, которую часто пропускают: `api.telegram.org:443` — это HTTPS с SNI,
и он может открываться через прокси, который НЕ пропускает сырой MTProto к
дата-центрам. Тогда connect() в Telethon падает, хотя «интернет есть».
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import time

from config_loader import load_config_from_txt
from io_utils import force_utf8
from proxy_config import describe, parse_proxy

DCS = [
    ("DC4 149.154.167.51:443", "149.154.167.51", 443),
    ("DC4 149.154.167.51:80", "149.154.167.51", 80),
    ("DC4 149.154.167.51:5222", "149.154.167.51", 5222),
    ("DC4b 149.154.167.91:443", "149.154.167.91", 443),
    ("DC1 149.154.175.53:443", "149.154.175.53", 443),
    ("DC5 91.108.56.130:443", "91.108.56.130", 443),
]
FRONTS = [("api.telegram.org", 443), ("web.telegram.org", 443), ("example.com", 443)]


class Socks5:
    """Минимальный SOCKS5-клиент: greeting → (auth) → CONNECT."""

    def __init__(self, host: str, port: int, user: str | None, password: str | None, timeout: float = 10):
        self.host, self.port, self.user, self.password, self.timeout = host, port, user, password, timeout

    def connect(self, dst: str, dport: int) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        methods = b"\x05\x02\x00\x02" if self.user else b"\x05\x01\x00"
        sock.sendall(methods)
        _, method = sock.recv(2)
        if method == 0x02:
            if not self.user:
                raise RuntimeError("прокси требует логин/пароль, а они не заданы")
            u, p = self.user.encode(), (self.password or "").encode()
            sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
            if sock.recv(2)[1] != 0x00:
                raise RuntimeError("SOCKS5: неверный логин или пароль")
        elif method != 0x00:
            raise RuntimeError(f"SOCKS5: сервер не принял ни один метод (0x{method:02x})")
        try:
            ip = socket.inet_aton(dst)
            addr = b"\x01" + ip
        except OSError:
            addr = b"\x03" + bytes([len(dst)]) + dst.encode()
        sock.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", dport))
        reply = sock.recv(4)
        if not reply or reply[1] != 0x00:
            codes = {1: "general failure", 2: "not allowed by ruleset", 3: "network unreachable",
                     4: "host unreachable", 5: "connection refused", 6: "TTL expired"}
            raise RuntimeError("SOCKS5 CONNECT: " + codes.get(reply[1] if reply else 1, "нет ответа"))
        return sock


def direct(dst: str, dport: int, timeout: float = 6) -> socket.socket:
    return socket.create_connection((dst, dport), timeout=timeout)


def main() -> int:
    force_utf8()
    ap = argparse.ArgumentParser(description="Проверка канала до Telegram DC")
    ap.add_argument("--config")
    args = ap.parse_args()

    accounts = load_config_from_txt(args.config, quiet=True)
    if not accounts:
        print("❌ нет аккаунтов в конфиге")
        return 2
    acc = accounts[0]
    proxy_raw = acc.get("proxy") or ""
    proxy = parse_proxy(proxy_raw)
    print(f"Прокси: {describe(proxy)}")

    opener = None
    if proxy is None:
        opener = lambda d, p: direct(d, p)  # noqa: E731
    elif proxy[0] == "mtproxy":
        print("MTProxy: туннель проверяется только реальным подключением Telethon — запустите main.py --check-net")
        return 0
    else:
        opener = Socks5(proxy[1], proxy[2], proxy[4], proxy[5]).connect  # type: ignore[union-attr]

    print("\n-- HTTPS-фронты (SNI, тут прокси обычно работает) --")
    front_ok = 0
    for dst, port in FRONTS:
        started = time.time()
        try:
            sock = opener(dst, port)
            sock.close()
            front_ok += 1
            print(f"  ✓ {dst}:{port} — {round((time.time() - started) * 1000)} мс")
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {dst}:{port} — {type(exc).__name__}: {exc}")

    print("\n-- Дата-центры MTProto (по ним и идёт connect) --")
    dc_ok = 0
    for label, dst, port in DCS:
        started = time.time()
        try:
            sock = opener(dst, port)
            sock.close()
            dc_ok += 1
            print(f"  ✓ {label} — {round((time.time() - started) * 1000)} мс")
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {label} — {type(exc).__name__}: {exc}")

    print("\n" + "=" * 52)
    if dc_ok:
        print(f"Итог: DC доступны ({dc_ok} из {len(DCS)}) — канал годится для Telethon")
        return 0
    if front_ok:
        print("Итог: прокси пускает только доменный HTTPS, MTProto к DC не проходит.")
        print("      Нужен MTProxy (секрет из @MTProxybot) или SOCKS5, где открыты 149.154.*")
        return 1
    print("Итог: канал не работает вообще — проверьте прокси и логин/пароль")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
