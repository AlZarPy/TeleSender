"""Защита от двойной отправки одного текста одному человеку."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_dedup.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db  # noqa: E402

TEXT = "Здравствуйте! Это Мария, куратор школы «Терра». 13 ноября — открытие 41-го потока."


def _clean() -> None:
    db.init()
    db.execute("DELETE FROM sends")


def test_same_text_blocks_second_send():
    _clean()
    db.log_send(0, "r2605s", "pechkin02", True, "test", 1, variant=0, text=TEXT)
    assert db.sent_same_recently("r2605s", TEXT) is True


def test_other_text_allowed():
    _clean()
    db.log_send(0, "r2605s", "pechkin02", True, "test", 1, variant=0, text=TEXT)
    assert db.sent_same_recently("r2605s", "Совсем другой текст про запуск") is False


def test_other_recipient_allowed():
    _clean()
    db.log_send(0, "r2605s", "pechkin02", True, "test", 1, variant=0, text=TEXT)
    assert db.sent_same_recently("someone_else", TEXT) is False


def test_failed_send_does_not_block():
    _clean()
    db.log_send(0, "r2605s", "pechkin02", False, "flood", 0, variant=0, text=TEXT)
    assert db.sent_same_recently("r2605s", TEXT) is False, "неудачная попытка не считается отправкой"


def test_case_and_at_sign_ignored():
    _clean()
    db.log_send(0, "R2605S", "pechkin02", True, "test", 1, variant=0, text=TEXT)
    assert db.sent_same_recently("@r2605s", TEXT) is True


def test_zero_hours_window():
    _clean()
    db.log_send(0, "r2605s", "pechkin02", True, "test", 1, variant=0, text=TEXT)
    assert db.sent_same_recently("r2605s", TEXT, hours=0) is False, "окно истекло — можно слать"


def test_sender_refuses_duplicate():
    src = (ROOT / "sender.py").read_text(encoding="utf-8")
    assert "sent_same_recently" in src, "sender должен проверять дубль"
    assert '"duplicate"' in src, "нужен отдельный код причины"


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
