"""Тесты автоматических синонимов."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import message, synonyms  # noqa: E402

fails = []


def check(name, cond, extra=None):
    print(("✓ " if cond else "✕ ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


r = synonyms.enrich("41 поток ТЕРРЫ стартует 13 ноября")
check("слова заменились группами", "{поток|набор|волна}" in r["text"] and r["replaced"] == 2, r)
check("варианты посчитаны (3 потока × 4 старта)", r["variants"] == 12, r["variants"])

r = synonyms.enrich("Стартует новый поток")
check("заглавная буква сохраняется", r["text"].startswith("{Стартует|Начинается|Открывается|Запускается}"), r["text"])

r = synonyms.enrich("41 поток стартует 13/11 и 19:00")
check("даты и числа не тронуты", "13/11" in r["text"] and "19:00" in r["text"], r["text"])

r = synonyms.enrich("Ссылка https://terra.ru/start и @terra_bot")
check("ссылки и упоминания не тронуты", r["replaced"] == 0 and "https://terra.ru/start" in r["text"], r)

r = synonyms.enrich("Уже готово: {стартует|начинается}")
check("готовая скобка не вложена", r["text"].count("{") == 1 and r["replaced"] == 0, r["text"])

text = "41 поток ТЕРРЫ стартует 13 ноября. Приглашаем предпринимателей."
one = synonyms.enrich(text)["text"]
two = synonyms.enrich(one)
check("повторный запуск ничего не ломает", two["replaced"] == 0 and two["text"] == one, two)

check("вложенных скобок нет", "{{" not in one, one)

# сквозной сценарий: слэши + синонимы → текст не повторяется
prepared = message.prepare("Привет/здравствуйте! Стартует/начинается новый поток для предпринимателей.")["text"]
final = synonyms.enrich(prepared)["text"]
flavours = {message.render(final, "", "Александр", "Муза") for _ in range(40)}
check("слэши и синонимы вместе дают много текстов", len(flavours) >= 4, len(flavours))
check("смысл сохраняется", all("новый" in t and any(w in t for w in ("поток", "набор", "волна"))
                              for t in flavours), list(flavours)[:2])

print()
if fails:
    print(f"провалено: {len(fails)}")
    sys.exit(1)
print("все проверки синонимов пройдены")
