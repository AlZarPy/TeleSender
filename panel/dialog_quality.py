"""Качество ответов ИИ-продавца: не врёт, не повторяется, не обещает лишнего.

Проверка стоит между моделью и отправкой. Правила делятся на четыре группы:

    факт   — дата, время, адрес, цена не должны противоречить базе фактов;
    повтор — новая реплика не должна быть пересказом уже отправленной;
    обещание — «гарантирую», «трудоустроим», «100%» и подобное запрещены;
    форма  — длина, канцелярит, отсутствие живого обращения.

Использование:
    issues = check(text, history=[...])
    if issues: переспросить модель или взять безопасный шаблон
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# База фактов: то, что бот имеет право утверждать. Остальное — только через человека.
FACTS = {
    "date": "13 ноября",
    "time": "15:00",
    "venue": "Конгресс-центр ЦМТ",
    "address": "Краснопресненская наб., 12",
    "city": "Москва",
    "price": "бесплатн",
    "school": "Школа взрывного роста AI",
    "community": "Терра",
}

# Обещания, за которые потом отвечает человек, а не бот.
BANNED_CLAIMS = (
    (r"трудоустро", "обещание трудоустройства"),
    (r"гарантир\w*\s+(работ|доход|результат)", "гарантия результата"),
    (r"\b100\s?%", "обещание «100%»"),
    (r"зарплат", "обещание зарплаты"),
    (r"инвестиц\w*\s+(доход|прибыл)", "обещание доходности"),
    (r"бесплатн\w*\s+навсегда", "обещание «бесплатно навсегда»"),
    (r"оплат\w*\s+(после|потом)\s+результат", "оплата после результата"),
)

# Канцелярит и шаблонность — сразу выдают робота.
CLERICAL = (
    r"уважаемый\s+(клиент|пользователь)",
    r"в\s+рамках\s+",
    r"осуществля\w+",
    r"является\s+возможност",
    r"с\s+целью\s+",
    r"доводим\s+до\s+вашего\s+сведения",
    r"данн(ая|ый)\s+(информац|предложен)",
)

MAX_CHARS = 240
REPEAT_RATIO = 0.78          # выше — считаем повтором
REPEAT_MIN_WORDS = 4

_DATE = re.compile(r"\b(\d{1,2})\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*", re.I)
_TIME = re.compile(r"\b(\d{1,2})[:.](\d{2})\b")
_HOUSE = re.compile(r"(?:наб\.?|улиц\w*|ул\.?|проспект\w*|пр-т)\s*[^,]{0,30},\s*(\d+\w?)", re.I)
_PRICE = re.compile(r"\b(\d[\d\s]{2,})\s*(?:₽|руб)", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def check_facts(text: str, facts: dict | None = None) -> list[dict]:
    f = facts or FACTS
    out: list[dict] = []
    low = _norm(text)

    want_date = _norm(f["date"])
    if want_date:
        day = want_date.split()[0]
        for m in _DATE.finditer(text):
            found = _norm(m.group(0))
            if found != want_date and m.group(1) != day:
                out.append({"code": "fact_date", "detail": f"названа дата «{m.group(0)}», верно «{f['date']}»"})

    for m in _TIME.finditer(text):
        found = f"{m.group(1)}:{m.group(2)}"
        if found.replace(":", ".") != _norm(f["time"]).replace(":", "."):
            if f"{m.group(1)}:{m.group(2)}" != f["time"]:
                out.append({"code": "fact_time", "detail": f"названо время {found}, верно {f['time']}"})

    for m in _HOUSE.finditer(text):
        if m.group(1) != "12":
            out.append({"code": "fact_address", "detail": f"дом {m.group(1)}, верно 12"})

    if re.search(r"\b\d[\d\s]{2,}\s*(?:₽|руб)", text) and "бесплат" not in low:
        out.append({"code": "fact_price", "detail": "названа цена, а вход бесплатный"})
    return out


def check_repeats(text: str, history: list[dict] | None) -> list[dict]:
    """Сравнение с нашими прошлыми репликами: пересказ того же — брак."""
    out: list[dict] = []
    ours = [h["text"] for h in (history or []) if h.get("who") == "us"][-6:]
    for prev in ours:
        if len(_norm(prev).split()) < REPEAT_MIN_WORDS:
            continue
        ratio = SequenceMatcher(None, _norm(prev), _norm(text)).ratio()
        if ratio >= REPEAT_RATIO:
            out.append({"code": "repeat", "detail": f"совпадение {ratio:.0%} с прошлой репликой"})
            break
    return out


def check_claims(text: str) -> list[dict]:
    out = []
    for pattern, label in BANNED_CLAIMS:
        if re.search(pattern, text, re.I):
            out.append({"code": "claim", "detail": label})
    return out


def check_form(text: str) -> list[dict]:
    out: list[dict] = []
    body = (text or "").strip()
    if not body:
        return [{"code": "empty", "detail": "пустой ответ"}]
    if len(body) > MAX_CHARS:
        out.append({"code": "long", "detail": f"{len(body)} знаков при норме {MAX_CHARS}"})
    for pattern in CLERICAL:
        if re.search(pattern, body, re.I):
            out.append({"code": "clerical", "detail": f"канцелярит: {pattern}"})
            break
    if body.count("!") >= 3:
        out.append({"code": "tone", "detail": "три и более восклицательных знака"})
    if re.search(r"[A-ZА-Я]{6,}", body):
        out.append({"code": "tone", "detail": "капс"})
    return out


def check(text: str, history: list[dict] | None = None,
          facts: dict | None = None) -> list[dict]:
    """Все замечания к реплике. Пустой список — реплику можно отправлять."""
    issues = check_form(text) + check_claims(text) + check_facts(text, facts) \
        + check_repeats(text, history)
    seen, unique = set(), []
    for i in issues:
        if i["code"] not in seen:
            seen.add(i["code"])
            unique.append(i)
    return unique


def summarise(codes: list[str]) -> list[dict]:
    """Сводка по кодам замечаний — для панели и /healthz."""
    labels = {
        "fact_date": "неверная дата",
        "fact_time": "неверное время",
        "fact_address": "неверный адрес",
        "fact_price": "неверная цена",
        "repeat": "повтор сказанного",
        "claim": "лишнее обещание",
        "long": "слишком длинно",
        "clerical": "канцелярит",
        "tone": "тон",
        "empty": "пустой ответ",
    }
    counts: dict[str, int] = {}
    for code in codes:
        counts[code] = counts.get(code, 0) + 1
    total = sum(counts.values()) or 1
    return [{"code": c, "label": labels.get(c, c), "count": n,
             "share": round(n / total, 3)}
            for c, n in sorted(counts.items(), key=lambda kv: -kv[1])]
