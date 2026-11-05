"""Тесты подготовки текста: слэши → варианты."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import message  # noqa: E402

fails = []


def check(name, cond, extra=None):
    print(("✓ " if cond else "✕ ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


r = message.prepare("Привет/здравствуйте, <ЕгоИмя>!")
check("два варианта приветствия", r["text"].startswith("{Привет|здравствуйте}"), r["text"])
check("групп одна, вариантов два", (r["groups"], r["variants"]) == (1, 2), r)
check("имя не тронуто", "<ЕгоИмя>" in r["text"], r["text"])

r = message.prepare("Привет/здравствуйте/добрый день")
check("три варианта", r["variants"] == 3, r)

r = message.prepare("делаешь много/мало, а растёшь медленно/быстро")
check("две группы дают 4 варианта", (r["groups"], r["variants"]) == (2, 4), r)

r = message.prepare("41 поток ТЕРРЫ стартует 13/11 в 19:00")
check("дата не превращается в варианты", r["groups"] == 0 and "13/11" in r["text"], r["text"])

r = message.prepare("Ссылка https://example.com/a/b и t.me/durov")
check("ссылки не тронуты", "https://example.com/a/b" in r["text"] and r["groups"] == 0, r["text"])

r = message.prepare("{уже|готово} и ещё раз/иначе")
check("готовые скобки не ломаются", r["text"].startswith("{уже|готово}"), r["text"])
check("новая группа рядом добавилась", r["groups"] == 1, r)

r = message.prepare("Текст без вариантов, просто приглашение.")
check("без слэшей ничего не меняется", not r["changed"] and r["variants"] == 1, r)

r = message.prepare("Привет/здравствуйте, <ЕгоИмя>!\n\n41 поток стартует 13 ноября.")
check("переводы строк сохраняются", "\n\n" in r["text"], repr(r["text"]))

# разные получатели — разные тексты
prepared = message.prepare("Привет/здравствуйте/добрый день, <ЕгоИмя>!")["text"]
seen = set()
for _ in range(30):
    seen.add(message.render(prepared, "", "Александр", "Муза"))
check("варианты дают разные сообщения", len(seen) >= 2, len(seen))
check("во всех есть имя", all("Муза" in s for s in seen), seen)

print()
if fails:
    print(f"провалено: {len(fails)}")
    sys.exit(1)
print("все проверки подготовки текста пройдены")
