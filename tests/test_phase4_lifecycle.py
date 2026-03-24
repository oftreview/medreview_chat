"""
tests/test_phase4_lifecycle.py — Testes da Fase 4 (Full Takeover / Lifecycle).

Valida:
1. Lifecycle hooks NÃO quebram quando Wild Memory não disponível
2. Lifecycle hooks NÃO propagam exceções
3. Lifecycle hooks NÃO bloqueiam a thread principal
4. Metrics tracking funciona
5. Escalação registra feedback signal
6. Reset dispara distilação antes de limpar
7. Manutenção diária roda sem erros
8. Endpoint /api/wild-memory/cron existe
9. Integridade dos arquivos (mínimo de mudanças)
"""

import os
import sys
import time
import threading
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_file(relpath):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, relpath)) as f:
        return f.read()


class TestLifecycleMetrics(unittest.TestCase):
    """Testa o sistema de métricas do lifecycle."""

    def test_metrics_initial_state(self):
        from src.core.wild_memory_lifecycle import LifecycleMetrics
        m = LifecycleMetrics()
        d = m.to_dict()
        self.assertEqual(d["total_escalations"], 0)
        self.assertEqual(d["total_session_ends"], 0)
        self.assertEqual(d["total_maintenance_runs"], 0)
        self.assertEqual(d["total_errors"], 0)

    def test_metrics_record_escalation(self):
        from src.core.wild_memory_lifecycle import LifecycleMetrics
        m = LifecycleMetrics()
        m.record_escalation()
        m.record_escalation()
        self.assertEqual(m.to_dict()["total_escalations"], 2)

    def test_metrics_record_session_end(self):
        from src.core.wild_memory_lifecycle import LifecycleMetrics
        m = LifecycleMetrics()
        m.record_session_end()
        self.assertEqual(m.to_dict()["total_session_ends"], 1)

    def test_metrics_record_maintenance(self):
        from src.core.wild_memory_lifecycle import LifecycleMetrics
        m = LifecycleMetrics()
        m.record_maintenance()
        d = m.to_dict()
        self.assertEqual(d["total_maintenance_runs"], 1)
        self.assertIsNotNone(d["last_maintenance_at"])

    def test_metrics_thread_safety(self):
        from src.core.wild_memory_lifecycle import LifecycleMetrics
        m = LifecycleMetrics()
        errors = []

        def _record(n):
            try:
                for _ in range(100):
                    m.record_escalation()
                    m.record_session_end()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_record, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertEqual(m.to_dict()["total_escalations"], 500)
        self.assertEqual(m.to_dict()["total_session_ends"], 500)


