"""
tests/unit/test_log_buffer.py — Comprehensive tests for src/core/log_buffer.py

Tests the log buffering system including:
- Ring buffer (deque) behavior
- Tag classification via regex
- Source extraction via regex
- get_logs filtering
- Batch persistence to Supabase
- Historical log queries
- stdout/stderr capture hook
"""
import os
import sys
import pytest
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, call

# Set environment variables before importing the module
os.environ["TEST_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = "test-key"

# Import the module under test
import src.core.log_buffer as log_buffer


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures and helpers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_log_buffer():
    """Reset module globals before each test."""
    log_buffer._buffer.clear()
    log_buffer._counter = 0
    log_buffer._persist_buffer.clear()
    log_buffer._last_flush = time.time()
    log_buffer._persist_enabled = None
    yield
    # Cleanup after test
    log_buffer._buffer.clear()
    log_buffer._counter = 0
    log_buffer._persist_buffer.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Tag Classification Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTagClassification:
    """Tests for _classify() function and tag regex patterns."""

    def test_classify_error_tag(self):
        """Test detection of error tags."""
        assert log_buffer._classify("[ERRO] Something went wrong") == "error"
        assert log_buffer._classify("Traceback (most recent call last)") == "error"
        assert log_buffer._classify("Exception: Invalid input") == "error"
        assert log_buffer._classify("Error in processing") == "error"

    def test_classify_security_tag(self):
        """Test detection of security tags."""
        assert log_buffer._classify("[SECURITY] Blocked request") == "security"
        assert log_buffer._classify("[INJECTION] SQL injection attempt") == "security"
        assert log_buffer._classify("[RATE_LIMIT] Too many requests") == "security"
        assert log_buffer._classify("[SANITIZ] Input sanitization failed") == "security"

    def test_classify_flush_tag(self):
        """Test detection of flush tags."""
        assert log_buffer._classify("[FLUSH] Writing to database") == "flush"

    def test_classify_debounce_tag(self):
        """Test detection of debounce tags."""
        assert log_buffer._classify("[DEBOUNCE] Throttling updates") == "debounce"

    def test_classify_system_tags(self):
        """Test detection of various system tags."""
        assert log_buffer._classify("[LLM] Processing request") == "system"
        assert log_buffer._classify("Cache: Hit ratio 0.95") == "system"
        assert log_buffer._classify("[CONFIG] Loading settings") == "system"
        assert log_buffer._classify("[CHAT API] Sending message") == "system"
        assert log_buffer._classify("[ZAPI] API call") == "system"
        assert log_buffer._classify("[FORM] Processing form") == "system"
        assert log_buffer._classify("[DB] Query executed") == "system"
        assert log_buffer._classify("[WM] Wild memory update") == "system"
        assert log_buffer._classify("[SHADOW] Shadow state") == "system"
        assert log_buffer._classify("[CONTEXT] Context updated") == "system"
        assert log_buffer._classify("[LIFECYCLE] Init complete") == "system"
        assert log_buffer._classify("[SCHEDULER] Job running") == "system"
        assert log_buffer._classify("[CRON] Maintenance task") == "system"
        assert log_buffer._classify("[MAINTENANCE] Cleanup") == "system"

    def test_classify_debug_default(self):
        """Test default tag when no pattern matches."""
        assert log_buffer._classify("Random log message") == "debug"
        assert log_buffer._classify("Just a regular print") == "debug"
        assert log_buffer._classify("") == "debug"


# ─────────────────────────────────────────────────────────────────────────────
# Source Extraction Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSourceExtraction:
    """Tests for _extract_source() function and source regex patterns."""

    def test_extract_source_database(self):
        """Test extraction of database source."""
        assert log_buffer._extract_source("[DB] Query completed") == "database"

    def test_extract_source_llm(self):
        """Test extraction of LLM source."""
        assert log_buffer._extract_source("[LLM] Token count: 150") == "llm"

    def test_extract_source_chat(self):
        """Test extraction of chat source."""
        assert log_buffer._extract_source("[CHAT API] Message sent") == "chat"

    def test_extract_source_zapi(self):
        """Test extraction of ZAPI source."""
        assert log_buffer._extract_source("[ZAPI] Request received") == "zapi"

    def test_extract_source_form(self):
        """Test extraction of form source."""
        assert log_buffer._extract_source("[FORM] Submission processed") == "form"

    def test_extract_source_config(self):
        """Test extraction of config source."""
        assert log_buffer._extract_source("[CONFIG] Settings loaded") == "config"

    def test_extract_source_security(self):
        """Test extraction of security source."""
        assert log_buffer._extract_source("[SECURITY] Access denied") == "security"

    def test_extract_source_wild_memory(self):
        """Test extraction of wild memory source."""
        assert log_buffer._extract_source("[SHADOW] State updated") == "wild_memory"
        assert log_buffer._extract_source("[WM] Memory changed") == "wild_memory"

    def test_extract_source_context(self):
        """Test extraction of context source."""
        assert log_buffer._extract_source("[CONTEXT] Context loaded") == "context"

    def test_extract_source_lifecycle(self):
        """Test extraction of lifecycle source."""
        assert log_buffer._extract_source("[LIFECYCLE] Init started") == "lifecycle"
        assert log_buffer._extract_source("[MAINTENANCE] Task running") == "lifecycle"

    def test_extract_source_scheduler(self):
        """Test extraction of scheduler source."""
        assert log_buffer._extract_source("[SCHEDULER] Job queued") == "scheduler"
        assert log_buffer._extract_source("[CRON] Task executed") == "scheduler"

    def test_extract_source_flush(self):
        """Test extraction of flush source."""
        assert log_buffer._extract_source("[FLUSH] Flushing data") == "flush"

    def test_extract_source_debounce(self):
        """Test extraction of debounce source."""
        assert log_buffer._extract_source("[DEBOUNCE] Event throttled") == "debounce"

    def test_extract_source_app_default(self):
        """Test default source when no pattern matches."""
        assert log_buffer._extract_source("Random message") == "app"
        assert log_buffer._extract_source("Just a print") == "app"


# ─────────────────────────────────────────────────────────────────────────────
# Ring Buffer and add_log Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRingBuffer:
    """Tests for ring buffer behavior and add_log() function."""

    def test_add_log_single_entry(self):
        """Test adding a single log entry."""
        log_buffer.add_log("[DB] Test message")
        assert len(log_buffer._buffer) == 1
        assert log_buffer._buffer[0]["msg"] == "[DB] Test message"
        assert log_buffer._buffer[0]["id"] == 1
        assert log_buffer._buffer[0]["tag"] == "system"

    def test_add_log_increments_counter(self):
        """Test that counter increments properly."""
        log_buffer.add_log("Message 1")
        log_buffer.add_log("Message 2")
        log_buffer.add_log("Message 3")
        assert log_buffer._counter == 3
        assert log_buffer._buffer[0]["id"] == 1
        assert log_buffer._buffer[1]["id"] == 2
        assert log_buffer._buffer[2]["id"] == 3

    def test_add_log_ignores_empty_messages(self):
        """Test that empty messages are ignored."""
        log_buffer.add_log("")
        log_buffer.add_log("   ")
        log_buffer.add_log("\n\t")
        assert len(log_buffer._buffer) == 0
        assert log_buffer._counter == 0

    def test_add_log_strips_whitespace(self):
        """Test that whitespace is stripped from messages."""
        log_buffer.add_log("  Message with spaces  \n")
        assert log_buffer._buffer[0]["msg"] == "Message with spaces"

    def test_add_log_sets_correct_tag(self):
        """Test that tag is correctly classified (source is not stored in buffer)."""
        log_buffer.add_log("[DB] Database query")
        entry = log_buffer._buffer[0]
        assert entry["tag"] == "system"
        # Note: source is NOT stored in buffer entry, only passed to _enqueue_persist
        assert "msg" in entry
        assert entry["msg"] == "[DB] Database query"

    def test_ring_buffer_maxlen_constraint(self):
        """Test that buffer respects maxlen=2000 constraint."""
        # Fill buffer beyond maxlen
        for i in range(2100):
            log_buffer.add_log(f"Message {i}")

        # Buffer should only contain last 2000 entries
        assert len(log_buffer._buffer) == 2000
        # First entry should be id=101 (2100 - 2000 + 1)
        assert log_buffer._buffer[0]["id"] == 101
        # Last entry should be id=2100
        assert log_buffer._buffer[-1]["id"] == 2100

    def test_add_log_enqueues_persist(self):
        """Test that add_log enqueues entries for persistence."""
        log_buffer.add_log("[DB] Test persist")
        assert len(log_buffer._persist_buffer) == 1
        assert log_buffer._persist_buffer[0]["message"] == "[DB] Test persist"
        assert log_buffer._persist_buffer[0]["tag"] == "system"
        assert log_buffer._persist_buffer[0]["source"] == "database"

    def test_add_log_time_format(self):
        """Test that time is correctly formatted as HH:MM:SS."""
        log_buffer.add_log("Test message")
        entry = log_buffer._buffer[0]
        # Check time format is HH:MM:SS
        assert len(entry["time"]) == 8
        assert entry["time"][2] == ":"
        assert entry["time"][5] == ":"


# ─────────────────────────────────────────────────────────────────────────────
# get_logs Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGetLogs:
    """Tests for get_logs() function."""

    def test_get_logs_empty_buffer(self):
        """Test get_logs on empty buffer."""
        result = log_buffer.get_logs()
        assert result == []

    def test_get_logs_all_entries(self):
        """Test get_logs returns all entries when since=0."""
        log_buffer.add_log("Message 1")
        log_buffer.add_log("Message 2")
        log_buffer.add_log("Message 3")

        result = log_buffer.get_logs(since=0)
        assert len(result) == 3
        assert result[0]["msg"] == "Message 1"
        assert result[-1]["msg"] == "Message 3"

    def test_get_logs_filters_by_since(self):
        """Test get_logs filters entries by since parameter."""
        log_buffer.add_log("Message 1")
        log_buffer.add_log("Message 2")
        log_buffer.add_log("Message 3")

        result = log_buffer.get_logs(since=1)
        assert len(result) == 2
        assert result[0]["id"] == 2
        assert result[1]["id"] == 3

    def test_get_logs_respects_limit(self):
        """Test get_logs respects limit parameter."""
        for i in range(10):
            log_buffer.add_log(f"Message {i}")

        result = log_buffer.get_logs(since=0, limit=5)
        assert len(result) == 5
        # Should return last 5 entries
        assert result[0]["id"] == 6
        assert result[-1]["id"] == 10

    def test_get_logs_limit_larger_than_available(self):
        """Test get_logs when limit is larger than available entries."""
        log_buffer.add_log("Message 1")
        log_buffer.add_log("Message 2")

        result = log_buffer.get_logs(since=0, limit=100)
        assert len(result) == 2

    def test_get_logs_since_beyond_buffer(self):
        """Test get_logs when since is beyond buffer range."""
        log_buffer.add_log("Message 1")
        log_buffer.add_log("Message 2")

        result = log_buffer.get_logs(since=100)
        assert result == []

    def test_get_logs_thread_safe(self):
        """Test that get_logs is thread-safe."""
        results = []

        def add_logs():
            for i in range(10):
                log_buffer.add_log(f"Message {i}")

        def get_logs_concurrent():
            result = log_buffer.get_logs(since=0)
            results.append(len(result))

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=add_logs))
            threads.append(threading.Thread(target=get_logs_concurrent))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not raise any errors
        assert all(r <= 30 for r in results)


