"""Сторож: решает, когда пора остановиться.

Пороги намеренно простые и объяснимые — не «умная» эвристика, а защита от того,
что рассылка продолжает долбить, когда канал уже сломан.

    • 10 ошибок подряд  → стоп кампании;
    • доля ошибок ≥ 40% после 20 попыток → стоп кампании;
    • 3 подряд «закрыт для сообщений» → аккаунт на паузу.

Логика вынесена в чистые функции, чтобы её можно было проверить тестами.
"""
from __future__ import annotations

STREAK_LIMIT = 10        # ошибок подряд
MIN_ATTEMPTS = 20        # меньше этого долю ошибок не считаем
FAIL_RATE = 0.40         # доля ошибок, после которой стоп
PRIVACY_STREAK = 3       # отказов «закрыт для сообщений» подряд


def verdict(stats: dict, fail_streak: int,
            streak_limit: int = STREAK_LIMIT,
            min_attempts: int = MIN_ATTEMPTS,
            fail_rate: float = FAIL_RATE) -> tuple[bool, str]:
    """Стоит ли останавливать кампанию. Возвращает (стоп, причина)."""
    sent = int(stats.get("sent") or 0)
    failed = int(stats.get("failed") or 0)
    attempted = sent + failed

    if fail_streak >= streak_limit:
        return True, f"{fail_streak} ошибок подряд"

    if attempted >= min_attempts and attempted:
        share = failed / attempted
        if share >= fail_rate:
            return True, f"доля ошибок {share:.0%} после {attempted} попыток"

    return False, ""


def account_verdict(privacy_streak: int,
                    limit: int = PRIVACY_STREAK) -> tuple[bool, str]:
    """Стоит ли отправлять аккаунт на паузу. Возвращает (пауза, причина)."""
    if privacy_streak >= limit:
        return True, f"{privacy_streak} отказа подряд «закрыт для сообщений»"
    return False, ""


def describe_thresholds() -> str:
    return (f"сторож: стоп при {STREAK_LIMIT} ошибках подряд или {FAIL_RATE:.0%} ошибок "
            f"после {MIN_ATTEMPTS} попыток; аккаунт на паузу при {PRIVACY_STREAK} отказах подряд")
