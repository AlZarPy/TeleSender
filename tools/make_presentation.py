"""Сборка видео-презентации «TheПечкин / Почтамт» без монтажной программы.

Пайплайн:
  1) слайды рисуются в HTML (фирменная бумажная тема) и снимаются headless-Chrome 1920×1080;
  2) анимация «путь сообщения» — 150 кадров, снятых тем же способом, склеиваются в клип;
  3) текст озвучивается edge-tts (русский идёт только с мультиязычным голосом);
  4) каждый слайд превращается в сегмент mp4 (картинка + голос с паузами);
  5) сегменты конкатенируются в готовый файл.

Запуск: .venv\\Scripts\\python.exe tools/make_presentation.py
Отдельные этапы: --only slides | flow | voice | build
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from presentation_data import CHAPTERS, FLOW_STEPS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "presentation"
SLIDES_DIR = WORK / "slides"
FRAMES = WORK / "frames"
AUDIO = WORK / "audio"
SEGS = WORK / "segments"

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
EDGE = Path(r"C:\Users\User\AppData\Local\hermes\installs\6b17de8c14938a10\environments"
            r"\7cbb0f53505049e891e31a484408fbc1\venv\Scripts\edge-tts.exe")
VOICE = "en-US-AndrewMultilingualNeural"
W, H, FPS = 1920, 1080, 30
FLOW_FRAMES, FLOW_FPS = 150, 15

BRAND_CSS = """
:root{
  --paper:#f5efe1; --paper-2:#fbf6ec; --ink:#332a22; --muted:#6a5945;
  --line:#d3c3a7; --line-strong:#b9a483; --ochre:#c98a1e; --ok:#2f6b3c; --bad:#8f3421;
}
*{box-sizing:border-box}
html,body{margin:0;width:1920px;height:1080px;overflow:hidden}
body{
  background:
    radial-gradient(1400px 700px at 15% -10%, #fdf9f0 0%, rgba(253,249,240,0) 60%),
    repeating-linear-gradient(0deg, rgba(160,130,90,.035) 0 1px, transparent 1px 30px),
    var(--paper);
  color:var(--ink); font:26px/1.5 "Segoe UI", -apple-system, Roboto, Arial, sans-serif;
  padding:74px 108px 58px; display:flex; flex-direction:column;
}
.kicker{font-size:19px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted);font-weight:700}
h1{font-family:Georgia,"PT Serif",serif;font-size:70px;line-height:1.1;margin:14px 0 10px;max-width:1500px}
.sub{font-size:29px;color:var(--muted);max-width:1300px}
.rule{height:2px;background:var(--line-strong);margin:26px 0 30px;opacity:.8}
.content{flex:1;display:flex;flex-direction:column;justify-content:center}
footer{margin-top:auto;display:flex;justify-content:space-between;align-items:center;
  border-top:1px dashed var(--line);padding-top:16px;font-size:19px;color:var(--muted)}
footer b{color:var(--ink);letter-spacing:.06em}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:22px}
.cards.two{grid-template-columns:repeat(2,1fr)}
.cards.three{grid-template-columns:repeat(3,1fr)}
.card{background:var(--paper-2);border:1px solid var(--line);border-radius:14px;
  padding:26px 24px;box-shadow:0 1px 0 rgba(80,60,35,.06), 0 8px 22px rgba(80,60,35,.06)}
.card .n{font-family:Georgia,serif;font-size:38px;font-weight:700;color:var(--ochre);line-height:1}
.card h3{font-family:Georgia,serif;font-size:30px;margin:10px 0 8px}
.card p{margin:0;font-size:21px;color:var(--muted);line-height:1.45}
.card.warn{border-left:5px solid var(--bad)}
.card.good{border-left:5px solid var(--ok)}
.card.accent{border-left:5px solid var(--ochre)}
.q{font-family:Georgia,serif;font-size:42px;line-height:1.4;max-width:1450px}
.q em{color:var(--ochre);font-style:normal}
.note{font-size:22px;color:var(--muted)}
.big-number{font-family:Georgia,serif;font-size:92px;line-height:1;color:var(--ink)}
/* схема пути сообщения */
.flow{position:relative;height:250px;margin-top:10px}
.node{position:absolute;z-index:3;width:238px;padding:18px 16px;background:var(--paper-2);
  border:1px solid var(--line);border-radius:12px;text-align:center;
  box-shadow:0 6px 18px rgba(80,60,35,.05)}
