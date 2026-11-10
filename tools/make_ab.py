"""Собрать A/B-тест: две кампании на одной базе, по половине контактов.

Группа A — «в лоб»: сразу полный текст со ссылкой, нейродиалогов нет.
Группа B — заход без ссылок + нейродиалоги (правила + модель).

Запуск:
    python tools/make_ab.py base/base_checked.csv --limit 160 --at 2026-11-11T10:00
Печатает, сколько ушло в каждую группу, и создаёт две кампании в статусе «черновик».
"""
from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel import db  # noqa: E402

TEXT_A = """{Здравствуйте|Добрый день}, <ЕгоИмя>!

13 ноября, 15:00 — Конгресс-центр ЦМТ, 4-й подъезд, Москва, Краснопресненская наб., 12.
Открытие 41-го потока бизнес-школы «Терра» и Школы взрывного роста AI.

Участие бесплатное, по регистрации: [получить билет](https://zapuskterra.ru/)

Программа и группа: https://t.me/+6lOUlnEV6-s0MTcy"""

TEXT_B = """👋 {Здравствуйте|Добрый день}, <ЕгоИмя>! {Это|На связи} <МоёИмя>, куратор
Школы взрывного роста AI, {сообщества предпринимателей|бизнес-клуба|образовательной
платформы для предпринимателей} «Терра».

📅 **13 ноября, 15:00** · Конгресс-центр ЦМТ, 4-й подъезд, Москва,
Краснопресненская наб., 12 · открытие 41-го потока

🧩 Чем занимаетесь? Пришлю **3 сценария**, где ИИ забирает рутину и освобождает
**{5–10|6–8} часов в неделю**: продажи, маркетинг, автоматизация. __Без воды, с цифрами.__

👉 **Достаточно одного слова.**"""


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("укажите csv: python tools/make_ab.py base/base_checked.csv [--limit N] [--at ISO]")
        return 2
    path = Path(args[0])
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 160
    at = args[args.index("--at") + 1] if "--at" in args else ""

    rows = [r for r in csv.DictReader(path.open(encoding="utf-8-sig")) if r["status"] == "ок"]
    random.Random(11).shuffle(rows)
    picked = rows[:limit]

    db.init()
    db.upsert_recipients([(r["username"], r["name"], "ab") for r in picked])

    a = [r["username"] for i, r in enumerate(picked) if i % 2 == 0]
    b = [r["username"] for i, r in enumerate(picked) if i % 2 == 1]

    ca = db.create_campaign("A · в лоб со ссылкой", TEXT_A, a, ab_group="A",
                            scheduled_at=at, attachment="media/poster-terra.jpg")
    cb = db.create_campaign("B · без ссылки + нейродиалоги", TEXT_B, b, ab_group="B",
                            scheduled_at=at)
    for cid in (ca, cb):
        db.set_campaign_status(cid, "draft")

    print(f"взято из базы: {len(picked)}")
    print(f"группа A: {len(a)} получателей (кампания {ca})")
    print(f"группа B: {len(b)} получателей (кампания {cb})")
    print("обе в статусе «черновик» — запуск только по команде")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
