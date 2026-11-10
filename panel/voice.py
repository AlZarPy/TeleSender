"""Расшифровка голосовых сообщений из ответов.

Зачем: человеку проще наговорить, чем печатать. Панель должна показать
текст такого ответа в журнале, иначе мы его «не слышим».

Распознаём локально: faster-whisper, модель small, CPU, int8.
Модель грузится один раз на процесс (~15 секунд), само голосовое
на 15 секунд считается за 3–7 секунд. Язык определяется автоматически:
португальский, русский, английский — все поддержаны.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

_MODEL = None
_MODEL_NAME = os.environ.get("SENDERX_WHISPER_MODEL", "small")


def _model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel

        _MODEL = WhisperModel(_MODEL_NAME, device="cpu", compute_type="int8")
    return _MODEL


def transcribe_file(path: str | Path) -> str:
    """Синхронная расшифровка файла. Возвращает текст или "" при неудаче."""
    try:
        segments, _info = _model().transcribe(str(path), vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception:  # noqa: BLE001 — расшифровка не должна ломать скан ответов
        return ""


async def transcribe_message(client, message) -> str:
    """Скачивает голосовое/аудио/кружок и возвращает текст.

    Пустая строка, если это не медиа или распознать не удалось.
    """
    media = getattr(message, "voice", None) or getattr(message, "audio", None) \
        or getattr(message, "video_note", None)
    if not media:
        return ""

    tmp_dir = Path(tempfile.gettempdir())
    suffix = ".ogg" if getattr(message, "voice", None) else ".m4a"
    target = tmp_dir / f"voice_{message.id}_{getattr(message, 'sender_id', 0)}{suffix}"
    try:
        got = await client.download_media(message, file=str(target))
        if not got:
            return ""
        # распознавание в отдельном потоке, чтобы не блокировать цикл Telethon
        return await asyncio.to_thread(transcribe_file, got)
    except Exception:  # noqa: BLE001
        return ""
    finally:
        try:
            target.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
