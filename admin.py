import datetime
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import check_credentials, require_admin
from client_auth import hash_token
from db import get_db
from models import AgentAuditLog, AgentClient
from pricing import cost_usd

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def fmt_cost(n: float) -> str:
    return f"${n:,.2f}"


templates.env.filters["fmt_tokens"] = fmt_tokens
templates.env.filters["fmt_cost"] = fmt_cost


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": None}
    )


@router.post("/login")
def login_submit(
    request: Request, username: str = Form(...), password: str = Form(...)
):
    if not check_credentials(username, password):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Usuário ou senha incorretos"}
        )
    request.session["is_admin"] = True
    return RedirectResponse(url="/admin/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    redirect = require_admin(request)
    if redirect:
        return redirect

    now = datetime.datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    clients_count = db.query(AgentClient).count()

    month_rows = (
        db.query(
            AgentAuditLog.client_name,
            func.count(AgentAuditLog.id).label("requests"),
            func.coalesce(func.sum(AgentAuditLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AgentAuditLog.output_tokens), 0).label("output_tokens"),
        )
        .filter(AgentAuditLog.created_at >= month_start)
        .group_by(AgentAuditLog.client_name)
        .all()
    )

    usage = [
        {
            "client_name": row.client_name,
            "requests": row.requests,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cost": cost_usd(row.input_tokens, row.output_tokens),
        }
        for row in month_rows
    ]
    usage.sort(key=lambda u: u["cost"], reverse=True)
    max_cost = max((u["cost"] for u in usage), default=0) or 1

    calls_month = sum(u["requests"] for u in usage)
    tokens_month = sum(u["input_tokens"] + u["output_tokens"] for u in usage)
    cost_month = sum(u["cost"] for u in usage)

    recent = (
        db.query(AgentAuditLog)
        .order_by(AgentAuditLog.created_at.desc())
        .limit(8)
        .all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "clients_count": clients_count,
            "calls_month": calls_month,
            "tokens_month": tokens_month,
            "cost_month": cost_month,
            "usage": usage,
            "max_cost": max_cost,
            "recent": recent,
        },
    )


