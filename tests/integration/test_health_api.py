"""
tests/integration/test_health_api.py — Testes de integracao dos endpoints de health.

Usa Flask test client com mocks.
Testa /health, /health/db, /health/memory, /api/metrics.
"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.integration
class TestHealthEndpoints:
    """Testa os endpoints de health check."""

    def test_health_returns_ok(self, client):
        """GET /health retorna status=ok."""
        resp = client.get("/health")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_db_returns_status(self, client):
        """GET /health/db retorna estado da conexao."""
        resp = client.get("/health/db")

        assert resp.status_code == 200
        data = resp.get_json()
        # With mocked database (enabled=False), should return gracefully
        assert "connected" in data or "enabled" in data

    def test_health_memory_returns_stats(self, client):
        """GET /health/memory retorna estatisticas de memoria."""
        resp = client.get("/health/memory")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "memory" in data
        memory_stats = data["memory"]
        assert "active_sessions" in memory_stats
        assert "db_successes" in memory_stats
        assert "db_failures" in memory_stats

    def test_metrics_returns_structure(self, client):
        """GET /api/metrics retorna estrutura de metricas."""
        resp = client.get("/api/metrics")

        assert resp.status_code == 200
        data = resp.get_json()
        assert "metrics" in data

    def test_health_security_returns_events(self, client):
        """GET /health/security retorna eventos de seguranca."""
        resp = client.get("/health/security")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "recent_events" in data
        assert "count" in data


@pytest.mark.integration
class TestResetAndHistory:
    """Testa endpoints auxiliares."""

    def test_history_returns_list(self, client):
        """GET /history retorna lista."""
        resp = client.get("/history?session_id=sandbox")

        assert resp.status_code == 200
        data = resp.get_json()
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_sessions_returns_list(self, client):
        """GET /sessions retorna lista de sessoes."""
        resp = client.get("/sessions")

        assert resp.status_code == 200
        data = resp.get_json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)