class TestLifecycleDisabled(unittest.TestCase):
    """Testa comportamento com lifecycle desabilitado."""

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": ""}, clear=False)
    def test_on_escalation_noop(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        lc.on_escalation("session123", "user456", {"motivo": "teste"})
        self.assertEqual(lc.metrics.to_dict()["total_escalations"], 0)

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": ""}, clear=False)
    def test_on_session_end_noop(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        lc.on_session_end("session123", "user456", reason="reset")
        self.assertEqual(lc.metrics.to_dict()["total_session_ends"], 0)

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": ""}, clear=False)
    def test_maintenance_disabled(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        result = lc.run_daily_maintenance()
        self.assertEqual(result["status"], "disabled")


class TestLifecycleEnabled(unittest.TestCase):
    """Testa comportamento com lifecycle habilitado."""

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_on_escalation_graceful_without_wm(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        with patch("wild_memory.init_medreview.get_wild_memory", return_value=None):
            lc.on_escalation("session123", "user456")
        self.assertEqual(lc.metrics.to_dict()["total_escalations"], 0)

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_on_escalation_records_metric(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        mock_wm = MagicMock()
        lc._wild_memory = mock_wm
        lc._init_attempted = True
        lc._enabled = True

        lc.on_escalation("session123", "user456", {"motivo": "preco"})
        time.sleep(0.1)  # Wait for thread to start
        self.assertEqual(lc.metrics.to_dict()["total_escalations"], 1)

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_on_session_end_records_metric(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        mock_wm = MagicMock()
        lc._wild_memory = mock_wm
        lc._init_attempted = True
        lc._enabled = True

        lc.on_session_end("session123", "user456", reason="reset")
        time.sleep(0.1)
        self.assertEqual(lc.metrics.to_dict()["total_session_ends"], 1)


class TestLifecycleNeverPropagatesExceptions(unittest.TestCase):

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_on_escalation_swallows_exceptions(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        lc._lazy_init = lambda: (_ for _ in ()).throw(RuntimeError("BOOM"))

        try:
            lc.on_escalation("session123", "user456")
        except Exception as e:
            self.fail(f"on_escalation propagou exceção: {e}")

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_on_session_end_swallows_exceptions(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        lc._lazy_init = lambda: (_ for _ in ()).throw(RuntimeError("BOOM"))

        try:
            lc.on_session_end("session123", "user456")
        except Exception as e:
            self.fail(f"on_session_end propagou exceção: {e}")


class TestLifecycleNeverBlocks(unittest.TestCase):

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_on_escalation_returns_immediately(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        mock_wm = MagicMock()
        lc._wild_memory = mock_wm
        lc._init_attempted = True
        lc._enabled = True

        start = time.time()
        lc.on_escalation("session123", "user456")
        elapsed_ms = (time.time() - start) * 1000
        self.assertLess(elapsed_ms, 50)

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_on_session_end_returns_immediately(self):
        from src.core.wild_memory_lifecycle import WildMemoryLifecycle
        lc = WildMemoryLifecycle()
        mock_wm = MagicMock()
        lc._wild_memory = mock_wm
        lc._init_attempted = True
        lc._enabled = True

        start = time.time()
        lc.on_session_end("session123", "user456", reason="reset",
                          messages=[{"role": "user", "content": "oi"}])
        elapsed_ms = (time.time() - start) * 1000
        self.assertLess(elapsed_ms, 50)


class TestEscalationIntegration(unittest.TestCase):
    """Verifica integração no escalation.py."""

    def test_lifecycle_import_in_escalation(self):
        source = _read_file("src/core/escalation.py")
        self.assertIn("from src.core.wild_memory_lifecycle import lifecycle", source)

    def test_on_escalation_called(self):
        source = _read_file("src/core/escalation.py")
        self.assertIn("_wild_lifecycle.on_escalation(", source)

    def test_escalation_hook_after_hubspot(self):
        """Hook deve ser chamado após o sync HubSpot."""
        source = _read_file("src/core/escalation.py")
        idx_hubspot = source.index("hubspot.sync_escalation")
        idx_lifecycle = source.index("_wild_lifecycle.on_escalation(")
        self.assertGreater(idx_lifecycle, idx_hubspot)


class TestSalesAgentIntegrationPhase4(unittest.TestCase):
    """Verifica integração no SalesAgent."""

    def test_lifecycle_import(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("from src.core.wild_memory_lifecycle import lifecycle", source)

    def test_on_session_end_in_reset(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("_wild_lifecycle.on_session_end(", source)

    def test_reset_distills_before_clearing(self):
        """on_session_end deve ser chamado ANTES de memory.reset."""
        source = _read_file("src/agent/sales_agent.py")
        idx_lifecycle = source.index("_wild_lifecycle.on_session_end(")
        idx_reset = source.index("self.memory.reset(session_id)")
        self.assertLess(idx_lifecycle, idx_reset)

    def test_reset_passes_messages(self):
        """Reset deve passar messages para distilação."""
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("messages=messages", source)


class TestCronEndpoint(unittest.TestCase):
    """Verifica endpoint de manutenção diária."""

    def test_cron_endpoint_exists(self):
        source = _read_file("src/api/health.py")
        self.assertIn("/api/wild-memory/cron", source)
        self.assertIn("wild_memory_cron", source)

    def test_cron_requires_auth(self):
        source = _read_file("src/api/health.py")
        self.assertIn("API_SECRET_TOKEN", source)
        self.assertIn("Unauthorized", source)


class TestHealthEndpointPhase4(unittest.TestCase):
    """Verifica health endpoint inclui lifecycle."""

    def test_health_includes_lifecycle(self):
        source = _read_file("src/api/health.py")
        self.assertIn("lifecycle", source)
        self.assertIn("lifecycle.get_status()", source)


class TestOriginalFilesIntegrityPhase4(unittest.TestCase):
    """Verifica integridade dos arquivos."""

    def test_memory_py_unchanged(self):
        source = _read_file("src/core/memory.py")
        self.assertNotIn("wild_memory", source)
        self.assertNotIn("lifecycle", source)
        self.assertIn("class ConversationMemory", source)

    def test_llm_py_unchanged_from_phase3(self):
        source = _read_file("src/core/llm.py")
        self.assertIn("memory_context: str = None", source)
        # No lifecycle references in llm.py
        self.assertNotIn("lifecycle", source)

    def test_chat_api_unchanged(self):
        source = _read_file("src/api/chat.py")
        self.assertNotIn("wild_memory", source)
        self.assertNotIn("lifecycle", source)

    def test_escalation_py_minimal_changes(self):
        """escalation.py deve ter exatamente 2 linhas wild: import + hook."""
        source = _read_file("src/core/escalation.py")
        wild_refs = [
            line.strip() for line in source.split("\n")
            if "wild" in line.lower()
            and not line.strip().startswith("#")
            and line.strip()
        ]
        self.assertEqual(
            len(wild_refs), 2,
            f"Esperado 2 referências wild em escalation.py: {wild_refs}"
        )

    def test_agent_reply_signature_intact(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("def reply(self, user_message: str, session_id: str", source)

    def test_agent_escalation_detection_intact(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("ESCALATION_TAG", source)
        self.assertIn("ESCALATION_FALLBACK_PHRASES", source)


if __name__ == "__main__":
    unittest.main()
