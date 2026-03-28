"""
src/app.py — Application Factory.
Creates and configures the Flask app with all blueprints registered.

NOTE: gevent monkey.patch_all() must be called in the entrypoint BEFORE importing this module.
This factory does NOT patch — it only creates the Flask app and registers blueprints.
"""
import os
from flask import Flask, redirect

# Resolve paths relative to this file (src/)
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app():
    """Create and configure the Flask application with all blueprints."""
    app = Flask(
        __name__,
        template_folder=os.path.join(_SRC_DIR, "templates"),
        static_folder=os.path.join(_SRC_DIR, "static"),
    )

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

    # Root redirect
    @app.route("/")
    def index():
        return redirect("/dashboard/sandbox")

    return app


# For gunicorn: `gunicorn src.app:app`
# IMPORTANT: Ensure gevent.monkey.patch_all() is called before importing this in the entrypoint.
app = create_app()
