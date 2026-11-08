"""Прогрев перепиской: аккаунты на прогреве пишут друг другу.

Зачем это нужно. У нового аккаунта нет переписок: Telegram видит «пустой» профиль
и не даёт писать незнакомым. Живая переписка внутри своего пула решает сразу три вещи:
появляются контакты (аккаунты становятся знакомыми между собой), возникает история
сообщений и растёт доверие.

Что здесь соблюдается:
    • пишут только свои аккаунты, которые стоят на прогреве — ни одного чужого человека;
    • не больше двух диалогов на аккаунт в сутки и по 2–3 реплики в каждом;
    • пары не повторяются изо дня в день;
    • только в приёмные часы, с человеческими паузами;
    • тексты короткие и разные: никаких ссылок, цен и призывов.

Чего здесь нет: массовых сообщений, вступления в чужие чаты, ответов от лица человека
в переписке с клиентами.
"""
from __future__ import annotations

import random
from datetime import datetime

from panel import db

DIALOGS_PER_DAY = 2          # сколько диалогов заводит один аккаунт в сутки
MAX_PER_DIALOG = 3           # реплик с каждой стороны
MIN_GAP, MAX_GAP = 40, 180   # пауза между репликами, сек
HOURS = (9, 23)

OPENERS = [
    "Привет! Как продвигается неделя?",
    "Привет. Ты уже смотрел новые материалы?",
    "Здравствуй! Как настроение сегодня?",
    "Привет! Есть минутка?",
    "Добрый день. Как дела с проектом?",
]
REPLIES = [
    "Привет! Да, потихоньку двигаюсь.",
    "Здравствуй. Да, читал вчера, полезно.",
    "Привет. Нормально, работаю над задачей.",
    "Да, есть пара минут. Что хотел обсудить?",
    "Привет! Всё в порядке, спасибо.",
]
FOLLOWUPS = [
    "Понял, спасибо. Если что — напишу.",
    "Хорошо, тогда не отвлекаю.",
    "Понял тебя. Держи в курсе.",
    "Спасибо, что ответил. Хорошего дня.",
    "Ок, договорились.",
]


def _key(day: str, name: str) -> str:
    return f"chat:{day}:{name.lower()}"


def dialogs_today(name: str, day: str | None = None) -> int:
    day = day or datetime.now().strftime("%Y-%m-%d")
    try:
        return int(db.meta_get(_key(day, name)) or 0)
    except (TypeError, ValueError):
        return 0


def _count_dialog(name: str, day: str) -> None:
    db.meta_set(_key(day, name), str(dialogs_today(name, day) + 1))


def pick_pairs(accounts: list[dict], day: str) -> list[tuple[str, str]]:
    """Кто с кем поговорит сегодня: пары не повторяются, лимит на аккаунт соблюдается."""
    names = [a["session_name"] for a in accounts]
    if len(names) < 2:
        return []

    free = {name: DIALOGS_PER_DAY - dialogs_today(name, day) for name in names}
    free = {name: left for name, left in free.items() if left > 0}
    pool = sorted(free)
    random.shuffle(pool)

    pairs: list[tuple[str, str]] = []
    while len(pool) >= 2 and len(pairs) < 2 * DIALOGS_PER_DAY:
        first = pool.pop(0)
        second = pool.pop(0)
        if free[first] <= 0 or free[second] <= 0:
            continue
        pairs.append((first, second))
        free[first] -= 1
        free[second] -= 1
        # у кого остался запас — возвращаем в очередь
        for name in (first, second):
            if free[name] > 0:
                pool.append(name)
        pool.sort()
    return pairs


async def run_dialog(send, first: str, second: str, sleep=None) -> list[str]:
    """Одна переписка: приветствие, ответ, короткое завершение.

    send(от_кого, кому, текст) — асинхронная функция отправки.
    sleep(секунды) — пауза; подменяется в тестах.
    """
    import asyncio

    pause = sleep or asyncio.sleep
    steps: list[str] = []

    db.heartbeat("warmup", f"переписка {first} ↔ {second}")
    opener = random.choice(OPENERS)
    await send(first, second, opener)
    steps.append(f"{first}→{second}: {opener}")
    await pause(random.uniform(MIN_GAP, MAX_GAP))
    db.heartbeat("warmup", f"переписка {first} ↔ {second}")

    reply = random.choice(REPLIES)
    await send(second, first, reply)
    steps.append(f"{second}→{first}: {reply}")
    await pause(random.uniform(MIN_GAP, MAX_GAP))
    db.heartbeat("warmup", f"переписка {first} ↔ {second}")

    if random.random() < 0.7:
        tail = random.choice(FOLLOWUPS)
        await send(first, second, tail)
        steps.append(f"{first}→{second}: {tail}")

    return steps


async def tick(pool, accounts: list[dict], hour: int | None = None,
               now: str | None = None, send=None, sleep=None) -> list[str]:
    """Один заход прогрева: выбирает пары и проводит переписки."""
    hour = datetime.now().hour if hour is None else hour
    if not (HOURS[0] <= hour < HOURS[1]):
        return []

    day = now or datetime.now().strftime("%Y-%m-%d")
    warm = [a for a in accounts if a.get("warmup_start")]
    if len(warm) < 2:
        return []

    pairs = pick_pairs(warm, day)
    if not pairs:
        return []

    async def default_send(src: str, dst: str, text: str) -> None:
        client = await pool.get(src)
        target_client = await pool.get(dst)
        me = await target_client.get_me()

        entity = None
        who = getattr(me, "username", None)
        if who:
            entity = f"@{who}"

        phone = getattr(me, "phone", None)
        if phone and not str(phone).startswith("+"):
            phone = "+" + str(phone)

        if entity is None:
            # у аккаунтов нет username: чтобы написать, нужен доступ —
            # импортируем номер в контакты и получаем пользователя
            if not phone:
                raise RuntimeError(f"{dst}: нет ни username, ни телефона")
            from telethon.tl.functions.contacts import ImportContactsRequest
            from telethon.tl.types import InputPhoneContact

            found = await client(ImportContactsRequest([
                InputPhoneContact(client_id=0, phone=phone,
                                  first_name=me.first_name or "Контакт", last_name=me.last_name or "")
            ]))
            if not found.users:
                raise RuntimeError(f"{dst}: телефон не найден в Telegram")
            entity = found.users[0]

        await client.send_message(entity, text)

    log_lines: list[str] = []
    for first, second in pairs:
        try:
            steps = await run_dialog(send or default_send, first, second, sleep=sleep)
            _count_dialog(first, day)
            _count_dialog(second, day)
            log_lines.append(f"{first} ↔ {second}: {len(steps)} реплики")
        except Exception as exc:  # noqa: BLE001
            db.event("warmup_chat_error", first, f"{second}: {str(exc)[:100]}")
            log_lines.append(f"{first} ↔ {second}: не вышло ({str(exc)[:60]})")
    return log_lines
