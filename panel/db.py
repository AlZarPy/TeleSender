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

import os
import re

# путь к базе можно вынести наружу (Docker, systemd): по умолчанию рядом с проектом
DB_PATH = Path(os.environ.get("SENDERX_DB") or (Path(__file__).resolve().parent.parent / "panel.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    session_name TEXT PRIMARY KEY,
    daily_limit  INTEGER NOT NULL DEFAULT 20,
    status       TEXT NOT NULL DEFAULT 'active',   -- active | paused
    paused_until REAL NOT NULL DEFAULT 0,
    warmup_start TEXT NOT NULL DEFAULT '',         -- дата начала прогрева (YYYY-MM-DD), пусто = не греем
    warmup_days  INTEGER NOT NULL DEFAULT 7,
    note         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS recipients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    first_name TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'active',     -- active | blocked
    replied    INTEGER NOT NULL DEFAULT 0,         -- ответил: писать повторно можно
    last_reply TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS campaigns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    template     TEXT NOT NULL,
    intro        TEXT NOT NULL DEFAULT '',         -- фирменное вступление (присказка)
    status       TEXT NOT NULL DEFAULT 'draft',    -- draft|running|paused|done|stopped
    min_delay    INTEGER NOT NULL DEFAULT 25,
    max_delay    INTEGER NOT NULL DEFAULT 70,
    hour_limit   INTEGER NOT NULL DEFAULT 10,      -- потолок отправок с аккаунта в час
    window_start INTEGER NOT NULL DEFAULT 9,
    window_end   INTEGER NOT NULL DEFAULT 21,
    allow_self   INTEGER NOT NULL DEFAULT 0,
    allow_repeat INTEGER NOT NULL DEFAULT 0,       -- разрешить писать тем, кому уже писали
    attachment   TEXT NOT NULL DEFAULT '',         -- путь или URL вложения (jpg, pdf, mp4)
    scheduled_at TEXT NOT NULL DEFAULT '',         -- не стартовать раньше этого времени
    attempts     INTEGER NOT NULL DEFAULT 0,       -- сколько попыток сделано
    fail_streak  INTEGER NOT NULL DEFAULT 0,       -- ошибок подряд
    stopped_reason TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
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
    updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
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
    ts           TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
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

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS warmup_actions (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    ts      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    channel TEXT NOT NULL,
    UNIQUE (account, channel)
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
    _migrate()


def _migrate() -> None:
    """Догоняем схему для баз, созданных до появления новых колонок."""
    want = {
        "campaigns": {
            "intro": "TEXT NOT NULL DEFAULT ''",
            "hour_limit": "INTEGER NOT NULL DEFAULT 10",
            "allow_repeat": "INTEGER NOT NULL DEFAULT 0",
            "attachment": "TEXT NOT NULL DEFAULT ''",
            "scheduled_at": "TEXT NOT NULL DEFAULT ''",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            "fail_streak": "INTEGER NOT NULL DEFAULT 0",
            "stopped_reason": "TEXT NOT NULL DEFAULT ''",
        },
        "accounts": {
            "warmup_start": "TEXT NOT NULL DEFAULT ''",
            "warmup_days": "INTEGER NOT NULL DEFAULT 7",
        },
        "recipients": {
            "replied": "INTEGER NOT NULL DEFAULT 0",
            "last_reply": "TEXT NOT NULL DEFAULT ''",
        },
    }
    with connect() as conn:
        for table, columns in want.items():
            have = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column, ddl in columns.items():
                if column not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        conn.commit()


# ── прогрев (обкатка) ───────────────────────────────────────────────────────
WARMUP_CURVE = (15, 15, 20, 20, 25, 30, 30)  # потолок по дням, дальше — дневная квота


def warmup_day(warmup_start: str, today: str | None = None) -> int:
    """Какой день прогрева идёт. 0 — прогрев не запущен."""
    if not warmup_start:
        return 0
    try:
        from datetime import date
        started = date.fromisoformat(warmup_start[:10])
        now = date.fromisoformat(today[:10]) if today else date.today()
        return max(1, (now - started).days + 1)
    except (ValueError, TypeError):
        return 0


def effective_limit(daily_limit: int, warmup_start: str, warmup_days: int = 7,
                    today: str | None = None) -> int:
    """Квота с учётом прогрева: новому аккаунту больше кривой не даём."""
    day = warmup_day(warmup_start, today)
    if not day or day > warmup_days:
        return daily_limit
    ceiling = WARMUP_CURVE[min(day, len(WARMUP_CURVE)) - 1]
    return min(daily_limit, ceiling)


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
                 WHERE ok=1 AND date(ts)=date('now','localtime') GROUP BY account""")
    sent_today = {r["account"]: r["c"] for r in today}
    out = []
    for acc in config_accounts:
        name = acc["session_name"]
        row = stored.get(name, {"daily_limit": 20, "status": "active", "paused_until": 0,
                                "warmup_start": "", "warmup_days": 7, "note": ""})
        paused = row["status"] == "paused"
        warmup_start = row.get("warmup_start") or ""
        warmup_days = row.get("warmup_days") or 7
        day = warmup_day(warmup_start)
        limit = effective_limit(row["daily_limit"], warmup_start, warmup_days)
        left = limit - sent_today.get(name, 0)
        out.append({
            **acc,
            "daily_limit": row["daily_limit"],
            "effective_limit": limit,
            "warmup_start": warmup_start,
            "warmup_days": warmup_days,
            "warmup_day": day,
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
                paused_until: float | None = None, note: str | None = None,
                warmup_start: str | None = None, warmup_days: int | None = None) -> None:
    execute("INSERT OR IGNORE INTO accounts(session_name) VALUES (?)", (name,))
    for column, value in (("daily_limit", daily_limit), ("status", status),
                          ("paused_until", paused_until), ("note", note),
                          ("warmup_start", warmup_start), ("warmup_days", warmup_days)):
        if value is not None:
            execute(f"UPDATE accounts SET {column}=? WHERE session_name=?", (value, name))


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
                    intro: str = "", min_delay: int = 25, max_delay: int = 70,
                    hour_limit: int = 10, window_start: int = 9, window_end: int = 21,
                    allow_self: bool = False, allow_repeat: bool = False,
                    scheduled_at: str = "", attachment: str = "") -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO campaigns(name, template, intro, min_delay, max_delay, hour_limit,
                                     window_start, window_end, allow_self, allow_repeat,
                                     scheduled_at, attachment)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, template, intro, min_delay, max_delay, hour_limit,
             window_start, window_end, int(allow_self), int(allow_repeat),
             scheduled_at, attachment),
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
               SET state=?, reason=?, account=?, msg_id=?, updated_at=datetime('now','localtime')
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
        extra = ", started_at=COALESCE(started_at, datetime('now','localtime'))"
    if status in ("done", "stopped"):
        extra = ", finished_at=datetime('now','localtime')"
    execute(f"UPDATE campaigns SET status=?{extra} WHERE id=?", (status, campaign_id))


def bump_attempt(campaign_id: int, ok: bool) -> None:
    """Считает попытки и серию ошибок подряд — по ним работает сторож."""
    if ok:
        execute("UPDATE campaigns SET attempts=attempts+1, fail_streak=0 WHERE id=?", (campaign_id,))
    else:
        execute("UPDATE campaigns SET attempts=attempts+1, fail_streak=fail_streak+1 WHERE id=?",
                (campaign_id,))


def stop_campaign(campaign_id: int, reason: str) -> None:
    execute("""UPDATE campaigns SET status='stopped', stopped_reason=?, finished_at=datetime('now','localtime')
               WHERE id=?""", (reason, campaign_id))
    event("watchdog_stop", "", f"кампания #{campaign_id} остановлена: {reason}")


def privacy_streak(account: str, limit: int = 5) -> int:
    """Сколько подряд последних отправок закрыты для сообщений."""
    rows = q("SELECT ok, reason FROM sends WHERE account=? ORDER BY id DESC LIMIT ?", (account, limit))
    streak = 0
    for row in rows:
        if not row["ok"] and row["reason"] in ("privacy", "forbidden"):
            streak += 1
        else:
            break
    return streak


# ── мелочи: настройки в базе и прогревочные подписки ───────────────────────
def meta_get(key: str, default: str = "") -> str:
    row = q1("SELECT value FROM meta WHERE key=?", (key,))
    return row["value"] if row else default


def meta_set(key: str, value: str) -> None:
    execute("""INSERT INTO meta(key, value) VALUES (?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (key, value))


def warmup_done(account: str, channel: str) -> bool:
    return q1("SELECT 1 AS x FROM warmup_actions WHERE account=? AND channel=?",
              (account, channel)) is not None


def warmup_mark(account: str, channel: str) -> None:
    execute("INSERT OR IGNORE INTO warmup_actions(account, channel) VALUES (?,?)", (account, channel))
    event("warmup", account, f"подписка на {channel}")


def warmup_count_today(account: str) -> int:
    row = q1("""SELECT COUNT(*) c FROM warmup_actions
                WHERE account=? AND date(ts)=date('now','localtime')""", (account,))
    return int(row["c"]) if row else 0


def promote_due() -> int:
    """Черновики с наступившим временем старта переводим в работу."""
    rows = q("""SELECT id, name FROM campaigns
                WHERE status='draft' AND scheduled_at<>'' AND scheduled_at<=datetime('now','localtime')""")
    for row in rows:
        set_campaign_status(row["id"], "running")
        event("campaign_scheduled_start", "", f"кампания «{row['name']}» стартовала по расписанию")
    return len(rows)


def campaign_due(campaign: dict) -> bool:
    when = (campaign.get("scheduled_at") or "").strip()
    if not when:
        return True
    row = q1("SELECT ? <= datetime('now','localtime') AS due", (when,))
    return bool(row and row["due"])


def sent_before(username: str) -> bool:
    """Писали ли этому адресату когда-либо раньше (успешно, в любой кампании)."""
    row = q1("SELECT 1 AS x FROM sends WHERE recipient=? AND ok=1 LIMIT 1", (username,))
    return row is not None


def hour_sent(account: str) -> int:
    """Сколько успешных отправок у аккаунта за последний час."""
    row = q1("""SELECT COUNT(*) c FROM sends
                WHERE account=? AND ok=1 AND ts >= datetime('now','localtime','-1 hour')""", (account,))
    return int(row["c"]) if row else 0


def remember_recipients(rows: list[dict]) -> int:
    """Помечает адресатов, которым уже писали (для предпросмотра)."""
    return sum(1 for r in rows if sent_before(r["username"]))


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


# ── ответы получателей (обратная почта) ─────────────────────────────────────
def mark_replied(username: str, when: str = "") -> bool:
    """Отмечает, что человек ответил. Возвращает True, если отметка новая."""
    row = q1("SELECT replied FROM recipients WHERE username=?", (username,))
    if row is None:
        return False
    was = int(row["replied"] or 0)
    execute("UPDATE recipients SET replied=1, last_reply=? WHERE username=?",
            (when or time.strftime("%Y-%m-%d %H:%M:%S"), username))
    return not was


def replied(limit: int = 20) -> list[sqlite3.Row]:
    return q("""SELECT username, first_name, last_reply FROM recipients
                WHERE replied=1 ORDER BY last_reply DESC LIMIT ?""", (limit,))


def replied_usernames() -> set[str]:
    return {r["username"].lower() for r in q("SELECT username FROM recipients WHERE replied=1")}


# ── история отправок из CLI (sent.jsonl) ────────────────────────────────────
def import_sent_jsonl(path: str = "sent.jsonl") -> int:
    """Подтягивает отправки, сделанные через main.py, чтобы не писать людям дважды."""
    import json
    from pathlib import Path as _Path

    file = _Path(path)
    if not file.exists():
        return 0
    added = 0
    with connect() as conn:
        for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            username = str(item.get("username") or item.get("recipient") or "").strip()
            if not username:
                continue
            ts = str(item.get("ts") or "")[:19].replace("T", " ") or time.strftime("%Y-%m-%d %H:%M:%S")
            account = str(item.get("account") or "cli")
            ok = 1 if item.get("ok") else 0
            exists = conn.execute(
                "SELECT 1 FROM sends WHERE recipient=? AND ts=? LIMIT 1", (username, ts)).fetchone()
            if exists:
                continue
            conn.execute("""INSERT INTO sends(campaign_id, recipient, account, ok, reason, ts)
                            VALUES (0,?,?,?,?,?)""",
                         (username, account, ok, str(item.get("reason") or ""), ts))
            added += 1
        conn.commit()
    if added:
        event("history_import", "cli", f"подтянуто отправок из sent.jsonl: {added}")
    return added


# ── архив и очистка журнала ────────────────────────────────────────────────
def export_csv(sql: str, params: tuple, path, header: bool = True) -> int:
    """Выгружает результат запроса в CSV. Возвращает число строк."""
    import csv
    rows = q(sql, params)
    if not rows:
        return 0
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        if header:
            writer.writerow(rows[0].keys())
        writer.writerows([tuple(r) for r in rows])
    return len(rows)


def archive_journal(folder) -> list:
    """Перед очисткой складывает квитанции и события в CSV."""
    from datetime import datetime
    from pathlib import Path as _Path

    folder = _Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    made = []
    sends = export_csv("SELECT * FROM sends ORDER BY id", (), folder / f"sends-{stamp}.csv")
    events = export_csv("SELECT * FROM events ORDER BY id", (), folder / f"events-{stamp}.csv")
    if sends:
        made.append(folder / f"sends-{stamp}.csv")
    if events:
        made.append(folder / f"events-{stamp}.csv")
    return made


def clear_events(keep_sends: bool = True) -> tuple[int, int]:
    """Чистит журнал событий (и по желанию квитанции). Возвращает (события, квитанции)."""
    events = q1("SELECT COUNT(*) c FROM events")["c"]
    execute("DELETE FROM events")
    sends = 0
    if not keep_sends:
        sends = q1("SELECT COUNT(*) c FROM sends")["c"]
        execute("DELETE FROM sends")
    event("journal_cleared", "", f"журнал очищен: событий {events}, квитанций {sends}")
    return int(events), int(sends)


# ── состав кампании: добавление из общей базы ──────────────────────────────
def add_targets(campaign_id: int, usernames: list[str] | None = None,
                only_active: bool = True) -> int:
    """Добавляет получателей в кампанию. usernames=None — всех активных из базы.

    Уже добавленных не дублируем (ключ campaign_id+recipient_id).
    Возвращает число реально добавленных.
    """
    where: list[str] = []
    params: list = []
    if usernames:
        marks = ",".join("?" * len(usernames))
        where.append(f"username IN ({marks})")
        params.extend(usernames)
    if only_active:
        where.append("status='active'")
    sql = "SELECT id FROM recipients" + (" WHERE " + " AND ".join(where) if where else "")

    added = 0
    with connect() as conn:
        for row in conn.execute(sql, tuple(params)).fetchall():
            cur = conn.execute(
                "INSERT OR IGNORE INTO campaign_targets(campaign_id, recipient_id) VALUES (?,?)",
                (campaign_id, row["id"]))
            added += 1 if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
    if added:
        event("campaign_targets_added", "", f"в кампанию #{campaign_id} добавлено получателей: {added}")
    return added


def base_not_in_campaign(campaign_id: int) -> int:
    """Сколько активных людей из базы ещё не в этой кампании."""
    row = q1("""SELECT COUNT(*) c FROM recipients r
                WHERE r.status='active' AND r.id NOT IN
                      (SELECT recipient_id FROM campaign_targets WHERE campaign_id=?)""",
             (campaign_id,))
    return int(row["c"]) if row else 0


# ── сегментация базы ───────────────────────────────────────────────────────
def distinct_tags() -> list[str]:
    """Все теги из базы. В поле tags может быть несколько через запятую."""
    seen: dict[str, int] = {}
    for row in q("SELECT tags FROM recipients WHERE tags<>''"):
        for part in str(row["tags"]).replace(";", ",").split(","):
            tag = part.strip()
            if tag:
                seen[tag] = seen.get(tag, 0) + 1
    return [f"{tag} ({count})" for tag, count in sorted(seen.items(), key=lambda x: -x[1])]


def tag_names() -> list[str]:
    return [re.sub(r"\s+\(\d+\)$", "", t) for t in distinct_tags()]


def segment(campaign_id: int = 0, tag: str = "", never_written: bool = False,
            answered_only: bool = False, only_active: bool = True) -> list[str]:
    """Возвращает username'ы, подходящие под фильтр.

    never_written — кому ещё ни разу не писали;
    answered_only — кто отвечал;
    campaign_id — исключить тех, кто уже в этой кампании.
    """
    sql = "SELECT r.username FROM recipients r"
    where: list[str] = []
    params: list = []
    if only_active:
        where.append("r.status='active'")
    if tag:
        where.append("(',' || replace(r.tags,' ','') || ',') LIKE ?")
        params.append(f"%,{tag.replace(' ', '')},%")
    if never_written:
        where.append("NOT EXISTS (SELECT 1 FROM sends s WHERE s.recipient=r.username AND s.ok=1)")
    if answered_only:
        where.append("r.replied=1")
    if campaign_id:
        where.append("r.id NOT IN (SELECT recipient_id FROM campaign_targets WHERE campaign_id=?)")
        params.append(campaign_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    return [r["username"] for r in q(sql, tuple(params))]


def add_segment(campaign_id: int, tag: str = "", never_written: bool = False,
                answered_only: bool = False) -> int:
    """Добавляет в кампанию всех, кто подходит под фильтр. Возвращает число."""
    names = segment(campaign_id, tag, never_written, answered_only)
    return add_targets(campaign_id, names) if names else 0


# ── удаление и конверсия ───────────────────────────────────────────────────
def remove_target(campaign_id: int, recipient_id: int) -> None:
    """Убирает человека из кампании (в базе он остаётся)."""
    execute("DELETE FROM campaign_targets WHERE campaign_id=? AND recipient_id=?",
            (campaign_id, recipient_id))


def remove_recipient(username: str) -> int:
    """Удаляет человека из базы и из всех кампаний. Квитанции остаются в истории."""
    row = q1("SELECT id FROM recipients WHERE username=?", (username,))
    if row is None:
        return 0
    rid = row["id"]
    execute("DELETE FROM campaign_targets WHERE recipient_id=?", (rid,))
    execute("DELETE FROM recipients WHERE id=?", (rid,))
    event("recipient_removed", "", f"из базы удалён @{username}")
    return 1


def campaign_funnel(campaign_id: int) -> dict:
    """Воронка кампании: сколько в маршруте, доставлено, ответили, конверсия."""
    row = q1("""SELECT
                  COUNT(*) total,
                  SUM(state='sent') sent,
                  SUM(state='failed') failed,
                  SUM(state='skipped') skipped,
                  SUM(state='pending') pending
                FROM campaign_targets WHERE campaign_id=?""", (campaign_id,))
    data = {k: int(row[k] or 0) for k in ("total", "sent", "failed", "skipped", "pending")} if row else {}
    replied = q1("""SELECT COUNT(*) c FROM campaign_targets t
                    JOIN recipients r ON r.id=t.recipient_id
                    WHERE t.campaign_id=? AND r.replied=1""", (campaign_id,))
    data["replied"] = int(replied["c"]) if replied else 0
    data["conversion"] = round(100 * data["replied"] / data["sent"], 1) if data.get("sent") else 0.0
    return data


def global_funnel() -> dict:
    """Общая воронка по всей базе: отправлено, ответили, конверсия."""
    sent = q1("SELECT COUNT(DISTINCT recipient) c FROM sends WHERE ok=1")
    replied = q1("SELECT COUNT(*) c FROM recipients WHERE replied=1")
    total = q1("SELECT COUNT(*) c FROM recipients")
    sent_n = int(sent["c"]) if sent else 0
    replied_n = int(replied["c"]) if replied else 0
    return {
        "sent": sent_n,
        "replied": replied_n,
        "base": int(total["c"]) if total else 0,
        "conversion": round(100 * replied_n / sent_n, 1) if sent_n else 0.0,
    }
