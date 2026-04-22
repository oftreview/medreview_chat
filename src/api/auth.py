"""
src/api/auth.py — Blueprint de login do dashboard.

Rotas:
- GET  /auth/login   → renderiza login.html
- POST /auth/login   → valida com Supabase Auth, grava sessão Flask
- GET  /auth/logout  → limpa sessão, desloga do Supabase

Credenciais são validadas via Supabase Auth nativo (supabase.auth.sign_in_with_password).
Usuários são criados manualmente pelo admin no painel do Supabase.
"""
import logging
import threading
import time

from flask import Blueprint, redirect, render_template, request, session, url_for

from src import config

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/auth")

# Rate limiter in-memory: IP → lista de timestamps de tentativas recentes.
# Sob Gunicorn multi-worker o limite efetivo é por worker (aceitável no escopo).
_attempts: dict[str, list[float]] = {}
_lock = threading.Lock()


def _client_ip() -> str:
    """Retorna o IP do cliente, respeitando X-Forwarded-For (Render/proxy)."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _check_rate(ip: str) -> bool:
    """Retorna True se a tentativa é permitida; False se bloqueada."""
    now = time.time()
    window = config.LOGIN_RATE_LIMIT_WINDOW_MINUTES * 60
    with _lock:
        arr = [t for t in _attempts.get(ip, []) if now - t < window]
        if len(arr) >= config.LOGIN_RATE_LIMIT_ATTEMPTS:
            _attempts[ip] = arr
            return False
        arr.append(now)
        _attempts[ip] = arr
        return True


def _safe_next(nxt: str) -> str:
    """Valida o parâmetro `next` para evitar open-redirect. Só aceita path relativo."""
    if not nxt or not nxt.startswith("/") or nxt.startswith("//"):
        return "/dashboard/sandbox"
    return nxt


@bp.route("/login", methods=["GET"])
def login():
    if "user_id" in session:
        return redirect("/dashboard/sandbox")
    nxt = _safe_next(request.args.get("next", ""))
    return render_template("login.html", next=nxt, error=None)


@bp.route("/login", methods=["POST"])
def login_post():
    ip = _client_ip()
    nxt = _safe_next(request.form.get("next", ""))

    if not _check_rate(ip):
        return (
            render_template(
                "login.html",
                next=nxt,
                error="Muitas tentativas. Aguarde alguns minutos e tente novamente.",
            ),
            429,
        )

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not email or not password:
        return (
            render_template("login.html", next=nxt, error="Informe email e senha."),
            400,
        )

    from src.core.database.client import _get_client

    db = _get_client()
    if db is None:
        logger.error("[auth] Supabase client indisponível no login")
        return (
            render_template(
                "login.html",
                next=nxt,
                error="Serviço de autenticação indisponível. Tente novamente em instantes.",
            ),
            503,
        )

    try:
        resp = db.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        logger.warning(f"[auth] Falha de login para {email} de {ip}: {e}")
        return (
            render_template("login.html", next=nxt, error="Email ou senha inválidos."),
            401,
        )

    user = getattr(resp, "user", None)
    if user is None:
        return (
            render_template("login.html", next=nxt, error="Email ou senha inválidos."),
            401,
        )

    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    session["email"] = user.email
    logger.info(f"[auth] Login bem-sucedido: {user.email} de {ip}")
    return redirect(nxt)


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    email = session.get("email", "")
    session.clear()
    try:
        from src.core.database.client import _get_client

        db = _get_client()
        if db is not None:
            db.auth.sign_out()
    except Exception as e:
        logger.debug(f"[auth] sign_out best-effort falhou: {e}")
    if email:
        logger.info(f"[auth] Logout: {email}")
    return redirect(url_for("auth.login"))
