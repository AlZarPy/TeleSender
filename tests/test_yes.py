"""Короткое согласие: «да», «+», «ок», «интересно» и синонимы = согласие."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_yes.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import followup  # noqa: E402

YES = ["да", "Да", "да!", "+", "ок", "ок!", "Окей", "ok", "хорошо", "интересно",
       "конечно", "давай", "давайте", "хочу", "пришлите", "скиньте", "👍", "yes",
       "Да, интересно", "да пришлите подробности", "ок, давайте"]
NO = ["нет", "не интересно", "не надо", "отстань", "это спам", "нет, спасибо"]


def test_yes_words_agree():
    for text in YES:
        assert followup.decided(text) == "announce", f"{text!r} → {followup.decided(text)}"


def test_refusals_still_refuse():
    for text in NO:
        assert followup.decided(text) == "refuse", f"{text!r} → {followup.decided(text)}"


def test_questions_go_to_dialog():
    assert followup.decided("а сколько это стоит?") in ("chat", "announce"), \
        followup.decided("а сколько это стоит?")
    assert followup.decided("чем я занимаюсь?") == "explain"


def test_long_message_not_treated_as_short_yes():
    long_text = ("да, я как раз думал про автоматизацию, но у нас своя CRM и непонятно, "
                 "как это всё совместить с текущими процессами")
    assert followup.decided(long_text) in ("chat", "explain"), followup.decided(long_text)


def test_empty_is_silence():
    assert followup.decided("") == "silence"


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
