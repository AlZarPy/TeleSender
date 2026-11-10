"""Тесты: вложения, повторы при сбоях, здоровье аккаунта."""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sender  # noqa: E402
from panel import db, health  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("✓ " if cond else "✕ ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


db.DB_PATH = Path(tempfile.mkdtemp()) / "mh.db"
db.init()

# ── временные сбои ─────────────────────────────────────────────────────────
check("таймаут — временный", sender.is_transient(TimeoutError()))
check("обрыв сети — временный", sender.is_transient(ConnectionResetError()))
check("ошибка сервера Telegram — временный",
      sender.is_transient(type("InternalServerError", (Exception,), {})()))
check("пустой username — не временный", not sender.is_transient(ValueError("no user")))
check("флуд не считается временным сбоем (обрабатывается отдельно)",
      not sender.is_transient(ZeroDivisionError()))


# ── вложение ───────────────────────────────────────────────────────────────
class FakeUser:
    id = 42
    first_name = "Муза"
    username = "muza"


class FakeClient:
    def __init__(self):
        self.sent = []

    async def get_entity(self, username):
        return FakeUser()

    async def send_file(self, entity, file, caption="", formatting_entities=None, link_preview=None):
        self.sent.append(("file", file, caption))

    async def send_message(self, entity, text, formatting_entities=None, link_preview=None):
        self.sent.append(("text", text))


client = FakeClient()
res = asyncio.run(sender.send_one(client, "muza", "Александр", "<ЕгоИмя>, привет",
                                  template_fn=lambda n: f"{n}, привет",
                                  attachment="https://example.com/programma.pdf"))
check("вложение отправлено файлом", res.ok and client.sent[0][0] == "file", client.sent)
check("подпись = текст сообщения", client.sent[0][2] == "Муза, привет", client.sent[0][2])

client2 = FakeClient()
long_text = "я" * 1100
res2 = asyncio.run(sender.send_one(client2, "muza", "А", "x", template_fn=lambda n: long_text,
                                   attachment="https://example.com/a.pdf"))
check("длинная подпись к вложению отклоняется", res2.reason == "caption_long", res2.reason)
check("файл при этом не отправлялся", client2.sent == [], client2.sent)

client3 = FakeClient()
res3 = asyncio.run(sender.send_one(client3, "muza", "А", "x", template_fn=lambda n: "текст"))
check("без вложения — обычное сообщение", res3.ok and client3.sent[0][0] == "text")

# ── здоровье аккаунта ──────────────────────────────────────────────────────
def acc(**kw):
    base = {"session_name": "sender1", "status": "active", "session_exists": True,
            "paused_now": False, "left_today": 10, "warmup_day": 0, "warmup_days": 7}
    base.update(kw)
    return base


h = health.account_health(acc())
check("чистый аккаунт — 100 и «здоров»", h["score"] == 100 and h["label"] == "здоров", h)

h = health.account_health(acc(session_exists=False))
check("без сессии — 0", h["score"] == 0 and h["level"] == "bad", h)

h = health.account_health(acc(status="paused"))
check("пауза снижает балл", h["score"] <= 60, h["score"])

# ошибки в последних отправках
for i in range(6):
    db.log_send(1, "someone", "sender1", i % 2 == 0)
h = health.account_health(acc())
check("доля ошибок 50% роняет здоровье", h["score"] <= 75, h["score"])
check("причина про ошибки есть",
      any("ошибок" in txt for _, txt in h["reasons"]), h["reasons"])

# флуды
for _ in range(2):
    db.event("flood", "sender2", "пауза 60с")
h = health.account_health(acc(session_name="sender2"))
check("флуды за сутки учитываются", h["score"] < 100 and any("флуд" in t for _, t in h["reasons"]), h)

h = health.account_health(acc(left_today=0))
check("выбранная квота — предупреждение", h["score"] < 100, h["score"])

# ── список с здоровьем ─────────────────────────────────────────────────────
items = health.with_health([acc(), acc(session_name="sender3", session_exists=False)])
check("with_health добавляет поле каждому", all("health" in i for i in items), len(items))
check("у второго нулевой балл", items[1]["health"]["score"] == 0)

print()
if fails:
    print(f"провалено: {len(fails)}")
    sys.exit(1)
print("все проверки вложений, повторов и здоровья пройдены")
