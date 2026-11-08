"""Определяет DC по одному ключу авторизации и сразу собирает сессию.

Некоторые продавцы отдают ключи без указания дата-центра. Ключ сам по себе
не говорит, к какому DC он относится, поэтому пробуем по очереди 1–5:
на верном DC Telegram подтверждает авторизацию.

Запуск:
    python tools/probe_keys.py --keys "путь/к/keys.txt" --out "путь/к/sessions"
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient  # noqa: E402
from telethon.crypto import AuthKey  # noqa: E402
from telethon.sessions import SQLiteSession  # noqa: E402

from config_loader import load_config_from_txt  # noqa: E402

DC = {
    1: ("149.154.175.53", 443),
    2: ("149.154.167.51", 443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.91", 443),
    5: ("91.108.56.130", 443),
}


def build(path: Path, key_hex: str, dc_id: int) -> None:
    if path.exists():
        path.unlink()
    session = SQLiteSession(str(path.with_suffix("")))
    ip, port = DC[dc_id]
    session.set_dc(dc_id, ip, port)
    session.auth_key = AuthKey(bytes.fromhex(key_hex))
    session.save()
    session.close()


async def try_dc(key_hex: str, dc_id: int, api_id: int, api_hash: str, probe: Path):
    build(probe, key_hex, dc_id)
    client = TelegramClient(str(probe.with_suffix("")), api_id, api_hash,
                            connection_retries=1, timeout=15)
    try:
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            return me
        return None
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def main_async(keys_file: Path, out_dir: Path) -> int:
    raw = keys_file.read_text(encoding="utf-8").replace("\n", ",")
    keys = [part.strip() for part in raw.split(",") if len(part.strip()) > 100]

    cfg = load_config_from_txt(None, quiet=True)[0]
    api_id, api_hash = cfg["api_id"], cfg["api_hash"]
    out_dir.mkdir(parents=True, exist_ok=True)
    probe = out_dir / "_probe"

    print(f"ключей в файле: {len(keys)}\n")
    found = []
    for index, key in enumerate(keys, 1):
        if len(key) % 2 or not all(c in "0123456789abcdefABCDEF" for c in key):
            print(f"  {index}: не hex — пропуск")
            continue
        print(f"  {index}: ключ {len(key) // 2} байт, ищу DC…", end=" ", flush=True)
        me = None
        dc_used = 0
        for dc_id in DC:
            me = await try_dc(key, dc_id, api_id, api_hash, probe)
            if me is not None:
                dc_used = dc_id
                break
        if me is None:
            print("не сработал ни на одном DC")
            continue
        name = str(me.phone or me.id)
        target = out_dir / f"{name}.session"
        build(target, key, dc_used)
        print(f"DC{dc_used} · {me.first_name or ''} +{me.phone}")
        found.append({"file": target, "phone": me.phone, "id": me.id,
                      "name": me.first_name or "", "dc": dc_used})

    (out_dir / "_probe.session").unlink(missing_ok=True)
    print(f"\nсобрано сессий: {len(found)} из {len(keys)}")
    seen: dict[int, str] = {}
    for rec in found:
        if rec["id"] in seen:
            print(f"  дубль: {rec['file'].name} = {seen[rec['id']]}")
        seen[rec["id"]] = rec["file"].name
    print(f"уникальных аккаунтов: {len(seen)}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ключи без DC → сессии")
    ap.add_argument("--keys", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main_async(Path(args.keys), Path(args.out))))
