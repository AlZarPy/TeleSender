"""Прикидка маршрута: сколько аккаунтов нужно, чтобы отправить N сообщений за D дней.

Считает по нашим же лимитам: потолок в час, окно часов, кривая прогрева.
Запуск:
    python tools/plan.py --recipients 5000 --days 6
    python tools/plan.py --recipients 5000 --days 6 --accounts 10 --daily 40
"""
from __future__ import annotations

import argparse
import math

WARMUP_CURVE = (15, 15, 20, 20, 25, 30, 30)   # потолок в сутки по дням прогрева


def day_ceiling(day: int, daily_limit: int) -> int:
    """Сколько сообщений аккаунт может отправить в конкретный день своей жизни."""
    if day <= len(WARMUP_CURVE):
        return min(daily_limit, WARMUP_CURVE[day - 1])
    return daily_limit


def per_day_capacity(accounts: int, hour_limit: int, window: int, daily_limit: int,
                     warmup_day: int = 0) -> list[int]:
    """Сколько всего можно отправить за каждый из дней, с учётом прогрева."""
    result = []
    for offset in range(60):
        total = 0
        for _ in range(accounts):
            day = warmup_day + offset + 1
            ceiling = day_ceiling(day, daily_limit) if warmup_day >= 0 else daily_limit
            total += min(hour_limit * window, ceiling)
        result.append(total)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Прикидка: хватит ли аккаунтов на объём")
    ap.add_argument("--recipients", type=int, required=True, help="сколько сообщений нужно отправить")
    ap.add_argument("--days", type=int, default=6, help="за сколько дней")
    ap.add_argument("--accounts", type=int, default=0, help="сколько аккаунтов есть (0 — посчитать нужное)")
    ap.add_argument("--hour-limit", type=int, default=10, help="потолок отправок с аккаунта в час")
    ap.add_argument("--window", type=int, default=12, help="сколько часов в сутки работает окно")
    ap.add_argument("--daily", type=int, default=40, help="дневная квота прогретого аккаунта")
    ap.add_argument("--warmup-day", type=int, default=0,
                    help="день прогрева, с которого начинаем (0 — аккаунты уже прогреты)")
    args = ap.parse_args()

    per_account_day = min(args.hour_limit * args.window, args.daily)
    print(f"Лимиты: {args.hour_limit} в час × {args.window} ч = {args.hour_limit * args.window} в сутки, "
          f"дневная квота {args.daily} → потолок {per_account_day} с аккаунта в день")
    print(f"Задача: {args.recipients} сообщений за {args.days} дн. "
          f"= {math.ceil(args.recipients / args.days)} в день\n")

    if args.accounts:
        capacity = per_day_capacity(args.accounts, args.hour_limit, args.window, args.daily, args.warmup_day)
        sent = 0
        for day in range(1, args.days + 1):
            can = capacity[day - 1]
            take = min(can, args.recipients - sent)
            sent += take
            print(f"  день {day}: можно {can:5}, нужно взять {take:5}, остаток {args.recipients - sent:5}")
        if sent >= args.recipients:
            print(f"\nХватает: {args.accounts} аккаунтов закроют объём за {args.days} дн.")
        else:
            need = math.ceil((args.recipients - sent) / max(1, per_account_day))
            print(f"\nНЕ хватает: не хватит {args.recipients - sent} сообщений.")
            print(f"Нужно ещё примерно {need} прогретых аккаунтов или {math.ceil((args.recipients - sent) / per_account_day)} "
                  f"дополнительных дней.")
    else:
        need = math.ceil(args.recipients / (args.days * per_account_day))
        print(f"Нужно аккаунтов: {need} (по {per_account_day} в день каждый)")

    print("\nПрогрев нового аккаунта (если начинать с нуля):")
    for day, ceiling in enumerate(WARMUP_CURVE, start=1):
        print(f"  день {day}: до {min(ceiling, args.daily)} сообщений")
    print("  дальше — дневная квота")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
