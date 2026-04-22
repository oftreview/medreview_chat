"""
src/api/__init__.py — Blueprint registry.
Imports all blueprints and provides register_blueprints() function.
"""


def register_blueprints(app):
    """Register all API blueprints with the Flask app."""
    from .auth import bp as auth_bp
    from .dashboard import bp as dashboard_bp
    from .chat import bp as chat_bp
    from .webhooks import bp as webhooks_bp
    from .escalation_api import bp as escalation_bp
    from .corrections_api import bp as corrections_bp
    from .analytics_api import bp as analytics_bp
    from .hubspot_api import bp as hubspot_bp
    from .health import bp as health_bp
    from .backlog_api import bp as backlog_bp

    for bp in [
        auth_bp,
        dashboard_bp,
        chat_bp,
        webhooks_bp,
        escalation_bp,
        corrections_bp,
        analytics_bp,
        hubspot_bp,
        health_bp,
        backlog_bp,
    ]:
        app.register_blueprint(bp)
