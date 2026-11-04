"""Тесты качества: прогрев, история CLI, ответы."""
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("✓ " if cond else "✕ ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


tmp = Path(tempfile.mkdtemp())
db.DB_PATH = tmp / "test.db"
db.init()

# ── прогрев ────────────────────────────────────────────────────────────────
today = date.today()
check("без даты прогрева — полная квота", db.effective_limit(50, "") == 50)
check("день 1 → 15", db.effective_limit(50, today.isoformat()) == 15)
check("день 3 → 20", db.effective_limit(50, (today - timedelta(days=2)).isoformat()) == 20)
check("день 6 → 30", db.effective_limit(50, (today - timedelta(days=5)).isoformat()) == 30)
check("день 8 → полная квота", db.effective_limit(50, (today - timedelta(days=7)).isoformat()) == 50)
check("прогрев не поднимает квоту выше дневной", db.effective_limit(10, today.isoformat()) == 10)
check("номер дня прогрева", db.warmup_day((today - timedelta(days=1)).isoformat()) == 2)
check("мусор в дате — прогрева нет", db.effective_limit(50, "не дата") == 50)

# ── история CLI ────────────────────────────────────────────────────────────
log = tmp / "sent.jsonl"
log.write_text("\n".join([
    json.dumps({"ts": "2026-11-05T00:39:09", "account": "Александр/sender1",
                "username": "R2605s", "ok": True, "reason": ""}),
    json.dumps({"ts": "2026-11-05T00:39:36", "account": "Александр/sender1",
                "username": "iqmuza2", "ok": True, "reason": ""}),
    "не json",
]), encoding="utf-8")

check("импорт истории CLI", db.import_sent_jsonl(str(log)) == 2, db.import_sent_jsonl(str(log)))
check("повторный импорт ничего не дублирует", db.import_sent_jsonl(str(log)) == 0)
check("после импорта человек считается получавшим", db.sent_before("R2605s"))

# ── ответы ─────────────────────────────────────────────────────────────────
db.upsert_recipients([("R2605s", "TheПечкин", ""), ("iqmuza2", "Муза", "")])
check("сначала никто не ответил", len(db.replied_usernames()) == 0)
check("отметка ответа", db.mark_replied("iqmuza2", "2026-11-05 01:00:00") is True)
check("повторная отметка — не новая", db.mark_replied("iqmuza2", "2026-11-05 01:00:00") is False)
check("ответивший в списке", "iqmuza2" in db.replied_usernames())
check("незнакомый не отмечается", db.mark_replied("никого_нет") is False)

# ── дедупликация с учётом ответа ───────────────────────────────────────────
def will_skip(username: str, allow_repeat: bool = False) -> bool:
    """Повторяет правило воркера: пропускаем, если писали и не ответил."""
    return (not allow_repeat) and db.sent_before(username) and username.lower() not in db.replied_usernames()


check("писали, молчит → пропуск", will_skip("R2605s") is True)
check("писали, ответил → пишем снова", will_skip("iqmuza2") is False)
check("писали, но повторы разрешены → пишем", will_skip("R2605s", True) is False)
check("не писали → пишем", will_skip("новичок") is False)

# ── сканер ответов (на заглушке клиента) ───────────────────────────────────
import asyncio  # noqa: E402

from panel import replies  # noqa: E402


class FakeDate:
    def astimezone(self):
        return self

    def strftime(self, fmt):
        return "2026-11-05 02:00:00"


class FakeMessage:
    def __init__(self, out: bool):
        self.out = out
        self.date = FakeDate()


class FakeEntity:
    def __init__(self, username):
        self.username = username


class FakeDialog:
    def __init__(self, username, out=False, is_user=True):
        self.is_user = is_user
        self.entity = FakeEntity(username)
        self.message = FakeMessage(out)


class FakeClient:
    def __init__(self, dialogs):
        self._dialogs = dialogs

    def iter_dialogs(self, limit=30):
        async def gen():
            for dialog in self._dialogs:
                yield dialog
        return gen()


found = asyncio.run(replies.scan_client(FakeClient([
    FakeDialog("iqmuza2"),            # ответил
    FakeDialog("R2605s", out=True),   # последним писали мы — не ответ
    FakeDialog("канал", is_user=False),
    FakeDialog(None),                 # без username
])))
check("сканер видит только ответы", [u for u, _ in found] == ["iqmuza2"], found)
fresh = replies.remember(found, "sender1")
check("сканер помнит ответ", "iqmuza2" in db.replied_usernames())
check("ответивший уже был отмечен раньше — не новый", fresh == [], fresh)

print()
if fails:
    print(f"провалено: {len(fails)}")
    sys.exit(1)
print("все проверки качества пройдены")
