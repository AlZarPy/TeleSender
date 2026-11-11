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
import sqlite3
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient

from config_loader import load_config_from_txt
from io_utils import force_utf8

# asyncio-задачи, которые живут дольше одной итерации цикла.
# Без сильной ссылки сборщик мусора может убить задачу до её завершения —
# именно из-за этого прогрев перепиской иногда не доходил до отправки.
_BACKGROUND: set[asyncio.Task] = set()
from proxy_config import describe, parse_proxy
from sender import FloodDetected, is_transient, send_one

ROOT = Path(__file__).resolve().parent.parent

from panel import (antispam, brand, checks, db, followup, interchat, message, notify,
                   pacing, readstatus, report, replies, unique, warmup, watchdog)


def resolve_attachment(value: str) -> str | None:
    """Вложение: URL отдаём как есть, локальный путь ищем рядом с проектом и в data."""
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        return value
    candidates = [Path(value), Path.cwd() / value, ROOT / value, ROOT / "media" / value]
    for path in candidates:
        if path.exists():
            return str(path)
    return value  # пусть Telethon скажет, что файла нет


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


BACKOFF_STEPS = (5, 15, 45, 120, 300)   # пауза после неудачных подключений
IDLE_CLOSE = 600                        # простаивающий клиент держим не дольше 10 минут


