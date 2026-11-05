"""Автоматические синонимы: разнообразит текст, не меняя смысла.

Зачем: одинаковые формулировки — главный признак рассылки для фильтров Telegram.
Слэши работают, когда автор сам придумал варианты; синонимы добавляют разнообразие
там, где автор об этом не думал.

Правила:
- только слова с одинаковым смыслом (не «дорого/дешево», а «стартует/начинается»);
- регистр сохраняется: «Стартует» → «{Стартует|Начинается}»;
- внутри готовых {…}, ссылок и @упоминаний ничего не меняется.
"""
from __future__ import annotations

import re

# группы взаимозаменяемых слов (первое — основное)
SYNONYMS: dict[str, tuple[str, ...]] = {
    "стартует": ("стартует", "начинается", "открывается", "запускается"),
    "начало": ("начало", "старт"),
    "приглашаем": ("приглашаем", "зовём", "ждём"),
    "приглашение": ("приглашение", "пригласительный"),
    "программа": ("программа", "проект"),
    "поток": ("поток", "набор", "волна"),
    "участники": ("участники", "команда"),
    "бесплатно": ("бесплатно", "без оплаты", "даром"),
    "подробности": ("подробности", "детали"),
    "успейте": ("успейте", "не опоздайте"),
    "места": ("места", "квоты"),
    "наставник": ("наставник", "ментор"),
    "предприниматели": ("предприниматели", "основатели бизнеса"),
    "результат": ("результат", "итог"),
    "быстрее": ("быстрее", "скорее"),
    "написать": ("написать", "сообщить"),
    "ответить": ("ответить", "откликнуться"),
    "посмотреть": ("посмотреть", "взглянуть", "ознакомиться"),
    "встреча": ("встреча", "созвон"),
    "сегодня": ("сегодня", "уже сейчас"),
}

_SAFE = re.compile(r"\{[^{}]*\}|https?://\S+|t\.me/\S+|@\w+|<[^<>]+>")

# слово (в нижнем регистре) → его группа
_WORD_TO_GROUP: dict[str, tuple[str, ...]] = {}
for _group in SYNONYMS.values():
    for _word in _group:
        _WORD_TO_GROUP[_word.lower()] = _group

# одно выражение сразу на все слова: длинные первыми,
# чтобы «основатели бизнеса» не разваливалось на два совпадения
_ALL = re.compile(
    r"(?<![А-Яа-яЁёA-Za-z])("
    + "|".join(re.escape(w) for w in sorted(_WORD_TO_GROUP, key=len, reverse=True))
    + r")(?![А-Яа-яЁёA-Za-z])",
    re.IGNORECASE,
)


def _match_case(source: str, target: str) -> str:
    """Подгоняет регистр замены под исходное слово."""
    if not target:
        return target
    if source.isupper() and len(source) > 1:
        return target.upper()
    if source[:1].isupper():
        return target[:1].upper() + target[1:]
    if source[:1].islower():
        return target[:1].lower() + target[1:]
    return target


def _spintax(found: str, group: tuple[str, ...]) -> str:
    options: list[str] = []
    for option in group:
        variant = _match_case(found, option)
        if variant.lower() not in [o.lower() for o in options]:
            options.append(variant)
    if len(options) < 2:
        return found
    return "{" + "|".join(options) + "}"


def enrich(text: str) -> dict:
    """Расставляет варианты синонимов. Возвращает текст и статистику."""
    protected: list[str] = []

    def keep(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    working = _SAFE.sub(keep, text)
    replaced = 0

    def swap(match: re.Match) -> str:
        nonlocal replaced
        found = match.group(0)
        group = _WORD_TO_GROUP.get(found.lower())
        if not group:
            return found
        result = _spintax(found, group)
        if result != found:
            replaced += 1
        return result

    working = _ALL.sub(swap, working)
    for index, value in enumerate(protected):
        working = working.replace(f"\x00{index}\x00", value)

    return {
        "text": working,
        "replaced": replaced,
        "changed": working != text,
        "variants": variants_count(working),
    }


def variants_count(text: str) -> int:
    """Сколько разных сообщений можно собрать из текста."""
    total = 1
    for block in re.findall(r"\{([^{}]*)\}", text):
        total *= max(1, len([p for p in block.split("|") if p.strip()]))
    return total
