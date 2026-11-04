"""Слой данных «Почтамта»: SQLite, без ORM.

Таблицы:
    accounts         — настройки каждого аккаунта из config.txt (квоты, пауза)
    recipients       — общая база получателей (username уникален)
    campaigns        — кампании: шаблон, паузы, окно, статус
    campaign_targets — очередь кампании (получатель × кампания)
    sends            — журнал фактических отправок
    events           — всё, что стоит показать человеку (flood, старт, стоп)
    worker_state     — heartbeat воркера
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "panel.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    session_name TEXT PRIMARY KEY,
    daily_limit  INTEGER NOT NULL DEFAULT 20,
    status       TEXT NOT NULL DEFAULT 'active',   -- active | paused
    paused_until REAL NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS recipients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    first_name TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'active',     -- active | blocked
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS campaigns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    template     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft',    -- draft|running|paused|done|stopped
    min_delay    INTEGER NOT NULL DEFAULT 25,
    max_delay    INTEGER NOT NULL DEFAULT 70,
    window_start INTEGER NOT NULL DEFAULT 9,
    window_end   INTEGER NOT NULL DEFAULT 21,
    allow_self   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT,
    finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS campaign_targets (
    campaign_id  INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    state        TEXT NOT NULL DEFAULT 'pending',  -- pending|sent|failed|skipped
    reason       TEXT NOT NULL DEFAULT '',
    account      TEXT NOT NULL DEFAULT '',
    msg_id       INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (campaign_id, recipient_id)
);

CREATE TABLE IF NOT EXISTS sends (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id  INTEGER NOT NULL,
    recipient    TEXT NOT NULL,
    account      TEXT NOT NULL,
    ok           INTEGER NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    msg_id       INTEGER NOT NULL DEFAULT 0,
    ts           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL DEFAULT (datetime('now')),
    kind    TEXT NOT NULL,
    account TEXT NOT NULL DEFAULT '',
    detail  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS worker_state (
    id     INTEGER PRIMARY KEY CHECK (id = 1),
    ts     REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    detail TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sends_ts ON sends(ts, account);
CREATE INDEX IF NOT EXISTS idx_targets_state ON campaign_targets(campaign_id, state);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def q1(sql: str, params: tuple = ()):
    rows = q(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        last = cur.lastrowid
        return int(last) if last is not None else 0


def event(kind: str, account: str = "", detail: str = "") -> None:
    execute("INSERT INTO events(kind, account, detail) VALUES (?,?,?)", (kind, account, detail))


# ── аккаунты ────────────────────────────────────────────────────────────────
def sync_accounts(session_names: list[str]) -> None:
    """Добавляет новые аккаунты из config.txt, не трогая их настройки."""
    for name in session_names:
        execute("INSERT OR IGNORE INTO accounts(session_name) VALUES (?)", (name,))


def accounts_with_config(config_accounts: list[dict]) -> list[dict]:
    """Сливает config.txt и настройки из БД в один список для интерфейса."""
    stored = {r["session_name"]: dict(r) for r in q("SELECT * FROM accounts")}
    today = q("""SELECT account, COUNT(*) c FROM sends
                 WHERE ok=1 AND date(ts)=date('now') GROUP BY account""")
    sent_today = {r["account"]: r["c"] for r in today}
    out = []
    for acc in config_accounts:
        name = acc["session_name"]
        row = stored.get(name, {"daily_limit": 20, "status": "active", "paused_until": 0, "note": ""})
        paused = row["status"] == "paused"
        left = row["daily_limit"] - sent_today.get(name, 0)
        out.append({
            **acc,
            "daily_limit": row["daily_limit"],
            "status": row["status"],
            "paused_until": row["paused_until"],
            "note": row["note"],
            "sent_today": sent_today.get(name, 0),
            "left_today": max(0, left),
            "paused_now": paused and (row["paused_until"] or 0) > time.time(),
            "session_exists": Path(f"{name}.session").exists(),
        })
    return out


def set_account(name: str, daily_limit: int | None = None, status: str | None = None,
                paused_until: float | None = None, note: str | None = None) -> None:
    execute("INSERT OR IGNORE INTO accounts(session_name) VALUES (?)", (name,))
    if daily_limit is not None:
        execute("UPDATE accounts SET daily_limit=? WHERE session_name=?", (daily_limit, name))
    if status is not None:
        execute("UPDATE accounts SET status=? WHERE session_name=?", (status, name))
    if paused_until is not None:
        execute("UPDATE accounts SET paused_until=? WHERE session_name=?", (paused_until, name))
    if note is not None:
        execute("UPDATE accounts SET note=? WHERE session_name=?", (note, name))


# ── получатели ──────────────────────────────────────────────────────────────
def upsert_recipients(items: list[tuple[str, str, str]]) -> tuple[int, int]:
    """items = [(username, first_name, tags)]. Возвращает (добавлено, уже было)."""
    added = existed = 0
    with connect() as conn:
        for username, first_name, tags in items:
            cur = conn.execute(
                "INSERT OR IGNORE INTO recipients(username, first_name, tags) VALUES (?,?,?)",
                (username, first_name, tags),
            )
            if cur.rowcount:
                added += 1
            else:
                existed += 1
        conn.commit()
    return added, existed


def block_recipient(username: str, blocked: bool = True) -> None:
    execute("UPDATE recipients SET status=? WHERE username=?",
            ("blocked" if blocked else "active", username))


# ── кампании ────────────────────────────────────────────────────────────────
def create_campaign(name: str, template: str, recipients: list[str], *,
                    min_delay: int = 25, max_delay: int = 70,
                    window_start: int = 9, window_end: int = 21,
                    allow_self: bool = False) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO campaigns(name, template, min_delay, max_delay,
                                     window_start, window_end, allow_self)
               VALUES (?,?,?,?,?,?,?)""",
            (name, template, min_delay, max_delay, window_start, window_end, int(allow_self)),
        )
        cid = cur.lastrowid or 0
        for username in recipients:
            row = conn.execute("SELECT id FROM recipients WHERE username=?", (username,)).fetchone()
            if row is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO campaign_targets(campaign_id, recipient_id) VALUES (?,?)",
                    (cid, row["id"]),
                )
        conn.commit()
    return int(cid)