class Pool:
    """Клиенты Telethon по одному на аккаунт, поднимаются лениво.

    Две вещи, которые берегут прокси и журнал:
      • после неудачного подключения аккаунт отдыхает по нарастающей (5→300 с),
        а не долбит прокси каждые несколько секунд;
      • клиент, которым не пользовались N минут, отключается — провайдер
        держит лишь пару одновременных соединений на логин.
    """

    def __init__(self, accounts: list[dict]):
        self.accounts = {a["session_name"]: a for a in accounts}
        self.clients: dict[str, TelegramClient] = {}
        # по одному замку на аккаунт: без него параллельные задачи поднимают
        # два клиента на один файл сессии и получают AuthKeyDuplicated
        self._locks: dict[str, asyncio.Lock] = {}
        self.me_ids: dict[str, int | None] = {}
        self.failures: dict[str, int] = {}
        self.paused_until: dict[str, float] = {}
        self.last_used: dict[str, float] = {}
        # провайдер прокси ограничивает число одновременных соединений на логин
        self._connect_slot = asyncio.Semaphore(int(os.environ.get("SENDERX_CONNECT_LIMIT", "3")))

    def _wait_left(self, name: str) -> float:
        return max(0.0, self.paused_until.get(name, 0.0) - time.time())

    def _note_failure(self, name: str, exc: BaseException) -> None:
        count = self.failures.get(name, 0) + 1
        self.failures[name] = count
        delay = BACKOFF_STEPS[min(count - 1, len(BACKOFF_STEPS) - 1)]
        self.paused_until[name] = time.time() + delay
        log(f"{name}: подключение не удалось ({type(exc).__name__}), пауза {delay} с")

    def _lock(self, name: str) -> asyncio.Lock:
        lock = self._locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[name] = lock
        return lock

    async def get(self, name: str) -> TelegramClient:
        """Выдаёт клиент под замком аккаунта: один клиент на сессию."""
        async with self._lock(name):
            return await self._get_unlocked(name)

    async def _get_unlocked(self, name: str) -> TelegramClient:
        if name in self.clients:
            client = self.clients[name]
            # клиент мог отвалиться по таймауту прокси — тогда поднимаем заново
            if client.is_connected():
                self.last_used[name] = time.time()
                return client
            self.clients.pop(name, None)
            self.me_ids.pop(name, None)

        wait = self._wait_left(name)
        if wait > 0:
            raise ConnectionError(f"{name}: пауза после сбоя, ещё {int(wait)} с")

        acc = self.accounts[name]
        if not acc.get("proxy") and os.environ.get("SENDERX_ALLOW_NO_PROXY") != "1":
            raise PermissionError(f"{name}: нет прокси — подключение запрещено")
        proxy = parse_proxy(acc.get("proxy"))
        options: dict = {}
        if isinstance(proxy, tuple) and proxy and proxy[0] == "mtproxy":
            # MTProto-прокси работает только для Telegram и соединяется по своему
            # протоколу — для него нужен отдельный класс соединения Telethon
            from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

            options = {"proxy": (proxy[1], int(proxy[2]), proxy[3]),
                       "connection": ConnectionTcpMTProxyRandomizedIntermediate}
        client = TelegramClient(name, acc["api_id"], acc["api_hash"],
                                connection_retries=1, request_retries=2,
                                auto_reconnect=False, timeout=30, **options)
        try:
            # Провайдер прокси держит лишь несколько одновременных соединений на
            # один логин, поэтому подключаемся не больше чем по CONNECT_LIMIT сразу
            async with self._connect_slot:
                await client.connect()
                ok = await client.is_user_authorized()
            if not ok:
                await client.disconnect()
                raise PermissionError(f"{name}: сессия не авторизована")
            me = await client.get_me()
        except Exception as exc:  # noqa: BLE001
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            # Блокировка базы — не проблема прокси: не отправляем аккаунт в бэкофф,
            # иначе живой аккаунт простаивает 300 секунд из-за чужой записи.
            if isinstance(exc, sqlite3.OperationalError):
                raise ConnectionError(f"{name}: база занята, повтор позже") from exc
            self._note_failure(name, exc)
            raise

        self.clients[name] = client
        self.me_ids[name] = getattr(me, "id", None)
        self.last_used[name] = time.time()
        self.failures[name] = 0
        self.paused_until.pop(name, None)
        log(f"{name}: подключён как @{getattr(me, 'username', '?')} ({describe(proxy)})")
        return client

    async def close_idle(self, max_idle: int = IDLE_CLOSE) -> int:
        """Отключает клиентов, которыми давно не пользовались. Возвращает их число."""
        now = time.time()
        closed = 0
        for name, client in list(self.clients.items()):
            if now - self.last_used.get(name, 0) < max_idle:
                continue
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.clients.pop(name, None)
            self.me_ids.pop(name, None)
            closed += 1
        if closed:
            log(f"простаивающих клиентов отключено: {closed}")
        return closed

    async def reset(self, name: str) -> None:
        """Сбрасывает клиент аккаунта — нужно после сетевого сбоя."""
        async with self._lock(name):
            await self._reset_unlocked(name)

    async def _reset_unlocked(self, name: str) -> None:
        client = self.clients.pop(name, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.me_ids.pop(name, None)

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


# Аккаунт, который прямо сейчас занят отправкой. Резервируется синхронно,
# до первого await: иначе параллельные run_once берут один и тот же аккаунт
# и пишут пачкой, без интервала и сверх часового лимита.
_BUSY: set[str] = set()


def pick_account(accounts: list[dict], hour_limit: int = 10) -> dict | None:
    now = time.time()
    usable = []
    for acc in accounts:
        if acc["status"] != "active":
            continue
        if acc["paused_until"] > now:
            continue
        if acc["session_name"] in _BUSY:
            continue
        if not pacing.ready(acc["session_name"]):
            continue
        if hour_limit and db.hour_sent(acc["session_name"]) >= hour_limit:
            continue
        left = account_capacity(acc["session_name"], acc.get("effective_limit") or acc["daily_limit"])
        if left > 0:
            usable.append((left, acc))
    if not usable:
        return None
    usable.sort(key=lambda pair: pair[0], reverse=True)
    chosen = usable[0][1]
    name = chosen["session_name"]

    # резервируем: сразу занимаем аккаунт и отодвигаем его следующий слот,
    # чтобы соседняя задача не взяла его же до фактической отправки
    _BUSY.add(name)
    day = chosen.get("warmup_day")
    pacing.after_send(name, 7 if day is None else int(day))
    return chosen


def release_account(name: str) -> None:
    _BUSY.discard(name)


def in_window(campaign: dict) -> bool:
    hour = datetime.now().hour
    start, end = campaign["window_start"], campaign["window_end"]
    return start <= hour < end if start <= end else (hour >= start or hour < end)


RETRY_DELAYS = (5, 15, 45)


async def _already_delivered(client, username: str, text: str, minutes: int = 15) -> bool:
    """Дошло ли уже наше сообщение. Нужно перед повтором: таймаут не значит «не отправлено»."""
    needle = (text or "").strip()[:80]
    if not needle:
        return False
    try:
        msgs = await client.get_messages(username, limit=5)
    except Exception:  # noqa: BLE001
        return False
    now = time.time()
    for msg in msgs:
        if not getattr(msg, "out", False):
            continue
        if (msg.message or "").strip()[:80] != needle:
            continue
        if now - msg.date.timestamp() < minutes * 60:
            return True
    return False


async def send_with_retry(pool: Pool, name: str, target: dict, caller,
                          verify=None) -> object:
    """Повторяет отправку при временных сбоях, но не создаёт дублей.

    verify(client) -> bool проверяет, дошло ли сообщение. Если дошло — повтор
    не нужен: адресат уже получил текст, второй такой же = жалоба и бан.
    """
    from sender import SendResult

    last: BaseException | None = None
    for attempt, delay in enumerate((0, *RETRY_DELAYS), start=1):
        if delay:
            log(f"↻ @{target['username']}: повтор {attempt - 1} через {delay} с")
            await asyncio.sleep(delay)
            await pool.reset(name)
        client = await pool.get(name)
        try:
            return await caller(client)
        except FloodDetected:
            raise
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001
            if not is_transient(exc):
                raise
            last = exc
            if verify is not None:
                try:
                    if await verify(client):
                        log(f"✅ @{target['username']}: сообщение уже дошло, повтор не нужен")
                        return SendResult(username=target["username"], ok=True,
                                          reason="delivered_verified")
                except Exception:  # noqa: BLE001
                    pass
    raise last if last else RuntimeError("send failed")


PARALLEL = int(os.getenv("SENDERX_PARALLEL", "3"))
DRY_RUN = False


async def run_batch(pool: Pool, campaign: dict, accounts: list[dict],
                    n: int | None = None) -> list[str]:
    """Несколько отправок одновременно — по одной на аккаунт.

    Интервал внутри аккаунта не сокращается: параллельность даёт то, что разные
    аккаунты не ждут друг друга, а не то, что один пишет чаще.
    """
    n = max(1, min(n or PARALLEL, 5))
    tasks = [asyncio.create_task(run_once(pool, campaign, accounts)) for _ in range(n)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[str] = []
    for r in results:
        if isinstance(r, Exception):
            db.event("batch_error", "", f"{type(r).__name__}: {str(r)[:80]}")
            out.append("retry")
        else:
            out.append(r)
    return out



_COPY_CACHE: dict[int, dict] = {}


def copy_gate(campaign: dict) -> str | None:
    """Проверка текста кампании на признаки спама до первой отправки.

    Возвращает причину остановки или None, если текст можно отправлять.
    Скор считается один раз на кампанию: текст не меняется во время волны.
    """
    cid = campaign["id"]
    res = _COPY_CACHE.get(cid)
    if res is None:
        res = antispam.score(campaign.get("template") or "")
        _COPY_CACHE[cid] = res
        db.event("copy_score", "", f"{res['points']}:{res['verdict']}")
        log(f"текст кампании {cid}: скор {res['points']} ({res['verdict']})")

    if res["verdict"] == "спам" and not os.environ.get("SENDERX_ALLOW_SPAMMY_TEXT"):
        reason = (f"текст похож на спам, {res['points']} баллов: "
                  + "; ".join(i["code"] for i in res["issues"]))
        db.stop_campaign(cid, reason)
        db.event("copy_blocked", "", reason)
        return reason

    # ИИ-уникализация: без переписанных под аккаунты текстов волна не начинается.
    # Спинтаксис меняет порядок вставок, но слова остаются те же — этого мало.
    if not os.environ.get("SENDERX_ALLOW_PLAIN_TEXT") and db.account_texts_count(cid) == 0:
        reason = ("текст не уникализирован под аккаунты: нет переписанных вариантов "
                  "(tools/rewrite_variants.py)")
        db.stop_campaign(cid, reason)
        db.event("copy_not_unique", "", reason)
        return reason
    return None


async def run_once(pool: Pool, campaign: dict, accounts: list[dict]) -> str:
    """Одна отправка. Резервирует аккаунт и обязательно освобождает его."""
    blocked = copy_gate(campaign)
    if blocked:
        return "done"

    hour_limit = campaign.get("hour_limit")
    acc = pick_account(accounts, 10 if hour_limit is None else int(hour_limit))
    if acc is None:
        left = [db.pacing_next_at(a["session_name"]) for a in accounts
                if a["status"] == "active"]
        if left and all(t > time.time() for t in left):
            db.heartbeat("waiting", "все аккаунты держат интервал между сообщениями")
        else:
            db.heartbeat("waiting", "нет аккаунта со свободной квотой (сутки или час)")
        return "wait"

    name = acc["session_name"]
    try:
        return await _send_once(pool, campaign, accounts, acc)
    finally:
        release_account(name)


async def _send_once(pool: Pool, campaign: dict, accounts: list[dict], acc: dict) -> str:
    name = acc["session_name"]
    target = db.claim_target(campaign["id"], name)
    if target is None:
        return "done"

    # Пока адресат не получил окончательный статус, он остаётся в очереди.
    # Иначе любое исключение (флуд, сеть, блокировка базы) уносит человека навсегда.
    settled = False

    def settle(state: str, reason: str = "") -> None:
        nonlocal settled
        db.close_target(campaign["id"], target["recipient_id"], state, reason, name)
        settled = True

    try:
        return await _send_once_body(pool, campaign, accounts, acc, target, settle)
    finally:
        if not settled:
            db.close_target(campaign["id"], target["recipient_id"], "pending",
                            "returned_after_error", name)
            db.event("target_returned", name,
                     f"@{target['username']} вернулся в очередь после сбоя")


async def _send_once_body(pool: Pool, campaign: dict, accounts: list[dict], acc: dict,
                          target: dict, settle) -> str:

    # Защита от повторных сообщений: одному и тому же человеку — один раз,
    # если в кампании не разрешено обратное. Исключение — те, кто ответил:
    # им писать повторно нормально, это уже диалог, а не спам.
    if (not campaign.get("allow_repeat")
            and db.sent_before(target["username"])
            and target["username"].lower() not in db.replied_usernames()):
        settle("skipped", "already")
        db.event("skipped_repeat", "", f"@{target['username']} уже получал сообщение")
        log(f"↩️ @{target['username']} уже получал — пропускаю")
        return "skipped"

    try:
        client = await pool.get(name)
    except PermissionError as exc:
        settle("pending")
        db.set_account(name, status="paused", paused_until=time.time() + 3600)
        db.event("account_unusable", name, str(exc))
        log(f"⛔ {exc} — аккаунт на паузе")
        return "retry"

    intro = campaign.get("intro") or ""
    template_body = campaign["template"]
    sender_name = acc["my_name"]

    chosen: dict = {"variant": -1, "text": ""}

    def compose(his_name: str) -> str:
        # текст собирается один раз: иначе при повторе уйдёт другой вариант,
        # а проверка «уже доставлено» не найдёт совпадения
        if chosen["text"]:
            return chosen["text"]

        # у каждого аккаунта свой набор вариантов: два аккаунта не отправят
        # байт-в-байт одинаковый текст
        pool_names = sorted(a["session_name"] for a in accounts) or [name]
        text, vidx = unique.pick(name, campaign["id"], template_body, pool_names)
        chosen["variant"] = vidx
        body = message.personalise(text, sender_name, his_name)
        head = message.personalise(message.expand_spintax(intro), sender_name, his_name).strip() if intro else ""
        if head and not head.endswith((".", "!", "?", ":", "…")):
            head += ":"
        final = (head + "\n\n" + body).strip() if head else body.strip()
        chosen["text"] = final
        return final

    me_id = None if campaign["allow_self"] else pool.me_ids.get(name)
    attachment = resolve_attachment(campaign.get("attachment") or "")

    if DRY_RUN:
        preview = compose(target["first_name"] or "")
        settle("pending")
        log(f"[dry] {name} → @{target['username']} · {len(preview)} симв. · "
            f"{preview.splitlines()[0][:60]}")
        return "dry"

    async def _do(client):
        return await send_one(client, target["username"], sender_name, template_body, me_id,
                              template_fn=compose, attachment=attachment)

    try:
        async def _verify(client) -> bool:
            return await _already_delivered(client, target["username"], chosen.get("text", ""))

        result = await send_with_retry(pool, name, target, _do, verify=_verify)
    except FloodDetected as exc:
        until = time.time() + exc.seconds
        db.set_account(name, paused_until=until)
        db.event("flood", name, f"пауза {exc.seconds}с на @{target['username']}")
        log(f"⏳ {name}: flood wait {exc.seconds}с — адресат уйдёт с другого аккаунта")
        return "retry"  # адресат вернётся в очередь через finally

    db.log_send(campaign["id"], target["username"], name, result.ok, result.reason,
                variant=chosen["variant"], text=chosen.get("text", ""))
    if result.ok:
        unique.remember(name, campaign["id"], chosen["variant"])
    settle("sent" if result.ok else "failed", result.reason)
    db.bump_attempt(campaign["id"], result.ok)

    # Сторож: 3 отказа «закрыт для сообщений» подряд — аккаунт на паузу.
    if not result.ok:
        pause, why = watchdog.account_verdict(db.privacy_streak(name))
        if pause:
            db.set_account(name, status="paused", paused_until=time.time() + 6 * 3600)
            db.event("account_paused", name, why)
            log(f"⛔ {name} на паузе 6 ч: {why}")
            await notify.send(pool, f"⛔ {name}: {why}. Аккаунт на паузе 6 часов.", name)

    if result.ok:
        day = db.warmup_day(acc.get("warmup_start") or "")
        wait = pacing.after_send(name, day)
        log(f"✅ {name} → @{target['username']} (следующее через {wait} с)")
    else:
        log(f"❌ {name} → @{target['username']}: {brand.reason_label(result.reason)}")
    return "sent"


async def main_async(args) -> int:
    global DRY_RUN
    DRY_RUN = bool(getattr(args, "dry_run", False))
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

    def live_accounts() -> list[dict]:
        """Аккаунты, которые реально работают: есть прокси и статус active.

        Без этого фильтра прогрев и скан ответов дёргали аккаунты на паузе,
        каждый такой вызов падал с «нет прокси» и тормозил весь цикл.
        """
        return [a for a in db.accounts_with_config(accounts_cfg)
                if a.get("proxy") and a.get("status") == "active"]
    last_reply_scan = 0.0
    last_read_scan = 0.0
    last_checks_scan = 0.0
    last_warmup = 0.0
    last_chat = 0.0
    last_idle_check = 0.0
    try:
        while True:
            # раз в 5 минут отпускаем клиентов, которыми давно не пользовались
            if not args.once and time.time() - last_idle_check > 300:
                last_idle_check = time.time()
                await pool.close_idle()

            # аккаунты, у которых пауза истекла, возвращаются в работу
            db.resume_due()

            # кампании, у которых наступило время старта, выходят из черновиков
            promoted = db.promote_due()
            if promoted:
                log(f"по расписанию стартовало кампаний: {promoted}")

            # прогрев подписками: раз в 20 минут, по одной подписке на аккаунт
            if not args.once and time.time() - last_warmup > 1200:
                last_warmup = time.time()
                try:
                    db.heartbeat("warmup", "прогрев подписками")
                    # личный аккаунт владельца в прогрев не берём
                    accs_now = [a for a in live_accounts()
                                if (db.account_group(a["session_name"]) or "") != "personal"]
                    log(f"🌱 прогрев подписками: {len(accs_now)} аккаунтов")
                    actions = await asyncio.wait_for(
                        warmup.tick(pool, accs_now), timeout=600)
                    if actions:
                        log("🌱 прогрев: " + ", ".join(actions))
                except Exception as exc:  # noqa: BLE001
                    db.event("warmup_error", "", str(exc)[:120])

            # прогрев перепиской: раз в 30 минут, только между своими аккаунтами
            if not args.once and time.time() - last_chat > 1800:
                last_chat = time.time()
                try:
                    db.heartbeat("warmup", "прогрев перепиской")
                    async def chat_tick():
                        try:
                            warm_pool = [a for a in live_accounts()
                                         if (db.account_group(a["session_name"]) or "") != "personal"]
                            chats = await asyncio.wait_for(
                                interchat.tick(pool, warm_pool), timeout=1200)
                            log("💬 прогрев перепиской: " +
                                ("; ".join(chats) if chats else "пар не выбрано"))
                        except Exception as exc:  # noqa: BLE001
                            db.event("warmup_chat_error", "", str(exc)[:120])

                    _chat_task = asyncio.create_task(chat_tick())
                    # держим сильную ссылку: иначе задача может быть собрана
                    # сборщиком мусора до того, как переписка дошла до отправки
                    _BACKGROUND.add(_chat_task)
                    _chat_task.add_done_callback(_BACKGROUND.discard)
                except Exception as exc:  # noqa: BLE001
                    db.event("warmup_chat_error", "", str(exc)[:120])

            # утренняя сводка: один раз в день после 10:00
            if not args.once and datetime.now().hour >= 10:
                today = datetime.now().strftime("%Y-%m-%d")
                if db.meta_get("last_report") != today:
                    text = report.build(db.accounts_with_config(accounts_cfg))
                    if await notify.send(pool, text):
                        db.meta_set("last_report", today)
                        log("📊 сводка за сутки отправлена в Telegram")

            # Ответы ищем часто: человек не должен ждать четверть часа.
            # Интервал настраивается: SENDERX_REPLY_SCAN (сек, по умолчанию 120).
            reply_scan = int(os.environ.get("SENDERX_REPLY_SCAN", "120"))
            if not args.once and time.time() - last_reply_scan > reply_scan:
                last_reply_scan = time.time()
                try:
                    fresh = await asyncio.wait_for(
                        replies.scan_pool(pool, live_accounts()), timeout=900)
                    if fresh:
                        log(f"💬 ответили: {', '.join('@' + u for u in fresh)}")
                except Exception as exc:  # noqa: BLE001
                    db.event("reply_scan_error", "", str(exc)[:120])

            # отметки о прочтении — реже: они не влияют на скорость ответа
            read_scan = int(os.environ.get("SENDERX_READ_SCAN", "300"))
            if not args.once and time.time() - last_read_scan > read_scan:
                last_read_scan = time.time()
                try:
                    read_now = await asyncio.wait_for(
                        readstatus.tick(pool, live_accounts()), timeout=600)
                    for line in read_now:
                        log(f"👁 {line}")
                except Exception as exc:  # noqa: BLE001
                    db.event("read_scan_error", "", str(exc)[:120])

            # здоровье и @SpamBot — раз в полчаса (он и сам пропускает свежие)
            if not args.once and time.time() - last_checks_scan > 1800:
                last_checks_scan = time.time()
                try:
                    checked = await asyncio.wait_for(
                        checks.tick(pool, live_accounts()), timeout=900)
                    for line in checked:
                        log(f"🩺 {line}")
                except Exception as exc:  # noqa: BLE001
                    db.event("check_error", "", str(exc)[:120])

                try:
                    answered = await asyncio.wait_for(
                        followup.tick(pool, live_accounts()), timeout=600)
                    for line in answered:
                        log(f"↩️ {line}")
                except Exception as exc:  # noqa: BLE001
                    db.event("followup_error", "", str(exc)[:120])

            campaign = db.q1("SELECT * FROM campaigns WHERE status='running' ORDER BY id LIMIT 1")
            if campaign is not None and not db.campaign_due(dict(campaign)):
                db.heartbeat("waiting", f"кампания «{campaign['name']}» ждёт старта: {campaign['scheduled_at']}")
                if args.once:
                    print("waiting_schedule")
                    return 0
                await asyncio.sleep(60)
                continue
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
            # Группа кампании: аккаунты группы A не должны отправлять текст группы B
            # и наоборот, иначе эксперимент смешивается.
            need_group = (campaign.get("account_group") or "").strip().lower()
            if need_group:
                accounts = [a for a in accounts
                            if (db.account_group(a["session_name"]) or "").lower() == need_group]
                if not accounts:
                    db.heartbeat("waiting",
                                 f"кампания «{campaign['name']}» ждёт аккаунты группы {need_group.upper()}")
                    if args.once:
                        print("no_accounts_for_group")
                        return 0
                    await asyncio.sleep(120)
                    continue
            db.heartbeat("working", f"кампания «{campaign['name']}»: {stats['pending']} в очереди")
            states = await run_batch(pool, campaign, accounts)
            state = "sent" if "sent" in states else states[0]

            # Сторож: серия ошибок или высокая их доля — кампанию останавливаем.
            if state == "sent":
                row = db.q1("SELECT fail_streak FROM campaigns WHERE id=?", (campaign["id"],))
                stop, why = watchdog.verdict(db.campaign_stats(campaign["id"]),
                                             int(row["fail_streak"]) if row else 0)
                if stop:
                    db.stop_campaign(campaign["id"], why)
                    log(f"🛑 сторож остановил кампанию «{campaign['name']}»: {why}")
                    try:
                        await notify.send(
                            pool, f"🛑 Кампания «{campaign['name']}» остановлена сторожем: {why}.\n"
                                  f"Проверьте аккаунты и текст, потом запустите снова.")
                    except Exception as exc:  # noqa: BLE001
                        db.event("notify_error", "", str(exc)[:120])
                    if args.once:
                        print("once:stopped_by_watchdog")
                        return 0
                    continue

            if args.once:
                print(f"once:{state}")
                return 0

            if state == "wait":
                await asyncio.sleep(60)
            elif state == "retry":
                await asyncio.sleep(5)
            elif state == "skipped":
                await asyncio.sleep(1)
            elif state == "dry":
                await asyncio.sleep(1)
            else:
                # интервал держит pacing на каждом аккаунте, здесь только
                # небольшая пауза между батчами
                await asyncio.sleep(5)
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
    parser.add_argument("--dry-run", action="store_true",
                        help="ничего не отправлять: показать, кому и что ушло бы")
    args = parser.parse_args()

    released = db.release_stale_targets(900)
    if released:
        log(f"↩️ {released} адресат(ов) вернулись в очередь после прошлого падения")

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
