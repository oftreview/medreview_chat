"""
tests/unit/test_health_extended.py — Extended health endpoint tests.

Tests ALL endpoints in src/api/health.py that are not covered by existing integration tests.
Covers:
- /health/hubspot — HubSpot connection status
- /health/wild-memory — Wild Memory component status
- /api/wild-memory/cron (POST) — Daily maintenance
- /api/config (POST) — Runtime configuration updates
- /api/logs — Recent logs
- /api/logs/history — Log history with filtering
- /api/logs/stats — Daily log statistics
- /api/logs/sources — Available log sources
- /api/logs/cleanup (POST) — Log cleanup
- /api/metrics/history — LLM usage history
- /api/metrics/daily — Daily cost statistics
- /api/metrics/totals — All-time accumulated totals
"""
import os
import pytest
from unittest.mock import patch, MagicMock

# Set environment variables before any imports
os.environ.setdefault("TEST_MODE", "true")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("API_SECRET_TOKEN", "test-secret-token")


@pytest.mark.unit
class TestHealthHubSpot:
    """Test /health/hubspot endpoint."""

    def test_health_hubspot_when_enabled_and_connected(self, client):
        """GET /health/hubspot returns 200 when HubSpot is connected."""
        with patch("src.api.health.hubspot.get_status") as mock_hubspot:
            mock_hubspot.return_value = {
                "enabled": True,
                "connected": True,
                "message": "Connected to HubSpot",
            }
            resp = client.get("/health/hubspot")

            assert resp.status_code == 200
            data = resp.get_json()
            assert data["enabled"] is True
            assert data["connected"] is True

    def test_health_hubspot_when_disabled(self, client):
        """GET /health/hubspot returns 200 when HubSpot is disabled."""
        with patch("src.api.health.hubspot.get_status") as mock_hubspot:
            mock_hubspot.return_value = {
                "enabled": False,
                "connected": False,
                "message": "HubSpot not enabled",
            }
            resp = client.get("/health/hubspot")

            assert resp.status_code == 200
            data = resp.get_json()
            assert data["enabled"] is False

    def test_health_hubspot_when_enabled_but_not_connected(self, client):
        """GET /health/hubspot returns 500 when HubSpot is enabled but not connected."""
        with patch("src.api.health.hubspot.get_status") as mock_hubspot:
            mock_hubspot.return_value = {
                "enabled": True,
                "connected": False,
                "message": "Failed to connect to HubSpot",
            }
            resp = client.get("/health/hubspot")

            assert resp.status_code == 500
            data = resp.get_json()
            assert data["connected"] is False


@pytest.mark.unit
class TestHealthWildMemory:
    """Test /health/wild-memory endpoint."""

    def test_health_wild_memory_returns_all_components(self, client):
        """GET /health/wild-memory returns status of all components."""
        with patch("src.core.wild_memory_shadow.shadow.get_status") as mock_shadow, \
             patch("src.core.wild_memory_context.context_injector.get_status") as mock_context, \
             patch("src.core.wild_memory_lifecycle.lifecycle.get_status") as mock_lifecycle, \
             patch("src.core.scheduler.get_status") as mock_scheduler:

            mock_shadow.return_value = {"active_sessions": 5, "total_memories": 100}
            mock_context.return_value = {"enabled": True, "cached_contexts": 20}
            mock_lifecycle.return_value = {"decay_enabled": True, "last_maintenance": "2026-03-28T10:00:00"}
            mock_scheduler.return_value = {"enabled": True, "jobs_scheduled": 3}

            resp = client.get("/health/wild-memory")

            assert resp.status_code == 200
            data = resp.get_json()
            assert "active_sessions" in data
            assert "context_injection" in data
            assert "lifecycle" in data
            assert "scheduler" in data

    def test_health_wild_memory_scheduler_import_error(self, client):
        """GET /health/wild-memory handles scheduler import error gracefully."""
        with patch("src.core.wild_memory_shadow.shadow.get_status") as mock_shadow, \
             patch("src.core.wild_memory_context.context_injector.get_status") as mock_context, \
             patch("src.core.wild_memory_lifecycle.lifecycle.get_status") as mock_lifecycle, \
             patch("src.core.scheduler.get_status", side_effect=ImportError("No module")):

            mock_shadow.return_value = {"active_sessions": 5}
            mock_context.return_value = {"enabled": True}
            mock_lifecycle.return_value = {"decay_enabled": True}

            resp = client.get("/health/wild-memory")

            assert resp.status_code == 200
            data = resp.get_json()
            assert data["scheduler"]["enabled"] is False
            assert data["scheduler"]["reason"] == "import_error"


