"""Загрузка получателей из CSV: чистка, дедупликация, отбраковка мусора."""
from __future__ import annotations

import csv
import os
import re

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
INVITE_MARKERS = ("joinchat", "+", "/addlist")


class RecipientsError(RuntimeError):
    pass


def normalise(raw: str) -> str | None:
    """'t.me/name', '@name', 'https://t.me/name' → 'name'; мусор → None."""
    value = (raw or "").strip()
    if not value:
        return None
    value = value.replace("https://", "").replace("http://", "").strip()
    for prefix in ("t.me/", "telegram.me/", "www.t.me/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    value = value.split("?", 1)[0].split("/", 1)[0].strip().lstrip("@")
    if any(marker in value.lower() for marker in INVITE_MARKERS):
        return None  # инвайт-ссылки и телефоны не поддерживаются
    return value if USERNAME_RE.match(value) else None


def load_recipients(csv_path: str = "recipients.csv") -> list[str]:
    """Возвращает уникальные username в исходном порядке, без пустых и дублей."""
    if not os.path.exists(csv_path):
        raise RecipientsError(f"Файл {csv_path} не найден")

    seen: set[str] = set()
    result: list[str] = []
    skipped = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames and "recipient" not in [f.strip() for f in reader.fieldnames]:
            raise RecipientsError(
                f"В {csv_path} нет колонки 'recipient' (найдено: {reader.fieldnames})"
            )
        for row in reader:
            value = normalise(row.get("recipient", ""))
            if not value:
                skipped += 1
                continue
            key = value.lower()
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            result.append(value)

    if skipped:
        print(f"⚠️ отброшено строк (мусор/дубли): {skipped}")
    return result
