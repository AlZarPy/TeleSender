"""Прогрев подписками: единственная «живая» активность, которую делает сервис.

Логика: новому аккаунту полезно выглядеть живым — читать каналы, а не только писать.
Поэтому в дни прогрева аккаунт подписывается на 1–3 канала из вашего списка в сутки.

Что здесь НЕ делается и почему:
    • не рассылаем сообщения по чатам во время прогрева — это и есть спам;
    • не ставим реакции и не комментируем — похоже на бота, банится;
    • не подписываемся на всё сразу — резкий рост подписок заметен.

Список каналов — файл warmup_channels.txt, по одному в строке:
    @durov
    https://t.me/nousresearch
Пустой файл или его отсутствие — прогрев подписками просто не работает.
"""
from __future__ import annotations

import asyncio

from pathlib import Path

from panel import db

CHANNELS_FILE = Path(__file__).resolve().parent.parent / "warmup_channels.txt"
PER_DAY = 3          # подписок на аккаунт в сутки


def channels(path: str | Path | None = None) -> list[str]:
    file = Path(path) if path else CHANNELS_FILE
    if not file.exists():
        return []
    out: list[str] = []
    for raw in file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def next_channel(account: str, available: list[str]) -> str | None:
    """Случайный канал, на который аккаунт ещё не подписан.

    Именно случайный: если все аккаунты пула подписываются на один и тот же канал
    в один час, это выглядит как coordinated-поведение и связывает аккаунты между собой.
    """
    import random

    free = [channel for channel in available if not db.warmup_done(account, channel)]
    return random.choice(free) if free else None


def should_tick(account: dict, per_day: int = PER_DAY) -> bool:
    """Греем только в дни прогрева и не больше per_day подписок в сутки."""
    day = account.get("warmup_day") or 0
    days = account.get("warmup_days") or 0
    if not day or not days or day > days:
        return False
    if account.get("status") != "active":
        return False
    return db.warmup_count_today(account["session_name"]) < per_day


async def tick(pool, accounts: list[dict], per_day: int = PER_DAY) -> list[str]:
    """Делает по одной подписке на аккаунт, которому это нужно. Возвращает список действий."""
    available = channels()
    if not available:
        return []
    done: list[str] = []
    for acc in accounts:
        if not should_tick(acc, per_day):
            continue
        name = acc["session_name"]
        channel = next_channel(name, available)
        if channel is None:
            continue
        try:
            from telethon.tl.functions.channels import JoinChannelRequest

            async def join() -> None:
                client = await pool.get(name)
                entity = await client.get_entity(channel)
                await client(JoinChannelRequest(entity))

            # подписка не должна вешать весь цикл: канал могли удалить,
            # прокси мог подвиснуть — ограничиваем каждую попытку
            await asyncio.wait_for(join(), timeout=45)
        except Exception as exc:  # noqa: BLE001 — один сбойный канал не должен ломать цикл
            db.event("warmup_error", name, f"{channel}: {str(exc)[:100]}")
            db.warmup_mark(name, channel)  # не зацикливаемся на проблемном канале
            continue
        db.warmup_mark(name, channel)
        done.append(f"{name} → {channel}")
    return done
