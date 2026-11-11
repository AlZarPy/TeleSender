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
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config_loader import ConfigError, load_config_from_txt
from csv_loader import normalise

from panel import antispam, brand, checks, db, health, message, metrics, synonyms, watchdog

PANEL_NAME = brand.PANEL
COOKIE = "pochtamt"
SESSION_TTL = 30 * 24 * 3600
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title=f"{brand.APP} · {brand.PANEL}", docs_url=None, redoc_url=None)


@app.middleware("http")
async def no_stale_pages(request: Request, call_next):
    """HTML не кэшируем: после обновления панели видно свежую страницу, а не старую."""
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.get("/healthz", response_class=JSONResponse)
def healthz():
    """Быстрая проверка здоровья: версия, база, воркер, скорость и очередь."""
    alive, worker = db.worker_alive()
    funnel = db.global_funnel()
    try:
        speed = metrics.summary()
    except Exception as exc:  # noqa: BLE001
        speed = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        ab = db.ab_stats()
    except Exception as exc:  # noqa: BLE001
        ab = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        texts = db.variant_stats()
    except Exception as exc:  # noqa: BLE001
        texts = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        objections = db.objection_stats(30)
    except Exception as exc:  # noqa: BLE001
        objections = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        dq = db.dialog_quality_stats(30)
    except Exception as exc:  # noqa: BLE001
        dq = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "build": BUILD if "BUILD" in globals() else "dev",
        "worker": {"alive": alive, "state": worker.get("state") if worker else None},
        "db": funnel,
        "speed": speed,
        "ab": ab,
        "texts": texts,
        "objections": objections,
        "dialog_quality": dq,
    }
BASE = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))
CSS_V = int((BASE / "static" / "style.css").stat().st_mtime)
templates.env.globals.update(
    css_v=CSS_V,
    T=brand.T,
    APP=brand.APP,
    PANEL=brand.PANEL,
    TAGLINE=brand.TAGLINE,
    reason_label=brand.reason_label,
    reason_hint=brand.reason_hint,
    campaign_status=brand.campaign_status,
    target_state=brand.target_state,
    stamp=brand.stamp,
    section_of=brand.section_of,
    crumbs=brand.crumbs,
    plural=brand.plural,
)


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
    """Адрес для телефона: домашняя сеть, а не докер-адаптер 172.17/172.18."""
    try:
        import psutil

        candidates: list[str] = []
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family.name != "AF_INET":
                    continue
                ip = addr.address
                if ip.startswith(("127.", "169.254.")):
                    continue
                if ip.startswith(("172.17.", "172.18.", "172.19.")) or "docker" in name.lower():
                    continue
                candidates.append(ip)
        for prefix in ("192.168.", "10."):
            for ip in candidates:
                if ip.startswith(prefix):
                    return ip
        if candidates:
            return candidates[0]
    except Exception:  # noqa: BLE001
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip.startswith(("192.168.", "10.")):
                return ip
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def build_id() -> str:
    """Короткий хеш сборки — чтобы в подвале было видно, свежая ли страница."""
    try:
        import subprocess

        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "dev"
    except Exception:
        return "dev"


BUILD = build_id()


