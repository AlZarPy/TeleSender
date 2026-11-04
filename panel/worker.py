"""Воркер «Почтамта»: берёт кампанию из БД и отправляет через пул аккаунтов.

Запускается отдельным процессом, чтобы панель можно было перезапускать
независимо:  python -m panel.worker        (цикл)
             python -m panel.worker --once (одна отправка и выход — для тестов)

Правила, которые здесь живут:
  • квота на аккаунт в сутки (accounts.daily_limit), берётся из БД;
  • ротация: следующим берём аккаунт с наибольшим остатком квоты;
  • FloodWait → аккаунт уходит в паузу, получатель остаётся в очереди;
  • окно отправки из кампании (часы), паузы со случайным разбросом;
  • себе не пишем, если в кампании не разрешено явно.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient

from config_loader import load_config_from_txt
from io_utils import force_utf8
from proxy_config import describe, parse_proxy
from sender import FloodDetected, send_one

from panel import brand, db, message, replies


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


class Pool:
    """Клиенты Telethon по одному на аккаунт, поднимаются лениво."""

    def __init__(self, accounts: list[dict]):
        self.accounts = {a["session_name"]: a for a in accounts}
        self.clients: dict[str, TelegramClient] = {}
        self.me_ids: dict[str, int | None] = {}

    async def get(self, name: str) -> TelegramClient:
        if name in self.clients:
            return self.clients[name]
        acc = self.accounts[name]
        proxy = parse_proxy(acc.get("proxy"))
        client = TelegramClient(name, acc["api_id"], acc["api_hash"], proxy=proxy)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise PermissionError(f"{name}: сессия не авторизована")
        me = await client.get_me()
        self.clients[name] = client
        self.me_ids[name] = getattr(me, "id", None)
        log(f"{name}: подключён как @{getattr(me, 'username', '?')} ({describe(proxy)})")
        return client

    async def close_all(self) -> None:
        for name, client in list(self.clients.items()):
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.clients.pop(name, None)


def account_capacity(name: str, limit: int) -> int:
    """Сколько ещё можно отправить этим аккаунтом сегодня."""
    row = db.q1("""SELECT COUNT(*) c FROM sends
                   WHERE account=? AND ok=1 AND date(ts)=date('now')""", (name,))
    return max(0, limit - (row["c"] if row else 0))


def pick_account(accounts: list[dict], hour_limit: int = 10) -> dict | None:
    now = time.time()
    usable = []
    for acc in accounts:
        if acc["status"] != "active":
            continue
        if acc["paused_until"] > now:
            continue
        if hour_limit and db.hour_sent(acc["session_name"]) >= hour_limit:
            continue
        left = account_capacity(acc["session_name"], acc.get("effective_limit") or acc["daily_limit"])
        if left > 0:
            usable.append((left, acc))
    if not usable:
        return None
    usable.sort(key=lambda pair: pair[0], reverse=True)
    return usable[0][1]


def in_window(campaign: dict) -> bool:
    hour = datetime.now().hour
    start, end = campaign["window_start"], campaign["window_end"]
    return start <= hour < end if start <= end else (hour >= start or hour < end)


async def run_once(pool: Pool, campaign: dict, accounts: list[dict]) -> str:
    """Одна отправка. Возвращает: sent | skipped | retry | wait | done."""
    target = db.next_target(campaign["id"])
    if target is None:
        return "done"

    # Защита от повторных сообщений: одному и тому же человеку — один раз,
    # если в кампании не разрешено обратное. Исключение — те, кто ответил:
    # им писать повторно нормально, это уже диалог, а не спам.
    if (not campaign.get("allow_repeat")
            and db.sent_before(target["username"])
            and target["username"].lower() not in db.replied_usernames()):
        db.close_target(campaign["id"], target["recipient_id"], "skipped", "already")
        db.event("skipped_repeat", "", f"@{target['username']} уже получал сообщение")
        log(f"↩️ @{target['username']} уже получал — пропускаю")
        return "skipped"

    acc = pick_account(accounts, campaign.get("hour_limit") or 10)
    if acc is None:
        db.heartbeat("waiting", "нет аккаунта со свободной квотой (сутки или час)")
        return "wait"

    name = acc["session_name"]
    try:
        client = await pool.get(name)
    except PermissionError as exc:
        db.set_account(name, status="paused", paused_until=time.time() + 3600)
        db.event("account_unusable", name, str(exc))
        log(f"⛔ {exc} — аккаунт на паузе")
        return "retry"

    intro = campaign.get("intro") or ""
    template_body = campaign["template"]
    sender_name = acc["my_name"]

    def compose(his_name: str) -> str:
        return message.render(template_body, intro, sender_name, his_name)

    me_id = None if campaign["allow_self"] else pool.me_ids.get(name)
    try:
        result = await send_one(client, target["username"], sender_name,
                                template_body, me_id, template_fn=compose)
    except FloodDetected as exc:
        until = time.time() + exc.seconds
        db.set_account(name, paused_until=until)
        db.event("flood", name, f"пауза {exc.seconds}с на @{target['username']}")
        log(f"⏳ {name}: flood wait {exc.seconds}с — адресат уйдёт с другого аккаунта")
        return "retry"

    db.log_send(campaign["id"], target["username"], name, result.ok, result.reason)
    db.close_target(campaign["id"], target["recipient_id"],
                    "sent" if result.ok else "failed", result.reason, name)
    if result.ok:
        log(f"✅ {name} → @{target['username']}")
    else:
        log(f"❌ {name} → @{target['username']}: {brand.reason_label(result.reason)}")
    return "sent"


async def main_async(args) -> int:
    db.init()
    accounts_cfg = load_config_from_txt(args.config, quiet=True)
    if not accounts_cfg:
        log("нет аккаунтов в конфиге")
        return 2
    db.sync_accounts([a["session_name"] for a in accounts_cfg])

    imported = db.import_sent_jsonl()
    if imported:
        log(f"подтянул историю CLI: {imported} отправок")

    pool = Pool(accounts_cfg)
    log(f"аккаунтов в пуле: {len(accounts_cfg)}")
    last_reply_scan = 0.0
    try:
        while True:
            # ответы ищем редко: раз в 10 минут, чтобы не тратить лимиты
            if not args.once and time.time() - last_reply_scan > 600:
                last_reply_scan = time.time()
                try:
                    fresh = await replies.scan_pool(pool, db.accounts_with_config(accounts_cfg))
                    if fresh:
                        log(f"💬 ответили: {', '.join('@' + u for u in fresh)}")
                except Exception as exc:  # noqa: BLE001
                    db.event("reply_scan_error", "", str(exc)[:120])

            campaign = db.q1("SELECT * FROM campaigns WHERE status='running' ORDER BY id LIMIT 1")
            if campaign is None:
                db.heartbeat("idle", "нет запущенных кампаний")
                if args.once:
                    return 0
                await asyncio.sleep(5)
                continue

            campaign = dict(campaign)
            stats = db.campaign_stats(campaign["id"])
            if stats["pending"] == 0:
                db.set_campaign_status(campaign["id"], "done")
                db.event("campaign_done", "", f"кампания «{campaign['name']}» завершена")
                log(f"🏁 кампания «{campaign['name']}» завершена")
                if args.once:
                    return 0
                continue

            if not in_window(campaign):
                db.heartbeat("waiting", f"вне окна {campaign['window_start']}:00–{campaign['window_end']}:00")
                if args.once:
                    print("outside_window")
                    return 0
                await asyncio.sleep(120)
                continue

            accounts = db.accounts_with_config(accounts_cfg)
            db.heartbeat("working", f"кампания «{campaign['name']}»: {stats['pending']} в очереди")
            state = await run_once(pool, campaign, accounts)

            if args.once:
                print(f"once:{state}")
                return 0

            if state == "wait":
                await asyncio.sleep(60)
            elif state == "retry":
                await asyncio.sleep(5)
            elif state == "skipped":
                await asyncio.sleep(1)
            else:
                delay = random.randint(campaign["min_delay"], campaign["max_delay"])
                log(f"   пауза {delay} с")
                await asyncio.sleep(delay)
    finally:
        await pool.close_all()
        db.heartbeat("stopped", "воркер остановлен")


def single_instance_lock():
    """Не даёт запустить второй воркер: два процесса отправляли бы дубли."""
    try:
        import msvcrt
    except ImportError:  # не Windows — блокировку не делаем
        return object()
    path = Path(__file__).resolve().parent / "worker.lock"
    handle = open(path, "a+")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def main() -> int:
    force_utf8()
    parser = argparse.ArgumentParser(description="Воркер рассылки «Почтамт»")
    parser.add_argument("--once", action="store_true", help="одна отправка и выход (тест)")
    parser.add_argument("--config", default=None, help="файл аккаунтов")
    args = parser.parse_args()

    lock = None
    if not args.once:
        lock = single_instance_lock()
        if lock is None:
            log("воркер уже запущен — второй экземпляр не нужен")
            return 1
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log("остановлен пользователем")
        return 0
    finally:
        if lock is not None and hasattr(lock, "close"):
            lock.close()


if __name__ == "__main__":
    sys.exit(main())
