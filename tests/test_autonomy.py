"""Тесты сторожа, планировщика и прогрева — без сети и без Telegram."""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db, warmup, watchdog  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("✓ " if cond else "✕ ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


# ── сторож кампании ────────────────────────────────────────────────────────
check("10 ошибок подряд → стоп",
      watchdog.verdict({"sent": 0, "failed": 10}, 10) == (True, "10 ошибок подряд"))
check("9 ошибок подряд → не стоп", watchdog.verdict({"sent": 0, "failed": 9}, 9)[0] is False)
check("5 ошибок из 5 при малом числе попыток → не стоп",
      watchdog.verdict({"sent": 0, "failed": 5}, 5)[0] is False)
check("доля ошибок 50% после 20 попыток → стоп",
      watchdog.verdict({"sent": 10, "failed": 10}, 1)[0] is True)
check("доля ошибок 30% после 20 попыток → продолжаем",
      watchdog.verdict({"sent": 14, "failed": 6}, 1)[0] is False)
check("успехи сбрасывают серию", watchdog.verdict({"sent": 30, "failed": 2}, 0)[0] is False)

# ── сторож аккаунта ────────────────────────────────────────────────────────
check("3 отказа подряд → пауза", watchdog.account_verdict(3)[0] is True)
check("2 отказа подряд → работаем", watchdog.account_verdict(2)[0] is False)

tmp = Path(tempfile.mkdtemp())
db.DB_PATH = tmp / "t.db"
db.init()

# ── планировщик ────────────────────────────────────────────────────────────
now = datetime.now()
past = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
future = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

db.upsert_recipients([("someone", "", "")])
cid_future = db.create_campaign("на будущее", "текст", ["someone"], scheduled_at=future)
cid_past = db.create_campaign("пора", "текст", ["someone"], scheduled_at=past)

check("будущая кампания не готова", db.campaign_due(dict(db.q1("SELECT * FROM campaigns WHERE id=?", (cid_future,)))) is False)
check("наступившая кампания готова", db.campaign_due(dict(db.q1("SELECT * FROM campaigns WHERE id=?", (cid_past,)))) is True)
check("без даты — сразу", db.campaign_due({"scheduled_at": ""}) is True)

promoted = db.promote_due()
check("пора стартовать: 1 кампания", promoted == 1, promoted)
check("она стала running", db.q1("SELECT status FROM campaigns WHERE id=?", (cid_past,))["status"] == "running")
check("будущая осталась черновиком", db.q1("SELECT status FROM campaigns WHERE id=?", (cid_future,))["status"] == "draft")

# ── попытки и серия ошибок ─────────────────────────────────────────────────
db.bump_attempt(cid_past, False)
db.bump_attempt(cid_past, False)
check("серия ошибок растёт", db.q1("SELECT fail_streak, attempts FROM campaigns WHERE id=?", (cid_past,))["fail_streak"] == 2)
db.bump_attempt(cid_past, True)
row = db.q1("SELECT fail_streak, attempts FROM campaigns WHERE id=?", (cid_past,))
check("успех сбрасывает серию", row["fail_streak"] == 0 and row["attempts"] == 3, dict(row))

# ── остановка сторожем ─────────────────────────────────────────────────────
db.stop_campaign(cid_past, "10 ошибок подряд")
row = db.q1("SELECT status, stopped_reason FROM campaigns WHERE id=?", (cid_past,))
check("кампания остановлена с причиной", row["status"] == "stopped" and "10 ошибок" in row["stopped_reason"])
check("в журнале есть запись сторожа",
      db.q1("SELECT 1 AS x FROM events WHERE kind='watchdog_stop' LIMIT 1") is not None)

# ── прогревочные подписки ──────────────────────────────────────────────────
channels = tmp / "channels.txt"
channels.write_text("# комментарий\n@durov\nhttps://t.me/nousresearch\n\n", encoding="utf-8")
check("список каналов читается", warmup.channels(channels) == ["@durov", "https://t.me/nousresearch"])
check("нет файла — пустой список", warmup.channels(tmp / "нет.txt") == [])

account_active = {"session_name": "sender1", "status": "active", "warmup_day": 2, "warmup_days": 7}
account_done = {"session_name": "sender1", "status": "active", "warmup_day": 9, "warmup_days": 7}
account_paused = {"session_name": "sender1", "status": "paused", "warmup_day": 2, "warmup_days": 7}
check("в дни прогрева — греем", warmup.should_tick(account_active) is True)
check("после прогрева — не греем", warmup.should_tick(account_done) is False)
check("на паузе — не греем", warmup.should_tick(account_paused) is False)

# канал выбирается случайно из непройденных: так пул не подписывается весь на один канал
pick = warmup.next_channel("sender1", ["@durov", "@nous"])
check("канал — из списка непройденных", pick in {"@durov", "@nous"})
db.warmup_mark("sender1", "@durov")
check("пройденный канал не выдаётся", warmup.next_channel("sender1", ["@durov", "@nous"]) == "@nous")
check("когда всё пройдено — None", warmup.next_channel("sender1", ["@durov"]) is None)
check("счётчик за сутки", db.warmup_count_today("sender1") == 1)
check("лимит 3 в сутки соблюдается", warmup.should_tick(account_active) is True)

db.warmup_mark("sender1", "@nous")
db.warmup_mark("sender1", "@third")
check("после 3 подписок за сутки — стоп", warmup.should_tick(account_active) is False)

print()
if fails:
    print(f"провалено: {len(fails)}")
    sys.exit(1)
print("все проверки сторожа, планировщика и прогрева пройдены")