# ─────────────────────────────────────────────────────────────────────────────
# Persistence and Batch Flush Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPersistence:
    """Tests for persistence buffer and flush behavior."""

    def test_enqueue_persist_adds_to_buffer(self):
        """Test that _enqueue_persist adds entries to persist buffer."""
        brt = datetime.now(timezone(timedelta(hours=-3)))
        log_buffer._enqueue_persist("system", "database", "Test message", brt)

        assert len(log_buffer._persist_buffer) == 1
        assert log_buffer._persist_buffer[0]["message"] == "Test message"
        assert log_buffer._persist_buffer[0]["tag"] == "system"
        assert log_buffer._persist_buffer[0]["source"] == "database"

    def test_enqueue_persist_truncates_long_messages(self):
        """Test that persist buffer truncates messages over 2000 chars."""
        brt = datetime.now(timezone(timedelta(hours=-3)))
        long_msg = "x" * 3000
        log_buffer._enqueue_persist("debug", "app", long_msg, brt)

        assert len(log_buffer._persist_buffer[0]["message"]) == 2000

    @patch("src.core.log_buffer._do_insert")
    def test_flush_on_batch_size_reached(self, mock_insert):
        """Test that flush triggers when batch size is reached."""
        brt = datetime.now(timezone(timedelta(hours=-3)))

        # Fill buffer to BATCH_SIZE (20)
        for i in range(log_buffer._BATCH_SIZE):
            log_buffer._enqueue_persist("debug", "app", f"Message {i}", brt)

        # Persist buffer should be empty after flush
        assert len(log_buffer._persist_buffer) == 0
        mock_insert.assert_called_once()

    @patch("src.core.database.client.is_enabled")
    @patch("src.core.database.client._get_client")
    def test_do_insert_calls_supabase(self, mock_get_client, mock_is_enabled):
        """Test that _do_insert calls Supabase insert."""
        mock_db = MagicMock()
        mock_get_client.return_value = mock_db
        mock_is_enabled.return_value = True

        batch = [{"message": "Test", "tag": "debug", "source": "app", "created_at": "2026-03-28T12:00:00"}]
        log_buffer._do_insert(batch)

        mock_db.table.assert_called_once_with("system_logs")
        mock_db.table().insert.assert_called_once_with(batch)

    @patch("src.core.database.client.is_enabled")
    def test_flush_to_supabase_disabled(self, mock_is_enabled):
        """Test that flush clears buffer when persistence is disabled."""
        mock_is_enabled.return_value = False

        log_buffer._persist_buffer.append({"message": "Test"})
        log_buffer._flush_to_supabase()

        assert len(log_buffer._persist_buffer) == 0

    @patch("src.core.database.client._get_client")
    def test_do_insert_handles_exception(self, mock_get_client):
        """Test that _do_insert handles exceptions gracefully."""
        mock_get_client.side_effect = Exception("Database error")

        batch = [{"message": "Test"}]
        # Should not raise exception
        log_buffer._do_insert(batch)


