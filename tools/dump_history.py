"""Выгрузка истории: копия базы и CSV отправок в backups/.

Зачем: база живёт на одном диске. Умер диск — умерла вся история: кто, когда,
что получил, кто ответил. Копия раз в сутки стоит секунды.

    python tools/dump_history.py                # сделать копию
    python tools/dump_history.py --keep 30      # хранить 30 последних
    python tools/dump_history.py --csv-only     # только CSV отправок
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import db  # noqa: E402

BACKUP_DIR = ROOT / "backups"


def dump_db(stamp: str) -> Path:
    db.init()
    BACKUP_DIR.mkdir(exist_ok=True)
    dst = BACKUP_DIR / f"panel-{stamp}.db"
    src = sqlite3.connect(db.DB_PATH)
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)          # безопасная копия работающей базы, не копирование файла
    out.close()
    src.close()
    return dst


def dump_csv(stamp: str) -> Path:
    db.init()
    BACKUP_DIR.mkdir(exist_ok=True)
    dst = BACKUP_DIR / f"sends-{stamp}.csv"
    rows = db.q("""SELECT s.ts, s.account, s.recipient, s.ok, s.reason, s.variant,
                          SUBSTR(s.text,1,500) AS text, s.read_at, c.name AS campaign
                   FROM sends s LEFT JOIN campaigns c ON c.id = s.campaign_id
                   ORDER BY s.id""")
    with dst.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["время", "аккаунт", "получатель", "доставлено", "причина",
                    "вариант", "текст", "прочитано", "кампания"])
        for r in rows:
            w.writerow([r["ts"], r["account"], r["recipient"], "да" if r["ok"] else "нет",
                        r["reason"], r["variant"], (r["text"] or "").replace("\n", " "),
                        r["read_at"], r["campaign"]])
    return dst


def prune(keep: int) -> list[Path]:
    files = sorted(BACKUP_DIR.glob("panel-*.db")) + sorted(BACKUP_DIR.glob("sends-*.csv"))
    removed = []
    for group in (sorted(BACKUP_DIR.glob("panel-*.db")), sorted(BACKUP_DIR.glob("sends-*.csv"))):
        for old in group[:-keep] if keep > 0 else []:
            old.unlink(missing_ok=True)
            removed.append(old)
    return removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=14, help="сколько копий хранить")
    ap.add_argument("--csv-only", action="store_true")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if not args.csv_only:
        p = dump_db(stamp)
        print(f"база: {p.name} ({p.stat().st_size // 1024} КБ)")
    p = dump_csv(stamp)
    print(f"отправки: {p.name} ({p.stat().st_size // 1024} КБ)")
    for old in prune(args.keep):
        print(f"удалена старая копия: {old.name}")
    print(f"каталог: {BACKUP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
