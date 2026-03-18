"""
src/api/dashboard.py — Dashboard routes.
Simple template rendering for dashboard pages.
"""
from flask import Blueprint, render_template

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.route("/sandbox")
def dashboard_sandbox():
    """Dashboard home page (sandbox)."""
    return render_template("dashboard/sandbox.html", active_page="sandbox")


@bp.route("/conversations")
def dashboard_conversations():
    """Conversations history dashboard."""
    return render_template("dashboard/conversations.html", active_page="conversations")


@bp.route("/corrections")
def dashboard_corrections():
    """Corrections management dashboard."""
    return render_template("dashboard/corrections.html", active_page="corrections")


@bp.route("/costs")
def dashboard_costs():
    """Costs and tokens dashboard."""
    return render_template("dashboard/costs.html", active_page="costs")


@bp.route("/analytics")
def dashboard_analytics():
    """Advanced analytics dashboard."""
    return render_template("dashboard/analytics.html", active_page="analytics")


@bp.route("/backlog")
def dashboard_backlog():
    """Product backlog management dashboard."""
    return render_template("dashboard/backlog.html", active_page="backlog")


@bp.route("/logs")
def dashboard_logs():
    """System logs dashboard."""
    return render_template("dashboard/logs.html", active_page="logs")
