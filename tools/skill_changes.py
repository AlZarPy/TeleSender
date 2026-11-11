"""Что изменилось в навыках за последние часы — для отчёта в конце сессии.

Смотрит файлы навыков (SKILL.md и references/) по времени изменения и печатает
список: какой навык, какой файл, когда. Нужен, чтобы владелец видел, что
самопроверка Hermes записала сама, и мог отменить лишнее.

    python tools/skill_changes.py            # за 6 часов
    python tools/skill_changes.py --hours 24
    python tools/skill_changes.py --skills   # только SKILL.md
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

SKILLS_DIR = Path.home() / "AppData/Local/hermes" / "skills"


def collect(hours: float, only_main: bool) -> list[dict]:
    cutoff = time.time() - hours * 3600
    out: list[dict] = []
    for path in SKILLS_DIR.rglob("*.md"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        if only_main and path.name != "SKILL.md":
            continue
        rel = path.relative_to(SKILLS_DIR)
        parts = rel.parts
        # .../<навык>/SKILL.md  или  .../<навык>/references/<файл>.md
        if parts[-1] == "SKILL.md":
            skill = parts[-2]
        elif len(parts) >= 3:
            skill = parts[-3]
        else:
            skill = parts[-2]
        out.append({
            "skill": skill,
            "file": str(Path(*parts[-2:])),
            "kind": "SKILL.md" if path.name == "SKILL.md" else "reference",
            "when": datetime.fromtimestamp(mtime).strftime("%d.%m %H:%M"),
            "minutes": int((time.time() - mtime) / 60),
        })
    return sorted(out, key=lambda r: r["minutes"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--skills", action="store_true", help="только SKILL.md, без references")
    args = ap.parse_args()

    rows = collect(args.hours, args.skills)
    if not rows:
        print(f"за {args.hours:g} ч навыки не менялись")
        return 0

    print(f"изменения в навыках за {args.hours:g} ч: {len(rows)}")
    for r in rows:
        mark = "основной" if r["kind"] == "SKILL.md" else "файл"
        print(f"  {r['when']} · {r['skill']:32s} · {mark:8s} · {r['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
