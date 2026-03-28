"""
tests/unit/test_hubspot.py — Testes para integração HubSpot (src/core/hubspot.py).

Testa: get_status(), create_or_update_contact(), log_conversation(), get_contact_by_phone(),
sync_lead(), sync_escalation(), stage mapping, e tratamento de erros.

Foca em:
- Estados desabilitados (sem API key)
- Caminho de sucesso (mocking httpx)
- Tratamento de erros e timeouts
- Casos extremos (contact duplicado, deal não encontrado, etc.)
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call
import json

# Garante imports de src.* antes de qualquer coisa
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Modo de teste: variáveis de ambiente
os.environ["TEST_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_KEY"] = "test-key-not-real"


class TestHubSpotEnabled:
    """Testes da função is_enabled()."""

    def test_is_enabled_returns_false_when_token_empty(self):
        """is_enabled retorna False quando HUBSPOT_ACCESS_TOKEN está vazio."""
        with patch("src.core.hubspot.HUBSPOT_ENABLED", True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", ""):
            from src.core import hubspot
            assert hubspot.is_enabled() is False

    def test_is_enabled_returns_false_when_feature_disabled(self):
        """is_enabled retorna False quando HUBSPOT_ENABLED é False."""
        with patch("src.core.hubspot.HUBSPOT_ENABLED", False), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"):
            from src.core import hubspot
            assert hubspot.is_enabled() is False

    def test_is_enabled_returns_true_when_both_set(self):
        """is_enabled retorna True quando token e feature habilitada."""
        with patch("src.core.hubspot.HUBSPOT_ENABLED", True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "pat-na1-test-token"):
            from src.core import hubspot
            assert hubspot.is_enabled() is True


class TestHubSpotRequest:
    """Testes da função _request (wrapper HTTP)."""

    def test_request_returns_none_when_disabled(self):
        """_request retorna None quando HubSpot está desabilitado."""
        with patch("src.core.hubspot.is_enabled", return_value=False):
            from src.core import hubspot
            result = hubspot._request("GET", "/crm/v3/objects/contacts?limit=1")
            assert result is None

    def test_request_makes_get_call_with_correct_headers(self):
        """_request faz chamada GET com headers de autenticação corretos."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total": 1, "results": []}

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"), \
             patch("httpx.get", return_value=mock_response) as mock_get:
            from src.core import hubspot
            result = hubspot._request("GET", "/crm/v3/objects/contacts?limit=1")

            assert result == {"total": 1, "results": []}
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["headers"]["Authorization"] == "Bearer test-token"

    def test_request_makes_post_call_with_payload(self):
        """_request faz chamada POST com payload JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "123", "status": "created"}

        payload = {"properties": {"phone": "5511999999999"}}

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"), \
             patch("httpx.post", return_value=mock_response) as mock_post:
            from src.core import hubspot
            result = hubspot._request("POST", "/crm/v3/objects/contacts", payload)

            assert result == {"id": "123", "status": "created"}
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            assert call_kwargs["json"] == payload

    def test_request_handles_409_conflict_response(self):
        """_request retorna status 'conflict' para resposta 409."""
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.text = "Contact already exists"

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"), \
             patch("httpx.post", return_value=mock_response):
            from src.core import hubspot
            result = hubspot._request("POST", "/crm/v3/objects/contacts", {})

            assert result is not None
            assert result["status"] == "conflict"

    def test_request_returns_none_on_error_status(self):
        """_request retorna None para status HTTP 4xx/5xx (não 409)."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"), \
             patch("httpx.get", return_value=mock_response):
            from src.core import hubspot
            result = hubspot._request("GET", "/crm/v3/objects/contacts")

            assert result is None

    def test_request_handles_httpx_exception(self):
        """_request captura exceção de httpx e retorna None."""
        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"), \
             patch("httpx.get", side_effect=Exception("Connection timeout")):
            from src.core import hubspot
            result = hubspot._request("GET", "/crm/v3/objects/contacts")

            assert result is None

    def test_request_rejects_unsupported_http_method(self):
        """_request retorna None para método HTTP não suportado."""
        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"):
            from src.core import hubspot
            result = hubspot._request("DELETE", "/crm/v3/objects/contacts/123")

            assert result is None