def campaign_stats(campaign_id: int) -> dict:
    row = q1("""SELECT
                  SUM(state='pending') pending, SUM(state='sent') sent,
                  SUM(state='failed') failed, SUM(state='skipped') skipped,
                  COUNT(*) total
                FROM campaign_targets WHERE campaign_id=?""", (campaign_id,))
    return {k: (row[k] or 0) for k in ("pending", "sent", "failed", "skipped", "total")}


def next_target(campaign_id: int):
    return q1("""SELECT t.recipient_id, r.username, r.first_name
                 FROM campaign_targets t JOIN recipients r ON r.id = t.recipient_id
                 WHERE t.campaign_id=? AND t.state='pending' AND r.status='active'
                 ORDER BY t.recipient_id LIMIT 1""", (campaign_id,))


def close_target(campaign_id: int, recipient_id: int, state: str, reason: str = "",
                 account: str = "", msg_id: int = 0) -> None:
    execute("""UPDATE campaign_targets
               SET state=?, reason=?, account=?, msg_id=?, updated_at=datetime('now')
               WHERE campaign_id=? AND recipient_id=?""",
            (state, reason, account, msg_id, campaign_id, recipient_id))


def log_send(campaign_id: int, recipient: str, account: str, ok: bool,
             reason: str = "", msg_id: int = 0) -> None:
    execute("""INSERT INTO sends(campaign_id, recipient, account, ok, reason, msg_id)
               VALUES (?,?,?,?,?,?)""",
            (campaign_id, recipient, account, int(ok), reason, msg_id))


def set_campaign_status(campaign_id: int, status: str) -> None:
    extra = ""
    if status == "running":
        extra = ", started_at=COALESCE(started_at, datetime('now'))"
    if status in ("done", "stopped"):
        extra = ", finished_at=datetime('now')"
    execute(f"UPDATE campaigns SET status=?{extra} WHERE id=?", (status, campaign_id))


def heartbeat(status: str = "idle", detail: str = "") -> None:
    execute("""INSERT INTO worker_state(id, ts, status, detail) VALUES (1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET ts=excluded.ts, status=excluded.status,
                                             detail=excluded.detail""",
            (time.time(), status, detail))


def worker_alive(max_age: float = 25.0) -> tuple[bool, dict]:
    row = q1("SELECT * FROM worker_state WHERE id=1")
    if not row:
        return False, {}
    data = dict(row)
    return (time.time() - data["ts"]) < max_age, data
