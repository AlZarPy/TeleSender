"""Свой набор текстов на каждый аккаунт: чтобы два аккаунта не отправили одно и то же.

Проблема, которую решает модуль: вариантов в шаблоне много, но выбираются они
случайно, поэтому один аккаунт повторяет фразу, а два разных могут отправить
байт-в-байт одинаковый текст разным людям. Для антиспама это признак фермы.

Как устроено:
    • список вариантов строится из шаблона один раз (`message.variants_list`);
    • у каждого варианта есть ровно один владелец-аккаунт, владение считается по
      стабильному хешу номера варианта — так наборы аккаунтов не пересекаются;
    • отправленный вариант отмечается в `used_variants`, повторно этот аккаунт его не берёт;
    • если свои варианты исчерпаны — берём чужие неиспользованные, но не повторяем свои.
"""
from __future__ import annotations

import hashlib

from . import db, message


def owner(variant: int, accounts: list[str]) -> str:
    """Какому аккаунту принадлежит вариант — стабильно и без пересечений."""
    if not accounts:
        return ""
    digest = hashlib.sha1(f"variant:{variant}".encode("utf-8")).hexdigest()
    return accounts[int(digest[:8], 16) % len(accounts)]


def pool_for(account: str, variants: list[str], accounts: list[str]) -> list[str]:
    """Варианты, которые принадлежат этому аккаунту."""
    return [text for idx, text in enumerate(variants) if owner(idx, accounts) == account]


def pick(account: str, campaign_id: int, template: str,
         accounts: list[str] | None = None, stage: int = 1) -> tuple[str, int]:
    """Возвращает (текст, номер варианта), ещё не отправленный этим аккаунтом.

    Приоритет — тексты, переписанные нейросетью под этот аккаунт (`account_texts`):
    они отличаются не порядком вставок, а словами. Спинтаксис остаётся запасным
    вариантом, когда переписанного текста нет.
    """
    rewritten = db.account_texts_get(account, campaign_id, stage)
    for row in rewritten:
        if not db.variant_taken(account, campaign_id, int(row["variant"])):
            return row["text"], int(row["variant"])

    variants = message.variants_list(template)
    if not variants:
        return template, -1

    names = sorted(accounts or [account])

    for idx, _text in enumerate(variants):
        if owner(idx, names) == account and not db.variant_taken(account, campaign_id, idx):
            return variants[idx], idx

    for idx, text in enumerate(variants):
        if not db.variant_taken(account, campaign_id, idx):
            return text, idx

    # все варианты этим аккаунтом уже использованы — работаем по кругу,
    # начиная со своего, чтобы порядок не был одинаковым у всех
    own = [i for i in range(len(variants)) if owner(i, names) == account] or list(range(len(variants)))
    seed = hashlib.sha1(f"{account}:{campaign_id}".encode()).digest()
    idx = own[seed[0] % len(own)]
    return variants[idx], idx


def remember(account: str, campaign_id: int, variant: int) -> None:
    if variant >= 0:
        db.mark_variant(account, campaign_id, variant)
