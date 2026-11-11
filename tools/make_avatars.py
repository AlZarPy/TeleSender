"""Генерация аватарок в нашем стиле через RouterAI (gemini-3.1-flash-image).

Стиль пула: деловой портрет, тёмный фон, неоновые дуги/свечение, тёплый взгляд,
без пинапа и без пафоса. Один аккаунт — один файл 1024x1024.

    python tools/make_avatars.py --set batch3        # 2 женских + 3 мужских
    python tools/make_avatars.py --set batch3 --only f1
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"
ENV_FILE = Path.home() / "AppData/Local/hermes/.env"
API = "https://routerai.ru/api/v1/images/generations"
MODEL = "google/gemini-3.1-flash-image"

BASE = (
    "Professional business portrait with subtle futuristic context, {subject}. "
    "{prop} "
    "Dark modern interior, soft glowing neon arcs in cyan and violet, holographic UI elements "
    "floating beside the subject, cinematic rim light, sharp focus on the face, warm friendly "
    "smile, confident calm expression, corporate but modern, photorealistic, 50mm lens, "
    "high detail, square composition, head and shoulders. "
    "No text, no letters, no logos, no watermark, no brand marks."
)

_OLD_BASE = (
    "Professional business headshot portrait, {subject}. "
    "Dark modern studio background with soft glowing neon rings in cyan and violet, "
    "subtle bokeh, cinematic rim light, sharp focus on the face, natural friendly smile, "
    "confident calm expression, corporate but warm, photorealistic, 50mm lens, high detail, "
    "square composition, head and shoulders. No text, no logos, no watermark."
)

SETS = {
    "holo": {
        "f3": ("a woman about 32 years old with vivid copper-red wavy hair, black blazer over a "
               "black top, minimal jewelry",
               "She sits at a desk with an open laptop, resting her chin on her hand; a translucent "
               "cyan hologram of a neural-network brain and a small bar chart floats above the screen."),
        "f4": ("a young woman about 27 years old with light brown hair in a loose bun, wearing a "
               "soft light hoodie with headphones around her neck",
               "She sits at a desk with a laptop and a coffee cup; a translucent holographic panel "
               "with a friendly robot icon and a three-item checklist glows beside her."),
        "m4": ("a man about 35 years old with short reddish hair and a neat beard, dark blue suit "
               "over a black turtleneck",
               "He holds a transparent futuristic tablet displaying a glowing holographic envelope "
               "icon; neon light trails curve behind him."),
        "m5": ("a man about 40 years old with short dark hair, trimmed beard, charcoal blazer over "
               "a white shirt, no tie",
               "A translucent holographic dashboard with charts and network nodes floats beside him, "
               "casting soft cyan light on his face."),
        "m6": ("a man about 29 years old with short black hair, clean shaven, black jacket over a "
               "dark green sweater",
               "He stands in a dark studio with a holographic flow diagram of connected nodes "
               "glowing in violet and cyan beside his shoulder."),
    },
    "batch3": {
        "f1": "a woman about 30 years old, blonde shoulder-length hair, light blue eyes, "
              "dark navy blazer, thin gold necklace, minimal makeup",
        "f2": "a woman about 35 years old, dark chestnut hair pulled back, brown eyes, "
              "black turtleneck under a charcoal blazer, small silver earrings",
        "m1": "a man about 33 years old, short dark hair, light stubble, dark blazer over a "
              "black shirt, no tie, thoughtful half-smile, hand near the chin",
        "m2": "a man about 40 years old, short brown hair, short beard, grey blazer over a "
              "white shirt without tie, glasses with thin frames",
        "m3": "a man about 28 years old, short black hair, clean shaven, dark green sweater "
              "under a black jacket, friendly open smile",
    },
}


def api_key() -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("HERMES_CUSTOM_ROUTERAI_RU_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("нет ключа RouterAI в .env")


def generate(prompt: str, out: Path, key: str) -> Path:
    body = json.dumps({"model": MODEL, "prompt": prompt, "size": "1024x1024",
                       "n": 1, "response_format": "b64_json"}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.load(resp)
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        out.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=240) as img:
            out.write_bytes(img.read())
    else:
        raise SystemExit(f"пустой ответ: {str(data)[:300]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="batch3")
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    items = SETS[args.set]
    if args.only:
        items = {k: v for k, v in items.items() if k == args.only}
    key = api_key()
    MEDIA.mkdir(exist_ok=True)

    for name, subject in items.items():
        out = MEDIA / f"av_{args.set}_{name}.png"
        if isinstance(subject, tuple):
            prompt = BASE.format(subject=subject[0], prop=subject[1])
        else:
            prompt = _OLD_BASE.format(subject=subject)
        try:
            t0 = time.time()
            generate(prompt, out, key)
            print(f"{name}: {out.name} · {out.stat().st_size // 1024} КБ · {time.time()-t0:.0f} с")
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: ОШИБКА {type(exc).__name__}: {str(exc)[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
