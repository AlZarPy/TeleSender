"""CLI к panel.antispam: оценка спамности текста.

    python tools/antispam_score.py docs/first-message-2-final.md
    python tools/antispam_score.py "текст сообщения"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.antispam import score  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    raw = sys.argv[1]
    path = Path(raw)
    text = path.read_text(encoding="utf-8") if path.exists() else raw
    if "```" in text:
        text = text.split("```")[1]
    res = score(text)
    print(f"оценка: {res['points']} → {res['verdict']}")
    print(f"знаков {res['chars']}, ссылок {res['links']}, эмодзи {res['emoji']}")
    for i in res["issues"]:
        print(f"  [{i['w']:+d}] {i['code']}: {i['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
