"""Подготовка текста рассылки: вступление, варианты, персонализация и проверки.

Три вещи, которые реально влияют на жалобы и попадание в спам:
  1) текст не должен быть одинаковым у всех — варианты через {a|b|c};
  2) обращение по имени — получатель видит, что письмо ему, а не «всем»;
  3) вступление (присказка) объясняет с первых слов, кто и почему пишет.

Всё это здесь: рендер, подсчёт вариантов и линтер «что не так с текстом».
"""
from __future__ import annotations

import random
import re

PH_ME = "<МоёИмя>"
PH_HIM = "<ЕгоИмя>"
SIZE_LIMIT = 900
MAX_LINKS = 2

SPAM_WORDS = (
    "заработок", "заработать", "крипт", "инвестиц", "гарантированн", "быстрый доход",
    "пассивный доход", "бесплатно", "скидка 90", "только сегодня", "успей",
    "нажми на ссылку", "перейди по ссылке", "розыгрыш", "приз", "выигрыш",
)

_SPINTAX = re.compile(r"\{([^{}]*)\}")
_LINK = re.compile(r"https?://|t\.me/|@[A-Za-z0-9_]{4,}")


def expand_spintax(text: str, rng: random.Random | None = None) -> str:
    """{привет|здравствуйте|добрый день} → один из вариантов. Поддерживает вложенность."""
    chooser = rng.choice if rng is not None else random.choice
    for _ in range(10):  # защита от бесконечной вложенности
        if "{" not in text:
            break
        text = _SPINTAX.sub(lambda m: chooser(m.group(1).split("|")), text)
    return text


def variants_count(text: str) -> int:
    """Сколько уникальных комбинаций даёт текст (для предупреждения об одинаковости)."""
    total = 1
    for block in _SPINTAX.findall(text):
        total *= max(1, len(block.split("|")))
    return total


def variants_list(text: str, cap: int = 240) -> list[str]:
    """Все уникальные тексты, которые можно собрать из шаблона (с ограничением).

    Нужен для того, чтобы закрепить за аккаунтом свой набор вариантов: тогда два
    аккаунта не отправят байт-в-байт одинаковую фразу.
    """
    import itertools

    blocks = _SPINTAX.findall(text)
    if not blocks:
        return [text]
    options = [block.split("|") for block in blocks]
    total = 1
    for opt in options:
        total *= max(1, len(opt))
    if total > cap:
        # слишком много комбинаций: перебираем не весь декартов продукт,
        # а cap срезов через равномерный шаг
        out: list[str] = []
        for i in range(cap):
            rng = random.Random(i)
            out.append(expand_spintax(text, rng))
        return list(dict.fromkeys(out))

    out = []
    for combo in itertools.product(*options):
        piece = text
        for block, choice in zip(blocks, combo):
            piece = piece.replace("{" + block + "}", choice, 1)
        out.append(piece)
    return list(dict.fromkeys(out))


def personalise(text: str, my_name: str, his_name: str) -> str:
    name = (his_name or "").strip() or "друг"
    return text.replace(PH_ME, my_name).replace(PH_HIM, name)


def render(template: str, intro: str, my_name: str, his_name: str,
           rng: random.Random | None = None) -> str:
    """Собирает финальный текст: вступление + тело, варианты и имена подставлены."""
    body = personalise(expand_spintax(template, rng), my_name, his_name)
    head = personalise(expand_spintax(intro, rng), my_name, his_name).strip() if intro else ""
    if head and not head.endswith((".", "!", "?", ":", "…")):
        head += ":"
    return (head + "\n\n" + body).strip() if head else body.strip()


def lint(template: str, intro: str = "") -> list[tuple[str, str]]:
    """Проверки качества текста. Возвращает список (уровень, пояснение).

    Уровни: bad — почти гарантированные жалобы; warn — риск; ok — что сделано хорошо.
    """
    notes: list[tuple[str, str]] = []
    full = (intro + "\n" + template).strip()

    if not intro.strip():
        notes.append(("warn", "нет вступления: получатель не понимает, кто пишет и почему"))
    else:
        notes.append(("ok", "есть вступление — первая строка объясняет повод"))

    if PH_HIM not in template:
        notes.append(("warn", "нет <ЕгоИмя>: без обращения по имени жалобы чаще"))
    else:
        notes.append(("ok", "есть обращение по имени"))

    combos = variants_count(template) * max(1, variants_count(intro))
    if combos == 1:
        notes.append(("warn", "текст одинаковый для всех: добавьте варианты {так|иначе}"))
    else:
        notes.append(("ok", f"вариантов текста: {combos}"))

    if len(full) > SIZE_LIMIT:
        notes.append(("warn", f"длинно: {len(full)} символов (лучше до {SIZE_LIMIT})"))

    links = len(_LINK.findall(full))
    if links > MAX_LINKS:
        notes.append(("bad", f"слишком много ссылок/упоминаний: {links} (норма до {MAX_LINKS})"))
    elif links == 0:
        notes.append(("ok", "нет ссылок — меньше похоже на рекламу"))

    letters = [c for c in full if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.5:
        notes.append(("bad", "больше половины букв в верхнем регистре — выглядит как реклама"))

    lowered = full.lower()
    hits = [w for w in SPAM_WORDS if w in lowered]
    if hits:
        notes.append(("bad", "слова-триггеры: " + ", ".join(hits)))

    if "http://" in lowered:
        notes.append(("warn", "ссылка по http:// — замените на https://"))

    return notes


def worst_level(notes: list[tuple[str, str]]) -> str:
    if any(level == "bad" for level, _ in notes):
        return "bad"
    if any(level == "warn" for level, _ in notes):
        return "warn"
    return "ok"


# ── подготовка текста: слэши → варианты ────────────────────────────────────
_URL = re.compile(r"https?://\S+|t\.me/\S+|@\w+")
_WORD = r"[А-Яа-яЁёA-Za-z][\w\-]*"
SLASH_GROUP = re.compile(rf"(?<![\w/.:-])({_WORD}(?:[ \t]+{_WORD})*(?:/{_WORD}(?:[ \t]+{_WORD})*)+)(?![\w/.:-])")


def prepare(text: str) -> dict:
    """Превращает «Привет/здравствуйте» в {Привет|здравствуйте}.

    Что не трогаем: ссылки, юзернеймы, даты и дроби (13/11), уже готовые
    фигурные скобки, пути к файлам. Возвращает текст и статистику.
    """
    protected: list[str] = []

    def keep(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    working = _URL.sub(keep, text)
    working = _SPINTAX.sub(keep, working)

    groups = 0

    def convert(match: re.Match) -> str:
        nonlocal groups
        raw = match.group(1)
        parts = [part.strip() for part in raw.split("/")]
        parts = [part for part in parts if part]
        if len(parts) < 2:
            return raw

        # последний вариант не должен съедать хвост предложения:
        # «Стартует/начинается новый поток» → {Стартует|начинается} новый поток
        tail = ""
        if len(parts[-1].split()) > 1:
            after = working[match.end():match.end() + 1]
            if after and not re.match(r"[.!?,;:)\]}\n\r—–-]", after):
                words = parts[-1].split()
                tail = " " + " ".join(words[1:])
                parts[-1] = words[0]

        groups += 1
        return "{" + "|".join(parts) + "}" + tail

    working = SLASH_GROUP.sub(convert, working)
    for index, value in enumerate(protected):
        working = working.replace(f"\x00{index}\x00", value)

    return {
        "text": working,
        "groups": groups,
        "variants": variants_count(working),
        "changed": working != text,
    }
