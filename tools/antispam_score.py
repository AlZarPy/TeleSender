"""Скор спамности текста: насколько первое сообщение похоже на рассылку.

Оценка не гадает «спам/не спам», а складывает признаки, которые реально бьют
по доставке: ссылка в первых строках, отсутствие имени, капс, рекламные слова,
канцелярит, длина. Проверено на своих текстах и на ответах @SpamBot.

Использование:
    python tools/antispam_score.py docs/first-message-2-final.md
    python tools/antispam_score.py "текст сообщения"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AD_WORDS = (
    "акци", "скидк", "только сегодня", "спецпредложен", "выгодн",
    "уникальн", "лучш", "гарантир", "бесплатно и", "успей",
    "не упусти", "ограниченное предложение", "распродаж",
)
CLERICAL = (
    "уважаемый клиент", "уважаемые", "в рамках", "осуществля",
    "доводим до вашего сведения", "является возможностью",
    "с целью", "данная информация", "настоящим",
)
LINK = re.compile(r"https?://|t\.me/|www\.", re.I)
SHORTENER = re.compile(r"bit\.ly|clck\.ru|goo\.gl|tinyurl|vk\.cc|is\.gd", re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def score(text: str) -> dict:
    t = (text or "").strip()
    head = t[:120]
    first_line = t.splitlines()[0] if t else ""
    links = LINK.findall(t)
    issues: list[dict] = []
    points = 0

    if LINK.search(head):
        points += 4
        issues.append({"code": "link_early", "w": 4,
                       "detail": "ссылка в первых 120 знаках — главный признак рассылки"})
    elif LINK.search(t[:400]):
        points += 2
        issues.append({"code": "link_soon", "w": 2,
                       "detail": "ссылка в первой половине текста"})
    elif links:
        points += 1
        issues.append({"code": "link_any", "w": 1, "detail": "ссылка есть в тексте"})
    if SHORTENER.search(t):
        points += 2
        issues.append({"code": "shortener", "w": 2, "detail": "сокращатель ссылок"})
    if len(links) >= 3:
        points += 3
        issues.append({"code": "many_links", "w": 3, "detail": f"ссылок {len(links)} — три и больше"})
    elif len(links) == 2:
        points += 2
        issues.append({"code": "many_links", "w": 2, "detail": "две ссылки"})
    if "{" not in first_line and not re.search(r"[А-ЯЁ][а-яё]+", first_line[:40]):
        points += 1
        issues.append({"code": "no_name", "w": 1, "detail": "в первой строке нет имени"})
    if re.search(r"[A-ZА-ЯЁ]{5,}", t):
        points += 2
        issues.append({"code": "caps", "w": 2, "detail": "слова капсом"})
    emoji = EMOJI.findall(t)
    if len(emoji) > 8:
        points += 2
        issues.append({"code": "emoji", "w": 2, "detail": f"эмодзи {len(emoji)} — перебор"})
    elif len(emoji) > 4:
        points += 1
        issues.append({"code": "emoji", "w": 1, "detail": f"эмодзи {len(emoji)}"})
    low = t.lower()
    hits = [w for w in AD_WORDS if w in low]
    if hits:
        points += 2
        issues.append({"code": "ad_words", "w": 2, "detail": ", ".join(hits[:4])})
    cler = [w for w in CLERICAL if w in low]
    if cler:
        points += 2
        issues.append({"code": "clerical", "w": 2, "detail": ", ".join(cler[:3])})
    if len(t) > 600:
        points += 1
        issues.append({"code": "long", "w": 1, "detail": f"{len(t)} знаков"})
    if "{" in t:
        issues.append({"code": "spintax", "w": 0,
                       "detail": "есть варианты (спинтаксис) — но одинаковость между аккаунтами это не лечит"})

    if points >= 4:
        verdict = "спам"
    elif points >= 2:
        verdict = "рискованно"
    else:
        verdict = "чисто"
    return {"points": points, "verdict": verdict, "issues": issues,
            "chars": len(t), "links": len(links), "emoji": len(emoji)}


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