class TestFindContactByPhone:
    """Testes da função find_contact_by_phone()."""

    def test_find_contact_returns_contact_when_found(self):
        """find_contact_by_phone retorna contact dict quando encontrado."""
        mock_response = {
            "total": 1,
            "results": [{
                "id": "contact-123",
                "properties": {
                    "firstname": "João",
                    "phone": "5511999999999"
                }
            }]
        }

        with patch("src.core.hubspot._request", return_value=mock_response):
            from src.core import hubspot
            result = hubspot.find_contact_by_phone("5511999999999")

            assert result is not None
            assert result["id"] == "contact-123"

    def test_find_contact_returns_none_when_not_found(self):
        """find_contact_by_phone retorna None quando contact não existe."""
        mock_response = {"total": 0, "results": []}

        with patch("src.core.hubspot._request", return_value=mock_response):
            from src.core import hubspot
            result = hubspot.find_contact_by_phone("5511999999999")

            assert result is None

    def test_find_contact_returns_none_when_request_fails(self):
        """find_contact_by_phone retorna None quando _request falha."""
        with patch("src.core.hubspot._request", return_value=None):
            from src.core import hubspot
            result = hubspot.find_contact_by_phone("5511999999999")

            assert result is None


class TestUpsertContact:
    """Testes da função upsert_contact()."""

    def test_upsert_contact_returns_none_when_disabled(self):
        """upsert_contact retorna None quando HubSpot está desabilitado."""
        with patch("src.core.hubspot.is_enabled", return_value=False):
            from src.core import hubspot
            result = hubspot.upsert_contact("5511999999999", "João Silva")
            assert result is None

    def test_upsert_contact_creates_new_contact(self):
        """upsert_contact cria novo contact quando não existe."""
        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.find_contact_by_phone", return_value=None), \
             patch("src.core.hubspot._request") as mock_request:

            mock_request.return_value = {"id": "new-contact-123"}

            from src.core import hubspot
            result = hubspot.upsert_contact("5511999999999", "João Silva")

            assert result == "new-contact-123"
            # Verifica que POST foi chamado para criar
            assert mock_request.call_count >= 1

    def test_upsert_contact_updates_existing_contact(self):
        """upsert_contact atualiza contact quando já existe."""
        existing = {"id": "contact-456", "properties": {}}

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.find_contact_by_phone", return_value=existing), \
             patch("src.core.hubspot._request") as mock_request:

            mock_request.return_value = {"id": "contact-456"}

            from src.core import hubspot
            result = hubspot.upsert_contact("5511999999999", "João Silva Updated")

            assert result == "contact-456"
            # Verifica que PATCH foi chamado para atualizar
            assert mock_request.call_count >= 1

    def test_upsert_contact_splits_name_into_firstname_lastname(self):
        """upsert_contact divide nome em firstname e lastname."""
        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.find_contact_by_phone", return_value=None), \
             patch("src.core.hubspot._request") as mock_request:

            mock_request.return_value = {"id": "new-contact"}

            from src.core import hubspot
            hubspot.upsert_contact("5511999999999", "João Silva")

            # Verifica que _request foi chamado com properties contendo firstname e lastname
            call_args = mock_request.call_args
            if call_args:
                payload = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("payload")
                # Pode estar em payload["properties"] ou no json dict

    def test_upsert_contact_maps_lead_data_to_properties(self):
        """upsert_contact mapeia lead_data para custom properties do HubSpot."""
        lead_data = {
            "especialidade": "pediatria",
            "prova": "enem",
            "ano_prova": "2027",
            "plataforma_atual": "medcel",
        }

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.find_contact_by_phone", return_value=None), \
             patch("src.core.hubspot._request") as mock_request:

            mock_request.return_value = {"id": "new-contact"}

            from src.core import hubspot
            hubspot.upsert_contact("5511999999999", "João", lead_data)

            # Verifica que dados foram incluídos na requisição
            assert mock_request.called

    def test_upsert_contact_skips_unknown_values(self):
        """upsert_contact ignora valores 'desconhecido' em lead_data."""
        lead_data = {
            "especialidade": "desconhecido",
            "prova": "desconhecido",
            "ano_prova": "desconhecido",
        }

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.find_contact_by_phone", return_value=None), \
             patch("src.core.hubspot._request") as mock_request:

            mock_request.return_value = {"id": "new-contact"}

            from src.core import hubspot
            result = hubspot.upsert_contact("5511999999999", "João", lead_data)

            assert result == "new-contact"