def percentile(sorted_values: list[int], pct: float) -> int:
    if not sorted_values:
        return 0
    k = (len(sorted_values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return round(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f))


HISTOGRAM_BUCKETS = [
    (0, 200, "0-200ms"),
    (200, 500, "200-500ms"),
    (500, 1000, "500ms-1s"),
    (1000, 2000, "1-2s"),
    (2000, 5000, "2-5s"),
    (5000, None, "5s+"),
]


@router.get("/monitoring")
def monitoring(request: Request, db: Session = Depends(get_db)):
    redirect = require_admin(request)
    if redirect:
        return redirect

    since = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    entries = (
        db.query(AgentAuditLog)
        .filter(AgentAuditLog.created_at >= since)
        .order_by(AgentAuditLog.created_at.asc())
        .all()
    )

    durations = sorted(e.duration_ms for e in entries)
    total = len(entries)
    errors = sum(1 for e in entries if e.status == "error")
    error_rate = (errors / total * 100) if total else 0.0

    histogram = []
    max_bucket = 1
    for low, high, label in HISTOGRAM_BUCKETS:
        count = sum(
            1 for d in durations if d >= low and (high is None or d < high)
        )
        histogram.append({"label": label, "count": count, "slow": low >= 2000})
        max_bucket = max(max_bucket, count)
    for h in histogram:
        h["height_pct"] = round(h["count"] / max_bucket * 100) if max_bucket else 0

    by_client: dict[str, list[AgentAuditLog]] = {}
    for e in entries:
        by_client.setdefault(e.client_name, []).append(e)

    clients_rows = []
    for name, rows in by_client.items():
        d = sorted(r.duration_ms for r in rows)
        err = sum(1 for r in rows if r.status == "error")
        rate = (err / len(rows) * 100) if rows else 0.0
        if rate == 0:
            health = "healthy"
        elif rate <= 5:
            health = "warning"
        else:
            health = "critical"
        clients_rows.append(
            {
                "client_name": name,
                "requests": len(rows),
                "p50": percentile(d, 0.5),
                "p90": percentile(d, 0.9),
                "error_rate": rate,
                "health": health,
                "last_seen": max(r.created_at for r in rows),
            }
        )
    clients_rows.sort(key=lambda r: r["requests"], reverse=True)

    now = datetime.datetime.utcnow()
    hourly_counts = [0] * 24
    for e in entries:
        hours_ago = int((now - e.created_at).total_seconds() // 3600)
        bucket = 23 - min(hours_ago, 23)
        hourly_counts[bucket] += 1
    max_hourly = max(hourly_counts) or 1
    chart_w, chart_h = 760, 120
    step = chart_w / 23
    points = [
        (round(i * step, 1), round(chart_h - (c / max_hourly * (chart_h - 8)), 1))
        for i, c in enumerate(hourly_counts)
    ]
    volume_line = " ".join(f"{x},{y}" for x, y in points)
    volume_area = f"0,{chart_h} " + volume_line + f" {chart_w},{chart_h}"

    return templates.TemplateResponse(
        "monitoring.html",
        {
            "request": request,
            "total": total,
            "p50": percentile(durations, 0.5),
            "p90": percentile(durations, 0.9),
            "p99": percentile(durations, 0.99),
            "error_rate": error_rate,
            "histogram": histogram,
            "chart_w": chart_w,
            "chart_h": chart_h,
            "volume_line": volume_line,
            "volume_area": volume_area,
            "max_hourly": max_hourly,
            "clients_rows": clients_rows,
        },
    )


@router.get("/clients")
def list_clients(request: Request, db: Session = Depends(get_db)):
    redirect = require_admin(request)
    if redirect:
        return redirect
    clients = db.query(AgentClient).order_by(AgentClient.created_at.desc()).all()
    return templates.TemplateResponse(
        "clients.html",
        {"request": request, "clients": clients, "new_token": None, "new_name": None},
    )


@router.post("/clients")
def create_client(
    request: Request,
    name: str = Form(...),
    base_url: str = Form(...),
    zabbix_mcp_url: str = Form(""),
    zabbix_mcp_token: str = Form(""),
    db: Session = Depends(get_db),
):
    redirect = require_admin(request)
    if redirect:
        return redirect
    token = secrets.token_urlsafe(32)
    client = AgentClient(
        name=name,
        base_url=base_url,
        token_hash=hash_token(token),
        zabbix_mcp_url=zabbix_mcp_url or None,
        zabbix_mcp_token=zabbix_mcp_token or None,
    )
    db.add(client)
    db.commit()
    clients = db.query(AgentClient).order_by(AgentClient.created_at.desc()).all()
    return templates.TemplateResponse(
        "clients.html",
        {
            "request": request,
            "clients": clients,
            "new_token": token,
            "new_name": name,
        },
    )


@router.post("/clients/{client_id}/mcp")
def update_client_mcp(
    request: Request,
    client_id: int,
    zabbix_mcp_url: str = Form(""),
    zabbix_mcp_token: str = Form(""),
    db: Session = Depends(get_db),
):
    redirect = require_admin(request)
    if redirect:
        return redirect
    agent_client = db.query(AgentClient).filter(AgentClient.id == client_id).first()
    if agent_client:
        agent_client.zabbix_mcp_url = zabbix_mcp_url or None
        agent_client.zabbix_mcp_token = zabbix_mcp_token or None
        db.commit()
    return RedirectResponse(url="/admin/clients", status_code=303)


@router.get("/audit")
def list_audit(request: Request, db: Session = Depends(get_db)):
    redirect = require_admin(request)
    if redirect:
        return redirect
    entries = (
        db.query(AgentAuditLog)
        .order_by(AgentAuditLog.created_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse(
        "audit.html", {"request": request, "entries": entries}
    )
