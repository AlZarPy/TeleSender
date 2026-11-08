"""Превращает купленные ключи (auth_key) в .session файлы, понятные панели.

Поддерживаются два формата, которые встречаются у продавцов:

1. Текстовый: строка вида `<hex 256 байт>:<dc_id>` — по строке на аккаунт.
2. JSON: {"auth_key": "<hex>", "dc_id": 1, "phone": "...", "app_id": 2496, ...}.

Что делает: создаёт рядом папку sessions/ с файлами `<номер>.session`, где номер
берётся из телефона или user_id. Панель потом читает их как обычные сессии.

Запуск:
    python tools/import_authkeys.py --dir "C:/Users/User/6_Программы/Downloads/Акк ТГ"
    python tools/import_authkeys.py --dir ... --check      # ещё и проверить вход
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telethon.crypto import AuthKey  # noqa: E402
from telethon.sessions import SQLiteSession  # noqa: E402

# адреса дата-центров Telegram: нужны, чтобы сессия знала, куда подключаться
DC = {
    1: ("149.154.175.53", 443),
    2: ("149.154.167.51", 443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.91", 443),
    5: ("91.108.56.130", 443),
}

HEX_LINE = re.compile(r"^([0-9a-fA-F]{300,})\s*:\s*(\d)\s*$")


def make_session(path: Path, key_hex: str, dc_id: int) -> bool:
    """Создаёт .session с готовым ключом. Возвращает True, если всё получилось."""
    try:
        key = AuthKey(bytes.fromhex(key_hex))
    except ValueError:
        return False
    if dc_id not in DC:
        return False
    if path.exists():
        path.unlink()
    session = SQLiteSession(str(path.with_suffix("")))
    ip, port = DC[dc_id]
    session.set_dc(dc_id, ip, port)
    session.auth_key = key
    session.save()
    session.close()
    return True


def read_txt(path: Path) -> list[dict]:
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        match = HEX_LINE.match(line)
        if not match:
            out.append({"source": f"{path.name}:{number}", "ok": False,
                        "why": "не похоже на ключ: ожидалось hex:dc"})
            continue
        out.append({"source": f"{path.name}:{number}", "key": match.group(1),
                    "dc": int(match.group(2)), "ok": True})
    return out


def read_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    key = data.get("auth_key") or ""
    dc = data.get("dc_id")
    if not key or not dc:
        return [{"source": path.name, "ok": False,
                 "why": "в файле нет auth_key/dc_id — только данные профиля, входа не будет",
                 "phone": data.get("phone", "")}]
    return [{"source": path.name, "ok": True, "key": key, "dc": int(dc),
             "phone": str(data.get("phone", "")), "user_id": str(data.get("user_id") or data.get("id") or ""),
             "app_id": data.get("app_id"), "app_hash": data.get("app_hash"),
             "proxy": data.get("proxy"), "twofa": data.get("twoFA")}]


def main() -> int:
    ap = argparse.ArgumentParser(description="Ключи → .session файлы")
    ap.add_argument("--dir", required=True, help="папка с купленными файлами")
    ap.add_argument("--out", default="", help="куда сложить сессии (по умолчанию <dir>/sessions)")
    ap.add_argument("--check", action="store_true", help="проверить вход по каждой сессии")
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f"нет папки {folder}")
        return 2

    out_dir = Path(args.out) if args.out else folder / "sessions"
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() == ".txt":
            records += read_txt(path)
        elif path.suffix.lower() == ".json":
            records += read_json(path)

    good, bad = [], []
    for index, rec in enumerate(records, 1):
        if not rec.get("ok"):
            bad.append(rec)
            continue
        name = rec.get("phone") or rec.get("user_id") or f"acc{index}"
        name = re.sub(r"\D", "", name) or f"acc{index}"
        session_path = out_dir / f"{name}.session"
        if make_session(session_path, rec["key"], rec["dc"]):
            rec["session"] = session_path
            good.append(rec)
        else:
            rec["why"] = "ключ или DC не разобрались"
            bad.append(rec)

    print(f"всего записей: {len(records)} · сессий создано: {len(good)} · отсеяно: {len(bad)}")
    for rec in good:
        note = f" · телефон +{rec['phone']}" if rec.get("phone") else ""
        print(f"  ✓ {rec['session'].name}: DC{rec['dc']}, {len(rec['key']) // 2} байт{note} · {rec['source']}")
    for rec in bad:
        print(f"  ✕ {rec['source']}: {rec.get('why')}")

    if good and args.check:
        print("\nпроверка входа:")
        import asyncio

        from config_loader import load_config_from_txt
        from telethon import TelegramClient

        config = load_config_from_txt(None, quiet=True)
        api_id, api_hash = config[0]["api_id"], config[0]["api_hash"]

        async def check(rec):
            client = TelegramClient(str(rec["session"].with_suffix("")), api_id, api_hash,
                                    connection_retries=2, timeout=20)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    return "не авторизован"
                me = await client.get_me()
                who = f"@{me.username}" if me.username else f"{me.first_name or ''} {me.id}"
                return f"ок · {who} · +{me.phone}" if me.phone else f"ок · {who}"
            except Exception as exc:  # noqa: BLE001
                return f"ошибка: {str(exc)[:60]}"
            finally:
                await client.disconnect()

        for rec in good:
            print(f"  {rec['session'].name}: {asyncio.run(check(rec))}")

    (out_dir / "accounts.json").write_text(
        json.dumps([{k: str(v) for k, v in rec.items() if k != "key"} for rec in records],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nсессии в {out_dir}")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
