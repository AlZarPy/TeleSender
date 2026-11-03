"""Смоук-тесты без сети и без Telegram: разбор конфига, чистка CSV, шаблоны, история.

Запуск:  python tests/test_smoke.py      (код возврата 0 — всё зелёное)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import ConfigError, load_config_from_txt, parse_account  # noqa: E402
from csv_loader import RecipientsError, load_recipients, normalise  # noqa: E402
from main import filter_pending, load_sent, record_sent  # noqa: E402
from sender import render  # noqa: E402

ok = 0
failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global ok
    if condition:
        ok += 1
        print(f"  ✓ {name}")
    else:
        failed.append(name)
        print(f"  ✗ {name} {detail}")


def test_config() -> None:
    print("config_loader")
    acc = parse_account("session_name=s1;api_id=12345;api_hash=abcdef123456;my_name=Аня")
    check("обязательные поля разобраны", acc["session_name"] == "s1" and acc["api_id"] == 12345)
    check("дефолты подставлены", (acc["min_delay"], acc["max_delay"], acc["max_per_account"]) == (20, 60, 50))
    acc2 = parse_account("session_name=s2;api_id=7;api_hash=h1234567;my_name=Б;min_delay=3;max_delay=9;max_per_account=2")
    check("переопределение лимитов", (acc2["min_delay"], acc2["max_delay"], acc2["max_per_account"]) == (3, 9, 2))

    for bad, why in [
        ("session_name=s;api_id=1;my_name=X", "нет api_hash"),
        ("session_name=s;api_id=abc;api_hash=h;my_name=X", "api_id не число"),
        ("session_name=s;api_id=1;api_hash=h;my_name=X;min_delay=10;max_delay=5", "max < min"),
    ]:
        try:
            parse_account(bad)
        except ValueError:
            check(f"отклонено: {why}", True)
        else:
            check(f"отклонено: {why}", False, "исключения не было")

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.txt"
        cfg.write_text(
            "# комментарий\n\n"
            "session_name=a;api_id=1;api_hash=hashaaaa;my_name=A\n"
            "session_name=a;api_id=2;api_hash=hashbbbb;my_name=B\n",
            encoding="utf-8",
        )
        try:
            load_config_from_txt(str(cfg), quiet=True)
        except ConfigError:
            check("дубли session_name ловятся", True)
        else:
            check("дубли session_name ловятся", False)

        missing = Path(tmp) / "nope.txt"
        try:
            load_config_from_txt(str(missing), quiet=True)
        except ConfigError:
            check("отсутствие файла — понятная ошибка", True)
        else:
            check("отсутствие файла — понятная ошибка", False)


def test_recipients() -> None:
    print("csv_loader")
    cases = {
        "t.me/durov": "durov",
        "@Durov": "Durov",
        "https://t.me/SomeOne?x=1": "SomeOne",
        "  t.me/user_name  ": "user_name",
        "+79991234567": None,
        "t.me/+AbCdEf": None,
        "": None,
        "ab": None,
    }
    for raw, expected in cases.items():
        got = normalise(raw)
        check(f"{raw!r} → {expected!r}", got == expected, f"получили {got!r}")

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "r.csv"
        csv_path.write_text(
            "recipient\n"
            "t.me/alpha\n"
            "@alpha\n"
            "https://t.me/beta\n"
            "t.me/+invite\n"
            "\n"
            "t.me/gamma\n",
            encoding="utf-8",
        )
        got = load_recipients(str(csv_path))
        check("дедуп и чистка", got == ["alpha", "beta", "gamma"], f"получили {got}")

        bad_col = Path(tmp) / "bad.csv"
        bad_col.write_text("name\nx\n", encoding="utf-8")
        try:
            load_recipients(str(bad_col))
        except RecipientsError:
            check("нет колонки recipient — ошибка", True)
        else:
            check("нет колонки recipient — ошибка", False)


def test_render() -> None:
    print("sender.render")
    text = render("Привет, <ЕгоИмя>! Я <МоёИмя>.", "Аня", "Иван")
    check("оба плейсхолдера", text == "Привет, Иван! Я Аня.")
    fallback = render("Привет, <ЕгоИмя>!", "Аня", "")
    check("пустое имя не оставляет дыру", "друг" in fallback, fallback)
    check("неизвестные скобки не ломаются", render("<Другое>", "Аня", "Иван") == "<Другое>")


def test_history() -> None:
    print("main.history")
    recipients = ["alpha", "beta", "gamma"]
    with tempfile.TemporaryDirectory() as tmp:
        log = str(Path(tmp) / "sent.jsonl")
        record_sent(log, "a/s", "alpha", True)
        record_sent(log, "a/s", "beta", False, "privacy")
        sent = load_sent(log)
        check("в историю попадает только ok", sent == {"alpha"}, str(sent))
        pending = filter_pending(recipients, sent)
        check("неудачные остаются в очереди", pending == ["beta", "gamma"], str(pending))
        check("--limit работает", filter_pending(recipients, set(), 2) == ["alpha", "beta"])
        check("регистр не создаёт дубль", filter_pending(["ALPHA"], {"alpha"}) == [])


def test_proxy() -> None:
    print("proxy_config")
    from proxy_config import describe, parse_proxy

    check("пустое значение → напрямую", parse_proxy("") is None and parse_proxy(None) is None)

    socks = parse_proxy("socks5://user:p%40ss@127.0.0.1:1080")
    check("socks5 разобран", isinstance(socks, tuple) and len(socks) == 6)
    assert socks is not None
    check("socks5 с логином разобран", socks[1] == "127.0.0.1" and socks[2] == 1080 and socks[4] == "user")
    check("пароль декодируется", socks[5] == "p@ss", str(socks[5]))
    check("rdns включён", socks[3] is True)

    mt = parse_proxy("mtproxy://proxy.example:443/ee1122334455")
    assert mt is not None
    check("mtproxy с секретом", mt[0] == "mtproxy" and mt[3] == "ee1122334455")

    for bad, why in [
        ("ftp://host:21", "неизвестная схема"),
        ("socks5://host", "нет порта"),
        ("mtproxy://host:443", "нет секрета"),
    ]:
        try:
            parse_proxy(bad)
        except (ValueError, RuntimeError):
            check(f"отклонено: {why}", True)
        else:
            check(f"отклонено: {why}", False)

    check("описание без прокси", describe(None) == "напрямую")
    check("конфиг с прокси валидируется",
          parse_account("session_name=s;api_id=1;api_hash=h1234567;my_name=A;proxy=socks5://127.0.0.1:9050")["proxy"]
          == "socks5://127.0.0.1:9050")


def main() -> int:
    for suite in (test_config, test_recipients, test_render, test_history, test_proxy):
        suite()
    print(f"\nПройдено: {ok}, провалено: {len(failed)}")
    if failed:
        print("Провалы: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
