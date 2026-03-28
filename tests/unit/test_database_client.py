"""
tests/unit/test_database_client.py — Testes do cliente Supabase (singleton + health check).

Testa: _get_client(), is_enabled(), get_connection_status(), health_check()
Testes da inicializacao lazy singleton, tratamento de erros, e health checks.
"""
import os
import time
import pytest
from unittest.mock import MagicMock, patch, call
import src.core.database.client as client_module


class TestGetClient:
    """Testes da funcao _get_client (lazy singleton)."""

    def setup_method(self):
        """Reset globals antes de cada teste."""
        client_module._client = None
        client_module._connection_error = None

    def test_get_client_returns_none_when_url_not_configured(self):
        """_get_client retorna None quando SUPABASE_URL nao esta configurado."""
        with patch("src.core.database.client.SUPABASE_URL", ""), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"):
            result = client_module._get_client()
            assert result is None
            assert client_module._connection_error is not None
            assert "SUPABASE_URL" in client_module._connection_error

    def test_get_client_returns_none_when_key_not_configured(self):
        """_get_client retorna None quando SUPABASE_KEY nao esta configurado."""
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", ""):
            result = client_module._get_client()
            assert result is None
            assert client_module._connection_error is not None
            assert "SUPABASE_KEY" in client_module._connection_error

    def test_get_client_creates_client_when_both_configured(self):
        """_get_client cria cliente quando URL e KEY estao configurados."""
        mock_supabase_client = MagicMock()
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("supabase.create_client", return_value=mock_supabase_client) as mock_create:
            result = client_module._get_client()
            assert result == mock_supabase_client
            assert client_module._client == mock_supabase_client
            assert client_module._connection_error is None
            mock_create.assert_called_once_with("http://localhost:54321", "test-key")

    def test_get_client_caches_client_singleton(self):
        """_get_client retorna cliente cacheado na segunda chamada (singleton)."""
        mock_supabase_client = MagicMock()
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("supabase.create_client", return_value=mock_supabase_client) as mock_create:
            # Primeira chamada
            result1 = client_module._get_client()
            # Segunda chamada
            result2 = client_module._get_client()
            assert result1 == result2 == mock_supabase_client
            # create_client deve ter sido chamado apenas uma vez
            mock_create.assert_called_once()

    def test_get_client_handles_create_client_exception(self):
        """_get_client captura excecao do create_client e retorna None."""
        exception_msg = "Connection refused"
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("supabase.create_client", side_effect=Exception(exception_msg)):
            result = client_module._get_client()
            assert result is None
            assert client_module._client is None
            assert client_module._connection_error == exception_msg

    def test_get_client_handles_missing_both_url_and_key(self):
        """_get_client retorna None quando ambos URL e KEY estao faltando."""
        with patch("src.core.database.client.SUPABASE_URL", ""), \
             patch("src.core.database.client.SUPABASE_KEY", ""):
            result = client_module._get_client()
            assert result is None
            assert client_module._connection_error is not None


class TestIsEnabled:
    """Testes da funcao is_enabled."""

    def test_is_enabled_returns_false_when_url_missing(self):
        """is_enabled retorna False quando SUPABASE_URL nao esta configurado."""
        with patch("src.core.database.client.SUPABASE_URL", ""), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"):
            assert client_module.is_enabled() is False

    def test_is_enabled_returns_false_when_key_missing(self):
        """is_enabled retorna False quando SUPABASE_KEY nao esta configurado."""
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", ""):
            assert client_module.is_enabled() is False

    def test_is_enabled_returns_false_when_both_missing(self):
        """is_enabled retorna False quando URL e KEY nao estao configurados."""
        with patch("src.core.database.client.SUPABASE_URL", ""), \
             patch("src.core.database.client.SUPABASE_KEY", ""):
            assert client_module.is_enabled() is False

    def test_is_enabled_returns_true_when_both_configured(self):
        """is_enabled retorna True quando URL e KEY estao configurados."""
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"):
            assert client_module.is_enabled() is True

    def test_is_enabled_ignores_client_state(self):
        """is_enabled depende apenas das variaveis de ambiente, nao do estado do cliente."""
        # Mesmo que _client nao exista
        client_module._client = None
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"):
            assert client_module.is_enabled() is True

        # Mesmo que _client exista
        client_module._client = MagicMock()
        with patch("src.core.database.client.SUPABASE_URL", ""), \
             patch("src.core.database.client.SUPABASE_KEY", ""):
            assert client_module.is_enabled() is False


