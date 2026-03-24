"""
tests/test_phase2_shadow.py — Testes da Fase 2 (Shadow Mode).

Valida:
1. Shadow observer NÃO quebra quando Wild Memory não está disponível
2. Shadow observer NÃO bloqueia o fluxo principal
3. Shadow observer NÃO propaga exceções
4. Metrics tracking funciona corretamente
5. Gate check funciona (skip mensagens triviais)
6. Env var controla ativação
7. Integração mínima no SalesAgent (import + 1 linha)
8. Endpoint /health/wild-memory retorna JSON válido
9. Integridade dos arquivos originais (nenhum arquivo core foi corrompido)
"""

import os
import sys
import time
import threading
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestShadowMetrics(unittest.TestCase):
    """Testa o sistema de métricas thread-safe."""

    def test_metrics_initial_state(self):
        from src.core.wild_memory_shadow import ShadowMetrics
        m = ShadowMetrics()
        d = m.to_dict()
        self.assertEqual(d["total_observed"], 0)
        self.assertEqual(d["total_distilled"], 0)
        self.assertEqual(d["total_skipped"], 0)
        self.assertEqual(d["total_errors"], 0)
        self.assertIsNone(d["last_error"])

    def test_metrics_record_observation(self):
        from src.core.wild_memory_shadow import ShadowMetrics
        m = ShadowMetrics()
        m.record_observation()
        m.record_observation()
        self.assertEqual(m.to_dict()["total_observed"], 2)
        self.assertIsNotNone(m.to_dict()["last_observation_at"])

    def test_metrics_record_distillation(self):
        from src.core.wild_memory_shadow import ShadowMetrics
        m = ShadowMetrics()
        m.record_distillation(150.0)
        m.record_distillation(250.0)
        d = m.to_dict()
        self.assertEqual(d["total_distilled"], 2)
        self.assertAlmostEqual(d["avg_distill_ms"], 200.0, places=1)

    def test_metrics_record_error(self):
        from src.core.wild_memory_shadow import ShadowMetrics
        m = ShadowMetrics()
        m.record_error("test error")
        d = m.to_dict()
        self.assertEqual(d["total_errors"], 1)
        self.assertEqual(d["last_error"], "test error")

    def test_metrics_thread_safety(self):
        """Métricas devem funcionar com acesso concorrente."""
        from src.core.wild_memory_shadow import ShadowMetrics
        m = ShadowMetrics()
        errors = []

        def _record(n):
            try:
                for _ in range(100):
                    m.record_observation()
                    m.record_distillation(10.0)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_record, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertEqual(m.to_dict()["total_observed"], 500)
        self.assertEqual(m.to_dict()["total_distilled"], 500)


class TestShadowObserverDisabled(unittest.TestCase):
    """Testa comportamento com shadow mode DESABILITADO."""

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": ""}, clear=False)
    def test_observe_noop_when_disabled(self):
        """observe() deve retornar imediatamente sem fazer nada."""
        from src.core.wild_memory_shadow import WildMemoryShadow
        s = WildMemoryShadow()
        # Should not raise, should not block
        s.observe("session123", "oi", "olá! como posso ajudar?")
        # Metrics should be zero (not even recorded)
        self.assertEqual(s.metrics.to_dict()["total_observed"], 0)

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "false"}, clear=False)
    def test_observe_noop_when_false(self):
        from src.core.wild_memory_shadow import WildMemoryShadow
        s = WildMemoryShadow()
        s.observe("session123", "oi", "olá!")
        self.assertEqual(s.metrics.to_dict()["total_observed"], 0)

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": ""}, clear=False)
    def test_status_when_disabled(self):
        from src.core.wild_memory_shadow import WildMemoryShadow
        s = WildMemoryShadow()
        s._lazy_init()
        status = s.get_status()
        self.assertFalse(status["enabled"])
        self.assertFalse(status["active"])


