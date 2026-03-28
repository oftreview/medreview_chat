"""
tests/unit/test_escalation_logic.py — Testes da logica de escalacao.

Testa: _format_brief_whatsapp, is_escalated
Sem I/O, sem chamadas externas.
"""
import pytest
from unittest.mock import MagicMock
from src.core.escalation import _format_brief_whatsapp, is_escalated


class TestFormatBriefWhatsapp:
    """Testes da formatacao do brief para WhatsApp."""

    def test_full_data_brief(self):
        """Brief com todos os dados do lead e formatado corretamente."""
        brief = {
            "lead_data": {
                "stage": "negociacao",
                "especialidade": "clinica_medica",
                "prova": "usp",
                "ano_prova": "2027",
                "ja_estuda": "sim",
                "plataforma_atual": "medcel",
                "motivo_escalacao": "preco_alto",
            },
            "total_messages": 15,
            "summary": "Lead: Quero saber o preco\nAgente: O R1 custa R$ 4990",
        }
        result = _format_brief_whatsapp(brief, "5511999999999")

        assert "5511999999999" in result
        assert "negociacao" in result
        assert "clinica_medica" in result
        assert "usp" in result
        assert "2027" in result
        assert "medcel" in result
        assert "preco_alto" in result
        assert "15 msgs" in result

    def test_empty_data_brief(self):
        """Brief sem dados do lead usa fallback."""
        brief = {
            "lead_data": {
                "stage": "desconhecido",
                "motivo_escalacao": "nao_especificado",
            },
            "total_messages": 3,
            "summary": "(sem resumo)",
        }
        result = _format_brief_whatsapp(brief, "5511999999999")

        assert "5511999999999" in result
        assert "desconhecido" in result
        assert "nenhum dado coletado ainda" in result

    def test_brief_contains_escalation_header(self):
        """Brief contem header de escalacao."""
        brief = {
            "lead_data": {"stage": "teste", "motivo_escalacao": "teste"},
            "total_messages": 1,
            "summary": "teste",
        }
        result = _format_brief_whatsapp(brief, "5511999999999")
        assert "ESCALA" in result.upper()

    def test_brief_contains_resolve_instruction(self):
        """Brief contem instrucao para resolver escalacao."""
        brief = {
            "lead_data": {"stage": "teste", "motivo_escalacao": "teste"},
            "total_messages": 1,
            "summary": "teste",
        }
        result = _format_brief_whatsapp(brief, "5511999999999")
        assert "/escalation/resolve" in result

    def test_partial_data_only_shows_available(self):
        """Brief com dados parciais so mostra o que foi coletado."""
        brief = {
            "lead_data": {
                "stage": "qualificacao",
                "especialidade": "pediatria",
                "motivo_escalacao": "duvida_tecnica",
            },
            "total_messages": 8,
            "summary": "Conversa sobre pediatria",
        }
        result = _format_brief_whatsapp(brief, "5511999999999")

        assert "pediatria" in result.lower()
        # Campos nao presentes nao devem aparecer
        assert "Plataforma atual" not in result


class TestIsEscalated:
    """Testes da funcao is_escalated."""

    def test_escalated_session_returns_true(self):
        """Sessao com status 'escalated' retorna True."""
        memory = MagicMock()
        memory.get_status.return_value = "escalated"
        assert is_escalated("5511999999999", memory) is True

    def test_active_session_returns_false(self):
        """Sessao com status 'active' retorna False."""
        memory = MagicMock()
        memory.get_status.return_value = "active"
        assert is_escalated("5511999999999", memory) is False

    def test_unknown_status_returns_false(self):
        """Sessao sem status (default) retorna False."""
        memory = MagicMock()
        memory.get_status.return_value = "unknown"
        assert is_escalated("5511999999999", memory) is False

    def test_calls_get_status_with_phone(self):
        """Verifica que get_status e chamado com o phone correto."""
        memory = MagicMock()
        memory.get_status.return_value = "active"
        is_escalated("5511999999999", memory)
        memory.get_status.assert_called_once_with("5511999999999")
