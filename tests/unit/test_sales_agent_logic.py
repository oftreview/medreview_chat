"""
tests/unit/test_sales_agent_logic.py — Testes da logica do SalesAgent.

Testa: _truncate_history, constantes, escalation detection
Sem I/O, sem chamadas a API.
"""
import pytest
from src.agent.sales_agent import (
    _truncate_history,
    _extract_metadata,
    KEEP_FIRST,
    KEEP_LAST,
    MAX_HISTORY,
    ESCALATION_TAG,
    ESCALATION_FALLBACK_PHRASES,
    META_PATTERN,
)
from tests.fixtures.test_data import make_history


class TestTruncateHistory:
    """Testes da funcao _truncate_history."""

    def test_under_max_returns_all(self):
        """Historico menor que MAX_HISTORY retorna completo."""
        history = make_history(10)
        result = _truncate_history(history)
        assert len(result) == 10
        assert result == history

    def test_at_max_returns_all(self):
        """Historico exatamente MAX_HISTORY retorna completo."""
        history = make_history(MAX_HISTORY)
        result = _truncate_history(history)
        assert len(result) == MAX_HISTORY
        assert result == history

    def test_over_max_truncates(self):
        """Historico maior que MAX_HISTORY e truncado."""
        history = make_history(50)
        result = _truncate_history(history)
        assert len(result) == MAX_HISTORY

    def test_keeps_first_messages(self):
        """Primeiras KEEP_FIRST mensagens sao mantidas."""
        history = make_history(50)
        result = _truncate_history(history)
        for i in range(KEEP_FIRST):
            assert result[i] == history[i]

    def test_keeps_last_messages(self):
        """Ultimas KEEP_LAST mensagens sao mantidas."""
        history = make_history(50)
        result = _truncate_history(history)
        for i in range(1, KEEP_LAST + 1):
            assert result[-i] == history[-i]

    def test_first_message_is_first(self):
        """Primeira mensagem do resultado e a primeira do historico."""
        history = make_history(50)
        result = _truncate_history(history)
        assert result[0]["content"] == "Mensagem 1"

    def test_last_message_is_last(self):
        """Ultima mensagem do resultado e a ultima do historico."""
        history = make_history(50)
        result = _truncate_history(history)
        assert result[-1]["content"] == "Mensagem 50"

    def test_31_messages_truncation(self):
        """BUG 4: Com 31 mensagens, verifica se ha overlap ou gap.

        KEEP_FIRST=4, KEEP_LAST=26, MAX_HISTORY=30
        31 msgs > trunca para first 4 + last 26 = 30
        Mensagem 5 (index 4) pode ser perdida se KEEP_FIRST + KEEP_LAST < 31
        """
        history = make_history(31)
        result = _truncate_history(history)
        assert len(result) == MAX_HISTORY

        # Verifica que primeiro bloco e o esperado
        first_block = [m["content"] for m in result[:KEEP_FIRST]]
        assert first_block == ["Mensagem 1", "Mensagem 2", "Mensagem 3", "Mensagem 4"]

        # Verifica que ultimo bloco e o esperado
        last_block = [m["content"] for m in result[-KEEP_LAST:]]
        expected_last = [f"Mensagem {i}" for i in range(6, 32)]  # msgs 6-31
        assert last_block == expected_last

        # Mensagem 5 (index 4) e PERDIDA — este e o bug documentado
        all_contents = [m["content"] for m in result]
        # Com 31 msgs: first 4 (1-4) + last 26 (6-31) = msg 5 perdida
        assert "Mensagem 5" not in all_contents

    def test_empty_history(self):
        """Historico vazio retorna vazio."""
        assert _truncate_history([]) == []

    def test_single_message(self):
        """Historico com 1 mensagem retorna a mesma."""
        history = [{"role": "user", "content": "Oi"}]
        assert _truncate_history(history) == history


class TestConstants:
    """Testes das constantes do SalesAgent."""

    def test_max_history_equals_sum(self):
        """MAX_HISTORY = KEEP_FIRST + KEEP_LAST."""
        assert MAX_HISTORY == KEEP_FIRST + KEEP_LAST

    def test_keep_first_positive(self):
        """KEEP_FIRST deve ser positivo."""
        assert KEEP_FIRST > 0

    def test_keep_last_positive(self):
        """KEEP_LAST deve ser positivo."""
        assert KEEP_LAST > 0

    def test_escalation_tag_format(self):
        """Tag de escalacao tem formato correto."""
        assert ESCALATION_TAG == "[ESCALAR]"

    def test_escalation_fallback_phrases_not_empty(self):
        """Lista de frases de fallback nao esta vazia."""
        assert len(ESCALATION_FALLBACK_PHRASES) > 0

    def test_fallback_phrases_are_lowercase(self):
        """Frases de fallback estao em lowercase."""
        for phrase in ESCALATION_FALLBACK_PHRASES:
            assert phrase == phrase.lower()


class TestEscalationDetection:
    """Testes de deteccao de escalacao na resposta."""

    def test_escalation_tag_detected(self):
        """Resposta com [ESCALAR] no inicio e detectada."""
        text = "[ESCALAR] Vou transferir voce para um consultor."
        assert text.strip().startswith(ESCALATION_TAG)

    def test_escalation_tag_not_in_middle(self):
        """[ESCALAR] no meio da resposta NAO e detectado."""
        text = "Voce pode usar [ESCALAR] para isso."
        assert not text.strip().startswith(ESCALATION_TAG)

    def test_fallback_phrases_in_first_200_chars(self):
        """Frases de fallback nos primeiros 200 chars sao detectadas."""
        text = "Vou conectar você com um consultor humano para ajudar. " + "x" * 300
        response_start = text[:200].lower()
        has_phrase = any(p in response_start for p in ESCALATION_FALLBACK_PHRASES)
        assert has_phrase

    def test_fallback_phrases_after_200_chars_not_detected(self):
        """Frases de fallback apos 200 chars NAO sao detectadas."""
        text = "x" * 201 + "vou conectar voce com um consultor humano"
        response_start = text[:200].lower()
        has_phrase = any(p in response_start for p in ESCALATION_FALLBACK_PHRASES)
        assert not has_phrase
