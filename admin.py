import hashlib
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import check_password, require_admin
from db import get_db
from models import AgentAuditLog, AgentClient

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
    return RedirectResponse(url="/admin/clients", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


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