def render(request: Request, name: str, **ctx):
    alive, worker = db.worker_alive()
    base_ctx = {
        "request": request,
        "panel": PANEL_NAME,
        "worker_alive": alive,
        "worker": worker,
        "stamp_text": brand.stamp(alive),
        "lan_ip": lan_ip(),
        "port": os.environ.get("PANEL_PORT", "8765"),
        "build": BUILD,
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
        copy = antispam.score(campaign.get("template") or "")
        campaign["copy_score"] = copy["points"]
        campaign["copy_verdict"] = copy["verdict"]
        campaign["stats"] = db.campaign_stats(campaign["id"])
    totals_row = db.q1("""SELECT
        SUM(ok=1) ok, SUM(ok=0) failed, COUNT(*) total FROM sends
        WHERE date(ts)=date('now')""")
    totals = {k: ((totals_row[k] if totals_row else 0) or 0) for k in ("ok", "failed", "total")}
    recent = [dict(r) for r in db.q("SELECT * FROM sends ORDER BY id DESC LIMIT 15")]
    events = [dict(r) for r in db.q("SELECT * FROM events ORDER BY id DESC LIMIT 10")]
    return render(request, "dashboard.html", accounts=checks.summary(health.with_health(accounts)),
                  quality=metrics.quality(7), campaigns=campaigns,
                  texts=db.variant_stats(), objections=db.objection_stats(30),
                  dialog_quality=db.dialog_quality_stats(30),
                  funnel=db.global_funnel(),
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
                    recipients: str = Form(""), intro: str = Form(""),
                    min_delay: int = Form(25), max_delay: int = Form(70),
                    hour_limit: int = Form(10), window_start: int = Form(9),
                    window_end: int = Form(21), allow_self: int = Form(0),
                    allow_repeat: int = Form(0), scheduled_at: str = Form(""),
                    attachment: str = Form(""),
                    user: str = Depends(current_user)):
    names: list[str] = []
    for raw in recipients.replace(",", "\n").splitlines():
        value = normalise(raw)
        if value:
            names.append(value)
    if not names:
        raise HTTPException(400, "нет получателей")
    db.upsert_recipients([(n, "", "") for n in names])
    when = scheduled_at.strip().replace("T", " ")
    if when and len(when) == 16:
        when += ":00"
    cid = db.create_campaign(name.strip() or "без названия", template.strip(), names,
                             intro=intro.strip(),
                             min_delay=min_delay, max_delay=max(min_delay, max_delay),
                             hour_limit=max(1, hour_limit),
                             window_start=window_start, window_end=window_end,
                             allow_self=bool(allow_self), allow_repeat=bool(allow_repeat),
                             scheduled_at=when, attachment=attachment.strip())
    db.event("campaign_created", "", f"кампания «{name}»: {len(names)} получателей")
    return RedirectResponse(f"/campaigns/{cid}", status_code=303)


@app.get("/campaigns/{cid}", response_class=HTMLResponse)
def campaign_page(request: Request, cid: int, user: str = Depends(current_user)):
    row = db.q1("SELECT * FROM campaigns WHERE id=?", (cid,))
    if row is None:
        raise HTTPException(404)
    campaign = dict(row)
    stats = db.campaign_stats(cid)
    targets = [dict(r) for r in db.q("""
        SELECT t.recipient_id, t.state, t.reason, t.account, t.updated_at,
               r.username, r.first_name, r.replied, r.last_reply
        FROM campaign_targets t JOIN recipients r ON r.id=t.recipient_id
        WHERE t.campaign_id=? ORDER BY t.updated_at DESC, t.recipient_id LIMIT 200""", (cid,))]
    sends = [dict(r) for r in db.q(
        "SELECT * FROM sends WHERE campaign_id=? ORDER BY id DESC LIMIT 50", (cid,))]
    notes = message.lint(campaign["template"], campaign.get("intro") or "")
    return render(request, "campaign.html", campaign=campaign, stats=stats,
                  targets=targets, sends=sends, notes=notes, worst=message.worst_level(notes),
                  base_left=db.base_not_in_campaign(cid), funnel=db.campaign_funnel(cid),
                  tags=db.tag_names(),
                  seg_never=len(db.segment(cid, never_written=True)),
                  seg_replied=len(db.segment(cid, answered_only=True)))


@app.post("/campaigns/{cid}/targets/{rid}/delete")
def campaign_remove_target(cid: int, rid: int, user: str = Depends(current_user)):
    """Убрать человека из кампании: он остаётся в базе."""
    db.remove_target(cid, rid)
    return RedirectResponse(f"/campaigns/{cid}", status_code=303)


@app.post("/base/delete")
def base_remove(username: str = Form(...), user: str = Depends(current_user)):
    """Удалить из базы совсем: из всех кампаний тоже убирается, квитанции остаются."""
    db.remove_recipient(username)
    return RedirectResponse("/base", status_code=303)


@app.post("/campaigns/{cid}/text")
def campaign_text(cid: int, template: str = Form(""), intro: str = Form(""),
                  action: str = Form("save"), user: str = Depends(current_user)):
    """Сохраняет текст кампании; action=prepare — ещё и превращает слэши в варианты."""
    if db.q1("SELECT id FROM campaigns WHERE id=?", (cid,)) is None:
        raise HTTPException(404)
    if action == "synonyms":
        body = synonyms.enrich(template)
        head = synonyms.enrich(intro)
        total = body["variants"] if body["changed"] else head["variants"]
    elif action == "prepare":
        body = message.prepare(template)
        head = message.prepare(intro)
        total = body["variants"] if body["groups"] else head["variants"]
    else:
        body, head, total = {"text": template}, {"text": intro}, 1
    db.execute("UPDATE campaigns SET template=?, intro=? WHERE id=?",
               (body["text"], head["text"], cid))
    if action == "synonyms":
        db.event("text_synonyms", "", f"кампания #{cid}: синонимов {body.get('replaced', 0)}, вариантов {total}")
        return RedirectResponse(f"/campaigns/{cid}?prepared={total}", status_code=303)
    if action == "prepare":
        db.event("text_prepared", "", f"кампания #{cid}: вариантов {total}")
        return RedirectResponse(f"/campaigns/{cid}?prepared={total}", status_code=303)
    return RedirectResponse(f"/campaigns/{cid}?saved=1", status_code=303)


@app.post("/tools/enrich")
def tools_enrich(text: str = Form(...), user: str = Depends(current_user)):
    """Добавляет автоматические синонимы: стартует/начинается/открывается."""
    return JSONResponse(synonyms.enrich(text))


@app.post("/tools/prepare")
def tools_prepare(text: str = Form(...), user: str = Depends(current_user)):
    """Готовит текст рассылки: слэши → варианты. Возвращает готовый текст и статистику."""
    return JSONResponse(message.prepare(text))


@app.post("/campaigns/{cid}/prepare")
def campaign_prepare(cid: int, user: str = Depends(current_user)):
    """То же самое, но для уже созданной кампании — правит шаблон и вступление."""
    row = db.q1("SELECT * FROM campaigns WHERE id=?", (cid,))
    if row is None:
        raise HTTPException(404)
    body = message.prepare(row["template"])
    intro = message.prepare(row["intro"] or "")
    db.execute("UPDATE campaigns SET template=?, intro=? WHERE id=?",
               (body["text"], intro["text"], cid))
    db.event("text_prepared", "", f"кампания #{cid}: вариантов {body['variants']}")
    return RedirectResponse(f"/campaigns/{cid}?prepared={body['variants']}", status_code=303)


@app.post("/campaigns/{cid}/add")
def campaign_add_recipients(cid: int, usernames: str = Form(""), all_base: int = Form(0),
                            tag: str = Form(""), never_written: int = Form(0),
                            answered_only: int = Form(0), user: str = Depends(current_user)):
    """Добавить в кампанию: список вручную, всю базу или сегмент по фильтру."""
    row = db.q1("SELECT * FROM campaigns WHERE id=?", (cid,))
    if row is None:
        raise HTTPException(404)
    if tag or never_written or answered_only:
        added = db.add_segment(cid, tag=tag.strip(), never_written=bool(never_written),
                               answered_only=bool(answered_only))
        return RedirectResponse(f"/campaigns/{cid}?added={added}", status_code=303)
    if all_base:
        added = db.add_targets(cid)
    else:
        names = [normalise(line) for line in usernames.replace(",", "\n").splitlines()]
        names = [n for n in names if n]
        if not names:
            return RedirectResponse(f"/campaigns/{cid}", status_code=303)
        db.upsert_recipients([(n, "", "") for n in names])
        added = db.add_targets(cid, names)
    return RedirectResponse(f"/campaigns/{cid}?added={added}", status_code=303)


@app.get("/campaigns/{cid}/preview", response_class=HTMLResponse)
def campaign_preview(request: Request, cid: int, user: str = Depends(current_user)):
    row = db.q1("SELECT * FROM campaigns WHERE id=?", (cid,))
    if row is None:
        raise HTTPException(404)
    campaign = dict(row)
    my_name = "Александр"
    for acc in db.accounts_with_config(config_accounts()):
        my_name = acc["my_name"]
        break
    rows = db.q("""SELECT r.username, r.first_name FROM campaign_targets t
                   JOIN recipients r ON r.id=t.recipient_id
                   WHERE t.campaign_id=? ORDER BY t.recipient_id LIMIT 5""", (cid,))
    samples = []
    for target in rows:
        samples.append({
            "username": target["username"],
            "already": db.sent_before(target["username"]),
            "text": message.render(campaign["template"], campaign.get("intro") or "",
                                   my_name, target["first_name"] or ""),
        })
    notes = message.lint(campaign["template"], campaign.get("intro") or "")
    return render(request, "preview.html", campaign=campaign, samples=samples, notes=notes,
                  worst=message.worst_level(notes))


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
    verb = {"start": "кампания запущена", "pause": "кампания на паузе",
            "stop": "кампания остановлена"}[action]
    db.event(f"campaign_{action}", "", f"{verb}: «{row['name']}»")
    return RedirectResponse(f"/campaigns/{cid}", status_code=303)


# ── база получателей ────────────────────────────────────────────────────────
@app.get("/base", response_class=HTMLResponse)
def base_page(request: Request, q: str = "", tag: str = "",
              user: str = Depends(current_user)):
    sql = "SELECT * FROM recipients"
    where: list[str] = []
    params: list = []
    if q.strip():
        like = f"%{q.strip()}%"
        where.append("(username LIKE ? OR first_name LIKE ? OR tags LIKE ?)")
        params += [like, like, like]
    if tag.strip():
        where.append("(',' || replace(tags,' ','') || ',') LIKE ?")
        params.append(f"%,{tag.strip().replace(' ', '')},%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = [dict(r) for r in db.q(sql + " ORDER BY id DESC LIMIT 500", tuple(params))]
    total = db.q1("SELECT COUNT(*) c FROM recipients")
    return render(request, "recipients.html", recipients=rows, query=q, tag=tag,
                  total=total["c"] if total else 0, tags=db.tag_names())


@app.post("/base/tag")
def base_tag(username: str = Form(...), tags: str = Form(""),
             user: str = Depends(current_user)):
    """Проставить теги человеку: так база делится на сегменты."""
    db.execute("UPDATE recipients SET tags=? WHERE username=?", (tags.strip(), username))
    return RedirectResponse(f"/base?q={username}", status_code=303)


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
    db.event("base_import", "", f"разгрузили мешок: +{added}, уже было {existed}")
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
    archives = sorted((BASE.parent / "journal").glob("*.csv"))[-5:] if (BASE.parent / "journal").exists() else []
    return render(request, "logs.html", sends=sends, events=events, archives=archives)


@app.on_event("startup")
def _import_cli_history() -> None:
    """Отправки через main.py кладём в журнал панели при старте, а не только в воркере."""
    try:
        db.init()
        imported = db.import_sent_jsonl()
        if imported:
            db.event("history_import", "cli", f"подтянуто отправок из sent.jsonl: {imported}")
    except Exception:  # noqa: BLE001 — панель должна подняться даже без файла
        pass


@app.post("/logs/clear")
def logs_clear(keep_sends: int = Form(1), user: str = Depends(current_user)):
    """Перед очисткой архивируем в CSV — история не теряется, просто уезжает в файл."""
    made = db.archive_journal(BASE.parent / "journal")
    events, sends = db.clear_events(keep_sends=bool(keep_sends))
    db.event("journal_cleared", "", f"событий {events}, квитанций {sends}, архив: {len(made)} файл(ов)")
    return RedirectResponse("/logs", status_code=303)


@app.get("/logs/export.csv")
def logs_export(user: str = Depends(current_user)):
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["время", "кампания", "аккаунт", "получатель", "результат", "причина"])
    for row in db.q("SELECT * FROM sends ORDER BY id"):
        writer.writerow([row["ts"], row["campaign_id"], row["account"], row["recipient"],
                         "доставлено" if row["ok"] else "ошибка", row["reason"]])
    return Response("\ufeff" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="pochtamt-sends.csv"'})


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: str = Depends(current_user)):
    accounts = health.with_health(db.accounts_with_config(config_accounts()))
    return render(request, "settings.html", accounts=accounts,
                  replied=db.replied(limit=10), today=time.strftime("%Y-%m-%d"),
                  thresholds=watchdog.describe_thresholds())


@app.post("/settings/account")
def settings_account(session_name: str = Form(...), daily_limit: int = Form(20),
                     status: str = Form("active"), warmup_start: str = Form(""),
                     warmup_days: int = Form(7), user: str = Depends(current_user)):
    warmup_start = warmup_start.strip()
    db.set_account(session_name, daily_limit=daily_limit, status=status,
                   paused_until=0 if status == "active" else time.time() + 3600,
                   warmup_start=warmup_start,
                   warmup_days=max(1, min(60, warmup_days)))
    note = f"квота={daily_limit}, статус={status}"
    if warmup_start:
        note += f", прогрев с {warmup_start} ({warmup_days} дн.)"
    db.event("account_settings", session_name, note)
    return RedirectResponse("/settings", status_code=303)


@app.get("/proxies", response_class=HTMLResponse)
def proxies_page(request: Request, user: str = Depends(current_user)):
    accounts = db.accounts_with_config(config_accounts())
    return render(request, "proxies.html", accounts=accounts)


def main() -> None:
    import uvicorn

    db.init()
    db.sync_accounts([a["session_name"] for a in config_accounts()])
    port = int(os.environ.get("PANEL_PORT", "8765"))
    print(f"«{PANEL_NAME}» слушает http://{lan_ip()}:{port}  (пароль в .env: PANEL_PASSWORD)")
    # по умолчанию слушаем все интерфейсы (панель обычно за прокси/туннелем);
    # на сервере ставим PANEL_HOST=127.0.0.1, чтобы порт не торчал наружу
    host = os.environ.get("PANEL_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
