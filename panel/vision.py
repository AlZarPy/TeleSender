"""Что на картинке и что в видео — для ответов от получателей.

Голосовые закрывает panel.voice, а здесь — фото, скриншоты, документы-картинки
и видео. Работает через vlm.py из Hermes (RouterAI, google/gemini-2.5-flash):
своя модель изображения не принимает.

Для видео берём 4 кадра через ffmpeg и описываем их вместе — этого достаточно,
чтобы понять «прислали фото афиши» или «записали видео с экрана».
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VLM = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "bin" / "vlm.py"
PROMPT = ("Опиши коротко, что на изображении. Если это афиша, билет, скриншот "
          "переписки или документа — перечисли ключевые надписи, даты и суммы.")


def _ask(path: str | Path, prompt: str = PROMPT) -> str:
    """Спросить у модели, что на картинке. Возвращает текст или ""."""
    if not VLM.exists():
        return ""
    try:
        out = subprocess.run([sys.executable, str(VLM), str(path), prompt],
                             capture_output=True, text=True, timeout=120,
                             encoding="utf-8", errors="replace")
        text = (out.stdout or "").strip()
        return text.replace("\n", " ")[:400]
    except Exception:  # noqa: BLE001 — описание не должно ломать скан ответов
        return ""


def _frames(video: str | Path, count: int = 4) -> list[str]:
    """Вытащить несколько кадров из видео во временные файлы."""
    made: list[str] = []
    tmp = Path(tempfile.gettempdir())
    try:
        probe = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                                "format=duration", "-of", "csv=p=0", str(video)],
                               capture_output=True, text=True, timeout=30)
        duration = float((probe.stdout or "0").strip() or 0)
    except Exception:  # noqa: BLE001
        duration = 0
    if duration <= 0:
        duration = 5
    step = max(1.0, duration / (count + 1))
    for i in range(count):
        target = tmp / f"frame_{os.getpid()}_{i}.jpg"
        try:
            subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", str(step * (i + 1)),
                            "-i", str(video), "-frames:v", "1", "-q:v", "4", str(target)],
                           timeout=45, check=False)
            if target.exists() and target.stat().st_size > 3000:
                made.append(str(target))
        except Exception:  # noqa: BLE001
            continue
    return made


def describe_image(path: str | Path) -> str:
    return _ask(path)


def describe_video(path: str | Path) -> str:
    frames = _frames(path)
    parts = []
    for i, frame in enumerate(frames, 1):
        seen = _ask(frame, f"Кадр {i} из видео. {PROMPT}")
        if seen:
            parts.append(seen)
    for frame in frames:
        try:
            Path(frame).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    if not parts:
        return ""
    return f"[видео, {len(parts)} кадра] " + " | ".join(parts)[:400]


async def describe_message(client, message) -> str:
    """Скачивает фото/видео из сообщения и возвращает описание словами."""
    kind = None
    suffix = ".bin"
    if getattr(message, "photo", None):
        kind = "photo"
        suffix = ".jpg"
    elif getattr(message, "video_note", None):
        kind = "video"
        suffix = ".mp4"
    elif getattr(message, "video", None):
        kind = "video"
        suffix = ".mp4"
    elif getattr(message, "document", None):
        mime = getattr(message.document, "mime_type", "") or ""
        if mime.startswith("image/"):
            kind, suffix = "photo", ".jpg"
        elif mime.startswith("video/"):
            kind, suffix = "video", ".mp4"
    if kind is None:
        return ""

    target = Path(tempfile.gettempdir()) / f"media_{message.id}_{getattr(message, 'sender_id', 0)}{suffix}"
    try:
        got = await client.download_media(message, file=str(target))
        if not got:
            return ""
        if kind == "photo":
            text = await asyncio.to_thread(describe_image, got)
            return f"[фото] {text}" if text else ""
        text = await asyncio.to_thread(describe_video, got)
        return text
    except Exception:  # noqa: BLE001
        return ""
    finally:
        try:
            target.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