# ─────────────────────────────────────────────────────────────────────────────
# Supabase Query Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSupabaseQueries:
    """Tests for get_history(), get_daily_stats(), and get_sources()."""

    @patch("src.core.database.client._get_client")
    def test_get_history_basic(self, mock_get_client):
        """Test get_history returns logs from Supabase."""
        mock_result = MagicMock()
        mock_result.data = [{"id": 1, "message": "Test"}]
        mock_result.count = 1

        # The query chain is dynamic based on filters. Use MagicMock's auto-chaining.
        mock_db = MagicMock()
        # MagicMock auto-chains: any method returns another MagicMock
        # We just need execute() at the end to return our result
        mock_db.table.return_value.select.return_value.order.return_value.range.return_value.execute.return_value = mock_result
        mock_get_client.return_value = mock_db

        result = log_buffer.get_history()

        assert result["logs"] == [{"id": 1, "message": "Test"}]
        assert result["total"] == 1
        assert result["page"] == 1

    @patch("src.core.database.client._get_client")
    def test_get_history_with_filters(self, mock_get_client):
        """Test get_history applies filters correctly."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_result.count = 0

        mock_db.table().select().eq().eq().gte().lt().ilike().order().range().execute.return_value = mock_result
        mock_get_client.return_value = mock_db

        log_buffer.get_history(tag="error", source="database", search="test")

        # Verify that filter calls were made
        mock_db.table.assert_called()

    @patch("src.core.database.client._get_client")
    def test_get_history_no_db(self, mock_get_client):
        """Test get_history returns empty result when DB is unavailable."""
        mock_get_client.return_value = None

        result = log_buffer.get_history()

        assert result == {"logs": [], "total": 0, "page": 1, "pages": 0}

    @patch("src.core.database.client._get_client")
    def test_get_history_exception(self, mock_get_client):
        """Test get_history handles exceptions gracefully."""
        mock_get_client.side_effect = Exception("Connection error")

        result = log_buffer.get_history()

        assert result["logs"] == []
        assert result["total"] == 0
        assert "error" in result

    @patch("src.core.database.client._get_client")
    def test_get_daily_stats(self, mock_get_client):
        """Test get_daily_stats returns RPC result."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"date": "2026-03-28", "count": 100}]

        mock_db.rpc().execute.return_value = mock_result
        mock_get_client.return_value = mock_db

        result = log_buffer.get_daily_stats()

        assert result == [{"date": "2026-03-28", "count": 100}]

    @patch("src.core.database.client._get_client")
    def test_get_daily_stats_no_db(self, mock_get_client):
        """Test get_daily_stats returns empty when DB unavailable."""
        mock_get_client.return_value = None

        result = log_buffer.get_daily_stats()

        assert result == []

    @patch("src.core.database.client._get_client")
    def test_get_sources(self, mock_get_client):
        """Test get_sources returns distinct sources."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"source": "database"},
            {"source": "llm"},
            {"source": "database"},
        ]

        mock_db.table().select().limit().execute.return_value = mock_result
        mock_get_client.return_value = mock_db

        result = log_buffer.get_sources()

        assert "database" in result
        assert "llm" in result
        assert len(set(result)) == len(result)  # All unique
        assert result == sorted(result)  # Should be sorted

    @patch("src.core.database.client._get_client")
    def test_get_sources_no_db(self, mock_get_client):
        """Test get_sources returns empty when DB unavailable."""
        mock_get_client.return_value = None

        result = log_buffer.get_sources()

        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# LogCapture and install Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLogCapture:
    """Tests for _LogCapture class and install() function."""

    def test_log_capture_write_intercepting(self):
        """Test that _LogCapture intercepts writes."""
        mock_original = MagicMock()
        capture = log_buffer._LogCapture(mock_original)

        capture.write("Test message")

        # Should have called original write
        mock_original.write.assert_called_once()
        # Should have added to log buffer
        assert len(log_buffer._buffer) == 1

    def test_log_capture_ignores_empty_writes(self):
        """Test that _LogCapture ignores empty writes."""
        mock_original = MagicMock()
        capture = log_buffer._LogCapture(mock_original)

        capture.write("")
        capture.write("   ")

        # Original write should still be called
        assert mock_original.write.call_count == 2
        # But buffer should be empty
        assert len(log_buffer._buffer) == 0

    def test_log_capture_flush(self):
        """Test that _LogCapture forwards flush() calls."""
        mock_original = MagicMock()
        capture = log_buffer._LogCapture(mock_original)

        capture.flush()

        mock_original.flush.assert_called_once()

    def test_log_capture_fileno(self):
        """Test that _LogCapture forwards fileno() calls."""
        mock_original = MagicMock()
        mock_original.fileno.return_value = 1
        capture = log_buffer._LogCapture(mock_original)

        result = capture.fileno()

        assert result == 1

    def test_log_capture_isatty(self):
        """Test that _LogCapture forwards isatty() calls."""
        mock_original = MagicMock()
        mock_original.isatty.return_value = True
        capture = log_buffer._LogCapture(mock_original)

        result = capture.isatty()

        assert result is True

    def test_install_captures_stdout(self):
        """Test that install() captures stdout."""
        original_stdout = sys.stdout

        try:
            log_buffer.install()

            # stdout should be wrapped
            assert isinstance(sys.stdout, log_buffer._LogCapture)
            assert isinstance(sys.stderr, log_buffer._LogCapture)
        finally:
            sys.stdout = original_stdout

    def test_install_idempotent(self):
        """Test that install() is idempotent (safe to call multiple times)."""
        log_buffer.install()
        first_stdout = sys.stdout

        log_buffer.install()
        second_stdout = sys.stdout

        # Should not double-wrap
        assert first_stdout is second_stdout
        assert isinstance(sys.stdout, log_buffer._LogCapture)


# ─────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_full_logging_flow(self):
        """Test complete flow from add_log to buffer storage."""
        log_buffer.add_log("[DB] User query")
        log_buffer.add_log("[LLM] Token count: 250")
        log_buffer.add_log("[SECURITY] Injection blocked")

        # Check in-memory buffer
        logs = log_buffer.get_logs()
        assert len(logs) == 3

        # Check tags (source is not stored in buffer, only passed to persist)
        assert logs[0]["tag"] == "system"
        assert logs[0]["msg"] == "[DB] User query"
        assert logs[1]["tag"] == "system"
        assert logs[2]["tag"] == "security"

    def test_logging_multiple_sources_and_tags(self):
        """Test logging with various sources and tag combinations."""
        messages = [
            ("[DB] Query", "system"),
            ("[ERRO] Failed operation", "error"),
            ("[SECURITY] Block attempt", "security"),
            ("[LLM] Processing", "system"),
            ("Random message", "debug"),
        ]

        for msg, expected_tag in messages:
            log_buffer.add_log(msg)

        logs = log_buffer.get_logs()
        for i, (msg, expected_tag) in enumerate(messages):
            assert logs[i]["tag"] == expected_tag
            assert logs[i]["tag"] == expected_tag

    @patch("src.core.database.client.is_enabled")
    @patch("src.core.database.client._get_client")
    def test_logging_with_persistence_flow(self, mock_get_client, mock_is_enabled):
        """Test logging flow with Supabase persistence."""
        mock_db = MagicMock()
        mock_get_client.return_value = mock_db
        mock_is_enabled.return_value = True

        # Add enough logs to trigger flush
        for i in range(log_buffer._BATCH_SIZE):
            log_buffer.add_log(f"[DB] Message {i}")

        # Wait a bit for async thread
        time.sleep(0.1)

        # Persist buffer should be cleared after flush
        assert len(log_buffer._persist_buffer) == 0

    def test_get_logs_with_various_filters(self):
        """Test get_logs with different since and limit combinations."""
        for i in range(50):
            log_buffer.add_log(f"Message {i}")

        # Test various combinations
        result = log_buffer.get_logs(since=0, limit=10)
        assert len(result) == 10
        assert result[0]["id"] == 41

        result = log_buffer.get_logs(since=30, limit=100)
        assert len(result) == 20
        assert result[0]["id"] == 31

        result = log_buffer.get_logs(since=45, limit=10)
        assert len(result) == 5
        assert result[-1]["id"] == 50
