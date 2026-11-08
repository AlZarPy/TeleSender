"""Проверка аккаунтов через @SpamBot: живой ли, есть ли ограничения.

Зачем: продавец пишет «без спамблока», но проверяется это только официальным способом.
@SpamBot отвечает либо «Good news, no limits», либо перечисляет ограничения.

Запуск:
    python tools/check_spam.py --sessions "путь/к/sessions"
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import load_config_from_txt  # noqa: E402
from telethon import TelegramClient  # noqa: E402


async def check(path: Path, api_id: int, api_hash: str) -> dict:
    client = TelegramClient(str(path.with_suffix("")), api_id, api_hash,
                            connection_retries=2, timeout=25)
    result = {"session": path.name, "ok": False, "who": "", "verdict": ""}
    try:
        await client.connect()
        if not await client.is_user_authorized():
            result["verdict"] = "не авторизован"
            return result
        me = await client.get_me()
        result["ok"] = True
        result["who"] = f"@{me.username}" if me.username else (me.first_name or str(me.id))
        await client.send_message("SpamBot", "/start")
        await asyncio.sleep(4)
        messages = await client.get_messages("SpamBot", limit=1)
        text = (messages[0].text if messages else "") or ""
        low = text.lower()
        if "good news" in low or "no limits" in low:
            result["verdict"] = "БЕЗ ОГРАНИЧЕНИЙ"
        elif "limited" in low or "restricted" in low or "ограничен" in low:
            result["verdict"] = "ЕСТЬ ОГРАНИЧЕНИЯ — в возврат"
        else:
            result["verdict"] = text.replace("\n", " ")[:120] or "ответ не разобран"
    except Exception as exc:  # noqa: BLE001
        result["verdict"] = f"ошибка: {str(exc)[:80]}"
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return result


async def main_async(folder: Path) -> int:
    from panel import db as panel_db

    alive, _ = panel_db.worker_alive()
    if alive:
        print("воркер держит сессии — сначала остановите его")
        return 3
    config = load_config_from_txt(None, quiet=True)
    api_id, api_hash = config[0]["api_id"], config[0]["api_hash"]
    sessions = sorted(folder.glob("*.session"))
    if not sessions:
        print(f"в {folder} нет сессий")
        return 2

    clean, dirty = 0, 0
    for path in sessions:
        res = await check(path, api_id, api_hash)
        print(f"{res['session']:24} {res['who'][:26]:26} {res['verdict']}")
        if res["verdict"] == "БЕЗ ОГРАНИЧЕНИЙ":
            clean += 1
        else:
            dirty += 1
    print(f"\nчистых: {clean} · с проблемами: {dirty}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Проверка через @SpamBot")
    ap.add_argument("--sessions", required=True)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main_async(Path(args.sessions))))
