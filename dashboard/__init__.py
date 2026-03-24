"""
Wild Memory Dashboard — Self-contained monitoring & control panel.

Install in any Flask application with 3 lines:

    from wild_memory.dashboard import register_dashboard
    register_dashboard(app)

Or with a custom adapter:

    from wild_memory.dashboard import register_dashboard
    from myapp.wild_adapter import MyAdapter
    register_dashboard(app, adapter=MyAdapter())

Then add a single link to your sidebar:

    <a href="/wild-memory">🧠 Wild Memory</a>

That's it. The dashboard handles everything else.
"""

from wild_memory.dashboard.adapter import WildMemoryAdapter, AutoDetectAdapter


def register_dashboard(app, adapter=None, url_prefix="/wild-memory"):
    """
    Register the Wild Memory Dashboard blueprint on a Flask app.

    Args:
        app: Flask application instance
        adapter: WildMemoryAdapter subclass (auto-detected if None)
        url_prefix: URL prefix for all dashboard routes (default: /wild-memory)

    Example:
        from wild_memory.dashboard import register_dashboard
        register_dashboard(app)
    """
    from wild_memory.dashboard.blueprint import bp

    # Use AutoDetectAdapter if none provided
    if adapter is None:
        adapter = AutoDetectAdapter()

    # Store adapter on the app for access by blueprint routes
    app.config["WILD_MEMORY_ADAPTER"] = adapter

    # Update URL prefix if custom
    if url_prefix != "/wild-memory":
        bp.url_prefix = url_prefix

    app.register_blueprint(bp)

    import logging
    logging.getLogger(__name__).info(
        f"[Wild Memory Dashboard] Registered at {url_prefix}"
    )
