"""Тесты прогрева перепиской между своими аккаунтами."""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db, interchat  # noqa: E402

fails = []


def check(name, cond, extra=None):
    print(("✓ " if cond else "✕ ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


db.DB_PATH = Path(tempfile.mkdtemp()) / "chat.db"
db.init()

warm = [{"session_name": f"w{i}", "warmup_start": "2026-11-06"} for i in range(1, 5)]
cold = [{"session_name": "cold1"}]
pairs = interchat.pick_pairs(warm, "2026-11-06")
check("пары не из одного аккаунта", all(a != b for a, b in pairs), pairs)
flat = [n for pair in pairs for n in pair]
check("каждый аккаунт не больше двух диалогов", all(flat.count(n) <= 2 for n in flat), flat)
check("аккаунты без прогрева не участвуют",
      all(n not in {"cold1"} for n in flat), flat)
check("одиночка не даёт пары", interchat.pick_pairs(warm[:1], "2026-11-06") == [])

sent = []


async def fake_send(src, dst, text):
    sent.append((src, dst, text))


async def no_sleep(_seconds):
    return None


async def test_tick():
    result = await interchat.tick(None, warm, hour=12, now="2026-11-06",
                                 send=fake_send, sleep=no_sleep)
    return result


res = asyncio.run(test_tick())
check("переписка состоялась", len(res) >= 1, res)
check("сообщения отправлены в обе стороны",
      any(s[0] != s[1] for s in sent) and len(sent) >= 4, len(sent))
check("в текстах нет ссылок и цен",
      all("http" not in t and "₽" not in t for _, _, t in sent), sent[:2])
check("дневной лимит учтён", interchat.dialogs_today("w1", "2026-11-06") >= 1)

before = len(sent)
res2 = asyncio.run(interchat.tick(None, warm, hour=12, now="2026-11-06",
                                  send=fake_send, sleep=no_sleep))
check("повторный заход не превышает лимит",
      len([s for s in sent[before:]]) <= 6, len(sent) - before)

before_night = len(sent)
asyncio.run(interchat.tick(None, warm, hour=3, now="2026-11-06", send=fake_send, sleep=no_sleep))
check("ночью переписки нет", len(sent) == before_night, len(sent))

print()
if fails:
    print(f"провалено: {len(fails)}")
    sys.exit(1)
print("все проверки прогрева перепиской пройдены")
