"""Стадии диалога: что можно и чего нельзя на каждом шаге переписки.

Идея из открытого SalesGPT (MIT): агент знает, где он в разговоре, и не продаёт
на первом слове, не повторяет анонс и не объясняет то, что человек уже понял.

Переходы считает код по признакам (был ли анонс, звучало ли возражение, спросили
ли адрес), модель только выбирает формулировку внутри стадии.
"""
from __future__ import annotations

import re

from . import db

# ── признаки ────────────────────────────────────────────────────────────────
REFUSE = re.compile(r"не\s*интерес|не\s*надо|не\s*пиш|отстань|это\s*спам|отпис|удали\s*меня", re.I)
OBJECTION = re.compile(r"далек|не\s*могу|нет\s*врем|дорого|позже|не\s*в\s*москв|другой\s*город|"
                       r"не\s*получится|занят|подумаю", re.I)
CLOSE = re.compile(r"адрес|где\s+проход|во\s*сколько|регистрац|билет|ссылк|записаться|как\s+попасть", re.I)
PAIN = re.compile(r"не\s*успева|теря(ем|ю)|рутин|съеда|много\s*времени|вручную|не\s*хватает", re.I)
NICHE = re.compile(r"опт|розниц|услуг|стройк|строит|ремонт|производств|завод|логистик|доставк|"
                   r"общепит|кафе|ресторан|медицин|клиник|образовани|школ|курс|недвижим|агентств|"
                   r"маркетплейс|магазин|айти|софт|сайт|маркетинг|реклам|юрист|бухгалтер|"
                   r"груз|авто|мебель|одежд|косметик|красот|салон|фитнес|туризм|отел|"
                   r"франшиз|импорт|экспорт|вэд", re.I)

STAGES = ("intro", "qualify", "value", "needs", "solution", "objection", "close", "end")
RANK = {name: i for i, name in enumerate(STAGES)}

# что разрешено и что запрещено на стадии
RULES = {
    "intro": ("представиться, ответить на вопрос по факту",
              "цена, ссылки, анонс, презентация программы"),
    "qualify": ("один уточняющий вопрос о его деле",
                "рассказ о программе, ссылки, длинные списки"),
    "value": ("1–2 факта под его нишу и один вопрос",
              "пересказывать программу дня, повторять первое сообщение"),
    "needs": ("открытый вопрос про его процесс и потери времени",
              "говорить про запись и адрес"),
    "solution": ("адрес, время, что взять с собой",
                 "повторный анонс, второй постер, ещё один рассказ о школе"),
    "objection": ("один ответ по существу возражения и вопрос",
                  "давление, скидки, уговоры, «ну приезжайте»"),
    "close": ("одна ссылка и один следующий шаг",
              "вопросы «а вы чем занимаетесь», повторная продажа"),
    "end": ("ничего", "любые сообщения"),
}


def block(stage: str) -> str:
    """Кусок промпта под текущую стадию."""
    ok, no = RULES.get(stage, RULES["intro"])
    return (f"Сейчас этап разговора: {stage}. "
            f"Можно: {ok}. Нельзя: {no}. Одна реплика, не больше двух фраз.")


def current(username: str) -> str:
    row = db.q1("SELECT stage FROM dialog_state WHERE username=?", (username,))
    return (row["stage"] if row else "") or "intro"


def signals(username: str) -> dict:
    """Что уже произошло в диалоге: отправляли ли анонс, сколько реплик."""
    invited = bool(db.q1(
        "SELECT 1 FROM events WHERE kind IN ('followup','sales_reply') "
        "AND detail LIKE ? AND detail LIKE '%announce%'", (f"%@{username}%",)))
    replies = db.q1("SELECT COUNT(*) c FROM events WHERE kind='sales_reply' AND detail LIKE ?",
                    (f"%@{username}%",))
    return {"announced": invited, "replies": int(replies["c"] if replies else 0)}


def decide(text: str, prev: str, *, announced: bool = False) -> str:
    """Новая стадия по входящей реплике.

    Правило: стадия не откатывается назад. Из objection можно вернуться в работу,
    во всех остальных случаях «наш опт» после отправленного анонса не возвращает
    разговор на стадию презентации.
    """
    t = (text or "").strip()
    prev = prev or "intro"

    if REFUSE.search(t):
        return "end"
    if prev == "end":
        return "end"
    if OBJECTION.search(t):
        return "objection"
    if CLOSE.search(t):
        return "close"

    if PAIN.search(t):
        cand = "needs"
    elif NICHE.search(t) and len(t.split()) <= 6:
        cand = "value"
    elif prev == "objection":
        cand = "value"          # возражение снято — возвращаемся к делу
    elif prev == "intro":
        cand = "qualify"
    elif announced and prev in ("value", "needs", "qualify"):
        cand = "solution"
    else:
        cand = prev

    if prev == "objection":
        return cand
    return cand if RANK.get(cand, 0) >= RANK.get(prev, 0) else prev


def update(username: str, text: str) -> str:
    """Пересчитывает стадию, сохраняет и возвращает её."""
    prev = current(username)
    info = signals(username)
    stage = decide(text, prev, announced=info["announced"])
    db.execute("""INSERT INTO dialog_state(username, stage, updated_at) VALUES(?,?,datetime('now','localtime'))
                  ON CONFLICT(username) DO UPDATE SET stage=excluded.stage,
                                                      updated_at=excluded.updated_at""",
               (username, stage))
    return stage


def mark(username: str, stage: str) -> None:
    """Принудительная стадия — когда код сам знает, что произошло (отправили анонс)."""
    db.execute("""INSERT INTO dialog_state(username, stage, updated_at) VALUES(?,?,datetime('now','localtime'))
                  ON CONFLICT(username) DO UPDATE SET stage=excluded.stage,
                                                      updated_at=excluded.updated_at""",
               (username, stage))


def stalled(username: str, limit_minutes: int = 60 * 12) -> bool:
    """Диалог не двигается: стадия не менялась дольше limit_minutes."""
    row = db.q1("""SELECT updated_at FROM dialog_state WHERE username=?""", (username,))
    if not row:
        return False
    row2 = db.q1("""SELECT (julianday('now','localtime') - julianday(?)) * 1440 AS minutes""",
                 (row["updated_at"],))
    return bool(row2) and float(row2["minutes"] or 0) > limit_minutes
