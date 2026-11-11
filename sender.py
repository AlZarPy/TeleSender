"""Отправка одного сообщения с честным результатом.

Больше не глотает ошибки: каждое сообщение возвращает SendResult, а FloodWait
поднимается наверх как FloodDetected, чтобы main мог переключить аккаунт и не
потерять получателя.
"""
from __future__ import annotations

import asyncio
import random
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


def _typing() -> bool:
    """Показывать «печатает…» перед первой отправкой. По умолчанию — да."""
    import os

    return os.getenv("SENDERX_TYPING", "1") not in ("0", "", "off", "false", "no")


def _preview() -> bool:
    """Раскрывать ли предпросмотр ссылки. По умолчанию — нет: лендинг подтягивает
    чужую картинку и заголовок, в холодном сообщении это выглядит как реклама."""
    import os

    return os.getenv("SENDERX_LINK_PREVIEW", "0") not in ("0", "", "off", "false", "no")


def _render_markup(text: str) -> tuple[str, list | None]:
    """Разметка → (чистый текст, сущности). Ссылки вида [текст](url) тоже тут.

    Если разбор не удался (в тексте остались ** или ]( ), отправляем как есть:
    лучше без форматирования, чем с мусорными звёздочками.
    """
    from telethon.extensions import markdown

    try:
        plain, entities = markdown.parse(text)
    except Exception:  # noqa: BLE001
        return text, None
    if "**" in plain or "](" in plain or "__" in plain:
        return text, None
    return plain, entities


def _link_ok(text: str) -> bool:
    """'md', если разметка Telegram корректна, иначе None — отправим как обычный текст.

    Страховка от имён получателей с подчёркиваниями и незакрытых **: без неё
    send_message с parse_mode='md' падает на разборе и сообщение не уходит.
    """
    from telethon.extensions import markdown

    try:
        markdown.parse(text)
    except Exception:  # noqa: BLE001
        return None
    return "md"


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


TRANSIENT_ERRORS = (ConnectionError, TimeoutError, OSError, asyncio.IncompleteReadError)


def is_transient(exc: BaseException) -> bool:
    """Временный ли сбой: сеть, таймаут, сервер Telegram. Такие имеет смысл повторить."""
    if isinstance(exc, TRANSIENT_ERRORS):
        return True
    name = type(exc).__name__.lower()
    return any(word in name for word in ("timeout", "internalserver", "servererror",
                                         "connection", "network"))


async def send_one(client, username: str, my_name: str, template: str, me_id: int | None = None,
                   template_fn=None, attachment: str | None = None) -> SendResult:
    """template_fn(his_name) -> текст: так панель подставляет свои варианты и вступление."""
    from panel import peers

    account = getattr(client, "session", None)
    account = getattr(account, "filename", "") if account else ""
    account = str(account).replace(".session", "")

    cached = peers.peer(account, username) if account else None
    if cached is not None:
        user = cached
    else:
        try:
            user = await client.get_entity(username)
        except (UsernameNotOccupiedError, UsernameInvalidError, PeerIdInvalidError, ValueError):
            return SendResult(username, False, "not_found")
        except FloodWaitError as exc:
            raise FloodDetected(exc.seconds, username) from exc
        if account and getattr(user, "access_hash", None):
            try:
                peers.remember(account, username, user)
            except Exception:  # noqa: BLE001
                pass

    if me_id is not None and getattr(user, "id", None) == me_id:
        return SendResult(username, False, "self")

    his_name = getattr(user, "first_name", "") or ""
    text = template_fn(his_name) if template_fn else render(template, my_name, his_name)

    # защита от дубля: тот же текст этому же человеку в течение суток не шлём
    from panel import db as _db

    if _db.sent_same_recently(username, text, hours=24):
        return SendResult(username, False, "duplicate")

    if attachment:
        if len(text) > 1024:
            return SendResult(username, False, "caption_long")
        try:
            cap, cap_entities = _render_markup(text)
            await client.send_file(user, attachment, caption=cap,
                                   formatting_entities=cap_entities, link_preview=_preview())
        except FloodWaitError as exc:
            raise FloodDetected(exc.seconds, username) from exc
        except UserPrivacyRestrictedError:
            return SendResult(username, False, "privacy")
        except ChatWriteForbiddenError:
            return SendResult(username, False, "forbidden")
        except FileNotFoundError:
            return SendResult(username, False, "media_missing")
        except Exception as exc:  # noqa: BLE001
            return SendResult(username, False, f"error:{type(exc).__name__}")
        return SendResult(username, True)

    if _typing():
        secs = max(2, min(8, round(len(text) / 12))) + random.uniform(0, 1.5)
        try:
            async with client.action(user, "typing"):
                await asyncio.sleep(secs)
        except Exception:  # noqa: BLE001 — нет индикатора, но отправить всё равно надо
            pass

    plain, entities = _render_markup(text)
    try:
        await client.send_message(user, plain, formatting_entities=entities,
                                  link_preview=_preview())
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