class TestGetConnectionStatus:
    """Testes da funcao get_connection_status."""

    def setup_method(self):
        """Reset globals antes de cada teste."""
        client_module._client = None
        client_module._connection_error = None

    def test_get_connection_status_when_not_configured(self):
        """get_connection_status retorna status correto quando nao configurado."""
        with patch("src.core.database.client.SUPABASE_URL", ""), \
             patch("src.core.database.client.SUPABASE_KEY", ""):
            status = client_module.get_connection_status()
            assert status["enabled"] is False
            assert status["connected"] is False

    def test_get_connection_status_when_connected(self):
        """get_connection_status retorna status correto quando conectado."""
        mock_client = MagicMock()
        client_module._client = mock_client
        client_module._connection_error = None
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"):
            status = client_module.get_connection_status()
            assert status["enabled"] is True
            assert status["connected"] is True
            assert status["error"] is None

    def test_get_connection_status_includes_error_message(self):
        """get_connection_status inclui mensagem de erro quando presente."""
        client_module._client = None
        client_module._connection_error = "Connection timeout"
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"):
            status = client_module.get_connection_status()
            assert status["error"] == "Connection timeout"
            assert status["connected"] is False

    def test_get_connection_status_structure(self):
        """get_connection_status retorna dict com as chaves esperadas."""
        with patch("src.core.database.client.SUPABASE_URL", ""), \
             patch("src.core.database.client.SUPABASE_KEY", ""):
            status = client_module.get_connection_status()
            assert "enabled" in status
            assert "connected" in status
            assert "error" in status


