"""Кэш собеседников: чтобы не искать юзернейм заново на каждую отправку.

Telegram ограничивает не только отправку, но и поиск пользователей
(`ResolveUsernameRequest`). Один раз нашёлся — сохраняем id и access_hash
в свою таблицу, дальше пишем по ним, не трогая поиск.

Access hash выдаётся каждому аккаунту свой, поэтому кэш привязан к паре
(аккаунт, юзернейм).
"""
from __future__ import annotations

from telethon.tl.types import InputPeerUser, User

from . import db


def peer(account: str, username: str) -> InputPeerUser | None:
    """Сохранённый собеседник, если он уже был найден этим аккаунтом."""
    row = db.q1("""SELECT peer_id, access_hash FROM peers
                   WHERE account=? AND username=?""", (account, username.lstrip("@").lower()))
    if not row:
        return None
    return InputPeerUser(int(row["peer_id"]), int(row["access_hash"]))


def remember(account: str, username: str, user: User) -> None:
    key = username.lstrip("@").lower()
    db.execute("""INSERT INTO peers(account, username, peer_id, access_hash, first_name)
                  VALUES(?,?,?,?,?)
                  ON CONFLICT(account, username) DO UPDATE SET
                    peer_id=excluded.peer_id, access_hash=excluded.access_hash,
                    first_name=CASE WHEN excluded.first_name<>'' THEN excluded.first_name
                                    ELSE peers.first_name END,
                    updated_at=datetime('now','localtime')""",
               (account, key, int(user.id), int(getattr(user, "access_hash", 0) or 0),
                (getattr(user, "first_name", "") or "")[:60]))


def name(account: str, username: str) -> str:
    """Имя собеседника из кэша: без него в тексте получается «друг»."""
    row = db.q1("SELECT first_name FROM peers WHERE account=? AND username=?",
                (account, username.lstrip("@").lower()))
    return (row["first_name"] if row and row["first_name"] else "")


def forget(account: str, username: str) -> None:
    db.execute("DELETE FROM peers WHERE account=? AND username=?",
               (account, username.lstrip("@").lower()))


def describe(username: str) -> dict:
    """Сколько аккаунтов уже знают этого человека."""
    row = db.q1("SELECT COUNT(*) n FROM peers WHERE username=?", (username.lstrip("@").lower(),))
    return {"known_by": int(row["n"]) if row else 0}
