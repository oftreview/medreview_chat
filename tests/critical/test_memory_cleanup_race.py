"""
tests/critical/test_memory_cleanup_race.py — Testes do BUG CRITICO 3.

Race no Cleanup de Memoria (src/core/memory.py:57-76)
_cleanup_expired() remove sessao enquanto add() esta sendo chamado.

Estes testes verificam que:
- Sessoes ativas nao sao removidas pelo cleanup
- Sessoes expiradas sao removidas
- Sessoes escalated nao sao removidas
- add() e cleanup() simultaneos nao corrompem estado
"""
import time
import threading
import pytest
from unittest.mock import patch, MagicMock

from src.core.memory import ConversationMemory, SESSION_TTL_SECONDS


@pytest.mark.critical
class TestCleanupActiveSessions:
    """Testa que cleanup nao remove sessoes ativas."""

    @pytest.fixture
    def memory(self):
        """Cria instancia de memoria com cleanup loop desabilitado."""
        with patch.object(ConversationMemory, "_start_cleanup_loop"):
            mem = ConversationMemory()
        return mem

    def test_cleanup_does_not_remove_active_session(self, memory):
        """Sessao com acesso recente NAO deve ser removida pelo cleanup."""
        user_id = "active-user-001"
        memory.sessions[user_id] = [{"role": "user", "content": "Oi"}]
        memory._last_access[user_id] = time.time()  # Acesso agora

        memory._cleanup_expired()

        assert user_id in memory.sessions, "Active session should NOT be removed"

    def test_cleanup_removes_expired_session(self, memory):
        """Sessao sem acesso > TTL deve ser removida."""
        user_id = "expired-user-001"
        memory.sessions[user_id] = [{"role": "user", "content": "Antiga"}]
        memory._last_access[user_id] = time.time() - SESSION_TTL_SECONDS - 60  # Expired

        memory._cleanup_expired()

        assert user_id not in memory.sessions, "Expired session should be removed"

    def test_cleanup_preserves_escalated_sessions(self, memory):
        """Sessoes escalated NUNCA devem ser removidas, mesmo expiradas."""
        user_id = "escalated-user-001"
        memory.sessions[user_id] = [{"role": "user", "content": "Escalado"}]
        memory.statuses[user_id] = "escalated"
        memory._last_access[user_id] = time.time() - SESSION_TTL_SECONDS - 3600  # Muito expirado

        memory._cleanup_expired()

        assert user_id in memory.sessions, "Escalated session should NOT be removed"

    def test_cleanup_removes_only_expired(self, memory):
        """Mix de sessoes: apenas as expiradas sao removidas."""
        # Sessao ativa
        memory.sessions["active"] = [{"role": "user", "content": "Ativa"}]
        memory._last_access["active"] = time.time()

        # Sessao expirada
        memory.sessions["expired"] = [{"role": "user", "content": "Antiga"}]
        memory._last_access["expired"] = time.time() - SESSION_TTL_SECONDS - 60

        # Sessao escalated expirada
        memory.sessions["escalated"] = [{"role": "user", "content": "Escalada"}]
        memory.statuses["escalated"] = "escalated"
        memory._last_access["escalated"] = time.time() - SESSION_TTL_SECONDS - 60

        memory._cleanup_expired()

        assert "active" in memory.sessions
        assert "expired" not in memory.sessions
        assert "escalated" in memory.sessions


@pytest.mark.critical
class TestConcurrentAddAndCleanup:
    """Testa que add() e cleanup() simultaneos nao corrompem estado."""

    @pytest.fixture
    def memory(self):
        with patch.object(ConversationMemory, "_start_cleanup_loop"):
            mem = ConversationMemory()
        return mem

    def test_concurrent_add_and_cleanup(self, memory):
        """add() e _cleanup_expired() chamados em threads nao devem corromper estado."""
        user_id = "concurrent-user-001"
        errors = []

        def add_messages():
            try:
                for i in range(50):
                    memory.sessions.setdefault(user_id, []).append(
                        {"role": "user", "content": f"Msg {i}"}
                    )
                    with memory._lock:
                        memory._last_access[user_id] = time.time()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"add error: {e}")

        def run_cleanup():
            try:
                for _ in range(20):
                    memory._cleanup_expired()
                    time.sleep(0.002)
            except Exception as e:
                errors.append(f"cleanup error: {e}")

        t1 = threading.Thread(target=add_messages)
        t2 = threading.Thread(target=run_cleanup)

        t1.start()
        t2.start()

        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Concurrent operations raised errors: {errors}"
        # Session should still be alive since we keep touching it
        assert user_id in memory.sessions, "Active session should survive concurrent cleanup"

    def test_cleanup_during_add_does_not_lose_new_data(self, memory):
        """Mesmo se cleanup roda, dados novos adicionados apos o touch devem persistir."""
        user_id = "race-user-001"

        # Set up session as almost expired
        memory.sessions[user_id] = [{"role": "user", "content": "Old msg"}]
        memory._last_access[user_id] = time.time() - SESSION_TTL_SECONDS + 1  # Almost expired

        # Touch it (simulating add)
        with memory._lock:
            memory._last_access[user_id] = time.time()
        memory.sessions[user_id].append({"role": "user", "content": "New msg"})

        # Run cleanup - session should survive because of fresh touch
        memory._cleanup_expired()

        assert user_id in memory.sessions, "Freshly touched session should survive cleanup"
        assert len(memory.sessions[user_id]) == 2

    def test_cleanup_clears_all_session_artifacts(self, memory):
        """Quando sessao expira, TODOS os artefatos sao limpos."""
        user_id = "full-cleanup-user"
        memory.sessions[user_id] = [{"role": "user", "content": "Msg"}]
        memory._loaded_from_db.add(user_id)
        memory._session_ids[user_id] = "uuid-123"
        memory._last_access[user_id] = time.time() - SESSION_TTL_SECONDS - 60

        memory._cleanup_expired()

        assert user_id not in memory.sessions
        assert user_id not in memory._loaded_from_db
        assert user_id not in memory._session_ids
        assert user_id not in memory._last_access
