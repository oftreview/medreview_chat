"""
tests/critical/test_history_truncation.py — Testes do BUG CRITICO 4.

Overlap na Truncagem de Historico (src/agent/sales_agent.py:158-163)
KEEP_FIRST=4, KEEP_LAST=26 perde msg do meio com 31 msgs.

Estes testes verificam que:
- 30 mensagens (exato MAX_HISTORY) nao sofrem truncagem
- 31 mensagens documenta o bug de gap/overlap
- 50 mensagens preservam integridade
- Ordem e preservada
"""
import pytest
from src.agent.sales_agent import (
    _truncate_history,
    KEEP_FIRST,
    KEEP_LAST,
    MAX_HISTORY,
)


@pytest.mark.critical
class TestHistoryTruncation:
    """Testes criticos de truncagem de historico."""

    def test_30_messages_no_truncation(self):
        """Exatamente MAX_HISTORY msgs retorna tudo sem truncar."""
        history = [{"role": "user", "content": f"Msg {i}"} for i in range(MAX_HISTORY)]

        result = _truncate_history(history)

        assert len(result) == MAX_HISTORY
        assert result == history

    def test_31_messages_truncation_documents_bug(self):
        """
        BUG 4: Com 31 msgs, KEEP_FIRST=4 + KEEP_LAST=26 = 30.
        A mensagem na posicao 4 (indice 4, a 5a msg) e PERDIDA.
        Este teste DOCUMENTA o bug — nao o corrige.
        """
        history = [{"role": "user", "content": f"Mensagem {i}"} for i in range(31)]

        result = _truncate_history(history)

        assert len(result) == KEEP_FIRST + KEEP_LAST  # 30

        # First 4 are kept
        for i in range(KEEP_FIRST):
            assert result[i]["content"] == f"Mensagem {i}"

        # Last 26 are kept (indices 5-30 of original)
        for i in range(KEEP_LAST):
            original_idx = 31 - KEEP_LAST + i
            assert result[KEEP_FIRST + i]["content"] == f"Mensagem {original_idx}"

        # BUG: Mensagem 4 is LOST (not in first 4 nor last 26)
        all_contents = [m["content"] for m in result]
        assert "Mensagem 4" not in all_contents, \
            "BUG 4 confirmed: Mensagem 4 is lost in truncation"

    def test_50_messages_truncation_integrity(self):
        """50 msgs: verifica que first e last sao preservados e gap esta correto."""
        history = [{"role": "user", "content": f"Msg {i}"} for i in range(50)]

        result = _truncate_history(history)

        assert len(result) == KEEP_FIRST + KEEP_LAST

        # First KEEP_FIRST preserved
        for i in range(KEEP_FIRST):
            assert result[i]["content"] == f"Msg {i}"

        # Last KEEP_LAST preserved
        for i in range(KEEP_LAST):
            original_idx = 50 - KEEP_LAST + i
            assert result[KEEP_FIRST + i]["content"] == f"Msg {original_idx}"

        # Gap: messages 4 through 23 are lost
        all_contents = set(m["content"] for m in result)
        for lost_idx in range(KEEP_FIRST, 50 - KEEP_LAST):
            assert f"Msg {lost_idx}" not in all_contents

    def test_truncation_preserves_order(self):
        """Primeira msg da truncagem e a primeira do original, ultima e a ultima."""
        history = [{"role": "user", "content": f"Msg {i}"} for i in range(40)]

        result = _truncate_history(history)

        assert result[0]["content"] == "Msg 0"
        assert result[-1]["content"] == "Msg 39"

    def test_exact_max_history_boundary(self):
        """Exatamente MAX_HISTORY nao deve truncar."""
        history = [{"role": "user", "content": f"Msg {i}"} for i in range(MAX_HISTORY)]

        result = _truncate_history(history)

        assert len(result) == MAX_HISTORY
        assert result[0]["content"] == "Msg 0"
        assert result[-1]["content"] == f"Msg {MAX_HISTORY - 1}"

    def test_one_over_max_loses_exactly_one_message(self):
        """MAX_HISTORY + 1 mensagens perde exatamente 1 mensagem."""
        n = MAX_HISTORY + 1
        history = [{"role": "user", "content": f"Msg {i}"} for i in range(n)]

        result = _truncate_history(history)

        assert len(result) == KEEP_FIRST + KEEP_LAST
        # Exactly one message lost (the one at index KEEP_FIRST)
        all_contents = [m["content"] for m in result]
        lost_count = n - len(result)
        assert lost_count == 1
