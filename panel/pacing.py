"""Темп отправки на аккаунт: чем моложе аккаунт, тем реже он пишет.

Смысл модуля — не ускорять, а не терять аккаунты. Интервал между сообщениями
с ОДНОГО аккаунта остаётся человеческим (минуты), зато разные аккаунты больше
не ждут друг друга в очереди: каждый идёт со своим темпом.
"""
from __future__ import annotations

import random
import time

from . import db

# (нижняя, верхняя) граница интервала в секундах по дню прогрева
BASE = {
    0: (180, 420),   # аккаунт без прогрева — как новичок
    1: (150, 360),
    2: (150, 360),
    3: (120, 300),
    4: (120, 300),
    5: (90, 240),
    6: (90, 240),
}
MATURE = (60, 180)    # с 7-го дня
LONG_PAUSE_CHANCE = 0.04   # изредка человек просто уходит по делам
LONG_PAUSE = (240, 900)


def interval(warmup_day: int, rng: random.Random | None = None) -> int:
    """Сколько секунд ждать этому аккаунту перед следующим сообщением."""
    rng = rng or random.Random()
    low, high = BASE.get(warmup_day, MATURE)
    delay = rng.randint(low, high)
    if rng.random() < LONG_PAUSE_CHANCE:
        delay += rng.randint(*LONG_PAUSE)
    return delay


def ready(account: str) -> bool:
    return db.pacing_next_at(account) <= time.time()


def after_send(account: str, warmup_day: int, rng: random.Random | None = None) -> int:
    """Ставит аккаунту следующий разрешённый момент. Возвращает паузу в секундах."""
    delay = interval(warmup_day, rng)
    db.pacing_set(account, time.time() + delay)
    return delay


def wait_left(account: str) -> int:
    return max(0, int(db.pacing_next_at(account) - time.time()))
