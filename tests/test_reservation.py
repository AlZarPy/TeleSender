"""Резервирование аккаунтов и замки клиентов: находки ревью Sonnet 5.5."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DB = Path(tempfile.gettempdir()) / "senderx_reserve.db"
os.environ["SENDERX_DB"] = str(TMP_DB)
TMP_DB.unlink(missing_ok=True)

from panel import db  # noqa: E402
from panel.worker import Pool, _BUSY, pick_account, release_account  # noqa: E402

ACC = {"status": "active", "paused_until": 0, "daily_limit": 20,
       "effective_limit": 15, "warmup_day": 7}


def _accs(n: int = 3) -> list[dict]:
    """Свежие аккаунты без интервалов и без занятости."""
    db.init()
    db.execute("DELETE FROM account_pacing")
    _BUSY.clear()
    return [dict(ACC, session_name=f"t{i}") for i in range(1, n + 1)]


def test_two_parallel_picks_get_different_accounts():
    accs = _accs(2)
    first = pick_account(accs, 10)
    second = pick_account(accs, 10)
    assert first and second, "оба вызова должны вернуть аккаунт"
    assert first["session_name"] != second["session_name"], (first, second)


def test_no_account_twice_while_busy():
    accs = _accs(1)
    assert pick_account(accs, 10) is not None
    assert pick_account(accs, 10) is None, "занятый аккаунт не должен выдаваться снова"


def test_release_frees_account():
    accs = _accs(1)
    pick_account(accs, 10)
    release_account("t1")
    assert "t1" not in _BUSY


def test_pick_advances_interval_immediately():
    accs = _accs(1)
    before = db.pacing_next_at("t1")
    pick_account(accs, 10)
    after = db.pacing_next_at("t1")
    assert after > before, (before, after)
    assert after > time.time(), "следующий слот должен быть в будущем"


def test_interval_blocks_second_send_without_busy():
    accs = _accs(1)
    pick_account(accs, 10)
    _BUSY.clear()  # сняли занятость, но интервал остался
    assert pick_account(accs, 10) is None, "интервал должен удержать повтор"


def test_pool_lock_is_per_account():
    pool = Pool([dict(ACC, session_name="a"), dict(ACC, session_name="b")])
    la1 = pool._lock("a")
    la2 = pool._lock("a")
    lb = pool._lock("b")
    assert la1 is la2, "один аккаунт — один замок"
    assert la1 is not lb, "разные аккаунты — разные замки"


def test_get_serialised_by_lock():
    """Два одновременных get не должны создавать клиент дважды."""
    pool = Pool([dict(ACC, session_name="z")])
    store: dict[str, object] = {}
    calls = {"n": 0}

    async def fake_get(name: str):
        if name in store:
            return store[name]
        calls["n"] += 1                    # считаем только реальные подключения
        await asyncio.sleep(0.05)
        store[name] = object()
        return store[name]

    pool._get_unlocked = fake_get  # type: ignore[assignment]

    async def run():
        return await asyncio.gather(pool.get("z"), pool.get("z"))

    first, second = asyncio.run(run())
    assert first is second, "под замком должен получиться один клиент"
    assert calls["n"] == 1, f"подключений {calls['n']}, а должно быть одно"


def test_worker_has_reservation_guard():
    src = (ROOT / "panel" / "worker.py").read_text(encoding="utf-8")
    assert "_BUSY" in src and "release_account" in src
    assert "async with self._lock(name)" in src


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
