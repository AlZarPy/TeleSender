"""Проверка базы перед рассылкой: кто живой, кому можно писать, кого уже трогали.

Читает xlsx/csv, вытаскивает @username из любой колонки (в том числе из ссылок
t.me/...), затем проверяет каждого живым клиентом: аккаунт существует, это не бот,
не удалён. Сообщений не отправляет.

Запуск:
    python tools/check_base.py база.xlsx --account pechkin01 --limit 360
Итог: base_checked.csv (username, name, status) и печать сводки.
"""
from __future__ import annotations

import asyncio
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_loader import load_config_from_txt  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402
from telethon import TelegramClient  # noqa: E402
from telethon.tl.functions.contacts import ResolveUsernameRequest  # noqa: E402

USERNAME = re.compile(r"(?:t\.me/|@)([A-Za-z][A-Za-z0-9_]{3,31})")
BARE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def read_rows(path: Path) -> list[list[str]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return [[c or "" for c in row] for row in csv.reader(fh)]
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    rows: list[list[str]] = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            rows.append([str(c) if c is not None else "" for c in row])
    return rows


def extract(rows: list[list[str]]) -> list[tuple[str, str]]:
    """[(username, имя или пусто)] — без повторов, в порядке появления."""
    out: dict[str, str] = {}
    for row in rows:
        for cell in row:
            cell = (cell or "").strip()
            if not cell:
                continue
            found = USERNAME.findall(cell)
            if not found and BARE.match(cell):
                found = [cell]
            for name in found:
                key = name.lower()
                if key in ("joinchat", "share", "addstickers", "proxy"):
                    continue
                label = next((c.strip() for c in row if c.strip() and c.strip() != cell
                              and not c.strip().startswith("@")), "")
                out.setdefault(key, label[:60])
    return list(out.items())


async def check(names: list[tuple[str, str]], account: str, limit: int) -> list[dict]:
    cfg = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    px = {}
    for line in Path("proxies.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ";" in line:
            n, u = line.split(";", 1)
            px[n.strip()] = u.strip()
    k, host, port, rdns, user, pwd = parse_proxy(px[account])
    client = TelegramClient(account, cfg[account]["api_id"], cfg[account]["api_hash"],
                            proxy=("socks5", host, int(port), rdns, user, pwd),
                            connection_retries=2, request_retries=2, timeout=40)
    await client.connect()
    results: list[dict] = []
    for username, label in names[:limit]:
        row = {"username": username, "name": label, "status": ""}
        try:
            found = await client(ResolveUsernameRequest(username))
            user = next((u for u in found.users if getattr(u, "username", "").lower() == username), None)
            if user is None:
                row["status"] = "нет такого"
            elif getattr(user, "bot", False):
                row["status"] = "бот"
            elif getattr(user, "deleted", False):
                row["status"] = "удалён"
            else:
                row["status"] = "ок"
                row["name"] = label or " ".join(
                    x for x in (user.first_name, user.last_name) if x)[:60]
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            row["status"] = ("нет такого" if "NoUser" in name or "UsernameNotOccupied" in name
                             else "бот" if "bot" in str(exc).lower()
                             else f"ошибка: {name}")
        results.append(row)
        await asyncio.sleep(0.7)   # не частим запросами
    await client.disconnect()
    return results


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("укажите файл базы: python tools/check_base.py база.xlsx [--account pechkin01]")
        return 2
    path = Path(args[0])
    account = args[args.index("--account") + 1] if "--account" in args else "pechkin01"
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 360
    if not path.exists():
        print("файл не найден:", path)
        return 2

    names = extract(read_rows(path))
    print(f"в файле: контактов {len(names)}")

    results = asyncio.run(check(names, account, limit))
    ok = [r for r in results if r["status"] == "ок"]
    bad = [r for r in results if r["status"] != "ок"]
    counts: dict[str, int] = {}
    for r in bad:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    out = path.parent / "base_checked.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["username", "name", "status"])
        w.writeheader()
        w.writerows(ok)
    print(f"живых: {len(ok)} | отсеяно: {len(bad)} ({counts})")
    print("готовый список:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
