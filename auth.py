import hmac
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
    # hmac.compare_digest em vez de == -- comparação de string comum do
    # Python retorna no primeiro byte diferente, então o tempo de resposta
    # varia com quantos caracteres batem (timing attack clássico contra
    # login). compare_digest sempre compara o tamanho inteiro, tempo
    # constante independente de onde a diferença está.
    user_ok = hmac.compare_digest(username, os.environ["ADMIN_USERNAME"])
    pass_ok = hmac.compare_digest(password, os.environ["ADMIN_PASSWORD"])
    return user_ok and pass_ok