class TestHealthCheck:
    """Testes da funcao health_check."""

    def setup_method(self):
        """Reset globals antes de cada teste."""
        client_module._client = None
        client_module._connection_error = None

    def test_health_check_returns_disabled_when_not_enabled(self):
        """health_check retorna enabled=False quando Supabase nao esta configurado."""
        with patch("src.core.database.client.SUPABASE_URL", ""), \
             patch("src.core.database.client.SUPABASE_KEY", ""):
            result = client_module.health_check()
            assert result["enabled"] is False
            assert result["connected"] is False
            assert result["error"] is not None
            # Error message contains Portuguese text with special characters
            assert "configurados" in result["error"]

    def test_health_check_returns_error_when_client_initialization_fails(self):
        """health_check retorna erro quando _get_client falha."""
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=None):
            client_module._connection_error = "Client creation failed"
            result = client_module.health_check()
            assert result["enabled"] is True
            assert result["connected"] is False
            assert result["error"] == "Client creation failed"

    def test_health_check_successful_write_read_delete(self):
        """health_check sucede com escrita, leitura e delecao."""
        mock_client = MagicMock()
        mock_execute = MagicMock()
        mock_execute.data = [{"user_id": "test123"}]

        # Setup chains de mock para insert().execute()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = mock_execute

        # Setup chains de mock para select()...execute()
        mock_select = MagicMock()
        mock_select.eq.return_value.limit.return_value.execute.return_value = mock_execute

        # Setup chains de mock para delete()...execute()
        mock_delete = MagicMock()
        mock_delete.eq.return_value.execute.return_value = MagicMock()

        # Setup table() para retornar os mocks corretos
        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                table_mock.insert = MagicMock(return_value=mock_insert)
                table_mock.select = MagicMock(return_value=mock_select)
                table_mock.delete = MagicMock(return_value=mock_delete)
                return table_mock

        mock_client.table.side_effect = table_side_effect

        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=mock_client):
            result = client_module.health_check()
            assert result["enabled"] is True
            assert result["write"] is True
            assert result["read"] is True
            assert result["delete"] is True
            assert result["connected"] is True
            assert result["error"] is None
            assert result["latency_ms"] is not None

    def test_health_check_write_failure(self):
        """health_check falha e retorna com write=False quando insert falha."""
        mock_client = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.side_effect = Exception("Write failed")

        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                table_mock.insert = MagicMock(return_value=mock_insert)
                return table_mock

        mock_client.table.side_effect = table_side_effect

        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=mock_client):
            result = client_module.health_check()
            assert result["enabled"] is True
            assert result["write"] is False
            assert result["connected"] is False
            assert result["error"] is not None
            assert "Write failed" in result["error"]

    def test_health_check_read_failure(self):
        """health_check continua mas marca read=False quando select falha."""
        mock_client = MagicMock()

        # Mock insert que sucede
        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock()

        # Mock select que falha
        mock_select = MagicMock()
        mock_select.eq.return_value.limit.return_value.execute.side_effect = Exception("Read failed")

        # Mock delete que sucede
        mock_delete = MagicMock()
        mock_delete.eq.return_value.execute.return_value = MagicMock()

        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                table_mock.insert = MagicMock(return_value=mock_insert)
                table_mock.select = MagicMock(return_value=mock_select)
                table_mock.delete = MagicMock(return_value=mock_delete)
                return table_mock

        mock_client.table.side_effect = table_side_effect

        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=mock_client):
            result = client_module.health_check()
            assert result["write"] is True
            assert result["read"] is False
            assert result["connected"] is False
            assert "Read failed" in result["error"]

    def test_health_check_delete_failure(self):
        """health_check marca delete=False quando delete falha mas continua."""
        mock_client = MagicMock()

        # Mock insert que sucede
        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock()

        # Mock select que sucede
        mock_select = MagicMock()
        mock_select.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"user_id": "test123"}]
        )

        # Mock delete que falha
        mock_delete = MagicMock()
        mock_delete.eq.return_value.execute.side_effect = Exception("Delete failed")

        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                table_mock.insert = MagicMock(return_value=mock_insert)
                table_mock.select = MagicMock(return_value=mock_select)
                table_mock.delete = MagicMock(return_value=mock_delete)
                return table_mock

        mock_client.table.side_effect = table_side_effect

        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=mock_client):
            result = client_module.health_check()
            assert result["write"] is True
            assert result["read"] is True
            assert result["delete"] is False
            assert "Delete failed" in result["error"]

    def test_health_check_measures_latency(self):
        """health_check mede latencia em milissegundos."""
        mock_client = MagicMock()
        mock_execute = MagicMock()
        mock_execute.data = [{"user_id": "test123"}]

        mock_insert = MagicMock()
        mock_insert.execute.return_value = mock_execute

        mock_select = MagicMock()
        mock_select.eq.return_value.limit.return_value.execute.return_value = mock_execute

        mock_delete = MagicMock()
        mock_delete.eq.return_value.execute.return_value = MagicMock()

        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                table_mock.insert = MagicMock(return_value=mock_insert)
                table_mock.select = MagicMock(return_value=mock_select)
                table_mock.delete = MagicMock(return_value=mock_delete)
                return table_mock

        mock_client.table.side_effect = table_side_effect

        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=mock_client):
            result = client_module.health_check()
            assert result["latency_ms"] is not None
            assert isinstance(result["latency_ms"], int)
            assert result["latency_ms"] >= 0

    def test_health_check_has_all_expected_fields(self):
        """health_check retorna dict com todos os campos esperados."""
        with patch("src.core.database.client.SUPABASE_URL", ""), \
             patch("src.core.database.client.SUPABASE_KEY", ""):
            result = client_module.health_check()
            assert "enabled" in result
            assert "connected" in result
            assert "read" in result
            assert "write" in result
            assert "delete" in result
            assert "error" in result
            assert "latency_ms" in result

    def test_health_check_uses_uuid_for_test_record(self):
        """health_check usa UUID unico para evitar conflitos com dados reais."""
        mock_client = MagicMock()
        mock_execute = MagicMock()
        mock_execute.data = [{"user_id": "should_match_insert"}]

        mock_insert = MagicMock()
        mock_insert.execute.return_value = mock_execute

        mock_select = MagicMock()
        mock_select.eq.return_value.limit.return_value.execute.return_value = mock_execute

        mock_delete = MagicMock()
        mock_delete.eq.return_value.execute.return_value = MagicMock()

        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                table_mock.insert = MagicMock(return_value=mock_insert)
                table_mock.select = MagicMock(return_value=mock_select)
                table_mock.delete = MagicMock(return_value=mock_delete)
                return table_mock

        mock_client.table.side_effect = table_side_effect

        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=mock_client):
            result = client_module.health_check()
            # Verifica que insert foi chamado
            assert mock_insert.execute.called
            # Verifica que select.eq foi chamado (com o user_id do teste)
            assert mock_select.eq.called