.node .num{font-size:15px;letter-spacing:.16em;color:var(--muted);font-weight:700}
.node .name{font-family:Georgia,serif;font-size:26px;margin-top:4px}
.node.passed{border-color:#a3c99c;background:#e4f0dd}
.node.active{border-color:var(--ochre);background:#fdf3df;box-shadow:0 0 0 4px rgba(201,138,30,.18)}
.node.active .name{color:#8a5a10}
.link{position:absolute;z-index:1;height:3px;background:var(--line-strong);top:74px}
.link.passed{background:#c98a1e}
.rail{position:absolute;z-index:1;height:3px;background:var(--line-strong);top:9px;opacity:.5}
.rail-passed{position:absolute;z-index:2;height:3px;background:var(--ochre);top:9px}
.dot{position:absolute;z-index:5;width:20px;height:20px;border-radius:50%;
  background:var(--ochre);box-shadow:0 0 0 6px rgba(201,138,30,.22);top:0;margin-left:-10px}
.caption{position:absolute;left:0;right:0;top:182px;font-size:27px;color:var(--ink)}
.caption b{display:block;font-size:31px;margin-bottom:6px}
.caption b{font-family:Georgia,serif}
.caption span{color:var(--muted)}
"""


def slide_page(kicker: str, title: str, body: str, page: int, total: int, sub: str = "") -> str:
    sub_html = f'<p class="sub">{sub}</p>' if sub else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<style>{BRAND_CSS}</style></head><body>
<span class="kicker">{kicker}</span>
<h1>{title}</h1>{sub_html}
<div class="rule"></div>
<div class="content">{body}</div>
<footer><span><b>TheПечкин</b> · Почтамт — панель управления</span>
<span>{page} / {total}</span></footer>
</body></html>"""


def flow_frame(progress: float, page: int, total: int) -> str:
    """Кадр анимации: точка едет по узлам, пройденные подсвечиваются."""
    n = len(FLOW_STEPS)
    step = progress * (n - 1)
    i0 = min(int(step), n - 1)
    frac = step - i0
    i1 = min(i0 + 1, n - 1)

    content_w = W - 2 * 108
    node_w = 238
    gap = (content_w - n * node_w) / (n - 1)
    left = 0
    starts = [left + k * (node_w + gap) for k in range(n)]
    centers = [s + node_w / 2 for s in starts]
    x = centers[i0] + (centers[i1] - centers[i0]) * frac
    current = i0 if frac < 0.5 else i1

    nodes, links = [], []
    for k, (name, _) in enumerate(FLOW_STEPS):
        cls = "active" if k == current else ("passed" if k < current else "")
        nodes.append(
            f'<div class="node {cls}" style="left:{starts[k]:.0f}px;top:34px">'
            f'<div class="num">{k + 1:02d}</div><div class="name">{name}</div></div>')
        if k < n - 1:
            cls = "link passed" if k < current else "link"
            links.append(f'<div class="{cls}" style="left:{starts[k] + node_w:.0f}px;'
                         f'width:{gap:.0f}px"></div>')

    rail_left, rail_right = centers[0], centers[-1]
    rail = (f'<div class="rail" style="left:{rail_left:.0f}px;width:{rail_right - rail_left:.0f}px"></div>'
            f'<div class="rail-passed" style="left:{rail_left:.0f}px;width:{max(0, x - rail_left):.0f}px"></div>')

    name, desc = FLOW_STEPS[current]
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<style>{BRAND_CSS}</style></head><body>
<span class="kicker">Демонстрация</span>
<h1>Путь сообщения</h1>
<div class="rule"></div>
<div class="flow">
{''.join(links)}
{rail}
{''.join(nodes)}
<div class="dot" style="left:{x:.0f}px"></div>
<div class="caption"><b>{current + 1}. {name}</b> <span>— {desc}</span></div>
</div>
<footer><span><b>TheПечкин</b> · Почтамт — панель управления</span>
<span>{page} / {total}</span></footer>
</body></html>"""


def shot(html_path: Path, png_path: Path) -> None:
    subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", f"--window-size={W},{H}",
                    f"--screenshot={png_path}", f"file:///{html_path.as_posix()}"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def render_slides() -> None:
    SLIDES_DIR.mkdir(parents=True, exist_ok=True)
    total = len(CHAPTERS)
    for i, ch in enumerate(CHAPTERS, 1):
        if ch.get("animated"):
            continue
        html = slide_page(ch["kicker"], ch["title"], ch["body"], i, total, ch.get("sub", ""))
        html_path = SLIDES_DIR / f"{ch['key']}.html"
        html_path.write_text(html, encoding="utf-8")
        shot(html_path, SLIDES_DIR / f"{ch['key']}.png")
        print("слайд:", ch["key"])


def render_flow() -> None:
    FRAMES.mkdir(parents=True, exist_ok=True)
    total = len(CHAPTERS)
    page = next(i for i, ch in enumerate(CHAPTERS, 1) if ch.get("animated"))
    for idx in range(FLOW_FRAMES):
        progress = idx / (FLOW_FRAMES - 1)
        html_path = FRAMES / f"flow_{idx:03d}.html"
        html_path.write_text(flow_frame(progress, page, total), encoding="utf-8")
        shot(html_path, FRAMES / f"flow_{idx:03d}.png")
        if idx % 25 == 0:
            print(f"  кадр {idx}/{FLOW_FRAMES}")
    print(f"кадры анимации: {FLOW_FRAMES}")


def render_voice() -> None:
    AUDIO.mkdir(parents=True, exist_ok=True)
    for ch in CHAPTERS:
        target = AUDIO / f"{ch['key']}.mp3"
        subprocess.run([str(EDGE), "--voice", VOICE, "--rate=+4%", "--pitch=-1Hz",
                        "--text", ch["voice"], "--write-media", str(target)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"озвучка: {ch['key']} — {ffprobe_duration(target):.1f} с")


def have_all(kind: str) -> bool:
    if kind == "slides":
        return all((SLIDES_DIR / f"{ch['key']}.png").exists()
                   for ch in CHAPTERS if not ch.get("animated"))
    if kind == "flow":
        return (FRAMES / f"flow_{FLOW_FRAMES - 1:03d}.png").exists()
    if kind == "voice":
        return all((AUDIO / f"{ch['key']}.mp3").exists() for ch in CHAPTERS)
    return False


def build_segments() -> list[Path]:
    SEGS.mkdir(parents=True, exist_ok=True)
    segs: list[Path] = []
    for ch in CHAPTERS:
        key = ch["key"]
        voice = AUDIO / f"{key}.mp3"
        seg = SEGS / f"{key}.mp4"
        if ch.get("animated"):
            video_len = FLOW_FRAMES / FLOW_FPS
            target = max(video_len, ffprobe_duration(voice) + 0.9)
            cmd = ["ffmpeg", "-y", "-framerate", str(FLOW_FPS), "-i", str(FRAMES / "flow_%03d.png"),
                   "-i", str(voice), "-filter_complex",
                   f"[0:v]fps={FPS},scale={W}:{H},"
                   f"tpad=stop_mode=clone:stop_duration={target:.2f},format=yuv420p[v];"
                   f"[1:a]adelay=450|450,apad=pad_dur={target:.2f}[a]",
                   "-map", "[v]", "-map", "[a]", "-t", f"{target:.2f}",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                   "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(seg)]
        else:
            dur = ffprobe_duration(voice) + 0.9
            fade_out = max(0.1, dur - 0.45)
            cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
                   "-i", str(SLIDES_DIR / f"{key}.png"), "-i", str(voice),
                   "-filter_complex",
                   f"[0:v]scale={W}:{H},fps={FPS},"
                   f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out:.2f}:d=0.4,format=yuv420p[v];"
                   f"[1:a]adelay=450|450,apad=pad_dur={dur:.2f}[a]",
                   "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                   "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(seg)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        segs.append(seg)
        print(f"сегмент: {key} — {ffprobe_duration(seg):.1f} с")
    return segs


def concat(segs: list[Path], out: Path) -> None:
    listing = SEGS / "list.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", "-movflags", "+faststart", str(out)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["slides", "flow", "voice", "build"], default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    for folder in (WORK, SLIDES_DIR, FRAMES, AUDIO, SEGS):
        folder.mkdir(parents=True, exist_ok=True)

    if args.only in (None, "slides") and (args.force or not have_all("slides")):
        render_slides()
    if args.only in (None, "flow") and (args.force or not have_all("flow")):
        render_flow()
    if args.only in (None, "voice") and (args.force or not have_all("voice")):
        render_voice()
    if args.only in (None, "build"):
        segs = build_segments()
        out = WORK / "ThePechkin-prezentaciya.mp4"
        concat(segs, out)
        print(f"\nготово: {out} ({ffprobe_duration(out):.1f} с, "
              f"{out.stat().st_size / 1_048_576:.1f} МБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