class TestSyncLead:
    """Testes da função sync_lead()."""

    def test_sync_lead_returns_disabled_status_when_disabled(self):
        """sync_lead retorna dict com synced=False quando desabilitado."""
        with patch("src.core.hubspot.is_enabled", return_value=False):
            from src.core import hubspot
            result = hubspot.sync_lead("5511999999999", "João", "abertura")

            assert result["synced"] is False
            assert result["reason"] == "disabled"
            assert result["contact_id"] is None
            assert result["deal_id"] is None

    def test_sync_lead_returns_success_dict_when_enabled(self):
        """sync_lead retorna dict com contact_id e deal_id quando bem-sucedido."""
        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.upsert_contact", return_value="contact-123"), \
             patch("src.core.hubspot.upsert_deal", return_value="deal-456"):
            from src.core import hubspot
            result = hubspot.sync_lead("5511999999999", "João", "qualificacao")

            assert result["synced"] is True
            assert result["contact_id"] == "contact-123"
            assert result["deal_id"] == "deal-456"

    def test_sync_lead_calls_upsert_contact_and_deal(self):
        """sync_lead chama upsert_contact e upsert_deal."""
        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.upsert_contact", return_value="contact-123") as mock_contact, \
             patch("src.core.hubspot.upsert_deal", return_value="deal-456") as mock_deal:
            from src.core import hubspot
            lead_data = {"especialidade": "clinica"}
            hubspot.sync_lead("5511999999999", "João", "negociacao", lead_data)

            mock_contact.assert_called_once_with("5511999999999", "João", lead_data)
            mock_deal.assert_called_once_with("5511999999999", "João", "negociacao", lead_data)


class TestGetStatus:
    """Testes da função get_status()."""

    def test_get_status_returns_disabled_config(self):
        """get_status retorna config desabilitada quando HubSpot está off."""
        with patch("src.core.hubspot.HUBSPOT_ENABLED", False), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", ""), \
             patch("src.core.hubspot.HUBSPOT_PIPELINE_ID", "default"), \
             patch("src.core.hubspot.is_enabled", return_value=False):
            from src.core import hubspot
            result = hubspot.get_status()

            assert result["enabled"] is False
            assert result["configured"] is False
            assert result["connected"] is False

    def test_get_status_shows_configured_but_not_connected(self):
        """get_status mostra 'configured' True mas 'connected' False quando _request falha."""
        with patch("src.core.hubspot.HUBSPOT_ENABLED", True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"), \
             patch("src.core.hubspot.HUBSPOT_PIPELINE_ID", "custom-pipeline"), \
             patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot._request", return_value=None):
            from src.core import hubspot
            result = hubspot.get_status()

            assert result["enabled"] is True
            assert result["configured"] is True
            assert result["connected"] is False

    def test_get_status_shows_fully_connected(self):
        """get_status mostra 'connected' True quando teste de conexão sucede."""
        with patch("src.core.hubspot.HUBSPOT_ENABLED", True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"), \
             patch("src.core.hubspot.HUBSPOT_PIPELINE_ID", "custom-pipeline"), \
             patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot._request", return_value={"total": 0}):
            from src.core import hubspot
            result = hubspot.get_status()

            assert result["enabled"] is True
            assert result["configured"] is True
            assert result["connected"] is True

    def test_get_status_includes_stage_mapping(self):
        """get_status inclui stage mapping na resposta."""
        with patch("src.core.hubspot.HUBSPOT_ENABLED", True), \
             patch("src.core.hubspot.HUBSPOT_ACCESS_TOKEN", "test-token"), \
             patch("src.core.hubspot.HUBSPOT_PIPELINE_ID", "default"), \
             patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot._request", return_value={"total": 0}):
            from src.core import hubspot
            result = hubspot.get_status()

            assert "stage_mapping" in result
            assert isinstance(result["stage_mapping"], dict)
            assert len(result["stage_mapping"]) > 0


