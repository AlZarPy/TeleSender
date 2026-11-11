"""Скор спамности: проверки на живых и эталонных текстах."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.antispam_score import score  # noqa: E402

CLEAN = ("Здравствуйте, Иван! Это Алексей, куратор Школы взрывного роста AI. "
         "Вы были на «Терре» в прошлом году — пишу по этому контакту. "
         "13 ноября в 15:00 открытие 41-го потока, Конгресс-центр ЦМТ. Рассказать программу?")


def test_clean_text_scores_low():
    r = score(CLEAN)
    assert r["verdict"] == "чисто", r
    assert r["points"] <= 2, r


def test_link_in_first_line_is_spam():
    r = score("Заходите https://zapuskterra.ru/ и регистрируйтесь")
    assert r["verdict"] == "спам", r
    assert any(i["code"] == "link_early" for i in r["issues"]), r


def test_three_links_raise_score():
    text = ("Привет! Мы рядом. Подробности тут: https://zapuskterra.ru/ , "
            "группа https://t.me/+abc и мастер-классы https://zapuskterra.ru/mk")
    r = score(text)
    assert r["points"] >= 3, r
    assert any(i["code"] == "many_links" for i in r["issues"]), r


def test_ad_words_and_caps():
    r = score("ТОЛЬКО СЕГОДНЯ АКЦИЯ! Уникальное предложение, скидка 50%, успейте!")
    assert r["points"] >= 4, r
    assert {i["code"] for i in r["issues"]} >= {"caps", "ad_words"}, r


def test_clerical_is_caught():
    r = score("Уважаемый клиент, в рамках проекта доводим до вашего сведения информацию.")
    assert any(i["code"] == "clerical" for i in r["issues"]), r


def test_shortener_is_caught():
    r = score("Подробнее: bit.ly/abc123")
    assert any(i["code"] == "shortener" for i in r["issues"]), r


def test_our_real_texts_ranking():
    """Наш «в лоб со ссылкой» должен быть рискованнее, чем «без ссылки»."""
    src = (ROOT / "tools" / "make_ab.py").read_text(encoding="utf-8")
    a = re.search(r'TEXT_A\s*=\s*"""(.*?)"""', src, re.S).group(1)
    b = re.search(r'TEXT_B\s*=\s*"""(.*?)"""', src, re.S).group(1)
    pa, pb = score(a)["points"], score(b)["points"]
    assert pa > pb, (pa, pb)
    assert score(b)["verdict"] == "чисто", score(b)


def main() -> int:
    passed, failures = 0, []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"  ок  {name}")
            except AssertionError as exc:
                failures.append(f"{name}: {exc}")
                print(f"  ПРОВАЛ {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
                print(f"  ОШИБКА {name}: {type(exc).__name__}: {exc}")
    print(f"\nПройдено: {passed}, провалено: {len(failures)}")
    if failures:
        print("Провалы: " + "; ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
