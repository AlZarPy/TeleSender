"""Правила отправки: окно, квота по попыткам, битое вложение."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_send_rules.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db, worker  # noqa: E402


def _clean() -> None:
    db.init()
    db.execute("DELETE FROM sends")
    db.execute("DELETE FROM events")


def test_failures_consume_quota():
    _clean()
    for i in range(3):
        db.log_send(1, f"user{i}", "quota_acc", False, "PrivacyRestricted")
    assert worker.account_capacity("quota_acc", 10) == 7, worker.account_capacity("quota_acc", 10)


def test_successes_consume_quota():
    _clean()
    db.log_send(1, "user1", "quota_acc2", True, "")
    assert worker.account_capacity("quota_acc2", 10) == 9


def test_window_equal_borders_means_always_open():
    assert worker.in_window({"window_start": 0, "window_end": 0}) is True
    assert worker.in_window({"window_start": 10, "window_end": 10}) is True


def test_window_regular_borders():
    hour = __import__("datetime").datetime.now().hour
    assert worker.in_window({"window_start": hour, "window_end": hour + 1}) is True
    assert worker.in_window({"window_start": (hour + 2) % 24, "window_end": (hour + 3) % 24}) is False


def test_missing_attachment_returns_none_and_logs():
    _clean()
    assert worker.resolve_attachment("нет_такого_файла_12345.png") is None
    row = db.q1("SELECT COUNT(*) n FROM events WHERE kind='attachment_missing'")
    assert row["n"] == 1, dict(row)


def test_existing_attachment_resolves():
    media = ROOT / "media"
    files = sorted(media.glob("*.png"))
    assert files, "в media должны быть картинки"
    assert worker.resolve_attachment(files[0].name) == str(files[0])


def test_url_attachment_passes_through():
    url = "https://example.com/pic.png"
    assert worker.resolve_attachment(url) == url


def test_empty_attachment_is_none():
    assert worker.resolve_attachment("") is None


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
