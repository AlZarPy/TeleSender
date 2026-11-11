"""Качество ответов ИИ-продавца: проверки на факты, повторы, обещания и форму."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import dialog_quality as dq  # noqa: E402

GOOD = ("Здравствуйте! Открытие 41-го потока — 13 ноября в 15:00, Конгресс-центр ЦМТ, "
        "Москва, Краснопресненская наб., 12. Вход бесплатный. Прислать программу?")


def test_good_reply_passes():
    assert dq.check(GOOD) == [], dq.check(GOOD)


def test_wrong_date_is_caught():
    bad = GOOD.replace("13 ноября", "14 ноября")
    codes = [i["code"] for i in dq.check(bad)]
    assert "fact_date" in codes, codes


def test_wrong_time_is_caught():
    bad = GOOD.replace("15:00", "16:00")
    codes = [i["code"] for i in dq.check(bad)]
    assert "fact_time" in codes, codes


def test_wrong_house_is_caught():
    bad = GOOD.replace("наб., 12", "наб., 15")
    codes = [i["code"] for i in dq.check(bad)]
    assert "fact_address" in codes, codes


def test_price_instead_of_free_is_caught():
    bad = "Участие 5000 руб, приходите 13 ноября в 15:00."
    codes = [i["code"] for i in dq.check(bad)]
    assert "fact_price" in codes, codes


def test_repeat_of_previous_reply_is_caught():
    history = [{"who": "them", "text": "а что там будет?"}, {"who": "us", "text": GOOD}]
    codes = [i["code"] for i in dq.check(GOOD, history=history)]
    assert "repeat" in codes, codes


def test_paraphrase_with_different_words_passes():
    history = [{"who": "us", "text": GOOD}]
    other = "Программа большая: 39 мастер-классов в пяти залах. Скинуть файлом?"
    codes = [i["code"] for i in dq.check(other, history=history)]
    assert "repeat" not in codes, codes


def test_banned_promise_is_caught():
    for text in ("Гарантируем результат через месяц.", "Мы вас трудоустроим после курса.",
                 "Доходность 100% в первый год."):
        codes = [i["code"] for i in dq.check(text)]
        assert "claim" in codes, (text, codes)


def test_long_reply_is_caught():
    codes = [i["code"] for i in dq.check("а" * 300)]
    assert "long" in codes, codes


def test_clerical_speech_is_caught():
    codes = [i["code"] for i in dq.check("Уважаемый клиент, в рамках проекта сообщаем.")]
    assert "clerical" in codes, codes


def test_tone_caps_and_exclamations():
    codes = [i["code"] for i in dq.check("СРОЧНО ПИШИТЕ!!! Это важно!!! Правда!!!")]
    assert "tone" in codes, codes


def test_empty_reply_is_caught():
    codes = [i["code"] for i in dq.check("   ")]
    assert "empty" in codes, codes


def test_summarise_groups_codes():
    rows = dq.summarise(["fact_date", "fact_date", "repeat"])
    assert rows[0]["code"] == "fact_date", rows
    assert rows[0]["count"] == 2, rows
    assert abs(sum(r["share"] for r in rows) - 1.0) < 0.01, rows


def test_quality_fail_is_logged_by_salesperson_path():
    import os
    import tempfile

    tmp = Path(tempfile.gettempdir()) / "senderx_dq.db"
    os.environ["SENDERX_DB"] = str(tmp)
    tmp.unlink(missing_ok=True)
    from panel import db

    db.init()
    db.event("quality_fail", "acct_a1", "fact_date: 14 ноября")
    row = db.q1("SELECT COUNT(*) n FROM events WHERE kind='quality_fail'")
    assert row and row["n"] == 1, dict(row) if row else None


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
