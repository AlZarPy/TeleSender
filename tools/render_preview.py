"""Рендер страниц панели в статические файлы — чтобы посмотреть тему без входа."""
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

ROOT = Path(r"C:\Users\User\projects\SenderX")
sys.path.insert(0, str(ROOT))

from panel import brand  # noqa: E402

OUT = Path(r"C:\Users\User\AppData\Local\hermes\cache\scratch\preview")
OUT.mkdir(parents=True, exist_ok=True)

env = Environment(loader=FileSystemLoader(str(ROOT / "panel" / "templates")), autoescape=True)
env.globals.update(
    T={}, APP=brand.APP, PANEL=brand.PANEL, TAGLINE=brand.TAGLINE,
    reason_label=brand.reason_label, reason_hint=brand.reason_hint,
    campaign_status=brand.campaign_status, target_state=brand.target_state,
    stamp=brand.stamp, section_of=brand.section_of, crumbs=brand.crumbs,
    plural=brand.plural,
)


class FakeRequest:
    def __init__(self, path):
        self.url = type("U", (), {"path": path})()
        self.query_params = {}


accounts = [
    {"session_name": "sender1", "my_name": "Александр", "status": "active", "paused_now": False,
     "session_exists": True, "proxy": "socks5://u:p@45.130.124.195:8000", "sent_today": 7,
     "daily_limit": 50, "effective_limit": 15, "left_today": 8, "warmup_day": 1, "warmup_days": 7},
    {"session_name": "sender2", "my_name": "Ольга", "status": "paused", "paused_now": False,
     "session_exists": False, "proxy": "", "sent_today": 0, "daily_limit": 30,
     "effective_limit": 30, "left_today": 30, "warmup_day": 0, "warmup_days": 7},
]
campaigns = [
    {"id": 3, "name": "Записка для Музы", "status": "running", "created_at": "2026-11-05 10:12",
     "stats": {"sent": 12, "total": 40, "pending": 26, "failed": 2, "skipped": 0},
     "scheduled_at": "", "window_start": 10, "window_end": 20, "min_delay": 30, "max_delay": 70,
     "hour_limit": 10, "allow_self": 0, "allow_repeat": 0, "template": "<ЕгоИмя>, здравствуйте!",
     "intro": "Я почтальон Печкин. Принёс записку для вас.", "stopped_reason": ""},
    {"id": 4, "name": "Анонс записи", "status": "draft", "created_at": "2026-11-05 12:00",
     "stats": {"sent": 0, "total": 25, "pending": 25, "failed": 0, "skipped": 0},
     "scheduled_at": "2026-11-06 10:00:00", "window_start": 10, "window_end": 20, "min_delay": 25,
     "max_delay": 60, "hour_limit": 10, "allow_self": 0, "allow_repeat": 0, "template": "текст",
     "intro": "", "stopped_reason": ""},
]
base_ctx = dict(
    lan_ip="192.168.0.107", port=8765, worker_alive=True, worker={"status": "working",
    "detail": "кампания «Записка для Музы»: 26 в очереди"}, accounts=accounts,
)

pages = {
    "dashboard.html": dict(base_ctx, totals={"ok": 12, "total": 14, "failed": 2}, campaigns=campaigns,
        recent=[{"ts": "2026-11-05 12:01", "account": "sender1", "recipient": "durov", "ok": 1, "reason": ""},
                {"ts": "2026-11-05 12:00", "account": "sender1", "recipient": "nobody_x", "ok": 0, "reason": "privacy"}],
        events=[{"ts": "2026-11-05 12:02", "kind": "flood", "account": "sender1", "detail": "пауза 42с"},
                {"ts": "2026-11-05 11:00", "kind": "campaign_start", "account": "", "detail": "кампания запущена"}],
        request=FakeRequest("/")),
    "campaigns.html": dict(base_ctx, campaigns=campaigns, request=FakeRequest("/campaigns")),
    "campaign.html": dict(base_ctx, campaign=campaigns[0],
        stats=campaigns[0]["stats"],
        targets=[{"username": "durov", "first_name": "Павел", "state": "sent", "reason": "",
                  "account": "sender1", "updated_at": "12:01"},
                 {"username": "nobody_x", "first_name": "", "state": "failed", "reason": "privacy",
                  "account": "sender1", "updated_at": "12:00"}],
        sends=[{"ts": "2026-11-05 12:01", "account": "sender1", "recipient": "durov", "ok": 1, "reason": ""}],
        notes=[("ok", "есть вступление — первая строка объясняет повод"),
               ("ok", "есть обращение по имени"), ("ok", "вариантов текста: 4"),
               ("warn", "длинно: 980 символов (лучше до 900)")],
        worst="warn", request=FakeRequest("/campaigns/3")),
    "settings.html": dict(base_ctx, replied=[{"username": "iqmuza2", "first_name": "Муза",
        "last_reply": "2026-11-05 11:20"}], today="2026-11-05",
        thresholds="сторож: стоп при 10 ошибках подряд или 40% ошибок после 20 попыток; "
                   "аккаунт на паузу при 3 отказах подряд",
        request=FakeRequest("/settings")),
    "login.html": dict(base_ctx, error=None, request=FakeRequest("/login")),
}

CSS = (ROOT / "panel" / "static" / "style.css").read_text(encoding="utf-8")

for name, ctx in pages.items():
    html = env.get_template(name).render(**ctx)
    # для file:// подставляем стили прямо в страницу, иначе они не подгрузятся
    html = re.sub(r'<link rel="stylesheet" href="/static/style\.css[^"]*">',
                  f"<style>\n{CSS}\n</style>", html)
    (OUT / name.replace(".html", ".rendered.html")).write_text(html, encoding="utf-8")
    print("готово:", name)
