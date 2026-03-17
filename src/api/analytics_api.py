"""
src/api/analytics_api.py — Advanced analytics endpoints.
Provides funnel, time-per-stage, keywords, quality, and summary analytics.
"""
from flask import Blueprint, request, jsonify

from src.core import database

bp = Blueprint("analytics_api", __name__)


@bp.route("/api/analytics/funnel", methods=["GET"])
def api_analytics_funnel():
    """
    Conversion funnel: leads at each stage, advancement rate, conversion rate.
    """
    return jsonify(database.analytics_funnel()), 200


@bp.route("/api/analytics/time-per-stage", methods=["GET"])
def api_analytics_time_per_stage():
    """Average time leads spend at each funnel stage."""
    return jsonify(database.analytics_time_per_stage()), 200


@bp.route("/api/analytics/keywords", methods=["GET"])
def api_analytics_keywords():
    """
    Most frequent keywords in lead messages.
    Query param: limit (default 30)
    """
    limit = int(request.args.get("limit", 30))
    return jsonify(database.analytics_keywords(limit=limit)), 200


@bp.route("/api/analytics/quality", methods=["GET"])
def api_analytics_quality():
    """
    Conversation quality score (engagement, depth, balance, progress).
    Query param: user_id (optional — if provided, analyze only that lead)
    """
    user_id = request.args.get("user_id", None)
    return jsonify(database.analytics_conversation_quality(user_id=user_id)), 200


@bp.route("/api/analytics/summary", methods=["GET"])
def api_analytics_summary():
    """
    Summary dashboard: funnel + quality + keywords + corrections in one endpoint.
    """
    funnel = database.analytics_funnel()
    quality = database.analytics_conversation_quality()
    keywords = database.analytics_keywords(limit=10)
    corrections = database.correction_analytics(days=7)

    return (
        jsonify({
            "funnel": funnel,
            "quality": {
                "avg_score": quality.get("avg_quality_score", 0),
                "total_conversations": quality.get("total_conversations", 0),
            },
            "top_keywords": keywords.get("keywords", [])[:10],
            "corrections_7d": corrections,
        }),
        200,
    )