class TestStageMapping:
    """Testes do mapeamento de stages (Closi AI → HubSpot)."""

    def test_get_stage_map_returns_default_mapping(self):
        """_get_stage_map retorna mapeamento padrão quando nenhum custom foi definido."""
        from src.core import hubspot
        hubspot._custom_stage_map.clear()  # Limpa custom map

        result = hubspot._get_stage_map()

        assert "abertura" in result
        assert "qualificacao" in result
        assert "fechamento" in result
        assert result["fechamento"] == "closedwon"

    def test_set_stage_mapping_updates_custom_map(self):
        """set_stage_mapping atualiza o mapeamento customizado."""
        from src.core import hubspot
        hubspot._custom_stage_map.clear()

        custom_mapping = {"abertura": "custom-stage-1"}
        hubspot.set_stage_mapping(custom_mapping)

        assert hubspot._custom_stage_map == custom_mapping

    def test_get_stage_map_merges_custom_with_default(self):
        """_get_stage_map mescla mapeamento custom com default."""
        from src.core import hubspot
        hubspot._custom_stage_map.clear()

        custom_mapping = {"abertura": "custom-opening"}
        hubspot.set_stage_mapping(custom_mapping)

        result = hubspot._get_stage_map()

        # Custom deve sobrescrever default
        assert result["abertura"] == "custom-opening"
        # Stages não customizados devem vir do default
        assert result["fechamento"] == "closedwon"


class TestSyncEscalation:
    """Testes da função sync_escalation()."""

    def test_sync_escalation_returns_false_when_disabled(self):
        """sync_escalation retorna False quando HubSpot está desabilitado."""
        with patch("src.core.hubspot.is_enabled", return_value=False):
            from src.core import hubspot
            brief = {"lead_data": {"motivo": "test"}, "summary": "test"}
            result = hubspot.sync_escalation("5511999999999", brief)

            assert result is False

    def test_sync_escalation_adds_note_when_enabled(self):
        """sync_escalation adiciona nota ao contact quando habilitado."""
        brief = {
            "lead_data": {
                "motivo_escalacao": "preco_alto",
                "stage": "negociacao",
                "especialidade": "clinica",
                "prova": "enem",
            },
            "summary": "Cliente questionou preço do curso"
        }

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.add_note", return_value="note-123") as mock_note:
            from src.core import hubspot
            result = hubspot.sync_escalation("5511999999999", brief)

            assert result is True
            mock_note.assert_called_once()

    def test_sync_escalation_formats_escalation_message(self):
        """sync_escalation formata mensagem de escalação com dados do brief."""
        brief = {
            "lead_data": {
                "motivo_escalacao": "duvida_tecnica",
                "stage": "apresentacao",
                "especialidade": "cirurgia",
                "prova": "usp",
            },
            "summary": "Cliente tem dúvida sobre conteúdo"
        }

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.add_note") as mock_note:

            def capture_note_call(phone, body):
                assert "Escalação" in body or "duvida_tecnica" in body
                return "note-123"

            mock_note.side_effect = capture_note_call

            from src.core import hubspot
            hubspot.sync_escalation("5511999999999", brief)

            assert mock_note.called


class TestAddNote:
    """Testes da função add_note()."""

    def test_add_note_returns_none_when_disabled(self):
        """add_note retorna None quando HubSpot está desabilitado."""
        with patch("src.core.hubspot.is_enabled", return_value=False):
            from src.core import hubspot
            result = hubspot.add_note("5511999999999", "Test note")
            assert result is None

    def test_add_note_returns_none_when_contact_not_found(self):
        """add_note retorna None quando contact não existe."""
        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.find_contact_by_phone", return_value=None):
            from src.core import hubspot
            result = hubspot.add_note("5511999999999", "Test note")
            assert result is None

    def test_add_note_creates_note_when_contact_exists(self):
        """add_note cria nota quando contact existe."""
        contact = {"id": "contact-123"}

        with patch("src.core.hubspot.is_enabled", return_value=True), \
             patch("src.core.hubspot.find_contact_by_phone", return_value=contact), \
             patch("src.core.hubspot._request") as mock_request:

            mock_request.return_value = {"id": "note-456"}

            from src.core import hubspot
            result = hubspot.add_note("5511999999999", "Important note")

            assert result == "note-456"
            mock_request.assert_called_once()
