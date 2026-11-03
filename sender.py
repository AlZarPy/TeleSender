"""Отправка одного сообщения с честным результатом.

Больше не глотает ошибки: каждое сообщение возвращает SendResult, а FloodWait
поднимается наверх как FloodDetected, чтобы main мог переключить аккаунт и не
потерять получателя.
"""
from __future__ import annotations

from dataclasses import dataclass

from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerIdInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)

PLACEHOLDER_ME = "<МоёИмя>"
PLACEHOLDER_HIM = "<ЕгоИмя>"


@dataclass(slots=True)
class SendResult:
    username: str
    ok: bool
    reason: str = ""

    def as_dict(self) -> dict:
        return {"username": self.username, "ok": self.ok, "reason": self.reason}


class FloodDetected(Exception):
    """Аккаунт упёрся в лимит: секунды ожидания и получатель, на котором это случилось."""

    def __init__(self, seconds: int, username: str):
        super().__init__(f"flood wait {seconds}s на {username}")
        self.seconds = seconds
        self.username = username


def render(template: str, my_name: str, his_name: str) -> str:
    """Подставляет имена; неизвестное имя получателя не оставляет пустых дыр."""
    name = (his_name or "").strip() or "друг"
    return template.replace(PLACEHOLDER_ME, my_name).replace(PLACEHOLDER_HIM, name)


async def send_one(client, username: str, my_name: str, template: str, me_id: int | None = None) -> SendResult:
    try:
        user = await client.get_entity(username)
    except (UsernameNotOccupiedError, UsernameInvalidError, PeerIdInvalidError, ValueError):
        return SendResult(username, False, "not_found")
    except FloodWaitError as exc:
        raise FloodDetected(exc.seconds, username) from exc

    if me_id is not None and getattr(user, "id", None) == me_id:
        return SendResult(username, False, "self")

    text = render(template, my_name, getattr(user, "first_name", "") or "")
    try:
        await client.send_message(user, text)
    except FloodWaitError as exc:
        raise FloodDetected(exc.seconds, username) from exc
    except UserPrivacyRestrictedError:
        return SendResult(username, False, "privacy")
    except ChatWriteForbiddenError:
        return SendResult(username, False, "forbidden")
    except Exception as exc:  # noqa: BLE001 — нужен тип ошибки в отчёте, а не падение
        return SendResult(username, False, f"error:{type(exc).__name__}")
    return SendResult(username, True)


async def send_messages(client, recipients: list[str], my_name: str, message_template: str,
                        min_delay: int = 20, max_delay: int = 60) -> list[SendResult]:
    """Совместимая обёртка над прежним API (последовательная отправка с паузами)."""
    import asyncio
    import random

    me = await client.get_me()
    results: list[SendResult] = []
    for username in recipients:
        results.append(await send_one(client, username, my_name, message_template, getattr(me, "id", None)))
        delay = random.randint(min_delay, max_delay)
        print(f"⏱ пауза {delay} с…")
        await asyncio.sleep(delay)
    return results
