"""Тесты отправки на поддельном клиенте: ни одного запроса в Telegram.

Проверяем ровно то, что раньше ломалось: ошибки не теряются, FloodWait поднимается
наверх для ротации, «себе» не отправляется.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telethon.errors import (  # noqa: E402
    FloodWaitError,
    UserPrivacyRestrictedError,
    UsernameNotOccupiedError,
)

from sender import FloodDetected, send_one  # noqa: E402

passed = 0
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failures.append(name)
        print(f"  ✗ {name} {detail}")


class FakeClient:
    """Минимальный двойник TelegramClient."""

    def __init__(self, entity=None, send_error=None, entity_error=None):
        self._entity = entity
        self._send_error = send_error
        self._entity_error = entity_error
        self.sent: list[tuple[object, str]] = []
        self.parse_modes: list[object] = []

    async def get_entity(self, username):
        if self._entity_error:
            raise self._entity_error
        return self._entity

    async def send_message(self, user, text, parse_mode=None):
        if self._send_error:
            raise self._send_error
        self.sent.append((user, text))
        self.parse_modes.append(parse_mode)


async def tests() -> None:
    print("sender.send_one на фейковом клиенте")

    user = SimpleNamespace(id=555, first_name="Иван")
    client = FakeClient(entity=user)
    result = await send_one(client, "ivan", "Аня", "Привет, <ЕгоИмя>! Я <МоёИмя>.", me_id=1)
    check("успешная отправка", result.ok and result.reason == "")
    check("шаблон отрендерен", bool(client.sent) and client.sent[0][1] == "Привет, Иван! Я Аня.",
          str(client.sent))
    check("разметка передаётся как md", client.parse_modes == ["md"], str(client.parse_modes))

    self_client = FakeClient(entity=SimpleNamespace(id=1, first_name="Я"))
    result = await send_one(self_client, "me", "Аня", "x", me_id=1)
    check("себе не отправляем", (not result.ok) and result.reason == "self")

    missing = FakeClient(entity_error=UsernameNotOccupiedError(request=None))
    result = await send_one(missing, "nobody", "Аня", "x", me_id=1)
    check("несуществующий username → not_found", (not result.ok) and result.reason == "not_found")

    private = FakeClient(entity=user, send_error=UserPrivacyRestrictedError(request=None))
    result = await send_one(private, "ivan", "Аня", "x", me_id=1)
    check("privacy → понятная причина", (not result.ok) and result.reason == "privacy")

    flooding = FakeClient(entity=user, send_error=FloodWaitError(request=None, capture=42))
    try:
        await send_one(flooding, "ivan", "Аня", "x", me_id=1)
    except FloodDetected as exc:
        check("FloodWait → FloodDetected с секундами", exc.seconds == 42 and exc.username == "ivan")
    else:
        check("FloodWait → FloodDetected с секундами", False, "исключение не поднялось")

    broken = FakeClient(entity=user, send_error=RuntimeError("boom"))
    result = await send_one(broken, "ivan", "Аня", "x", me_id=1)
    check("прочие ошибки помечаются типом", (not result.ok) and result.reason == "error:RuntimeError",
          result.reason)


def main() -> int:
    asyncio.run(tests())
    print(f"\nПройдено: {passed}, провалено: {len(failures)}")
    if failures:
        print("Провалы: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