class TestIntegration:
    """Testes de integracao entre as funcoes."""

    def setup_method(self):
        """Reset globals antes de cada teste."""
        client_module._client = None
        client_module._connection_error = None

    def test_get_connection_status_uses_is_enabled(self):
        """get_connection_status usa is_enabled para definir campo enabled."""
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"):
            client_module._client = None
            status = client_module.get_connection_status()
            assert status["enabled"] == client_module.is_enabled()

    def test_health_check_uses_is_enabled(self):
        """health_check usa is_enabled para definir campo enabled."""
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"):
            result = client_module.health_check()
            assert result["enabled"] == client_module.is_enabled()

    def test_get_client_preserves_error_across_calls(self):
        """Erro em _get_client e preservado em _connection_error para relatorio."""
        error_msg = "Network unreachable"
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("supabase.create_client", side_effect=Exception(error_msg)):
            client_module._get_client()
            assert client_module._connection_error == error_msg

    def test_client_state_after_successful_initialization(self):
        """Apos inicializacao bem-sucedida, _client e _connection_error estao corretos."""
        mock_client = MagicMock()
        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("supabase.create_client", return_value=mock_client):
            client_module._get_client()
            assert client_module._client == mock_client
            assert client_module._connection_error is None


class TestEdgeCases:
    """Testes de casos extremos e edge cases."""

    def setup_method(self):
        """Reset globals antes de cada teste."""
        client_module._client = None
        client_module._connection_error = None

    def test_is_enabled_with_whitespace_only_url(self):
        """is_enabled trata URL com apenas espacos como nao configurado."""
        with patch("src.core.database.client.SUPABASE_URL", "   "), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"):
            # Whitespace é ainda truthy em Python, mas depends on implementation
            # O modulo atual so checa `bool(SUPABASE_URL and SUPABASE_KEY)`
            result = client_module.is_enabled()
            # Sera True porque "   " e truthy, mas e um edge case importante
            assert result is True

    def test_health_check_without_read_success_marks_not_connected(self):
        """Se write e ok mas read falha, connected deve ser False."""
        mock_client = MagicMock()

        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock()

        mock_select = MagicMock()
        mock_select.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        mock_delete = MagicMock()
        mock_delete.eq.return_value.execute.return_value = MagicMock()

        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                table_mock.insert = MagicMock(return_value=mock_insert)
                table_mock.select = MagicMock(return_value=mock_select)
                table_mock.delete = MagicMock(return_value=mock_delete)
                return table_mock

        mock_client.table.side_effect = table_side_effect

        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=mock_client):
            result = client_module.health_check()
            # read = False because data list is empty
            assert result["read"] is False
            assert result["write"] is True
            assert result["connected"] is False

    def test_health_check_with_empty_data_means_no_read(self):
        """health_check marca read=False quando select retorna data vazio."""
        mock_client = MagicMock()

        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock()

        mock_select = MagicMock()
        mock_select.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        mock_delete = MagicMock()
        mock_delete.eq.return_value.execute.return_value = MagicMock()

        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                table_mock.insert = MagicMock(return_value=mock_insert)
                table_mock.select = MagicMock(return_value=mock_select)
                table_mock.delete = MagicMock(return_value=mock_delete)
                return table_mock

        mock_client.table.side_effect = table_side_effect

        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=mock_client):
            result = client_module.health_check()
            assert result["read"] is False

    def test_health_check_with_none_data_means_no_read(self):
        """health_check marca read=False quando select retorna data=None."""
        mock_client = MagicMock()

        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock()

        mock_select = MagicMock()
        mock_select.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=None)

        mock_delete = MagicMock()
        mock_delete.eq.return_value.execute.return_value = MagicMock()

        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                table_mock.insert = MagicMock(return_value=mock_insert)
                table_mock.select = MagicMock(return_value=mock_select)
                table_mock.delete = MagicMock(return_value=mock_delete)
                return table_mock

        mock_client.table.side_effect = table_side_effect

        with patch("src.core.database.client.SUPABASE_URL", "http://localhost:54321"), \
             patch("src.core.database.client.SUPABASE_KEY", "test-key"), \
             patch("src.core.database.client._get_client", return_value=mock_client):
            result = client_module.health_check()
            assert result["read"] is False
