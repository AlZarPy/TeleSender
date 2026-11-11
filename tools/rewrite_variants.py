"""ИИ-уникализация: переписывает текст кампании под каждый аккаунт.

Зачем: спинтаксис меняет порядок вставок, но слова остаются те же. Telegram связывает
аккаунты по одинаковому содержимому, поэтому текст должен отличаться словами, а не
только фигурными скобками. Переписанные варианты лежат в `account_texts`, и
`panel/unique.py` берёт их раньше шаблона.

    python tools/rewrite_variants.py --campaign 17 --group b --stage 1
    python tools/rewrite_variants.py --campaign 17 --group b --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import antispam, db  # noqa: E402

ENV_FILE = Path.home() / "AppData/Local/hermes/.env"
API = "https://routerai.ru/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"
PLACEHOLDERS = ("<ЕгоИмя>", "<МоёИмя>", "{{LINK}}")

SYSTEM = """Ты пишешь короткие холодные сообщения в Telegram от имени куратора школы.
Твоя задача — переписать готовый текст так, чтобы он звучал по-другому, но говорил то же.

Жёсткие требования:
- сохрани все факты: дату, время, адрес, слово «бесплатно», шаги записи, если они есть;
- сохрани плейсхолдеры <ЕгоИмя> (имя адресата), <МоёИмя> (имя куратора), {{LINK}} (ссылка);
- длина не больше 450 знаков, либо эталон + 130 знаков (для длинных сообщений);
- начни с обращения по имени, в первых 40 знаках — имя и кто ты;
- никаких ссылок, если их не было в исходнике;
- без слов «акция», «скидка», «уникальный», «успейте», без капса, эмодзи максимум два;
- живой человеческий тон, как будто пишешь лично одному человеку.

СТРУКТУРА — ГЛАВНОЕ. Утверждённую разметку менять нельзя:
- если в исходнике есть жирный заголовок (**текст**), он должен остаться жирным и первым;
- если есть подзаголовки курсивом (__текст__), они остаются курсивом;
- если есть список через «—», он остаётся списком с тем же числом пунктов;
- количество блоков и пустых строк между ними сохраняется;
- **первая строка-заголовок не меняется вообще**: тот же текст, то же выделение, тот же эмодзи.
  Меняются только слова внутри блоков, начиная со второй строки;
- переписывай СЛОВА и порядок фраз внутри блоков, а не структуру.

Верни только текст сообщения, без кавычек и пояснений."""


def api_key() -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("HERMES_CUSTOM_ROUTERAI_RU_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("нет ключа RouterAI")


def ask(prompt: str, model: str, key: str, temperature: float = 0.8) -> str:
    body = json.dumps({"model": model, "temperature": temperature, "max_tokens": 1200,
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(API, data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    return (data["choices"][0]["message"].get("content") or "").strip()


def valid(text: str, original: str) -> tuple[bool, str]:
    """Проверки: плейсхолдеры, длина, факты, спам-скор."""
    # лимит привязан к эталону: у второго сообщения он длиннее, чем у первого
    # запас на живую формулировку: у второго сообщения блоков больше, чем у первого
    limit = max(450, len(original) + 130)
    if not text or len(text) > limit:
        return False, f"длина {len(text)} > {limit}"
    for ph in PLACEHOLDERS:
        if ph in original and ph not in text:
            return False, f"потерян {ph}"
    if "13 ноября" in original and "13 ноября" not in text:
        return False, "потеряна дата"
    if "15:00" in original and "15:00" not in text:
        return False, "потеряно время"
    if "Краснопресненская" in original and "Краснопресненская" not in text:
        return False, "потерян адрес"
    # разметка утверждённого текста должна сохраниться: иначе пропадает вся его структура
    if "**" in original and text.count("**") < 2:
        return False, "потерян жирный заголовок"
    if "__" in original and text.count("__") < 2:
        return False, "потеряны подзаголовки курсивом"
    if original.count("—") >= 2 and text.count("—") < 2:
        return False, "потерян список"
    # заголовок утверждён владельцем: он должен остаться символ в символ
    orig_head = original.splitlines()[0].strip() if original.strip() else ""
    new_head = text.splitlines()[0].strip() if text.strip() else ""
    if orig_head.startswith("**") and new_head != orig_head:
        return False, "изменён заголовок"
    score = antispam.score(text)
    if score["verdict"] == "спам":
        return False, f"спам-скор {score['points']}"
    return True, ""


def persona(acc: dict) -> str:
    note = (acc.get("note") or "").strip()
    return note or acc["session_name"]


def rewrite_for(name: str, acc: dict, template: str, variants: int, model: str,
                key: str, dry: bool) -> list[str]:
    out: list[str] = []
    for i in range(variants):
        prompt = (f"Профиль куратора: {persona(acc)}.\n"
                  f"Исходный текст:\n{template}\n\n"
                  f"Перепиши иначе, вариант {i + 1}: смени зачин и порядок аргументов, "
                  f"но сохрани все факты и плейсхолдеры.")
        for attempt in range(3):
            try:
                text = ask(prompt, model, key, temperature=0.7 + 0.1 * attempt)
            except Exception as exc:  # noqa: BLE001
                print(f"   {name} вариант {i + 1}: ошибка {type(exc).__name__}")
                time.sleep(2)
                continue
            text = text.strip().strip('"').strip("«»")
            ok, why = valid(text, template)
            if ok:
                out.append(text)
                break
            print(f"   {name} вариант {i + 1}: отброшен ({why})")
            time.sleep(1)
    if dry:
        return out
    if out:
        db.account_texts_put(name, acc["campaign_id"], acc["stage"], out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", type=int, required=True)
    ap.add_argument("--group", default="")
    ap.add_argument("--accounts", default="")
    ap.add_argument("--stage", type=int, default=1)
    ap.add_argument("--variants", type=int, default=3)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db.init()
    camp = db.q1("SELECT * FROM campaigns WHERE id=?", (args.campaign,))
    if not camp:
        print("кампания не найдена")
        return 1
    template = camp["template"] or ""
    if not template.strip():
        print("у кампании пустой текст")
        return 1

    if args.accounts:
        names = [a.strip() for a in args.accounts.split(",") if a.strip()]
    elif args.group:
        names = [r["session_name"] for r in
                 db.q("SELECT session_name FROM accounts WHERE status='active' AND grp=? "
                      "ORDER BY session_name", (args.group,))]
    else:
        names = [r["session_name"] for r in
                 db.q("SELECT session_name FROM accounts WHERE status='active' ORDER BY session_name")]
    names = [n for n in names if n != "sender1"]
    if not names:
        print("нет аккаунтов")
        return 1

    key = api_key()
    print(f"кампания {args.campaign} «{camp['name']}» · аккаунтов {len(names)} · "
          f"вариантов на аккаунт {args.variants} · модель {args.model}")

    total = 0
    for name in names:
        acc = dict(db.q1("SELECT session_name, note FROM accounts WHERE session_name=?", (name,)))
        acc["campaign_id"] = args.campaign
        acc["stage"] = args.stage
        texts = rewrite_for(name, acc, template, args.variants, args.model, key, args.dry_run)
        total += len(texts)
        best = min((antispam.score(t)["points"] for t in texts), default=0)
        print(f"{name}: готово {len(texts)} из {args.variants}, минимальный спам-скор {best}")
        for t in texts[:1]:
            print("   пример: " + t[:90].replace("\n", " ") + "…")
        time.sleep(1)

    print(f"\nвсего текстов: {total}"
          + ("" if args.dry_run else f", аккаунтов в базе: {db.account_texts_count(args.campaign)}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
