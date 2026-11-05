"""Тесты сегментации базы: теги, история, ответы."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("✓ " if cond else "✕ ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


db.DB_PATH = Path(tempfile.mkdtemp()) / "seg.db"
db.init()

db.upsert_recipients([
    ("клиент_один", "Павел", "клиенты"),
    ("клиент_два", "Муза", "клиенты,музыка"),
    ("музыкант", "Олег", "музыка"),
    ("новичок", "Ира", ""),
])
db.execute("UPDATE recipients SET status='blocked' WHERE username='новичок'")

# теги
tags = db.tag_names()
check("теги собираются из базы", set(tags) == {"клиенты", "музыка"}, tags)
check("счётчик у тега в подсказке", any(t.startswith("клиенты (2)") for t in db.distinct_tags()),
      db.distinct_tags())

# сегмент по тегу
seg = set(db.segment(tag="клиенты"))
check("по тегу «клиенты» — двое", seg == {"клиент_один", "клиент_два"}, seg)
seg = set(db.segment(tag="музыка"))
check("по тегу «музыка» — двое, включая пересечение",
      seg == {"клиент_два", "музыкант"}, seg)
check("заблокированные не попадают", "новичок" not in seg)

# кампания и добавление сегментом
cid = db.create_campaign("сегмент", "текст", ["клиент_один"])
check("в кампании 1 получатель",
      db.q1("SELECT COUNT(*) c FROM campaign_targets WHERE campaign_id=?", (cid,))["c"] == 1)

added = db.add_segment(cid, tag="музыка")
check("сегмент добавил двоих новых по тегу «музыка»", added == 2, added)
check("теперь в кампании трое",
      db.q1("SELECT COUNT(*) c FROM campaign_targets WHERE campaign_id=?", (cid,))["c"] == 3)

# история: «кому ещё не писали»
db.log_send(cid, "клиент_один", "sender1", True)
never = set(db.segment(cid, never_written=True))
check("«только новым» отсекает тех, кому доставляли", "клиент_один" not in never, never)
check("остальные остаются", "клиент_два" in set(db.segment(never_written=True)),
      db.segment(never_written=True))

# ответы
db.mark_replied("клиент_два", "2026-11-05 10:00:00")
replied = set(db.segment(answered_only=True))
check("«только ответившим»", replied == {"клиент_два"}, replied)

# повторное добавление не дублирует
before = db.q1("SELECT COUNT(*) c FROM campaign_targets WHERE campaign_id=?", (cid,))["c"]
db.add_segment(cid, tag="музыка")
after = db.q1("SELECT COUNT(*) c FROM campaign_targets WHERE campaign_id=?", (cid,))["c"]
check("дубликаты не создаются", before == after, (before, after))

print()
if fails:
    print(f"провалено: {len(fails)}")
    sys.exit(1)
print("все проверки сегментации пройдены")
