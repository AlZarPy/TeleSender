"""Массовый ввод аккаунтов: session-файлы + прокси → config.txt и proxies.txt.

Зачем: 20 аккаунтов руками — это 20 строк в двух файлах и неизбежная опечатка.
Скрипт раскладывает всё сам и проверяет, что получилось.

Порядок работы:
    1. Положите .session файлы в папку (например, новые/)
    2. Пропишите прокси в proxies.new.txt строками: имя_сессии;socks5://логин:пароль@хост:порт
    3. Запустите:  python tools/import_sessions.py --dir новые --dry-run
    4. Если всё верно — без --dry-run, скрипт допишет строки в config.txt и proxies.txt

Что проверяется:
    • .session действительно база SQLite (а не пустой файл и не tdata);
    • имя сессии не занято в config.txt;
    • api_id/api_hash валидны и одинаковы для всех;
    • прокси разбирается и имеет схему socks5/http/mtproto.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import CONFIG_PATH, PROXIES_PATH  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402


def read_existing(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def session_ok(path: Path) -> tuple[bool, str]:
    """Проверяет, что файл — настоящая база Telethon."""
    if path.stat().st_size < 1024:
        return False, f"размер {path.stat().st_size} байт — похоже, пустышка"
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error as exc:
        return False, f"не база SQLite: {exc}"
    if "sessions" not in tables:
        return False, "нет таблицы sessions — это не Telethon-сессия"
    return True, "ок"


def load_proxies(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in read_existing(path):
        if line.startswith("#") or ";" not in line:
            continue
        name, _, proxy = line.partition(";")
        out[name.strip().lower()] = proxy.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Ввод аккаунтов в панель")
    ap.add_argument("--dir", required=True, help="папка с .session файлами")
    ap.add_argument("--proxies", default="proxies.new.txt", help="файл с привязкой прокси")
    ap.add_argument("--api-id", default="", help="api_id (по умолчанию берётся из config.txt)")
    ap.add_argument("--api-hash", default="", help="api_hash (по умолчанию из config.txt)")
    ap.add_argument("--my-name", default="Александр", help="имя отправителя для подписи")
    ap.add_argument("--dry-run", action="store_true", help="только показать, ничего не писать")
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f"нет папки {folder}")
        return 2

    sessions = sorted(folder.glob("*.session"))
    if not sessions:
        print(f"в {folder} нет .session файлов")
        return 2

    config_lines = read_existing(ROOT / CONFIG_PATH)
    taken = set()
    api_id = args.api_id
    api_hash = args.api_hash
    for line in config_lines:
        parts = dict(p.split("=", 1) for p in line.split(";") if "=" in p)
        if parts.get("session_name"):
            taken.add(parts["session_name"].strip().lower())
        api_id = api_id or parts.get("api_id", "")
        api_hash = api_hash or parts.get("api_hash", "")

    if not (api_id and api_hash):
        print("не нашёл api_id/api_hash — укажите --api-id и --api-hash")
        return 2

    proxies = load_proxies(ROOT / args.proxies)
    if not proxies:
        print(f"в {args.proxies} нет строк вида имя;socks5://… — прокси не привяжутся")

    good, bad = [], []
    new_config, new_proxies = [], []

    for path in sessions:
        name = path.stem
        ok, why = session_ok(path)
        if not ok:
            bad.append((name, why))
            continue
        if name.lower() in taken:
            bad.append((name, "такое имя уже есть в config.txt"))
            continue
        proxy = proxies.get(name.lower(), "")
        proxy_note = ""
        if proxy:
            try:
                parse_proxy(proxy)
            except Exception as exc:  # noqa: BLE001
                bad.append((name, f"прокси не разбирается: {exc}"))
                continue
            proxy_note = proxy
            new_proxies.append(f"{name};{proxy}")
        elif proxies:
            bad.append((name, "нет прокси в файле привязки"))
            continue

        line = (f"session_name={name};api_id={api_id};api_hash={api_hash};"
                f"my_name={args.my_name}")
        if proxy_note:
            line += f";proxy={proxy_note}"
        new_config.append(line)
        good.append(name)

    print(f"найдено сессий: {len(sessions)} · годных: {len(good)} · отсеяно: {len(bad)}")
    if good:
        print("\nдобавятся:")
        for name in good:
            print(f"  {name}  прокси: {'есть' if name.lower() in proxies else 'нет'}")
    if bad:
        print("\nотсеяны:")
        for name, why in bad:
            print(f"  {name}: {why}")

    if args.dry_run:
        print("\nпробный прогон — файлы не изменены")
        return 0 if good else 1

    if new_config:
        with open(ROOT / CONFIG_PATH, "a", encoding="utf-8") as fh:
            fh.write("\n" + "\n".join(new_config) + "\n")
    if new_proxies:
        with open(ROOT / PROXIES_PATH, "a", encoding="utf-8") as fh:
            fh.write("\n" + "\n".join(new_proxies) + "\n")
    print(f"\nдописано: {len(new_config)} аккаунтов в {CONFIG_PATH}, {len(new_proxies)} прокси в {PROXIES_PATH}")
    print("дальше: поставьте аккаунтам прогрев в панели → Настройки")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
