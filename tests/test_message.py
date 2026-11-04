"""Тесты текстового модуля: варианты, персонализация, линтер."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import message  # noqa: E402

fails = []


def check(name, cond, extra="") -> None:
    print(("✓ " if cond else "✕ ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


# варианты
check("варианты раскрываются в один из списка",
      message.expand_spintax("{привет|здравствуйте}", random.Random(1)) in ("привет", "здравствуйте"))
check("вложенные варианты", message.expand_spintax("{a|{b|c}}", random.Random(3)) in ("a", "b", "c"))
check("подсчёт вариантов", message.variants_count("{a|b|c} {d|e}") == 6, message.variants_count("{a|b|c} {d|e}"))
check("текст без вариантов = 1", message.variants_count("просто текст") == 1)

# сборка
text = message.render("Привет, <ЕгоИмя>! {Как дела|Как ты}?", "Я Печкин, принёс записку для <ЕгоИмя>",
                      "Александр", "Муза", random.Random(7))
check("вступление первым абзацем", text.startswith("Я Печкин, принёс записку для Муза"))
check("двоеточие после вступления", "Муза:" in text)
check("имя подставлено в тело", "<ЕгоИмя>" not in text and "Привет, Муза!" in text)
check("вариант выбран", "{" not in text)

# пустое имя
check("без имени — «друг»", "друг" in message.render("Привет, <ЕгоИмя>", "", "А", "", random.Random(1)))

# линтер
notes = message.lint("КУПИ СЕЙЧАС! Заработок и инвестиции. https://a.ru https://b.ru https://c.ru @one",
                     "")
levels = {lvl for lvl, _ in notes}
check("линтер ловит капс и триггеры", "bad" in levels)
check("линтер видит много ссылок", any("ссылок" in t for _, t in notes))
good = message.lint("Привет, <ЕгоИмя>! Пишу по делу: помогу с записью. {Спасибо|Благодарю}.",
                    "Я Печкин, принёс записку для <ЕгоИмя>")
check("хороший текст — нет bad", message.worst_level(good) != "bad", good)

# лимит длины
long_notes = message.lint("я" * 1000, "")
check("длинный текст — предупреждение", any("длинно" in t for _, t in long_notes))

print()
if fails:
    print(f"провалено: {len(fails)}")
    sys.exit(1)
print("все проверки текста пройдены")
