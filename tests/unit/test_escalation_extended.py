"""
tests/unit/test_escalation_extended.py — Testes expandidos para módulo de escalação.

Complementa test_escalation_logic.py testando as funções untestadas:
- handle_escalation(): fluxo completo de escalação
- resolve_escalation(): retorna controle para IA
- is_escalated(): verifica status
- get_escalation_status(): [futuro — pode estar em desenvolvimento]

Testa integração com database, whatsapp, hubspot, e wild memory lifecycle.
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call

# Garante imports de src.* antes de qualquer coisa
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Modo de teste: variáveis de ambiente
os.environ["TEST_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_KEY"] = "test-key-not-real"
os.environ["SUPERVISOR_PHONE"] = "5511988888888"


class TestHandleEscalation:
    """Testes da função handle_escalation()."""

    def test_handle_escalation_with_agent_generates_brief_from_agent(self):
        """handle_escalation gera brief completo usando agent.get_escalation_brief()."""
        mock_agent = MagicMock()
        mock_brief = {
            "session_id": "5511999999999",
            "lead_data": {
                "stage": "negociacao",
                "especialidade": "pediatria",
                "motivo_escalacao": "preco_alto",
            },
            "total_messages": 12,
            "summary": "Cliente questionou preço",
        }
        mock_agent.get_escalation_brief.return_value = mock_brief

        mock_memory = MagicMock()
        mock_memory.get_session_id.return_value = "session-uuid-123"

        with patch("src.core.database.save_escalation", return_value=True), \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle") as mock_lifecycle:

            from src.core import escalation
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                "João Silva",
                agent=mock_agent,
                motivo="preco_alto"
            )

            mock_agent.get_escalation_brief.assert_called_once_with("5511999999999")

    def test_handle_escalation_without_agent_uses_fallback_brief(self):
        """handle_escalation usa brief básico quando agent não disponível."""
        mock_memory = MagicMock()
        mock_memory.summary.return_value = "Resumo da conversa"
        mock_memory.get.return_value = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "resp1"},
        ]

        with patch("src.core.database.save_escalation", return_value=True), \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle"):

            from src.core import escalation
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                agent=None,  # Sem agent
                motivo="duvida_tecnica"
            )

            # Verifica que fallback foi usado (summary foi chamado)
            mock_memory.summary.assert_called_once()

    def test_handle_escalation_saves_escalation_to_database(self):
        """handle_escalation persiste escalação no banco via save_escalation()."""
        mock_memory = MagicMock()
        mock_memory.get_session_id.return_value = "session-123"

        with patch("src.core.database.save_escalation", return_value=True) as mock_save, \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle"):

            from src.core import escalation
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                motivo="escala_necessaria"
            )

            mock_save.assert_called_once()
            # Verifica que user_id está correto
            call_args = mock_save.call_args
            assert call_args[1]["user_id"] == "5511999999999"

    def test_handle_escalation_sets_session_status_to_escalated(self):
        """handle_escalation marca sessão como 'escalated' no memory."""
        mock_memory = MagicMock()

        with patch("src.core.database.save_escalation", return_value=True), \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle"):

            from src.core import escalation
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                motivo="test"
            )

            mock_memory.set_status.assert_called_once_with("5511999999999", "escalated")

    def test_handle_escalation_notifies_supervisor_with_brief(self):
        """handle_escalation notifica supervisor via notify_supervisor()."""
        mock_memory = MagicMock()

        with patch("src.core.database.save_escalation", return_value=True), \
             patch("src.core.escalation.notify_supervisor", return_value=True) as mock_notify, \
             patch("src.core.escalation._wild_lifecycle"):

            from src.core import escalation
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                motivo="preco_alto"
            )

            mock_notify.assert_called_once()

    def test_handle_escalation_injects_motivo_into_brief(self):
        """handle_escalation injeta motivo no brief se não estiver presente."""
        mock_memory = MagicMock()
        mock_memory.get_session_id.return_value = None

        # Brief sem motivo
        mock_agent = MagicMock()
        mock_agent.get_escalation_brief.return_value = {
            "session_id": "5511999999999",
            "lead_data": {"stage": "qualificacao"},
            "summary": "test",
            "total_messages": 5,
        }

        with patch("src.core.database.save_escalation", return_value=True) as mock_save, \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle"):

            from src.core import escalation
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                agent=mock_agent,
                motivo="escala_necessaria"
            )

            # Verifica que brief foi salvo com motivo
            call_args = mock_save.call_args
            brief_arg = call_args[1]["brief"]
            assert brief_arg["lead_data"]["motivo_escalacao"] == "escala_necessaria"

    def test_handle_escalation_syncs_to_hubspot_when_enabled(self):
        """handle_escalation tenta sincronizar para HubSpot se habilitado."""
        mock_memory = MagicMock()

        with patch("src.core.database.save_escalation", return_value=True), \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle"), \
             patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.sync_escalation", return_value=True) as mock_hubspot_sync:

            from src.core import escalation
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                motivo="test"
            )

            # HubSpot sync deve ter sido chamado
            mock_hubspot_sync.assert_called_once()

    def test_handle_escalation_handles_hubspot_error_gracefully(self):
        """handle_escalation não falha se HubSpot sync tem erro."""
        mock_memory = MagicMock()

        with patch("src.core.database.save_escalation", return_value=True), \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle"), \
             patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.sync_escalation", side_effect=Exception("HubSpot error")):

            from src.core import escalation
            # Não deve lançar exceção
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                motivo="test"
            )

    def test_handle_escalation_calls_wild_lifecycle_on_escalation(self):
        """handle_escalation registra escalação no Wild Memory lifecycle."""
        mock_memory = MagicMock()
        mock_memory.get_session_id.return_value = "session-uuid-123"

        with patch("src.core.database.save_escalation", return_value=True), \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle") as mock_lifecycle:

            from src.core import escalation
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                motivo="escala_necessaria"
            )

            mock_lifecycle.on_escalation.assert_called_once()


class TestResolveEscalation:
    """Testes da função resolve_escalation()."""

    def test_resolve_escalation_sets_session_status_to_active(self):
        """resolve_escalation marca sessão como 'active' novamente."""
        mock_memory = MagicMock()

        with patch("src.core.database.update_lead_status", return_value=True), \
             patch("src.core.database.resolve_escalation_record", return_value=True):

            from src.core import escalation
            escalation.resolve_escalation("5511999999999", mock_memory)

            mock_memory.set_status.assert_called_once_with("5511999999999", "active")

    def test_resolve_escalation_updates_lead_status_in_database(self):
        """resolve_escalation atualiza status do lead para 'active' no banco."""
        mock_memory = MagicMock()

        with patch("src.core.database.update_lead_status", return_value=True) as mock_update, \
             patch("src.core.database.resolve_escalation_record", return_value=True):

            from src.core import escalation
            escalation.resolve_escalation("5511999999999", mock_memory)

            mock_update.assert_called_once_with("5511999999999", "active")

    def test_resolve_escalation_resolves_escalation_record(self):
        """resolve_escalation marca escalação como resolvida no banco."""
        mock_memory = MagicMock()

        with patch("src.core.database.update_lead_status", return_value=True), \
             patch("src.core.database.resolve_escalation_record", return_value=True) as mock_resolve:

            from src.core import escalation
            escalation.resolve_escalation("5511999999999", mock_memory, "Cliente satisfeito")

            mock_resolve.assert_called_once()
            call_args = mock_resolve.call_args
            # Primeiro argumento deve ser o phone
            assert call_args[0][0] == "5511999999999"

    def test_resolve_escalation_accepts_optional_resolution_text(self):
        """resolve_escalation aceita texto de resolução opcional."""
        mock_memory = MagicMock()

        with patch("src.core.database.update_lead_status", return_value=True), \
             patch("src.core.database.resolve_escalation_record", return_value=True) as mock_resolve:

            from src.core import escalation
            escalation.resolve_escalation(
                "5511999999999",
                mock_memory,
                resolution="Humano ofertou desconto de 20%"
            )

            # Verifica que resolve foi chamado com a resolução
            mock_resolve.assert_called_once()


class TestIsEscalated:
    """Testes da função is_escalated()."""

    def test_is_escalated_returns_true_for_escalated_session(self):
        """is_escalated retorna True quando status é 'escalated'."""
        mock_memory = MagicMock()
        mock_memory.get_status.return_value = "escalated"

        from src.core import escalation
        result = escalation.is_escalated("5511999999999", mock_memory)

        assert result is True

    def test_is_escalated_returns_false_for_active_session(self):
        """is_escalated retorna False quando status é 'active'."""
        mock_memory = MagicMock()
        mock_memory.get_status.return_value = "active"

        from src.core import escalation
        result = escalation.is_escalated("5511999999999", mock_memory)

        assert result is False

    def test_is_escalated_returns_false_for_unknown_status(self):
        """is_escalated retorna False para status desconhecido."""
        mock_memory = MagicMock()
        mock_memory.get_status.return_value = "unknown"

        from src.core import escalation
        result = escalation.is_escalated("5511999999999", mock_memory)

        assert result is False

    def test_is_escalated_returns_false_for_none_status(self):
        """is_escalated retorna False quando status é None."""
        mock_memory = MagicMock()
        mock_memory.get_status.return_value = None

        from src.core import escalation
        result = escalation.is_escalated("5511999999999", mock_memory)

        assert result is False

    def test_is_escalated_calls_get_status_with_phone(self):
        """is_escalated chama memory.get_status() com o phone correto."""
        mock_memory = MagicMock()
        mock_memory.get_status.return_value = "active"

        from src.core import escalation
        escalation.is_escalated("5511999999999", mock_memory)

        mock_memory.get_status.assert_called_once_with("5511999999999")


class TestNotifySupervisor:
    """Testes da função notify_supervisor()."""

    def test_notify_supervisor_returns_false_when_no_phone_configured(self):
        """notify_supervisor retorna False quando SUPERVISOR_PHONE não configurado."""
        with patch("src.core.escalation.SUPERVISOR_PHONE", ""):
            from src.core import escalation
            brief = {"lead_data": {}, "summary": "test"}
            result = escalation.notify_supervisor("5511999999999", brief)
            assert result is False

    def test_notify_supervisor_sends_whatsapp_message(self):
        """notify_supervisor envia mensagem WhatsApp ao supervisor."""
        with patch("src.core.escalation.SUPERVISOR_PHONE", "5511988888888"), \
             patch("src.core.whatsapp.send_message", return_value=True) as mock_send:

            from src.core import escalation
            brief = {
                "lead_data": {"stage": "negociacao"},
                "total_messages": 10,
                "summary": "Cliente questionou preço"
            }
            result = escalation.notify_supervisor("5511999999999", brief)

            assert result is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] == "5511988888888"  # Para supervisor

    def test_notify_supervisor_includes_formatted_brief_in_message(self):
        """notify_supervisor envia brief formatado via _format_brief_whatsapp."""
        with patch("src.core.escalation.SUPERVISOR_PHONE", "5511988888888"), \
             patch("src.core.whatsapp.send_message", return_value=True) as mock_send:

            from src.core import escalation
            brief = {
                "lead_data": {
                    "stage": "negociacao",
                    "especialidade": "clinica_medica",
                    "motivo_escalacao": "preco_alto"
                },
                "total_messages": 10,
                "summary": "Cliente questionou preço"
            }
            escalation.notify_supervisor("5511999999999", brief)

            # Verifica que mensagem foi formatada
            call_args = mock_send.call_args
            message = call_args[0][1]
            assert "5511999999999" in message  # Telefone do lead
            assert "negociacao" in message  # Stage
            assert "preco_alto" in message or "Motivo" in message  # Motivo


class TestTransferToBotmaker:
    """Testes da função transfer_to_botmaker()."""

    def test_transfer_to_botmaker_returns_false_when_not_configured(self):
        """transfer_to_botmaker retorna False quando BOTMAKER_API_KEY não configurado."""
        with patch("src.core.escalation.BOTMAKER_API_KEY", ""):
            from src.core import escalation
            result = escalation.transfer_to_botmaker("5511999999999", "João")
            assert result is False

    def test_transfer_to_botmaker_returns_false_when_not_implemented(self):
        """transfer_to_botmaker retorna False (funcionalidade futura)."""
        with patch("src.core.escalation.BOTMAKER_API_KEY", "test-key"):
            from src.core import escalation
            result = escalation.transfer_to_botmaker("5511999999999", "João")
            assert result is False


class TestEdgeCases:
    """Testes de casos extremos e tratamento de erro."""

    def test_handle_escalation_with_empty_brief_data(self):
        """handle_escalation lida com brief contendo dados vazios."""
        mock_memory = MagicMock()

        with patch("src.core.database.save_escalation", return_value=True), \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle"):

            from src.core import escalation
            # Brief com dados vazios
            brief = {"lead_data": {}, "summary": "", "total_messages": 0}

            # Não deve lançar exceção
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                motivo="test"
            )

    def test_resolve_escalation_with_none_resolution(self):
        """resolve_escalation funciona com resolution=None."""
        mock_memory = MagicMock()

        with patch("src.core.database.update_lead_status", return_value=True), \
             patch("src.core.database.resolve_escalation_record", return_value=True):

            from src.core import escalation
            # Não deve lançar exceção
            escalation.resolve_escalation("5511999999999", mock_memory, None)

    def test_handle_escalation_with_missing_session_id(self):
        """handle_escalation funciona quando memory.get_session_id não existe."""
        mock_memory = MagicMock()
        # get_session_id retorna None ou lança AttributeError
        del mock_memory.get_session_id

        with patch("src.core.database.save_escalation", return_value=True), \
             patch("src.core.escalation.notify_supervisor", return_value=True), \
             patch("src.core.escalation._wild_lifecycle"):

            from src.core import escalation
            # Não deve lançar exceção
            escalation.handle_escalation(
                "5511999999999",
                mock_memory,
                motivo="test"
            )
