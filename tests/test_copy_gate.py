"""Страж текста: воркер не начинает волну, если кампания пахнет спамом."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_copygate.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import antispam, db  # noqa: E402
from panel.worker import copy_gate  # noqa: E402

SPAMMY = ("СРОЧНО! Только сегодня акция, скидка 50%. Регистрируйтесь: "
          "https://zapuskterra.ru/ и https://t.me/+abc , ещё https://zapuskterra.ru/mk")
CLEAN = ("Здравствуйте, Иван! Это Алексей, куратор Школы взрывного роста AI. "
         "Вы были на «Терре» в прошлом году. 13 ноября в 15:00 открытие 41-го потока.")


def _campaign(template: str, name: str) -> dict:
    db.init()
    db.execute("INSERT INTO campaigns(name, template, status) VALUES(?,?,'active')",
               (name, template))
    return dict(db.q1("SELECT * FROM campaigns WHERE name=?", (name,)))


def test_spammy_campaign_is_stopped_before_sending():
    camp = _campaign(SPAMMY, "спамная")
    reason = copy_gate(camp)
    assert reason, "страж должен остановить кампанию"
    row = db.q1("SELECT status, stopped_reason FROM campaigns WHERE id=?", (camp["id"],))
    assert row["status"] == "stopped", dict(row)
    assert "спам" in row["stopped_reason"], dict(row)
    event = db.q1("SELECT COUNT(*) n FROM events WHERE kind='copy_blocked'")
    assert event["n"] >= 1, dict(event)


def test_clean_campaign_is_allowed():
    camp = _campaign(CLEAN, "чистая")
    # текст чистый, но должен быть ещё уникализирован под аккаунты
    db.account_texts_put("acct_x", camp["id"], 1, [CLEAN])
    assert copy_gate(camp) is None
    row = db.q1("SELECT status FROM campaigns WHERE id=?", (camp["id"],))
    assert row["status"] == "active", dict(row)


def test_score_is_logged_once_per_campaign():
    camp = _campaign(CLEAN, "логирование")
    db.execute("DELETE FROM events WHERE kind='copy_score'")
    copy_gate(camp)
    copy_gate(camp)
    n = db.q1("SELECT COUNT(*) n FROM events WHERE kind='copy_score'")
    assert n["n"] == 1, dict(n)


def test_env_override_allows_spammy_text():
    camp = _campaign(SPAMMY, "обход")
    db.account_texts_put("acct_x", camp["id"], 1, [SPAMMY])
    os.environ["SENDERX_ALLOW_SPAMMY_TEXT"] = "1"
    try:
        assert copy_gate(camp) is None
        row = db.q1("SELECT status FROM campaigns WHERE id=?", (camp["id"],))
        assert row["status"] == "active", dict(row)
    finally:
        os.environ.pop("SENDERX_ALLOW_SPAMMY_TEXT", None)


def test_verdict_thresholds():
    assert antispam.score(CLEAN)["verdict"] == "чисто"
    assert antispam.score(SPAMMY)["verdict"] == "спам"
    risky = antispam.score("Привет! Ссылка на программу: https://zapuskterra.ru/")
    assert risky["verdict"] in ("рискованно", "спам"), risky


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
