"""Прогоняет ревью Sonnet по частям: несколько вызовов вместо одного огромного."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"

CHUNKS = {
    "панель-2": "panel/db.py,panel/unique.py,panel/facts.py",
    "диалоги": "panel/dialog_quality.py,panel/salesperson.py,panel/followup.py,panel/stages.py",
    "тексты": "panel/antispam.py,tools/rewrite_variants.py",
}


def main() -> int:
    out = ROOT / "docs" / "sonnet-review.md"
    for name, files in CHUNKS.items():
        print(f"\n### {name}: {files}", flush=True)
        res = subprocess.run([str(PY), "tools/sonnet_review.py", "--files", files],
                             cwd=str(ROOT), capture_output=True, text=True, timeout=600)
        text = (res.stdout or "") + (res.stderr or "")
        with out.open("a", encoding="utf-8") as fh:
            fh.write(f"\n\n## {name}\n\n{text}\n")
        print(text[-1500:], flush=True)
    print("\nготово, всё в docs/sonnet-review.md", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
