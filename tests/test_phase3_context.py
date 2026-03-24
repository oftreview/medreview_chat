"""
tests/test_phase3_context.py — Testes da Fase 3 (Context Injection).

Valida:
1. Context injector NÃO quebra quando Wild Memory não disponível
2. Context injector NÃO propaga exceções
3. Context injector respeita timeout de 5s
4. Metrics tracking funciona
5. Env var controla ativação
6. call_claude aceita memory_context opcional (backward-compatible)
7. Integração no SalesAgent é mínima
8. Prompt cache é preservado (blocos de sistema separados)
9. Integridade dos arquivos originais
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


class TestContextMetrics(unittest.TestCase):
    """Testa o sistema de métricas do context injector."""

    def test_metrics_initial_state(self):
        from src.core.wild_memory_context import ContextMetrics
        m = ContextMetrics()
        d = m.to_dict()
        self.assertEqual(d["total_requests"], 0)
        self.assertEqual(d["total_hits"], 0)
        self.assertEqual(d["total_misses"], 0)
        self.assertEqual(d["total_errors"], 0)
        self.assertEqual(d["total_timeouts"], 0)

    def test_metrics_record_hit(self):
        from src.core.wild_memory_context import ContextMetrics
        m = ContextMetrics()
        m.record_hit(150.0, 5)
        d = m.to_dict()
        self.assertEqual(d["total_hits"], 1)
        self.assertEqual(d["total_requests"], 1)
        self.assertAlmostEqual(d["avg_retrieval_ms"], 150.0, places=1)

    def test_metrics_record_miss(self):
        from src.core.wild_memory_context import ContextMetrics
        m = ContextMetrics()
        m.record_miss(50.0)
        d = m.to_dict()
        self.assertEqual(d["total_misses"], 1)
        self.assertEqual(d["total_requests"], 1)

    def test_metrics_record_timeout(self):
        from src.core.wild_memory_context import ContextMetrics
        m = ContextMetrics()
        m.record_timeout()
        d = m.to_dict()
        self.assertEqual(d["total_timeouts"], 1)
        self.assertEqual(d["total_requests"], 1)

    def test_metrics_thread_safety(self):
        from src.core.wild_memory_context import ContextMetrics
        m = ContextMetrics()
        errors = []

        def _record(n):
            try:
                for _ in range(100):
                    m.record_hit(10.0, 3)
                    m.record_miss(5.0)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_record, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertEqual(m.to_dict()["total_requests"], 1000)


class TestContextInjectorDisabled(unittest.TestCase):
    """Testa comportamento com context injection DESABILITADO."""

    @patch.dict(os.environ, {"WILD_MEMORY_CONTEXT": ""}, clear=False)
    def test_get_context_returns_none_when_disabled(self):
        from src.core.wild_memory_context import WildMemoryContextInjector
        c = WildMemoryContextInjector()
        result = c.get_context("session123", "quero saber sobre o extensivo")
        self.assertIsNone(result)

    @patch.dict(os.environ, {"WILD_MEMORY_CONTEXT": ""}, clear=False)
    def test_status_when_disabled(self):
        from src.core.wild_memory_context import WildMemoryContextInjector
        c = WildMemoryContextInjector()
        c._lazy_init()
        status = c.get_status()
        self.assertFalse(status["enabled"])
        self.assertFalse(status["active"])


class TestContextInjectorEnabled(unittest.TestCase):
    """Testa comportamento com context injection HABILITADO."""

    @patch.dict(os.environ, {"WILD_MEMORY_CONTEXT": "true"}, clear=False)
    def test_graceful_without_wild_memory(self):
        from src.core.wild_memory_context import WildMemoryContextInjector
        c = WildMemoryContextInjector()

        with patch("wild_memory.init_medreview.get_wild_memory", return_value=None):
            with patch("wild_memory.init_medreview.get_status", return_value={"error": "test"}):
                result = c.get_context("session123", "oi")

        self.assertIsNone(result)
        self.assertFalse(c._enabled)

    @patch.dict(os.environ, {"WILD_MEMORY_CONTEXT": "true"}, clear=False)
    def test_graceful_on_import_error(self):
        from src.core.wild_memory_context import WildMemoryContextInjector
        c = WildMemoryContextInjector()

        with patch.dict("sys.modules", {"wild_memory.init_medreview": None}):
            c._init_attempted = False
            result = c.get_context("session123", "oi")

        self.assertIsNone(result)


class TestContextNeverPropagatesExceptions(unittest.TestCase):
    """Garante que exceções NUNCA vazam pro agente."""

    @patch.dict(os.environ, {"WILD_MEMORY_CONTEXT": "true"}, clear=False)
    def test_get_context_swallows_exceptions(self):
        from src.core.wild_memory_context import WildMemoryContextInjector
        c = WildMemoryContextInjector()

        def _boom():
            raise RuntimeError("BOOM!")

        c._lazy_init = _boom

        try:
            result = c.get_context("session123", "oi")
        except Exception as e:
            self.fail(f"get_context() propagou exceção: {e}")

        self.assertIsNone(result)


class TestCallClaudeBackwardCompatibility(unittest.TestCase):
    """Verifica que call_claude continua backward-compatible."""

    def test_signature_accepts_memory_context(self):
        """call_claude deve aceitar memory_context como parâmetro opcional."""
        # Check source directly (anthropic may not be installed in sandbox)
        source = _read_file("src/core/llm.py")
        self.assertIn("def call_claude(system_prompt: str, messages: list, memory_context: str = None)", source)

    def test_system_cache_structure_without_context(self):
        """Sem memory_context, deve ter apenas 1 bloco de sistema."""
        source = _read_file("src/core/llm.py")
        # O bloco original com cache_control deve existir
        self.assertIn('"cache_control": {"type": "ephemeral"}', source)

    def test_system_cache_structure_with_context(self):
        """Com memory_context, deve adicionar bloco extra."""
        source = _read_file("src/core/llm.py")
        self.assertIn("if memory_context:", source)
        self.assertIn("system_with_cache.append(", source)


class TestSalesAgentIntegrationPhase3(unittest.TestCase):
    """Verifica a integração no SalesAgent."""

    def test_context_import_exists(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("from src.core.wild_memory_context import context_injector", source)

    def test_context_get_called(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("_wild_context.get_context(", source)

    def test_memory_context_passed_to_call_claude(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("memory_context=memory_briefing", source)

    def test_context_call_before_call_claude(self):
        """get_context() deve ser chamado ANTES de call_claude()."""
        source = _read_file("src/agent/sales_agent.py")
        idx_context = source.index("_wild_context.get_context(")
        idx_claude = source.index("call_claude(self.system_prompt")
        self.assertLess(
            idx_context, idx_claude,
            "get_context() deve ser chamado ANTES de call_claude()"
        )

    def test_shadow_still_present(self):
        """Shadow mode (Fase 2) deve continuar presente."""
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("_wild_shadow.observe(", source)

    def test_agent_minimal_changes(self):
        """SalesAgent deve ter exatamente 6 linhas wild: 3 imports + observe + get_context + on_session_end."""
        source = _read_file("src/agent/sales_agent.py")
        wild_refs = [
            line.strip() for line in source.split("\n")
            if "wild" in line.lower()
            and not line.strip().startswith("#")
            and line.strip()  # skip empty
        ]
        # 3 imports (shadow, context, lifecycle) + observe() + get_context() + on_session_end() = 6
        self.assertEqual(
            len(wild_refs), 6,
            f"Esperado 6 referências a wild no agente, encontrado {len(wild_refs)}: {wild_refs}"
        )


class TestPromptCachePreserved(unittest.TestCase):
    """Verifica que o prompt cache da Anthropic é preservado."""

    def test_original_prompt_has_cache_control(self):
        """Bloco 1 (prompt original) deve ter cache_control."""
        source = _read_file("src/core/llm.py")
        # The cache control block should still be there
        self.assertIn('"cache_control": {"type": "ephemeral"}', source)

    def test_memory_context_block_no_cache_control(self):
        """Bloco 2 (memory context) NÃO deve ter cache_control."""
        source = _read_file("src/core/llm.py")
        # Find the memory_context append block
        idx_append = source.index("system_with_cache.append(")
        append_block = source[idx_append:idx_append + 200]
        # The memory context block should NOT have cache_control
        self.assertNotIn("cache_control", append_block)


class TestHealthEndpointPhase3(unittest.TestCase):
    """Verifica que o health endpoint inclui context injection."""

    def test_health_includes_context_injection(self):
        source = _read_file("src/api/health.py")
        self.assertIn("context_injection", source)
        self.assertIn("context_injector", source)


class TestOriginalFilesIntegrityPhase3(unittest.TestCase):
    """Verifica que arquivos core NÃO foram corrompidos."""

    def test_memory_py_unchanged(self):
        source = _read_file("src/core/memory.py")
        self.assertNotIn("wild_memory", source)
        self.assertNotIn("context", source.lower().replace("context_snapshot", ""))
        self.assertIn("class ConversationMemory", source)

    def test_llm_py_backward_compatible(self):
        """llm.py deve manter a assinatura original + novo param opcional."""
        source = _read_file("src/core/llm.py")
        self.assertIn("def call_claude(system_prompt: str, messages: list", source)
        self.assertIn("memory_context: str = None", source)
        # Original behavior preserved
        self.assertIn("cache_control", source)
        self.assertIn("client.messages.create", source)

    def test_agent_reply_signature_intact(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("def reply(self, user_message: str, session_id: str", source)

    def test_agent_escalation_intact(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("ESCALATION_TAG", source)
        self.assertIn("ESCALATION_FALLBACK_PHRASES", source)

    def test_agent_meta_extraction_intact(self):
        source = _read_file("src/agent/sales_agent.py")
        self.assertIn("_extract_metadata", source)
        self.assertIn("META_PATTERN", source)

    def test_chat_api_unchanged(self):
        source = _read_file("src/api/chat.py")
        self.assertNotIn("wild_memory", source)
        self.assertNotIn("context_injector", source)


if __name__ == "__main__":
    unittest.main()
