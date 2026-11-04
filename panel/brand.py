"""Фирменный словарь TheПечкин.

Одно место, где живут все подписи интерфейса. Технические имена (accounts, campaigns,
targets) остаются в коде и базе — меняется только то, что видит человек.

Правило бренда: юмор в названиях, серьёзность в цифрах.
"""
from __future__ import annotations

APP = "TheПечкин"
PANEL = "Почтамт"
TAGLINE = "записки, которые узнают с первых слов"

# Подписи разделов и сущностей
T = {
    "accounts": "Почтальоны",
    "account": "почтальон",
    "brigade": "бригада почтальонов",
    "campaigns": "Обходы",
    "campaign": "обход",
    "route": "маршрут",
    "bag": "сумка почтальона",
    "rest": "привал",
    "warmup": "обкатка",
    "note": "записка",
    "template": "образец записки",
    "handwritings": "почерки",
    "catchphrase": "присказка",
    "hours": "приёмные часы",
    "gait": "походка",
    "trial": "пробный обход",
    "self_note": "письмо себе",
    "stamps": "штемпели",
    "return_to_sender": "возврат отправителю",
    "receipts": "квитанции",
    "receipt": "квитанция",
    "marks": "отметки на конверте",
    "watchman": "сторож",
    "backmail": "обратная почта",
    "estimate": "прикидка маршрута",
    "telegram_summary": "телеграмма",
    "road_scout": "разведка дороги",
    "credentials": "удостоверения",
    "unload_bag": "разгрузить мешок",
    "inventory": "опись",
}

# Состояния обхода
CAMPAIGN_STATUS = {
    "draft": "черновик",
    "running": "в пути",
    "paused": "на привале",
    "done": "доставлено",
    "stopped": "остановлен",
}

# Состояния получателя в маршруте
TARGET_STATE = {
    "pending": "в маршруте",
    "sent": "квитанция",
    "failed": "отметка",
    "skipped": "пропущен",
}

# Отметки на конверте вместо технических кодов ошибок
REASON = {
    "not_found": "адрес не найден",
    "privacy": "дверь не открыли",
    "forbidden": "заколочено",
    "self": "себе",
    "flood": "привал",
}

REASON_HINT = {
    "not_found": "такого username нет или он давно удалён",
    "privacy": "получатель запретил сообщения от незнакомых",
    "forbidden": "в этот чат писать нельзя",
    "self": "это ваш собственный аккаунт",
    "flood": "Telegram попросил подождать",
}


def reason_label(code: str) -> str:
    """error:TimeoutError → «ДТП: TimeoutError»; известные коды — по-человечески."""
    if not code:
        return ""
    if code in REASON:
        return REASON[code]
    if code.startswith("error:"):
        return "ДТП: " + code.split(":", 1)[1]
    return code


def reason_hint(code: str) -> str:
    return REASON_HINT.get(code, "")


def campaign_status(value: str) -> str:
    return CAMPAIGN_STATUS.get(value, value)


def target_state(value: str) -> str:
    return TARGET_STATE.get(value, value)


def stamp(worker_alive: bool) -> str:
    """Сквозной штемпель в углу страницы."""
    return "ПОЧТАМТ · ДОСТАВЛЕНО" if worker_alive else "ПОЧТАМТ · В ПУТИ"
