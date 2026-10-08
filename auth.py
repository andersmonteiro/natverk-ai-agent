import os

from fastapi import Request
from fastapi.responses import RedirectResponse


def is_logged_in(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def require_admin(request: Request):
    if not is_logged_in(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return None


def check_credentials(username: str, password: str) -> bool:
    return (
        username == os.environ["ADMIN_USERNAME"]
        and password == os.environ["ADMIN_PASSWORD"]
    )
