"""Разовый аудит проекта сильной моделью (Claude Sonnet 5.5).

Собирает ключевые файлы и тексты кампаний, отправляет ревьюеру, печатает замечания.
Ничего не меняет в проекте.

    python tools/sonnet_review.py                # полный аудит
    python tools/sonnet_review.py --only panel   # только код панели
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import db  # noqa: E402

ENV_FILE = Path.home() / "AppData/Local/hermes/.env"
API = "https://routerai.ru/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-5.5"

CODE_FILES = [
    "panel/worker.py", "panel/db.py", "panel/unique.py", "panel/antispam.py",
    "panel/facts.py", "panel/dialog_quality.py", "panel/salesperson.py",
    "panel/followup.py", "panel/warmup.py", "panel/pacing.py", "panel/checks.py",
    "panel/stages.py", "tools/rewrite_variants.py",
]

SYSTEM = """Ты senior-ревьюер Python-проекта. Тебе дали код рассыльщика Telegram и тексты кампаний.

Задача: найти реальные ошибки, дыры и недоработки, которые проявятся в работе.
Не пересказывай код, не хвали, не предлагай «улучшить читаемость».

Ищи конкретно:
1. логические ошибки и гонки (SQLite, asyncio, пауза между отправками);
2. места, где аккаунт может получить бан без вины владельца (темп, дубли, ссылки, повторы);
3. расхождения между кодом и заявленным поведением (гейты, лимиты, стадии диалога);
4. ошибки в текстах кампаний: неверные факты, обещания, канцелярит, слишком длинные абзацы;
5. места, где при сбое теряются данные (очередь, статусы, деньги/аккаунты).

Формат ответа — только список, по одной строке на замечание:
КРИТИЧНО|ФАЙЛ|что не так|как исправить (конкретно)
ВАЖНО|ФАЙЛ|что не так|как исправить
МЕЛОЧЬ|ФАЙЛ|что не так|как исправить

Не больше 20 пунктов, только то, что действительно стоит править."""


def api_key() -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("HERMES_CUSTOM_ROUTERAI_RU_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("нет ключа RouterAI")


def bundle(only: str, files: list[str] | None = None) -> str:
    parts: list[str] = []
    for rel in (files or CODE_FILES):
        if only == "panel" and not rel.startswith("panel/") and not rel.startswith("tools/"):
            continue
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        parts.append(f"\n=== {rel} ===\n{text[:28000]}")

    if only != "panel" and not files:
        db.init()
        for camp in db.q("""SELECT id, name, status, template FROM campaigns
                            WHERE COALESCE(template,'')<>'' ORDER BY id DESC LIMIT 6"""):
            parts.append(f"\n=== КАМПАНИЯ {camp['id']} · {camp['name']} ({camp['status']}) ===\n"
                         f"{camp['template'][:4000]}")

        rewritten = db.q("""SELECT account, text FROM account_texts
                            WHERE campaign_id=(SELECT MAX(campaign_id) FROM account_texts)
                            LIMIT 3""")
        for row in rewritten:
            parts.append(f"\n=== ПЕРЕПИСАННЫЙ ТЕКСТ {row['account']} ===\n{row['text'][:1500]}")

        doc = ROOT / "docs" / "two-stage-41-final.md"
        if doc.exists():
            parts.append(f"\n=== docs/two-stage-41-final.md ===\n{doc.read_text(encoding='utf-8')[:4000]}")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", choices=["", "panel"])
    ap.add_argument("--files", default="", help="список файлов через запятую")
    ap.add_argument("--out", default="docs/sonnet-review.md")
    args = ap.parse_args()

    files = [f.strip() for f in args.files.split(",") if f.strip()] or None
    content = bundle(args.only, files)
    print(f"материала: {len(content)} знаков ≈ {len(content)//3} токенов")

    body = json.dumps({
        "model": MODEL,
        "temperature": 0.2,
        "max_tokens": 9000,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": content + "\n\nПроведи ревью по формату."},
        ],
    }).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
        choice = data["choices"][0]
        text = (choice["message"].get("content") or "").strip()
        if not text:
            text = f"[пустой ответ, finish_reason={choice.get('finish_reason')}, usage={data.get('usage')}]"
    except Exception as exc:  # noqa: BLE001
        print(f"Sonnet не ответил: {type(exc).__name__}: {str(exc)[:200]}")
        return 1

    out = ROOT / args.out
    out.write_text("# Разовый аудит Claude Sonnet 5.5\n\n" + text + "\n", encoding="utf-8")
    print(text)
    print(f"\nсохранено: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
