"""Кампания «opt-in»: рассылка только тем, кто дал согласие.

Отличие от групп A и B: здесь адресат — тот, кто сам оставил контакт (заявка,
регистрация, участник группы школы). В базе это флаг `recipients.consent=1`,
и воркер физически не возьмёт человека без него.

Использование:
    python tools/make_optin.py --consent consent.txt        # отметить согласие
    python tools/make_optin.py --campaign                   # создать кампанию
    python tools/make_optin.py --consent consent.txt --campaign
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import db  # noqa: E402

TEMPLATE_PATH = ROOT / "docs" / "optin-text.md"
CAMPAIGN_NAME = "C · opt-in (по согласию)"
UNSUB = "Если неактуально — напишите «стоп», больше писать не буду."


def load_first_text() -> str:
    """Первый текст из docs/optin-text.md (блок в тройных кавычках)."""
    raw = TEMPLATE_PATH.read_text(encoding="utf-8")
    blocks = [b.strip("\n") for b in raw.split("```")[1::2]]
    if not blocks:
        raise SystemExit("в docs/optin-text.md не найден текст в ```")
    return blocks[0] + "\n\n" + UNSUB


def mark_consent(path: Path) -> tuple[int, int]:
    """Отмечает согласие по списку @username, по одному в строке."""
    ok = missing = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.strip().lstrip("@").split()[0] if line.strip() else ""
        if not name or name.startswith("#"):
            continue
        if db.set_consent(name, True):
            ok += 1
        else:
            missing += 1
    return ok, missing


def create_campaign(limit: int = 40) -> int:
    """Создаёт черновик кампании с требованием согласия."""
    exists = db.q1("SELECT id FROM campaigns WHERE name=?", (CAMPAIGN_NAME,))
    if exists:
        print(f"кампания уже есть: id {exists['id']}")
        return int(exists["id"])

    template = load_first_text()
    db.execute("""INSERT INTO campaigns(name, template, status, intro, min_delay, max_delay,
                                        window_start, window_end, requires_consent)
                  VALUES(?,?,'draft','',90,240,'09:00','21:00',1)""",
               (CAMPAIGN_NAME, template))
    row = db.q1("SELECT id FROM campaigns WHERE name=?", (CAMPAIGN_NAME,))
    if not row:
        raise SystemExit("кампания не создалась")
    cid = int(row["id"])

    rows = db.q(f"""SELECT id FROM recipients
                    WHERE consent=1 AND status='active'
                    ORDER BY id LIMIT ?""", (limit,))
    for r in rows:
        db.execute("""INSERT OR IGNORE INTO campaign_targets(campaign_id, recipient_id, state)
                      VALUES(?,?,'pending')""", (cid, r["id"]))
    print(f"кампания {cid} «{CAMPAIGN_NAME}»: целей {len(rows)} (only consent=1)")
    return cid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consent", help="файл со списком @username, кому согласие подтверждено")
    ap.add_argument("--campaign", action="store_true", help="создать кампанию")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    db.init()
    if args.consent:
        ok, missing = mark_consent(Path(args.consent))
        print(f"согласие отмечено: {ok}, не найдено в базе: {missing}")
    if args.campaign:
        create_campaign(args.limit)
    if not args.consent and not args.campaign:
        s = db.consent_stats()
        print(f"в базе {s['total']} адресатов, согласие у {s['agreed']} ({s['share'] * 100:.0f}%)")
        print("примеры команд: --consent consent.txt | --campaign")
    print("готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