class TestShadowObserverEnabled(unittest.TestCase):
    """Testa comportamento com shadow mode HABILITADO mas sem Wild Memory."""

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_observe_graceful_without_wild_memory(self):
        """Se Wild Memory não inicializa, observe() não quebra."""
        from src.core.wild_memory_shadow import WildMemoryShadow
        s = WildMemoryShadow()

        # Mock get_wild_memory to return None
        with patch("wild_memory.init_medreview.get_wild_memory", return_value=None):
            with patch("wild_memory.init_medreview.get_status", return_value={"error": "test"}):
                s.observe("session123", "oi", "olá!")

        # Should have tried but not crashed
        self.assertTrue(s._init_attempted)
        self.assertFalse(s._enabled)

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_observe_graceful_on_import_error(self):
        """Se wild_memory não está instalado, observe() não quebra."""
        from src.core.wild_memory_shadow import WildMemoryShadow
        s = WildMemoryShadow()

        with patch.dict("sys.modules", {"wild_memory.init_medreview": None}):
            # Force re-init
            s._init_attempted = False
            s.observe("session123", "oi", "olá!")

        self.assertFalse(s._enabled)

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_status_enabled_but_unavailable(self):
        from src.core.wild_memory_shadow import WildMemoryShadow
        s = WildMemoryShadow()

        with patch("wild_memory.init_medreview.get_wild_memory", return_value=None):
            with patch("wild_memory.init_medreview.get_status", return_value={"error": "deps"}):
                s._lazy_init()

        status = s.get_status()
        self.assertTrue(status["enabled"])
        self.assertFalse(status["active"])
        self.assertFalse(status["wild_memory_available"])


class TestShadowNeverBlocks(unittest.TestCase):
    """Garante que observe() NUNCA bloqueia a thread principal."""

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_observe_returns_immediately(self):
        """observe() deve retornar em < 50ms mesmo com Wild Memory."""
        from src.core.wild_memory_shadow import WildMemoryShadow
        s = WildMemoryShadow()

        # Mock Wild Memory to simulate slow processing
        mock_wm = MagicMock()
        mock_wm.distill_gate.should_distill.return_value = True
        mock_wm.ner = MagicMock()
        mock_wm.ner.extract.return_value = []

        s._wild_memory = mock_wm
        s._init_attempted = True
        s._enabled = True

        start = time.time()
        s.observe("session123", "mensagem de teste longa o suficiente", "resposta do agente")
        elapsed_ms = (time.time() - start) * 1000

        # Must return in < 50ms (thread spawn + observe overhead)
        self.assertLess(elapsed_ms, 50, f"observe() bloqueou por {elapsed_ms:.0f}ms!")


class TestShadowNeverPropagatesExceptions(unittest.TestCase):
    """Garante que exceções NUNCA vazam pro agente."""

    @patch.dict(os.environ, {"WILD_MEMORY_SHADOW": "true"}, clear=False)
    def test_observe_swallows_all_exceptions(self):
        """Mesmo com erro interno, observe() não propaga exceção."""
        from src.core.wild_memory_shadow import WildMemoryShadow
        s = WildMemoryShadow()

        # Force _lazy_init to raise
        def _boom():
            raise RuntimeError("BOOM!")

        s._lazy_init = _boom

        # This should NOT raise
        try:
            s.observe("session123", "oi", "olá!")
        except Exception as e:
            self.fail(f"observe() propagou exceção: {e}")


