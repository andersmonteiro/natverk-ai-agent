import datetime
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import check_password, require_admin
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
def login_submit(request: Request, password: str = Form(...)):
    if not check_password(password):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Senha incorreta"}
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
    db: Session = Depends(get_db),
):
    redirect = require_admin(request)
    if redirect:
        return redirect
    token = secrets.token_urlsafe(32)
    client = AgentClient(name=name, base_url=base_url, token_hash=hash_token(token))
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