@pytest.mark.unit
class TestWildMemoryCron:
    """Test /api/wild-memory/cron endpoint (POST)."""

    def test_wild_memory_cron_with_valid_auth(self, client):
        """POST /api/wild-memory/cron with valid token runs maintenance."""
        with patch("src.core.wild_memory_lifecycle.lifecycle.run_daily_maintenance") as mock_maintenance, \
             patch("src.config.API_SECRET_TOKEN", "test-secret-token"):

            mock_maintenance.return_value = {
                "status": "ok",
                "decay_run": True,
                "cleanup_run": True,
                "sessions_cleaned": 5,
            }

            headers = {"Authorization": "Bearer test-secret-token"}
            resp = client.post("/api/wild-memory/cron", headers=headers)

            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"
            mock_maintenance.assert_called_once()

    def test_wild_memory_cron_without_auth_token(self, client):
        """POST /api/wild-memory/cron without auth returns 401."""
        with patch("src.config.API_SECRET_TOKEN", "test-secret-token"):
            resp = client.post("/api/wild-memory/cron")

            assert resp.status_code == 401
            data = resp.get_json()
            assert "error" in data

    def test_wild_memory_cron_with_invalid_token(self, client):
        """POST /api/wild-memory/cron with wrong token returns 401."""
        with patch("src.config.API_SECRET_TOKEN", "test-secret-token"):
            headers = {"Authorization": "Bearer wrong-token"}
            resp = client.post("/api/wild-memory/cron", headers=headers)

            assert resp.status_code == 401

    def test_wild_memory_cron_no_token_configured(self, client):
        """POST /api/wild-memory/cron works without token if none configured."""
        with patch("src.core.wild_memory_lifecycle.lifecycle.run_daily_maintenance") as mock_maintenance, \
             patch("src.config.API_SECRET_TOKEN", ""):

            mock_maintenance.return_value = {"status": "ok"}

            resp = client.post("/api/wild-memory/cron")

            assert resp.status_code == 200
            mock_maintenance.assert_called_once()


