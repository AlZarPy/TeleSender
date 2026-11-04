"""Названия продукта и словари подписей.

Бренд — только в двух местах: сервис TheПечкин и панель «Почтамт».
Всё остальное в интерфейсе — обычными словами, чтобы человек с первого раза
понимал, куда нажать и что произойдёт.
"""
from __future__ import annotations

APP = "TheПечкин"
PANEL = "Почтамт"
TAGLINE = "рассылка в Telegram с контролем доставки"

# Технические ключи оставлены как есть: по ним живут база и API.
CAMPAIGN_STATUS = {
    "draft": "черновик",
    "running": "отправляется",
    "paused": "пауза",
    "done": "завершена",
    "stopped": "остановлена",
}

TARGET_STATE = {
    "pending": "в очереди",
    "sent": "отправлено",
    "failed": "ошибка",
    "skipped": "пропущен",
}

REASON = {
    "not_found": "адрес не найден",
    "privacy": "закрыт для сообщений",
    "forbidden": "писать нельзя",
    "self": "это ваш аккаунт",
    "already": "уже писали",
    "flood": "flood wait",
}

REASON_HINT = {
    "not_found": "такого username нет или он удалён",
    "privacy": "получатель запретил сообщения от незнакомых",
    "forbidden": "в этот чат писать нельзя",
    "self": "отправка самому себе пропускается",
    "already": "этому адресату уже успешно писали раньше",
    "flood": "Telegram попросил подождать",
}

T: dict[str, str] = {}


def reason_label(code: str) -> str:
    if not code:
        return ""
    if code in REASON:
        return REASON[code]
    if code.startswith("error:"):
        return "ошибка: " + code.split(":", 1)[1]
    return code


def reason_hint(code: str) -> str:
    return REASON_HINT.get(code, "")


def campaign_status(value: str) -> str:
    return CAMPAIGN_STATUS.get(value, value)


def target_state(value: str) -> str:
    return TARGET_STATE.get(value, value)


def stamp(worker_alive: bool) -> str:
    return "почтамт работает" if worker_alive else "почтамт закрыт"