class TestSalesAgentIntegration(unittest.TestCase):
    """Verifica que a integração no SalesAgent é mínima e correta."""

    def test_shadow_import_exists(self):
        """SalesAgent deve importar o shadow."""
        import importlib
        source = open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "src/agent/sales_agent.py"
            )
        ).read()
        self.assertIn("from src.core.wild_memory_shadow import shadow", source)

    def test_shadow_observe_called_in_reply(self):
        """SalesAgent.reply() deve chamar shadow.observe() após salvar resposta."""
        source = open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "src/agent/sales_agent.py"
            )
        ).read()
        self.assertIn("_wild_shadow.observe(", source)

    def test_shadow_call_after_memory_add(self):
        """shadow.observe() deve vir DEPOIS de memory.add(assistant)."""
        source = open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "src/agent/sales_agent.py"
            )
        ).read()
        idx_memory_add = source.index('self.memory.add(session_id, "assistant"')
        idx_shadow = source.index("_wild_shadow.observe(")
        self.assertGreater(
            idx_shadow, idx_memory_add,
            "shadow.observe() deve ser chamado APÓS memory.add(assistant)"
        )

    def test_shadow_call_before_return(self):
        """shadow.observe() deve vir ANTES do return result."""
        source = open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "src/agent/sales_agent.py"
            )
        ).read()
        idx_shadow = source.index("_wild_shadow.observe(")
        idx_return = source.index("return result")
        self.assertLess(
            idx_shadow, idx_return,
            "shadow.observe() deve ser chamado ANTES de return result"
        )


class TestHealthEndpoint(unittest.TestCase):
    """Verifica que o endpoint /health/wild-memory existe."""

    def test_health_endpoint_registered(self):
        source = open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "src/api/health.py"
            )
        ).read()
        self.assertIn("/health/wild-memory", source)
        self.assertIn("health_wild_memory", source)


class TestOriginalFilesIntegrity(unittest.TestCase):
    """Verifica que arquivos core NÃO foram corrompidos."""

    def _read(self, relpath):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, relpath)) as f:
            return f.read()

    def test_memory_py_unchanged(self):
        """core/memory.py não deve ter referência a wild_memory."""
        source = self._read("src/core/memory.py")
        self.assertNotIn("wild_memory", source)
        self.assertNotIn("shadow", source)
        self.assertIn("class ConversationMemory", source)

    def test_llm_py_exists(self):
        """core/llm.py deve existir (dependência do agente)."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertTrue(os.path.exists(os.path.join(root, "src/core/llm.py")))

    def test_database_module_exists(self):
        """core/database/ deve existir."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertTrue(os.path.isdir(os.path.join(root, "src/core/database")))

    def test_agent_reply_signature_intact(self):
        """SalesAgent.reply() deve manter sua assinatura original."""
        source = self._read("src/agent/sales_agent.py")
        self.assertIn("def reply(self, user_message: str, session_id: str", source)
        self.assertIn("return result", source)

    def test_agent_escalation_intact(self):
        """Lógica de escalação do agente deve estar intacta."""
        source = self._read("src/agent/sales_agent.py")
        self.assertIn("ESCALATION_TAG", source)
        self.assertIn("ESCALATION_FALLBACK_PHRASES", source)
        self.assertIn("escalate", source)

    def test_agent_meta_extraction_intact(self):
        """Extração de [META] deve estar intacta."""
        source = self._read("src/agent/sales_agent.py")
        self.assertIn("_extract_metadata", source)
        self.assertIn("META_PATTERN", source)

    def test_chat_api_unchanged(self):
        """chat.py não deve ter referência direta a wild_memory."""
        source = self._read("src/api/chat.py")
        self.assertNotIn("wild_memory", source)
        self.assertNotIn("shadow", source)

    def test_sales_agent_shadow_present(self):
        """SalesAgent deve ter shadow import + observe()."""
        source = self._read("src/agent/sales_agent.py")
        shadow_refs = [
            line for line in source.split("\n")
            if "_wild_shadow" in line and not line.strip().startswith("#")
        ]
        # Deve ter exatamente 2 linhas com shadow: import + observe
        self.assertEqual(
            len(shadow_refs), 2,
            f"Esperado 2 referências a _wild_shadow no agente, encontrado {len(shadow_refs)}: {shadow_refs}"
        )


if __name__ == "__main__":
    unittest.main()