@pytest.mark.unit
class TestConfigUpdate:
    """Test /api/config endpoint (POST)."""

    def test_config_update_model(self, client):
        """POST /api/config updates OPENROUTER_MODEL."""
        resp = client.post(
            "/api/config",
            json={"model": "anthropic/claude-opus-4"}
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_config_update_max_tokens(self, client):
        """POST /api/config updates MAX_TOKENS."""
        resp = client.post(
            "/api/config",
            json={"max_tokens": 8000}
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_config_update_both(self, client):
        """POST /api/config updates both model and max_tokens."""
        resp = client.post(
            "/api/config",
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 2000
            }
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_config_update_empty_payload(self, client):
        """POST /api/config with empty payload returns current values."""
        resp = client.post("/api/config", json={})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "model" in data
        assert "max_tokens" in data

    def test_config_update_no_json(self, client):
        """POST /api/config with no JSON body handles gracefully."""
        resp = client.post("/api/config")

        assert resp.status_code == 200


@pytest.mark.unit
class TestLogsEndpoints:
    """Test /api/logs/* endpoints."""

    def test_api_logs_returns_recent_logs(self, client):
        """GET /api/logs returns recent logs."""
        with patch("src.core.log_buffer.get_logs") as mock_get_logs:
            mock_get_logs.return_value = [
                {"timestamp": "2026-03-28T10:00:00", "level": "INFO", "message": "Test log 1"},
                {"timestamp": "2026-03-28T10:01:00", "level": "WARNING", "message": "Test log 2"},
            ]

            resp = client.get("/api/logs")

            assert resp.status_code == 200
            data = resp.get_json()
            assert "logs" in data
            assert len(data["logs"]) == 2

    def test_api_logs_with_since_parameter(self, client):
        """GET /api/logs?since=N filters logs by timestamp."""
        with patch("src.core.log_buffer.get_logs") as mock_get_logs:
            mock_get_logs.return_value = [
                {"timestamp": "2026-03-28T10:05:00", "level": "INFO", "message": "Recent log"},
            ]

            resp = client.get("/api/logs?since=1000000")

            assert resp.status_code == 200
            mock_get_logs.assert_called_once_with(since=1000000)

    def test_api_logs_import_error(self, client):
        """GET /api/logs returns empty list if log_buffer not available."""
        with patch("src.core.log_buffer.get_logs", side_effect=ImportError):
            resp = client.get("/api/logs")

            assert resp.status_code == 200
            data = resp.get_json()
            assert data["logs"] == []

    def test_api_logs_history_returns_filtered_logs(self, client):
        """GET /api/logs/history returns logs with filters."""
        with patch("src.core.log_buffer.get_history") as mock_get_history:
            mock_get_history.return_value = {
                "logs": [
                    {"id": 1, "tag": "agent", "source": "sales_agent", "message": "Test 1"},
                ],
                "total": 1,
                "page": 1,
            }

            resp = client.get("/api/logs/history?tag=agent&source=sales_agent&page=1&per_page=50")

            assert resp.status_code == 200
            data = resp.get_json()
            assert "logs" in data
            mock_get_history.assert_called_once()

    def test_api_logs_history_with_search(self, client):
        """GET /api/logs/history supports full-text search."""
        with patch("src.core.log_buffer.get_history") as mock_get_history:
            mock_get_history.return_value = {"logs": [], "total": 0, "page": 1}

            resp = client.get("/api/logs/history?search=error&date_from=2026-03-01&date_to=2026-03-28")

            assert resp.status_code == 200
            mock_get_history.assert_called_once()

    def test_api_logs_stats_returns_daily_stats(self, client):
        """GET /api/logs/stats returns daily log volume."""
        with patch("src.core.log_buffer.get_daily_stats") as mock_get_stats:
            mock_get_stats.return_value = [
                {"date": "2026-03-28", "count": 42},
                {"date": "2026-03-27", "count": 38},
            ]

            resp = client.get("/api/logs/stats?days=30")

            assert resp.status_code == 200
            data = resp.get_json()
            assert "stats" in data
            mock_get_stats.assert_called_once_with(days_back=30)

    def test_api_logs_stats_default_days(self, client):
        """GET /api/logs/stats defaults to 30 days."""
        with patch("src.core.log_buffer.get_daily_stats") as mock_get_stats:
            mock_get_stats.return_value = []

            resp = client.get("/api/logs/stats")

            assert resp.status_code == 200
            mock_get_stats.assert_called_once_with(days_back=30)

    def test_api_logs_sources_returns_list(self, client):
        """GET /api/logs/sources returns available log sources."""
        with patch("src.core.log_buffer.get_sources") as mock_get_sources:
            mock_get_sources.return_value = ["sales_agent", "webhook", "scheduler", "system"]

            resp = client.get("/api/logs/sources")

            assert resp.status_code == 200
            data = resp.get_json()
            assert "sources" in data
            assert len(data["sources"]) == 4

    def test_api_logs_cleanup_with_valid_auth(self, client):
        """POST /api/logs/cleanup with valid token deletes old logs."""
        with patch("src.config.API_SECRET_TOKEN", "test-secret-token"), \
             patch("src.core.database.client._get_client") as mock_get_client:

            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.data = 25
            mock_db.rpc.return_value.execute.return_value = mock_result
            mock_get_client.return_value = mock_db

            headers = {"Authorization": "Bearer test-secret-token"}
            resp = client.post("/api/logs/cleanup?days=30", headers=headers)

            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"
            assert data["deleted"] == 25

    def test_api_logs_cleanup_without_auth(self, client):
        """POST /api/logs/cleanup without auth returns 401."""
        with patch("src.config.API_SECRET_TOKEN", "test-secret-token"):
            resp = client.post("/api/logs/cleanup")

            assert resp.status_code == 401

    def test_api_logs_cleanup_no_token_configured(self, client):
        """POST /api/logs/cleanup works without token if none configured."""
        with patch("src.config.API_SECRET_TOKEN", ""), \
             patch("src.core.database.client._get_client") as mock_get_client:

            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.data = 10
            mock_db.rpc.return_value.execute.return_value = mock_result
            mock_get_client.return_value = mock_db

            resp = client.post("/api/logs/cleanup?days=30")

            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"

    def test_api_logs_cleanup_database_unavailable(self, client):
        """POST /api/logs/cleanup returns 500 if database unavailable."""
        with patch("src.config.API_SECRET_TOKEN", ""), \
             patch("src.core.database.client._get_client") as mock_get_client:

            mock_get_client.return_value = None

            resp = client.post("/api/logs/cleanup")

            assert resp.status_code == 500
            data = resp.get_json()
            assert "error" in data

    def test_api_logs_cleanup_exception_handling(self, client):
        """POST /api/logs/cleanup returns 500 on exception."""
        with patch("src.config.API_SECRET_TOKEN", ""), \
             patch("src.core.database.client._get_client") as mock_get_client:

            mock_get_client.side_effect = Exception("Database error")

            resp = client.post("/api/logs/cleanup")

            assert resp.status_code == 500


@pytest.mark.unit
class TestMetricsEndpoints:
    """Test /api/metrics/* endpoints."""

    def test_api_metrics_history_returns_usage(self, client):
        """GET /api/metrics/history returns LLM usage history."""
        with patch("src.core.metrics.get_history") as mock_get_history:
            mock_get_history.return_value = {
                "records": [
                    {
                        "id": 1,
                        "model": "claude-3-sonnet-20240229",
                        "input_tokens": 500,
                        "output_tokens": 250,
                        "cost": 0.002,
                        "created_at": "2026-03-28T10:00:00",
                    }
                ],
                "total": 1,
                "page": 1,
            }

            resp = client.get("/api/metrics/history?model=claude-3-sonnet-20240229&page=1&per_page=50")

            assert resp.status_code == 200
            data = resp.get_json()
            assert "records" in data
            mock_get_history.assert_called_once()

    def test_api_metrics_history_with_date_range(self, client):
        """GET /api/metrics/history filters by date range."""
        with patch("src.core.metrics.get_history") as mock_get_history:
            mock_get_history.return_value = {"records": [], "total": 0, "page": 1}

            resp = client.get(
                "/api/metrics/history?date_from=2026-03-01&date_to=2026-03-28&page=1&per_page=100"
            )

            assert resp.status_code == 200
            mock_get_history.assert_called_once()

    def test_api_metrics_daily_returns_stats(self, client):
        """GET /api/metrics/daily returns daily cost statistics."""
        with patch("src.core.metrics.get_daily_stats") as mock_get_stats:
            mock_get_stats.return_value = [
                {"date": "2026-03-28", "total_cost": 1.25, "total_tokens": 5000},
                {"date": "2026-03-27", "total_cost": 0.95, "total_tokens": 4200},
            ]

            resp = client.get("/api/metrics/daily?days=30")

            assert resp.status_code == 200
            data = resp.get_json()
            assert "stats" in data
            assert len(data["stats"]) == 2
            mock_get_stats.assert_called_once_with(days_back=30)

    def test_api_metrics_daily_default_days(self, client):
        """GET /api/metrics/daily defaults to 30 days."""
        with patch("src.core.metrics.get_daily_stats") as mock_get_stats:
            mock_get_stats.return_value = []

            resp = client.get("/api/metrics/daily")

            assert resp.status_code == 200
            mock_get_stats.assert_called_once_with(days_back=30)

    def test_api_metrics_totals_returns_accumulated(self, client):
        """GET /api/metrics/totals returns all-time accumulated totals."""
        with patch("src.core.metrics.get_totals") as mock_get_totals:
            mock_get_totals.return_value = {
                "total_calls": 1500,
                "total_input_tokens": 750000,
                "total_output_tokens": 375000,
                "total_cache_read": 200000,
                "total_cache_write": 50000,
                "total_cost": 45.50,
            }

            resp = client.get("/api/metrics/totals")

            assert resp.status_code == 200
            data = resp.get_json()
            assert "totals" in data
            assert data["totals"]["total_calls"] == 1500
            mock_get_totals.assert_called_once_with(since=None)

    def test_api_metrics_totals_with_since_parameter(self, client):
        """GET /api/metrics/totals filters by since timestamp."""
        with patch("src.core.metrics.get_totals") as mock_get_totals:
            mock_get_totals.return_value = {
                "total_calls": 100,
                "total_cost": 5.25,
            }

            resp = client.get("/api/metrics/totals?since=2026-03-01T00:00:00Z")

            assert resp.status_code == 200
            mock_get_totals.assert_called_once_with(since="2026-03-01T00:00:00Z")


@pytest.mark.unit
class TestConfigUpdateActualModule:
    """Test /api/config updates actual src.config module values."""

    def test_config_update_actually_changes_model(self, client):
        """POST /api/config actually updates src.config.OPENROUTER_MODEL."""
        import src.config
        original_model = src.config.OPENROUTER_MODEL

        try:
            resp = client.post(
                "/api/config",
                json={"model": "anthropic/claude-opus-4"}
            )

            assert resp.status_code == 200
            assert src.config.OPENROUTER_MODEL == "anthropic/claude-opus-4"
        finally:
            src.config.OPENROUTER_MODEL = original_model

    def test_config_update_actually_changes_max_tokens(self, client):
        """POST /api/config actually updates src.config.MAX_TOKENS."""
        import src.config
        original_max_tokens = src.config.MAX_TOKENS

        try:
            resp = client.post(
                "/api/config",
                json={"max_tokens": 8192}
            )

            assert resp.status_code == 200
            assert src.config.MAX_TOKENS == 8192
        finally:
            src.config.MAX_TOKENS = original_max_tokens
