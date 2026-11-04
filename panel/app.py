"""«Почтамт» — веб-панель SenderX.

Запуск:  python -m panel.app            (http://<ip>:8765)
Пароль:  PANEL_PASSWORD из .env (генерируется при первом запуске)

Панель только управляет состоянием в SQLite; отправкой занимается panel.worker.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import socket
import time
import urllib.parse
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config_loader import ConfigError, load_config_from_txt
from csv_loader import normalise

from panel import db

PANEL_NAME = "Почтамт"
COOKIE = "pochtamt"
SESSION_TTL = 30 * 24 * 3600
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

app = FastAPI(title=PANEL_NAME, docs_url=None, redoc_url=None)
BASE = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


# ── доступ ──────────────────────────────────────────────────────────────────
def _env_value(key: str, default: str = "") -> str:
    if os.environ.get(key):
        return os.environ[key]
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return default


def ensure_secrets() -> tuple[str, str]:
    """Пароль и ключ подписи: из .env или генерируем и сохраняем туда."""
    password, secret = _env_value("PANEL_PASSWORD"), _env_value("PANEL_SECRET")
    lines = []
    if not password:
        password = secrets.token_urlsafe(12)
        lines.append(f"PANEL_PASSWORD={password}")
    if not secret:
        secret = secrets.token_hex(32)
        lines.append(f"PANEL_SECRET={secret}")
    if lines:
        with ENV_PATH.open("a", encoding="utf-8") as fh:
            fh.write("\n# панель «Почтамт»\n" + "\n".join(lines) + "\n")
    return password, secret


PANEL_PASSWORD, PANEL_SECRET = ensure_secrets()


def _sign(ts: str) -> str:
    mac = hmac.new(PANEL_SECRET.encode(), ts.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def make_cookie() -> str:
    ts = str(int(time.time()))
    return f"{ts}.{_sign(ts)}"


def cookie_valid(value: str | None) -> bool:
    if not value or "." not in value:
        return False
    ts, sig = value.split(".", 1)
    if not ts.isdigit() or time.time() - int(ts) > SESSION_TTL:
        return False
    return hmac.compare_digest(sig, _sign(ts))


def current_user(request: Request) -> str:
    if not cookie_valid(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return "operator"


# ── общие данные для шаблонов ───────────────────────────────────────────────
def config_accounts() -> list[dict]:
    try:
        return load_config_from_txt(None, quiet=True)
    except ConfigError:
        return []


def lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def render(request: Request, name: str, **ctx):
    alive, worker = db.worker_alive()
    base_ctx = {
        "request": request,
        "panel": PANEL_NAME,
        "worker_alive": alive,
        "worker": worker,
        "lan_ip": lan_ip(),
        "port": os.environ.get("PANEL_PORT", "8765"),
    }
    return templates.TemplateResponse(request, name, {**base_ctx, **ctx})


# ── вход ────────────────────────────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return render(request, "login.html", error=error)


@app.post("/login")
def login_submit(request: Request, password: str = Form("")):
    if not hmac.compare_digest(password.strip(), PANEL_PASSWORD):
        db.event("login_failed", "", request.client.host if request.client else "")
        return RedirectResponse("/login?error=1", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, make_cookie(), max_age=SESSION_TTL, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ── дашборд ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user: str = Depends(current_user)):
    accounts = db.accounts_with_config(config_accounts())
    campaigns = [dict(r) for r in db.q("SELECT * FROM campaigns ORDER BY id DESC LIMIT 5")]
    for campaign in campaigns:
        campaign["stats"] = db.campaign_stats(campaign["id"])
    totals_row = db.q1("""SELECT
        SUM(ok=1) ok, SUM(ok=0) failed, COUNT(*) total FROM sends
        WHERE date(ts)=date('now')""")
    totals = {k: ((totals_row[k] if totals_row else 0) or 0) for k in ("ok", "failed", "total")}
    recent = [dict(r) for r in db.q("SELECT * FROM sends ORDER BY id DESC LIMIT 15")]
    events = [dict(r) for r in db.q("SELECT * FROM events ORDER BY id DESC LIMIT 10")]
    return render(request, "dashboard.html", accounts=accounts, campaigns=campaigns,
                  totals=totals, recent=recent, events=events)


# ── кампании ────────────────────────────────────────────────────────────────
@app.get("/campaigns", response_class=HTMLResponse)
def campaigns_page(request: Request, user: str = Depends(current_user)):
    items = []
    for row in db.q("SELECT * FROM campaigns ORDER BY id DESC"):
        campaign = dict(row)
        campaign["stats"] = db.campaign_stats(campaign["id"])
        items.append(campaign)
    return render(request, "campaigns.html", campaigns=items)


@app.post("/campaigns")
def campaign_create(request: Request, name: str = Form(...), template: str = Form(...),
                    recipients: str = Form(""), min_delay: int = Form(25),
                    max_delay: int = Form(70), window_start: int = Form(9),
                    window_end: int = Form(21), allow_self: int = Form(0),
                    user: str = Depends(current_user)):
    names: list[str] = []
    for raw in recipients.replace(",", "\n").splitlines():
        value = normalise(raw)
        if value:
            names.append(value)
    if not names:
        raise HTTPException(400, "нет получателей")
    db.upsert_recipients([(n, "", "") for n in names])
    cid = db.create_campaign(name.strip() or "без названия", template.strip(), names,
                             min_delay=min_delay, max_delay=max(min_delay, max_delay),
                             window_start=window_start, window_end=window_end,
                             allow_self=bool(allow_self))
    db.event("campaign_created", "", f"«{name}»: {len(names)} получателей")
    return RedirectResponse(f"/campaigns/{cid}", status_code=303)


@app.get("/campaigns/{cid}", response_class=HTMLResponse)
def campaign_page(request: Request, cid: int, user: str = Depends(current_user)):
    row = db.q1("SELECT * FROM campaigns WHERE id=?", (cid,))
    if row is None:
        raise HTTPException(404)
    campaign = dict(row)
    stats = db.campaign_stats(cid)
    targets = [dict(r) for r in db.q("""
        SELECT t.state, t.reason, t.account, t.updated_at, r.username, r.first_name
        FROM campaign_targets t JOIN recipients r ON r.id=t.recipient_id
        WHERE t.campaign_id=? ORDER BY t.updated_at DESC, t.recipient_id LIMIT 200""", (cid,))]
    sends = [dict(r) for r in db.q(
        "SELECT * FROM sends WHERE campaign_id=? ORDER BY id DESC LIMIT 50", (cid,))]
    return render(request, "campaign.html", campaign=campaign, stats=stats,
                  targets=targets, sends=sends)


@app.post("/campaigns/{cid}/{action}")
def campaign_action(cid: int, action: str, user: str = Depends(current_user)):
    if action not in ("start", "pause", "stop", "delete"):
        raise HTTPException(400)
    row = db.q1("SELECT * FROM campaigns WHERE id=?", (cid,))
    if row is None:
        raise HTTPException(404)
    if action == "delete":
        db.execute("DELETE FROM campaign_targets WHERE campaign_id=?", (cid,))
        db.execute("DELETE FROM campaigns WHERE id=?", (cid,))
        return RedirectResponse("/campaigns", status_code=303)
    db.set_campaign_status(cid, {"start": "running", "pause": "paused", "stop": "stopped"}[action])
    db.event(f"campaign_{action}", "", f"«{row['name']}»")
    return RedirectResponse(f"/campaigns/{cid}", status_code=303)


# ── база получателей ────────────────────────────────────────────────────────
@app.get("/base", response_class=HTMLResponse)
def base_page(request: Request, q: str = "", user: str = Depends(current_user)):
    sql = "SELECT * FROM recipients"
    params: tuple = ()
    if q.strip():
        sql += " WHERE username LIKE ? OR first_name LIKE ? OR tags LIKE ?"
        like = f"%{q.strip()}%"
        params = (like, like, like)
    rows = [dict(r) for r in db.q(sql + " ORDER BY id DESC LIMIT 500", params)]
    total = db.q1("SELECT COUNT(*) c FROM recipients")
    return render(request, "recipients.html", recipients=rows, query=q,
                  total=total["c"] if total else 0)


@app.post("/base/import")
def base_import(recipients: str = Form(""), tags: str = Form(""),
                user: str = Depends(current_user)):
    parsed: list[tuple[str, str, str]] = []
    for raw in recipients.replace(",", "\n").splitlines():
        line = raw.strip()
        if not line:
            continue
        first_name = ""
        if ";" in line:
            line, _, first_name = line.partition(";")
        value = normalise(line)
        if value:
            parsed.append((value, first_name.strip(), tags.strip()))
    added, existed = db.upsert_recipients(parsed)
    db.event("base_import", "", f"добавлено {added}, уже было {existed}")
    return RedirectResponse(f"/base?q=&imported={added}", status_code=303)


@app.post("/base/block")
def base_block(username: str = Form(...), blocked: int = Form(1),
               user: str = Depends(current_user)):
    db.block_recipient(username, bool(blocked))
    return RedirectResponse("/base", status_code=303)


# ── журналы и настройки ─────────────────────────────────────────────────────
@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, user: str = Depends(current_user)):
    sends = [dict(r) for r in db.q("SELECT * FROM sends ORDER BY id DESC LIMIT 300")]
    events = [dict(r) for r in db.q("SELECT * FROM events ORDER BY id DESC LIMIT 100")]
    return render(request, "logs.html", sends=sends, events=events)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: str = Depends(current_user)):
    accounts = db.accounts_with_config(config_accounts())
    return render(request, "settings.html", accounts=accounts)


@app.post("/settings/account")
def settings_account(session_name: str = Form(...), daily_limit: int = Form(20),
                     status: str = Form("active"), user: str = Depends(current_user)):
    db.set_account(session_name, daily_limit=daily_limit, status=status,
                   paused_until=0 if status == "active" else time.time() + 3600)
    db.event("account_settings", session_name, f"лимит={daily_limit}, статус={status}")
    return RedirectResponse("/settings", status_code=303)


def main() -> None:
    import uvicorn

    db.init()
    db.sync_accounts([a["session_name"] for a in config_accounts()])
    port = int(os.environ.get("PANEL_PORT", "8765"))
    print(f"«{PANEL_NAME}» слушает http://{lan_ip()}:{port}  (пароль в .env: PANEL_PASSWORD)")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
