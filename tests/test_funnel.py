"""Тесты воронки и удаления получателей."""
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


db.DB_PATH = Path(tempfile.mkdtemp()) / "funnel.db"
db.init()

db.upsert_recipients([("a_one", "Аня", ""), ("b_two", "Борис", ""), ("c_three", "Вера", "")])
cid = db.create_campaign("воронка", "текст", ["a_one", "b_two", "c_three"])

# двое доставлено, один ошибка
db.close_target(cid, 1, "sent", "", "sender1")
db.close_target(cid, 2, "sent", "", "sender1")
db.close_target(cid, 3, "failed", "privacy", "sender1")
db.log_send(cid, "a_one", "sender1", True)
db.log_send(cid, "b_two", "sender1", True)

f = db.campaign_funnel(cid)
check("в маршруте трое", f["total"] == 3, f)
check("доставлено двое", f["sent"] == 2, f)
check("одна ошибка", f["failed"] == 1, f)
check("ответов пока нет", f["replied"] == 0 and f["conversion"] == 0.0, f)

db.mark_replied("a_one", "2026-11-06 10:00:00")
f = db.campaign_funnel(cid)
check("ответ учтён", f["replied"] == 1, f)
check("конверсия 50% (1 из 2 доставленных)", f["conversion"] == 50.0, f)

g = db.global_funnel()
check("глобальная воронка видит доставку", g["sent"] == 2, g)   # a_one и b_two
check("глобальная конверсия считается", g["conversion"] > 0, g)

# удаление из кампании — база не страдает
db.remove_target(cid, 3)
f = db.campaign_funnel(cid)
check("из кампании убран один", f["total"] == 2, f)
check("в базе он остался",
      db.q1("SELECT COUNT(*) c FROM recipients WHERE username='c_three'")["c"] == 1)

# удаление из базы — убирает из кампаний, квитанции остаются
before_sends = db.q1("SELECT COUNT(*) c FROM sends")["c"]
db.remove_recipient("a_one")
check("из базы удалён", db.q1("SELECT COUNT(*) c FROM recipients WHERE username='a_one'")["c"] == 0)
check("из кампаний тоже", db.q1("SELECT COUNT(*) c FROM campaign_targets WHERE recipient_id=1")["c"] == 0)
check("квитанции сохранились", db.q1("SELECT COUNT(*) c FROM sends")["c"] == before_sends)
check("конверсия пересчиталась", db.campaign_funnel(cid)["replied"] == 0)

print()
if fails:
    print(f"провалено: {len(fails)}")
    sys.exit(1)
print("все проверки воронки и удаления пройдены")
