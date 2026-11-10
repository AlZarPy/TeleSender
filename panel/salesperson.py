"""Ответы в диалогах живым языком.

Правила по-прежнему ловят очевидное (отказ, согласие, «не понял»). Сюда попадает
всё остальное: модель читает последние реплики и отвечает коротко и по-человечески.

Границы заданы здесь, а не в промпте: длина, стоп-фразы, число реплик в диалоге,
запрет на обещания от имени школы и передача живому человеку, если его просят.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from . import db

DEFAULT_MODEL = os.getenv("SENDERX_SALES_MODEL", "anthropic/claude-sonnet-5.5")
FALLBACK_MODEL = "deepseek/deepseek-v4.1-flash-1017"
MAX_CHARS = 220          # длинное сообщение в диалоге сразу выдаёт робота
MAX_REPLIES = 3          # больше трёх реплик без ответного интереса — молчим
MEMORY_TURNS = 30        # сколько реплик диалога помним
MEMORY_CHARS = 6000      # и сколько знаков из них влезает в запрос

# просят человека или спрашивают, кто мы: отвечает живой
HUMAN = re.compile(r"позов|позвон|созвон|набери|человек[а]?\s|руководител|"
                   r"ты\s*бот|вы\s*бот|робот|нейросет|ии\s*отвеч|автоответ", re.I)

# обрывки, по которым видно шаблон; модель их не должна выдавать
BANNED = re.compile(r"уважаемый предприниматель|специальное предложение|не упустите|"
                    r"только сегодня|гарантируем рост|денег назад", re.I)

SYSTEM = """Ты — куратор школы «Терра», пишешь в Telegram человеку, который ответил на первое сообщение.
Пиши как живой человек в переписке: коротко, простыми словами, без канцелярита.

Как звучит живая речь: «ага, понял», «слушайте», «тут такое дело», «да, есть вариант».
Сначала отреагируй на то, что человек сказал. Потом один факт. Потом короткий вопрос.
Не перечисляй программу, если про неё не спросили. Не расписывай всё сразу.

Жёсткие рамки:
- 1–2 фразы, не больше 220 знаков.
- Без маркетинговых штампов: «специальное предложение», «не упустите», «уважаемый предприниматель».
- Не больше одного эмодзи, можно ноль.
- Не обещай того, чего нет: гарантий роста, мест, скидок, трудоустройства.
- Не выдумывай имена наставников, цены и даты, кроме тех, что даны ниже.
- Если спрашивают про цену — участие бесплатное по регистрации.
- Если просят позвонить или спрашивают, человек ты или бот, — не выкручивайся:
  скажи, что сейчас подключится живой куратор и он позвонит.

Факты, которые можно называть:
13 ноября, 15:00, Конгресс-центр ЦМТ, 4-й подъезд, Москва, Краснопресненская наб., 12.
Участие бесплатное, по регистрации на zapuskterra.ru. 41-й поток.
39 мастер-классов, 6 школ, школа «Нейросети» (ведёт Илья Дрозд), разборы с наставниками
в 16:00 и 19:00, наставничество 3 месяца в группе 8–10 человек, раз в неделю.
Направления: продажи, маркетинг, автоматизация, ИИ-агенты, нейропродавец,
контент-завод, вайбкодинг, ИИ в бизнес-процессах.

Отвечай на последнюю реплику по смыслу. Не пересказывай наше первое сообщение."""


def _api_key() -> str:
    key = os.getenv("HERMES_CUSTOM_ROUTERAI_RU_API_KEY") or os.getenv("ROUTERAI_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", ".env")
    try:
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("HERMES_CUSTOM_ROUTERAI_RU_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def replies_so_far(username: str) -> int:
    row = db.q1("SELECT COUNT(*) c FROM events WHERE kind='sales_reply' AND detail LIKE ?",
                (f"%@{username}",))
    return int(row["c"] if row else 0)


def _clean(text: str) -> str:
    text = (text or "").strip().strip('"').strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS]
        for sep in (". ", "! ", "? "):
            pos = cut.rfind(sep)
            if pos > 120:
                return cut[:pos + 1]
        return cut.rstrip() + "…"
    return text


CHAT_FALLBACK = ("Понял. Скину ссылку на группу школы — там программа и записи, "
                 "а по вопросам отвечу тут: ")


def context(history: list[dict]) -> list[dict]:
    """Последние реплики диалога в пределах лимита знаков. Старое отбрасываем."""
    tail = history[-MEMORY_TURNS:]
    total, kept = 0, []
    for item in reversed(tail):
        piece = item["text"][:400]
        if total + len(piece) > MEMORY_CHARS and kept:
            break
        kept.append({"who": item["who"], "text": piece})
        total += len(piece)
    kept.reverse()
    return kept


def compose(history: list[dict], account_name: str, attempts: int = 2) -> str | None:
    """history = [{'who': 'them'|'us', 'text': str}, ...], последняя — входящая."""
    if not _api_key():
        return None
    dialog = "\n".join(
        ("Он: " if h["who"] == "them" else "Ты: ") + h["text"][:400] for h in history[-6:]
    )
    body = json.dumps({
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM + f"\n\nТебя зовут {account_name}."},
            {"role": "user", "content": f"Переписка:\n{dialog}\n\nОтветь одной репликой."},
        ],
        "temperature": 0.7,
        "max_tokens": 220,
    }).encode()
    req = urllib.request.Request(
        "https://routerai.ru/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.load(resp)
        text = (data["choices"][0]["message"].get("content") or "").strip()
    except Exception as exc:  # noqa: BLE001
        db.event("sales_error", account_name, f"{type(exc).__name__}: {str(exc)[:80]}")
        return None
    text = _clean(text)
    if not text or BANNED.search(text):
        if attempts > 1:
            return compose(history, account_name, attempts - 1)
        return None
    return text


def needs_human(text: str) -> bool:
    return bool(HUMAN.search(text or ""))
