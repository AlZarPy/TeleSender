"""Собирает лист из аватарок: 5 портретов в ряд с подписями.

    python tools/make_sheet.py media/av_batch3_*.png --out media/sheet_batch3.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

THUMB = 320
PAD = 12
LABEL_H = 34


def load_font(size: int = 18):
    for path in (r"C:/Windows/Fonts/segoeui.ttf", r"C:/Windows/Fonts/arial.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="media/sheet.png")
    args = ap.parse_args()

    paths = []
    for pattern in args.files:
        p = Path(pattern)
        if p.exists():
            paths.append(p)
        else:
            paths.extend(sorted(Path().glob(pattern)))
    paths = [p for p in paths if p.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    if not paths:
        print("нет файлов")
        return 1

    cols = len(paths)
    width = cols * THUMB + (cols + 1) * PAD
    height = THUMB + LABEL_H + 2 * PAD
    sheet = Image.new("RGB", (width, height), (245, 239, 225))  # бумажный фон панели
    draw = ImageDraw.Draw(sheet)
    font = load_font()

    for i, p in enumerate(paths):
        img = Image.open(p).convert("RGB")
        side = min(img.size)
        img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                        (img.width + side) // 2, (img.height + side) // 2))
        img = img.resize((THUMB, THUMB), Image.LANCZOS)
        x = PAD + i * (THUMB + PAD)
        sheet.paste(img, (x, PAD))
        label = p.stem.replace("av_batch3_", "").replace("av_", "")
        draw.text((x + 6, PAD + THUMB + 8), label, fill=(51, 42, 34), font=font)

    out = Path(args.out)
    sheet.save(out)
    print(f"лист: {out} · {sheet.size[0]}x{sheet.size[1]} · {out.stat().st_size // 1024} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
