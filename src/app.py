"""
src/app.py — Application Factory.
Creates and configures the Flask app with all blueprints registered.

NOTE: gevent monkey.patch_all() must be called in the entrypoint BEFORE importing this module.
This factory does NOT patch — it only creates the Flask app and registers blueprints.
"""
import os
from datetime import timedelta

from flask import Flask, jsonify, redirect, request, session, url_for

from src import config

# Resolve paths relative to this file (src/)
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))

# Endpoints que NÃO exigem login. Novos blueprints ficam protegidos por padrão.
_PUBLIC_ENDPOINT_PREFIXES = ("auth.", "health.", "webhooks.")


def create_app():
    """Create and configure the Flask application with all blueprints."""
    app = Flask(
        __name__,
        template_folder=os.path.join(_SRC_DIR, "templates"),
        static_folder=os.path.join(_SRC_DIR, "static"),
    )

    # ── Session / cookies ────────────────────────────────────────────────
    if config.AUTH_DISABLED:
        print(
            "\n"
            "============================================================\n"
            "  [!] AUTH_DISABLED=true -- LOGIN DESATIVADO\n"
            "  Dashboard acessivel SEM autenticacao. Apenas para local.\n"
            "============================================================\n",
            flush=True,
        )
    elif not config.SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY não configurada. Gere com "
            '`python -c "import secrets; print(secrets.token_hex(32))"` '
            "e defina como variável de ambiente. "
            "(Para pular auth em desenvolvimento local, use AUTH_DISABLED=true.)"
        )
    app.secret_key = config.SECRET_KEY or "dev-insecure-key-auth-disabled"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = not config.DEBUG
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.permanent_session_lifetime = timedelta(hours=config.SESSION_LIFETIME_HOURS)

    # Install log capture (stdout/stderr → ring buffer for /api/logs)
    try:
        from src.core.log_buffer import install as install_log_capture
        install_log_capture()
    except Exception:
        pass

    # Register all blueprints
    from src.api import register_blueprints
    register_blueprints(app)

    # Start background scheduler (Wild Memory daily maintenance)
    try:
        from src.core.scheduler import init_scheduler
        init_scheduler(app)
    except Exception:
        pass

    # Register Wild Memory Dashboard
    try:
        from wild_memory.dashboard import register_dashboard
        from src.core.wild_memory_adapter import ClosiAdapter
        register_dashboard(app, adapter=ClosiAdapter())
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[Wild Memory Dashboard] Failed to register: {e}")

    # Register Test Dashboard
    try:
        from tests.dashboard.blueprint import bp as test_dashboard_bp
        app.register_blueprint(test_dashboard_bp)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[Test Dashboard] Failed to register: {e}")

    # ── Auth guard global ────────────────────────────────────────────────
    # Protege todas as rotas exceto static, auth.*, health.*, webhooks.*.
    # Blueprints novos ficam protegidos automaticamente (fail-secure).
    @app.before_request
    def require_auth():
        # Modo dev local: injeta sessão fake e libera tudo.
        if config.AUTH_DISABLED:
            session.setdefault("user_id", "local-dev")
            session.setdefault("email", "local@dev")
            return None
        ep = request.endpoint or ""
        if ep == "static" or ep.startswith(_PUBLIC_ENDPOINT_PREFIXES):
            return None
        if "user_id" in session:
            return None
        # API calls → 401 JSON (frontend redireciona)
        if request.path.startswith("/api/") or request.is_json:
            return jsonify(error="unauthorized"), 401
        # Páginas HTML → redirect para login
        return redirect(url_for("auth.login", next=request.path))

    # Root redirect — só vai para o dashboard se logado
    @app.route("/")
    def index():
        if config.AUTH_DISABLED or "user_id" in session:
            return redirect("/dashboard/sandbox")
        return redirect(url_for("auth.login"))

    return app


# For gunicorn: `gunicorn src.app:app`
# IMPORTANT: Ensure gevent.monkey.patch_all() is called before importing this in the entrypoint.
app = create_app()
