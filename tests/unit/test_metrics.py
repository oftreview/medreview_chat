"""
tests/unit/test_metrics.py — Comprehensive tests for src/core/metrics.py

Tests the thread-safe metrics singleton that collects API usage metrics with dual-write
to memory and Supabase. Covers:
- record_call() cost calculation and accumulation
- get_metrics() snapshots
- _enqueue_persist() buffer management
- _flush_to_supabase() persistence logic
- get_history(), get_daily_stats(), get_totals() queries
"""
import os
import sys
import pytest
import threading
import time
from unittest.mock import patch, MagicMock, Mock

# ── Environment Setup ────────────────────────────────────────────────────────
os.environ["TEST_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Helpers to Reset Global State ────────────────────────────────────────────

def reset_metrics_state():
    """Reset all global metric state to initial values."""
    import src.core.metrics as metrics_module

    metrics_module._totals = {
        "total_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read": 0,
        "total_cache_write": 0,
        "total_cost": 0.0,
    }

    metrics_module._recent_calls.clear()
    metrics_module._persist_buffer.clear()
    metrics_module._last_flush = time.time()
    metrics_module._persist_enabled = None


@pytest.fixture(autouse=True)
def metrics_fixture():
    """Auto-use fixture to reset metrics before and after each test."""
    reset_metrics_state()
    yield
    reset_metrics_state()


@pytest.fixture
def mock_is_enabled():
    """Mock is_enabled to return False by default (disables Supabase writes)."""
    with patch("src.core.database.client.is_enabled", return_value=False):
        yield


@pytest.fixture
def mock_db_client():
    """Mock Supabase _get_client."""
    mock_client = MagicMock()
    with patch("src.core.database.client._get_client", return_value=mock_client):
        yield mock_client


# ── Test: Cost Calculation ───────────────────────────────────────────────────

class TestCostCalculation:
    """Tests for correct cost calculation with different models."""

    def test_record_call_known_model_calculates_correct_cost(self, mock_is_enabled):
        """Test cost calculation for a known model (claude-haiku-4-5-20251001)."""
        import src.core.metrics as metrics

        # claude-haiku-4-5-20251001: input=1.0, output=5.0 per million
        # cost = (1000 * 1.0 + 500 * 5.0) / 1_000_000 = 3500 / 1_000_000 = 0.0035
        metrics.record_call("claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=500)

        snapshot = metrics.get_metrics()
        assert snapshot["total_cost"] == 0.0035

    def test_record_call_known_model_sonnet_cost(self, mock_is_enabled):
        """Test cost calculation for claude-sonnet-4-20250514."""
        import src.core.metrics as metrics

        # claude-sonnet-4-20250514: input=3.0, output=15.0
        # cost = (2000 * 3.0 + 1000 * 15.0) / 1_000_000 = 21000 / 1_000_000 = 0.021
        metrics.record_call("claude-sonnet-4-20250514", input_tokens=2000, output_tokens=1000)

        snapshot = metrics.get_metrics()
        assert snapshot["total_cost"] == 0.021

    def test_record_call_unknown_model_uses_default_prices(self, mock_is_enabled):
        """Test cost calculation for unknown model uses default prices (3.0, 15.0)."""
        import src.core.metrics as metrics

        # Default: input=3.0, output=15.0
        # cost = (1000 * 3.0 + 500 * 15.0) / 1_000_000 = 10500 / 1_000_000 = 0.0105
        metrics.record_call("unknown-model-xyz", input_tokens=1000, output_tokens=500)

        snapshot = metrics.get_metrics()
        assert snapshot["total_cost"] == 0.0105

    def test_record_call_zero_tokens_zero_cost(self, mock_is_enabled):
        """Test that zero tokens result in zero cost."""
        import src.core.metrics as metrics

        metrics.record_call("claude-opus-4-6", input_tokens=0, output_tokens=0)

        snapshot = metrics.get_metrics()
        assert snapshot["total_cost"] == 0.0


# ── Test: Accumulation and State ─────────────────────────────────────────────

class TestMetricsAccumulation:
    """Tests for accumulation of metrics across multiple calls."""

    def test_record_call_increments_total_calls(self, mock_is_enabled):
        """Test that total_calls increments correctly."""
        import src.core.metrics as metrics

        assert metrics.get_metrics()["total_calls"] == 0

        metrics.record_call("claude-haiku-4-5-20251001", 100, 50)
        assert metrics.get_metrics()["total_calls"] == 1

        metrics.record_call("claude-haiku-4-5-20251001", 100, 50)
        assert metrics.get_metrics()["total_calls"] == 2

    def test_record_call_increments_token_counts(self, mock_is_enabled):
        """Test that input and output token counts accumulate."""
        import src.core.metrics as metrics

        metrics.record_call("claude-haiku-4-5-20251001", input_tokens=100, output_tokens=50)
        metrics.record_call("claude-haiku-4-5-20251001", input_tokens=200, output_tokens=75)

        snapshot = metrics.get_metrics()
        assert snapshot["total_input_tokens"] == 300
        assert snapshot["total_output_tokens"] == 125

    def test_record_call_increments_cache_metrics(self, mock_is_enabled):
        """Test that cache_read and cache_write accumulate."""
        import src.core.metrics as metrics

        metrics.record_call("claude-haiku-4-5-20251001", 100, 50, cache_read=30, cache_write=10)
        metrics.record_call("claude-haiku-4-5-20251001", 100, 50, cache_read=20, cache_write=5)

        snapshot = metrics.get_metrics()
        assert snapshot["total_cache_read"] == 50
        assert snapshot["total_cache_write"] == 15

    def test_multiple_record_calls_accumulate_cost(self, mock_is_enabled):
        """Test that costs from multiple calls accumulate correctly."""
        import src.core.metrics as metrics

        # Call 1: cost = (1000 * 1.0 + 500 * 5.0) / 1_000_000 = 0.0035
        metrics.record_call("claude-haiku-4-5-20251001", 1000, 500)

        # Call 2: cost = (1000 * 1.0 + 500 * 5.0) / 1_000_000 = 0.0035
        metrics.record_call("claude-haiku-4-5-20251001", 1000, 500)

        snapshot = metrics.get_metrics()
        assert abs(snapshot["total_cost"] - 0.007) < 1e-6


# ── Test: get_metrics() ──────────────────────────────────────────────────────

class TestGetMetrics:
    """Tests for get_metrics() snapshot."""

    def test_get_metrics_returns_snapshot_dict(self, mock_is_enabled):
        """Test that get_metrics returns a dict with expected keys."""
        import src.core.metrics as metrics

        snapshot = metrics.get_metrics()

        assert isinstance(snapshot, dict)
        assert "total_calls" in snapshot
        assert "total_input_tokens" in snapshot
        assert "total_output_tokens" in snapshot
        assert "total_cache_read" in snapshot
        assert "total_cache_write" in snapshot
        assert "total_cost" in snapshot
        assert "recent_calls" in snapshot

    def test_get_metrics_includes_model_and_max_tokens(self, mock_is_enabled):
        """Test that get_metrics includes model and max_tokens from config."""
        import src.core.metrics as metrics

        snapshot = metrics.get_metrics()

        assert "model" in snapshot
        assert "max_tokens" in snapshot

    def test_get_metrics_includes_recent_calls_list(self, mock_is_enabled):
        """Test that get_metrics includes recent_calls as a list."""
        import src.core.metrics as metrics

        metrics.record_call("claude-haiku-4-5-20251001", 100, 50)

        snapshot = metrics.get_metrics()

        assert isinstance(snapshot["recent_calls"], list)
        assert len(snapshot["recent_calls"]) == 1
        assert snapshot["recent_calls"][0]["input_tokens"] == 100
        assert snapshot["recent_calls"][0]["output_tokens"] == 50
        assert snapshot["recent_calls"][0]["model"] == "claude-haiku-4-5-20251001"

    def test_get_metrics_recent_calls_includes_cost(self, mock_is_enabled):
        """Test that each recent call includes calculated cost."""
        import src.core.metrics as metrics

        metrics.record_call("claude-haiku-4-5-20251001", 1000, 500)

        snapshot = metrics.get_metrics()
        call = snapshot["recent_calls"][0]

        assert "cost" in call
        assert call["cost"] == 0.0035

    def test_get_metrics_total_cost_is_rounded(self, mock_is_enabled):
        """Test that total_cost is rounded to 6 decimal places."""
        import src.core.metrics as metrics

        metrics.record_call("claude-haiku-4-5-20251001", 1000, 500)

        snapshot = metrics.get_metrics()

        # Check that total_cost has been rounded
        cost_str = str(snapshot["total_cost"])
        decimal_places = len(cost_str.split('.')[-1]) if '.' in cost_str else 0
        assert decimal_places <= 6


# ── Test: _recent_calls Deque Behavior ──────────────────────────────────────

class TestRecentCallsDeque:
    """Tests for _recent_calls deque with maxlen=50."""

    def test_recent_calls_maxlen_50(self, mock_is_enabled):
        """Test that _recent_calls maintains max length of 50."""
        import src.core.metrics as metrics

        # Add 60 calls, only last 50 should remain
        for i in range(60):
            metrics.record_call("claude-haiku-4-5-20251001", 100, 50)

        snapshot = metrics.get_metrics()

        assert len(snapshot["recent_calls"]) == 50

    def test_recent_calls_preserves_order(self, mock_is_enabled):
        """Test that recent_calls maintains insertion order."""
        import src.core.metrics as metrics

        for i in range(5):
            metrics.record_call("claude-haiku-4-5-20251001", 100 * (i + 1), 50)

        snapshot = metrics.get_metrics()

        # Verify order (first call should have 100 input tokens, second 200, etc.)
        assert snapshot["recent_calls"][0]["input_tokens"] == 100
        assert snapshot["recent_calls"][1]["input_tokens"] == 200
        assert snapshot["recent_calls"][4]["input_tokens"] == 500


# ── Test: Thread Safety ──────────────────────────────────────────────────────

class TestThreadSafety:
    """Tests for thread safety of concurrent record_calls."""

    def test_concurrent_record_calls_no_data_loss(self, mock_is_enabled):
        """Test that concurrent calls don't lose data."""
        import src.core.metrics as metrics

        def worker(thread_id, num_calls):
            for i in range(num_calls):
                metrics.record_call("claude-haiku-4-5-20251001", 100, 50)

        threads = []
        num_threads = 10
        calls_per_thread = 10

        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i, calls_per_thread))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        snapshot = metrics.get_metrics()

        # Should have 100 total calls (10 threads * 10 calls each)
        assert snapshot["total_calls"] == num_threads * calls_per_thread
        assert snapshot["total_input_tokens"] == num_threads * calls_per_thread * 100

    def test_concurrent_get_metrics_consistent(self, mock_is_enabled):
        """Test that get_metrics is thread-safe during concurrent calls."""
        import src.core.metrics as metrics

        results = []

        def record_and_read(thread_id):
            for i in range(5):
                metrics.record_call("claude-haiku-4-5-20251001", 100, 50)
                snapshot = metrics.get_metrics()
                results.append(snapshot["total_calls"])

        threads = []
        for i in range(5):
            t = threading.Thread(target=record_and_read, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Final snapshot should have 25 calls (5 threads * 5 calls)
        final = metrics.get_metrics()
        assert final["total_calls"] == 25


# ── Test: _enqueue_persist and Buffer Management ──────────────────────────────

class TestPersistanceBuffer:
    """Tests for _enqueue_persist and buffer management."""

    def test_enqueue_persist_adds_to_buffer(self, mock_is_enabled):
        """Test that _enqueue_persist adds entries to the buffer."""
        import src.core.metrics as metrics
        from datetime import datetime, timezone, timedelta

        _BRT = timezone(timedelta(hours=-3))
        now_brt = datetime.now(_BRT)

        metrics._enqueue_persist(
            "claude-haiku-4-5-20251001",
            1000, 500, 30, 10,
            0.0035,
            now_brt
        )

        # Buffer should have one entry
        assert len(metrics._persist_buffer) == 1
        assert metrics._persist_buffer[0]["model"] == "claude-haiku-4-5-20251001"
        assert metrics._persist_buffer[0]["input_tokens"] == 1000

    def test_enqueue_persist_batch_size_triggers_flush(self, mock_is_enabled):
        """Test that reaching BATCH_SIZE triggers flush."""
        import src.core.metrics as metrics
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch as mock_patch

        _BRT = timezone(timedelta(hours=-3))
        now_brt = datetime.now(_BRT)

        with mock_patch.object(metrics, "_flush_to_supabase") as mock_flush:
            # Fill buffer to BATCH_SIZE
            for i in range(metrics._BATCH_SIZE):
                metrics._enqueue_persist(
                    "claude-haiku-4-5-20251001",
                    100, 50, 0, 0, 0.0005, now_brt
                )

            # Should trigger flush
            mock_flush.assert_called_once()

    def test_enqueue_persist_interval_triggers_flush(self, mock_is_enabled):
        """Test that flush interval triggers flush."""
        import src.core.metrics as metrics
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch as mock_patch

        _BRT = timezone(timedelta(hours=-3))
        now_brt = datetime.now(_BRT)

        # Manually set last_flush to old time
        metrics._last_flush = time.time() - (metrics._FLUSH_INTERVAL + 1)

        with mock_patch.object(metrics, "_flush_to_supabase") as mock_flush:
            metrics._enqueue_persist(
                "claude-haiku-4-5-20251001",
                100, 50, 0, 0, 0.0005, now_brt
            )

            # Should trigger flush because interval exceeded
            mock_flush.assert_called_once()


# ── Test: _flush_to_supabase ─────────────────────────────────────────────────

class TestFlushToSupabase:
    """Tests for _flush_to_supabase behavior."""

    def test_flush_clears_buffer_when_persist_disabled(self, mock_is_enabled):
        """Test that flush clears buffer when persist_enabled is False."""
        import src.core.metrics as metrics
        from datetime import datetime, timezone, timedelta

        _BRT = timezone(timedelta(hours=-3))
        now_brt = datetime.now(_BRT)

        # Add items to buffer
        metrics._enqueue_persist(
            "claude-haiku-4-5-20251001",
            100, 50, 0, 0, 0.0005, now_brt
        )

        assert len(metrics._persist_buffer) > 0

        # Mock is_enabled to return False
        with patch("src.core.database.client.is_enabled", return_value=False):
            metrics._persist_enabled = None  # Reset lazy init
            metrics._flush_to_supabase()

        # Buffer should be cleared
        assert len(metrics._persist_buffer) == 0

    def test_flush_spawns_thread_when_persist_enabled(self, mock_is_enabled):
        """Test that flush spawns background thread when persist is enabled."""
        import src.core.metrics as metrics
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch as mock_patch

        _BRT = timezone(timedelta(hours=-3))
        now_brt = datetime.now(_BRT)

        # Add items to buffer
        metrics._enqueue_persist(
            "claude-haiku-4-5-20251001",
            100, 50, 0, 0, 0.0005, now_brt
        )

        # Mock is_enabled to return True and mock the thread
        with patch("src.core.database.client.is_enabled", return_value=True), \
             mock_patch("threading.Thread") as mock_thread:
            metrics._persist_enabled = None  # Reset lazy init
            metrics._flush_to_supabase()

            # Thread should have been created
            mock_thread.assert_called_once()

    def test_flush_does_nothing_when_buffer_empty(self, mock_is_enabled):
        """Test that flush returns early when buffer is empty."""
        import src.core.metrics as metrics

        # Buffer is already empty
        assert len(metrics._persist_buffer) == 0

        with patch("src.core.database.client.is_enabled", return_value=True):
            metrics._persist_enabled = None
            # Should return early without error
            metrics._flush_to_supabase()

        assert len(metrics._persist_buffer) == 0


# ── Test: get_history ────────────────────────────────────────────────────────

class TestGetHistory:
    """Tests for get_history() query function."""

    def test_get_history_returns_empty_when_no_db(self):
        """Test that get_history returns empty dict when DB is None."""
        import src.core.metrics as metrics

        with patch("src.core.database.client._get_client", return_value=None):
            result = metrics.get_history()

        assert result["calls"] == []
        assert result["total"] == 0
        assert result["page"] == 1
        assert result["pages"] == 0

    def test_get_history_returns_calls_with_model_filter(self, mock_db_client):
        """Test that get_history filters by model."""
        import src.core.metrics as metrics

        mock_response = MagicMock()
        mock_response.data = [
            {
                "id": 1,
                "model": "claude-haiku-4-5-20251001",
                "input_tokens": 100,
                "output_tokens": 50,
            }
        ]
        mock_response.count = 1

        # Create a chain that returns itself so we can execute at the end
        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = mock_response

        mock_db_client.table.return_value = mock_query

        result = metrics.get_history(model="claude-haiku-4-5-20251001")

        # Verify table was called
        mock_db_client.table.assert_called_with("llm_usage")

    def test_get_history_with_pagination(self, mock_db_client):
        """Test that get_history respects pagination parameters."""
        import src.core.metrics as metrics

        mock_response = MagicMock()
        mock_response.data = []
        mock_response.count = 100

        # Create a chain that returns itself so we can execute at the end
        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = mock_response

        mock_db_client.table.return_value = mock_query

        result = metrics.get_history(page=2, per_page=25)

        # Pages should be calculated: ceil(100 / 25) = 4
        assert result["pages"] == 4

    def test_get_history_handles_exception(self):
        """Test that get_history handles exceptions gracefully."""
        import src.core.metrics as metrics

        with patch("src.core.database.client._get_client", side_effect=Exception("DB error")):
            result = metrics.get_history()

        assert result["calls"] == []
        assert result["total"] == 0
        assert "error" in result


# ── Test: get_daily_stats ────────────────────────────────────────────────────

class TestGetDailyStats:
    """Tests for get_daily_stats() query function."""

    def test_get_daily_stats_returns_empty_when_no_db(self):
        """Test that get_daily_stats returns empty list when DB is None."""
        import src.core.metrics as metrics

        with patch("src.core.database.client._get_client", return_value=None):
            result = metrics.get_daily_stats(days_back=30)

        assert result == []

    def test_get_daily_stats_calls_rpc_with_days_back(self, mock_db_client):
        """Test that get_daily_stats calls RPC with days_back parameter."""
        import src.core.metrics as metrics

        mock_response = MagicMock()
        mock_response.data = [
            {"date": "2026-03-28", "calls": 10, "total_tokens": 5000, "total_cost": 0.05}
        ]

        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = mock_response

        mock_db_client.rpc.return_value = mock_rpc

        result = metrics.get_daily_stats(days_back=30)

        # Verify RPC was called with correct parameters
        mock_db_client.rpc.assert_called_with("llm_daily_stats", {"days_back": 30})
        assert len(result) == 1

    def test_get_daily_stats_returns_data_when_available(self, mock_db_client):
        """Test that get_daily_stats returns RPC data."""
        import src.core.metrics as metrics

        mock_response = MagicMock()
        mock_response.data = [
            {"date": "2026-03-28", "calls": 10},
            {"date": "2026-03-27", "calls": 8},
        ]

        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = mock_response

        mock_db_client.rpc.return_value = mock_rpc

        result = metrics.get_daily_stats(days_back=7)

        assert len(result) == 2
        assert result[0]["calls"] == 10

    def test_get_daily_stats_handles_exception(self):
        """Test that get_daily_stats handles exceptions gracefully."""
        import src.core.metrics as metrics

        with patch("src.core.database.client._get_client", side_effect=Exception("DB error")):
            result = metrics.get_daily_stats(days_back=30)

        assert result == []


# ── Test: get_totals ─────────────────────────────────────────────────────────

class TestGetTotals:
    """Tests for get_totals() query function."""

    def test_get_totals_returns_empty_when_no_db(self):
        """Test that get_totals returns empty dict when DB is None."""
        import src.core.metrics as metrics

        with patch("src.core.database.client._get_client", return_value=None):
            result = metrics.get_totals()

        assert result == {}

    def test_get_totals_calls_rpc_without_since(self, mock_db_client):
        """Test that get_totals calls RPC with since=None when not provided."""
        import src.core.metrics as metrics

        mock_response = MagicMock()
        mock_response.data = [
            {
                "total_calls": 1000,
                "total_input_tokens": 50000,
                "total_output_tokens": 25000,
                "total_cost": 5.0,
            }
        ]

        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = mock_response

        mock_db_client.rpc.return_value = mock_rpc

        result = metrics.get_totals()

        # Verify RPC was called with since=None
        mock_db_client.rpc.assert_called_with("llm_totals", {"since": None})
        assert result["total_calls"] == 1000

    def test_get_totals_calls_rpc_with_since_date(self, mock_db_client):
        """Test that get_totals calls RPC with since parameter when provided."""
        import src.core.metrics as metrics

        mock_response = MagicMock()
        mock_response.data = [
            {
                "total_calls": 500,
                "total_input_tokens": 25000,
                "total_output_tokens": 12500,
                "total_cost": 2.5,
            }
        ]

        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = mock_response

        mock_db_client.rpc.return_value = mock_rpc

        result = metrics.get_totals(since="2026-03-01")

        # Verify RPC was called with since parameter
        mock_db_client.rpc.assert_called_with("llm_totals", {"since": "2026-03-01"})

    def test_get_totals_handles_empty_response(self, mock_db_client):
        """Test that get_totals returns empty dict when RPC returns empty data."""
        import src.core.metrics as metrics

        mock_response = MagicMock()
        mock_response.data = []

        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = mock_response

        mock_db_client.rpc.return_value = mock_rpc

        result = metrics.get_totals()

        assert result == {}

    def test_get_totals_handles_exception(self):
        """Test that get_totals handles exceptions gracefully."""
        import src.core.metrics as metrics

        with patch("src.core.database.client._get_client", side_effect=Exception("DB error")):
            result = metrics.get_totals()

        assert result == {}


# ── Integration Test: Full Workflow ──────────────────────────────────────────

class TestIntegration:
    """Integration tests for complete metrics workflow."""

    def test_full_workflow_multiple_calls_persist_and_query(self, mock_is_enabled, mock_db_client):
        """Test complete workflow: record calls, check snapshot, query history."""
        import src.core.metrics as metrics

        # Record some calls
        metrics.record_call("claude-haiku-4-5-20251001", 1000, 500, cache_read=100, cache_write=50)
        metrics.record_call("claude-sonnet-4-20250514", 2000, 1000)

        # Get snapshot
        snapshot = metrics.get_metrics()
        assert snapshot["total_calls"] == 2
        assert snapshot["total_input_tokens"] == 3000
        assert snapshot["total_output_tokens"] == 1500

        # Verify cost calculation
        # Call 1: (1000*1.0 + 500*5.0) / 1_000_000 = 0.0035
        # Call 2: (2000*3.0 + 1000*15.0) / 1_000_000 = 0.021
        # Total: 0.0245
        assert abs(snapshot["total_cost"] - 0.0245) < 1e-6

        # Query history (mocked)
        mock_response = MagicMock()
        mock_response.data = snapshot["recent_calls"]
        mock_response.count = len(snapshot["recent_calls"])

        # Create a chain that returns itself so we can execute at the end
        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = mock_response

        mock_db_client.table.return_value = mock_query

        history = metrics.get_history(page=1, per_page=50)
        assert len(history["calls"]) == 2
