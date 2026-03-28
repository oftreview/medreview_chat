"""
tests/unit/test_database_corrections.py — Tests for src/core/database/corrections.py

Testa: corrections CRUD, archiving, reincidence tracking, analytics, JSON dual-write.
Mocks _get_client() e Supabase queries.
"""
import os
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# Set test mode and API key before imports
os.environ["TEST_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = "test-key"

import src.core.database.corrections as corrections_module


class TestJsonHelpers:
    """Tests para JSON fallback helpers."""

    def test_load_corrections_json_file_not_exists(self):
        """_load_corrections_json retorna [] se arquivo nao existe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nonexistent.json")
            result = corrections_module._load_corrections_json(path)
            assert result == []

    def test_load_corrections_json_valid_file(self):
        """_load_corrections_json carrega e retorna lista de correcoes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "corrections.json")
            test_data = [{"id": "corr-001", "categoria": "resposta"}]
            with open(path, 'w') as f:
                json.dump(test_data, f)
            result = corrections_module._load_corrections_json(path)
            assert result == test_data

    def test_load_corrections_json_empty_file(self):
        """_load_corrections_json com arquivo vazio retorna []."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "corrections.json")
            with open(path, 'w') as f:
                json.dump(None, f)
            result = corrections_module._load_corrections_json(path)
            assert result == []

    def test_load_corrections_json_malformed_json(self):
        """_load_corrections_json com JSON invalido retorna []."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "corrections.json")
            with open(path, 'w') as f:
                f.write("{invalid json}")
            result = corrections_module._load_corrections_json(path)
            assert result == []

    def test_save_corrections_json_creates_file(self):
        """_save_corrections_json cria arquivo e retorna True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "corrections.json")
            test_data = [{"id": "corr-001", "categoria": "resposta"}]
            result = corrections_module._save_corrections_json(path, test_data)
            assert result is True
            assert os.path.exists(path)
            with open(path) as f:
                loaded = json.load(f)
            assert loaded == test_data

    def test_save_corrections_json_creates_directories(self):
        """_save_corrections_json cria diretorios se nao existem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "new", "dir", "corrections.json")
            test_data = [{"id": "corr-001"}]
            result = corrections_module._save_corrections_json(path, test_data)
            assert result is True
            assert os.path.exists(path)

    def test_save_corrections_json_handles_unicode(self):
        """_save_corrections_json preserva caracteres unicode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "corrections.json")
            test_data = [{"id": "corr-001", "resposta_errada": "Resposta com acentuação"}]
            corrections_module._save_corrections_json(path, test_data)
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            assert loaded[0]["resposta_errada"] == "Resposta com acentuação"


class TestSaveCorrection:
    """Tests para save_correction (CRUD create/update)."""

    def test_save_correction_db_not_connected(self):
        """save_correction retorna False quando DB nao conectado."""
        correction = {"id": "corr-001", "categoria": "resposta"}
        with patch("src.core.database.corrections._get_client", return_value=None):
            result = corrections_module.save_correction(correction)
            assert result is False

    def test_save_correction_requires_id(self):
        """save_correction usa campo 'id' como correction_id."""
        mock_db = MagicMock()
        correction = {"id": "corr-001", "categoria": "resposta"}
        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.save_correction(correction)
            # Verifica que upsert foi chamado com correction_id
            call_args = mock_db.table.return_value.upsert.call_args
            assert call_args[0][0]["correction_id"] == "corr-001"

    def test_save_correction_maps_fields(self):
        """save_correction mapeia todos os campos da correcao."""
        mock_db = MagicMock()
        correction = {
            "id": "corr-001",
            "categoria": "resposta_errada",
            "severidade": "critica",
            "gatilho": "cliente pergunta sobre preco",
            "resposta_errada": "Resposta incorreta",
            "resposta_correta": "Resposta correta",
            "regra": "Se cliente pergunta preco, responder com oferta especial",
            "status": "ativa"
        }
        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.save_correction(correction)
            call_args = mock_db.table.return_value.upsert.call_args
            row = call_args[0][0]
            assert row["categoria"] == "resposta_errada"
            assert row["severidade"] == "critica"
            assert row["gatilho"] == "cliente pergunta sobre preco"

    def test_save_correction_includes_conversation_links(self):
        """save_correction inclui links para conversa original."""
        mock_db = MagicMock()
        correction = {
            "id": "corr-001",
            "categoria": "resposta",
            "conversation_user_id": "user-123",
            "conversation_message_id": "msg-456"
        }
        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.save_correction(correction)
            call_args = mock_db.table.return_value.upsert.call_args
            row = call_args[0][0]
            assert row["conversation_user_id"] == "user-123"
            assert row["conversation_message_id"] == "msg-456"

    def test_save_correction_uses_defaults(self):
        """save_correction aplica valores padrao para campos faltando."""
        mock_db = MagicMock()
        correction = {"id": "corr-001"}
        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.save_correction(correction)
            call_args = mock_db.table.return_value.upsert.call_args
            row = call_args[0][0]
            assert row["categoria"] == "outro"
            assert row["severidade"] == "alta"
            assert row["status"] == "ativa"

    def test_save_correction_upsert_success(self):
        """save_correction retorna True quando upsert sucede."""
        mock_db = MagicMock()
        mock_db.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        correction = {"id": "corr-001"}
        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            result = corrections_module.save_correction(correction)
            assert result is True

    def test_save_correction_upsert_failure(self):
        """save_correction retorna False quando upsert falha."""
        mock_db = MagicMock()
        mock_db.table.return_value.upsert.side_effect = Exception("DB error")
        correction = {"id": "corr-001"}
        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            result = corrections_module.save_correction(correction)
            assert result is False


class TestLoadCorrections:
    """Tests para load_corrections (CRUD read)."""

    def test_load_corrections_db_not_connected(self):
        """load_corrections retorna [] quando DB nao conectado."""
        with patch("src.core.database.corrections._get_client", return_value=None):
            result = corrections_module.load_corrections()
            assert result == []

    def test_load_corrections_returns_all_active(self):
        """load_corrections retorna todas as correcoes ativas por padrao."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"correction_id": "corr-001", "status": "ativa"},
            {"correction_id": "corr-002", "status": "ativa"}
        ]

        # Build mock chain: select -> order -> neq -> execute
        neq_mock = MagicMock()
        neq_mock.execute.return_value = mock_result

        order_mock = MagicMock()
        order_mock.neq.return_value = neq_mock

        select_mock = MagicMock()
        select_mock.order.return_value = order_mock

        mock_db.table.return_value.select.return_value = select_mock

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            result = corrections_module.load_corrections()
            assert len(result) == 2

    def test_load_corrections_excludes_archived_by_default(self):
        """load_corrections exclui correcoes arquivadas por padrao."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []

        # Build mock chain: select -> order -> neq -> execute
        neq_mock = MagicMock()
        neq_mock.execute.return_value = mock_result

        order_mock = MagicMock()
        order_mock.neq.return_value = neq_mock

        select_mock = MagicMock()
        select_mock.order.return_value = order_mock

        mock_db.table.return_value.select.return_value = select_mock

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.load_corrections(include_archived=False)
            # Verifica que .neq("status", "arquivada") foi chamado
            order_mock.neq.assert_called_with("status", "arquivada")

    def test_load_corrections_includes_archived_when_requested(self):
        """load_corrections inclui arquivadas quando include_archived=True."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        query_chain = MagicMock()
        query_chain.order.return_value.execute.return_value = mock_result
        mock_db.table.return_value.select.return_value = query_chain

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.load_corrections(include_archived=True)
            # .neq nao deve ser chamado
            query_chain.neq.assert_not_called()

    def test_load_corrections_filters_by_status(self):
        """load_corrections filtra por status quando fornecido."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []

        # Build mock chain: select -> order -> eq -> execute
        eq_mock = MagicMock()
        eq_mock.execute.return_value = mock_result

        order_mock = MagicMock()
        order_mock.eq.return_value = eq_mock

        select_mock = MagicMock()
        select_mock.order.return_value = order_mock

        mock_db.table.return_value.select.return_value = select_mock

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.load_corrections(status="arquivada")
            # Verifica que .eq("status", "arquivada") foi chamado
            order_mock.eq.assert_called_with("status", "arquivada")


class TestIncrementReincidence:
    """Tests para increment_reincidence."""

    def test_increment_reincidence_db_not_connected(self):
        """increment_reincidence retorna False quando DB nao conectado."""
        with patch("src.core.database.corrections._get_client", return_value=None):
            result = corrections_module.increment_reincidence("corr-001")
            assert result is False

    def test_increment_reincidence_increments_counter(self):
        """increment_reincidence incrementa reincidencia_count."""
        mock_db = MagicMock()
        # Mock select para obter contador atual
        mock_select_result = MagicMock()
        mock_select_result.data = [{"reincidencia_count": 5}]

        select_chain = MagicMock()
        select_chain.eq.return_value.limit.return_value.execute.return_value = mock_select_result

        # Mock update
        update_chain = MagicMock()
        update_chain.eq.return_value.execute.return_value = MagicMock()

        def table_side_effect(table_name):
            table_mock = MagicMock()
            if "select" in str(table_name):
                return select_chain
            table_mock.select.return_value = select_chain
            table_mock.update.return_value = update_chain
            return table_mock

        mock_db.table.return_value.select.return_value = select_chain
        mock_db.table.return_value.update.return_value = update_chain

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.increment_reincidence("corr-001")
            # Verifica que update foi chamado com contador incrementado
            update_call = mock_db.table.return_value.update.call_args
            assert update_call[0][0]["reincidencia_count"] == 6

    def test_increment_reincidence_sets_reincidence_flag(self):
        """increment_reincidence seta reincidencia=True."""
        mock_db = MagicMock()
        mock_select_result = MagicMock()
        mock_select_result.data = [{"reincidencia_count": 0}]

        select_chain = MagicMock()
        select_chain.eq.return_value.limit.return_value.execute.return_value = mock_select_result

        update_chain = MagicMock()
        update_chain.eq.return_value.execute.return_value = MagicMock()

        mock_db.table.return_value.select.return_value = select_chain
        mock_db.table.return_value.update.return_value = update_chain

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.increment_reincidence("corr-001")
            update_call = mock_db.table.return_value.update.call_args
            assert update_call[0][0]["reincidencia"] is True

    def test_increment_reincidence_sets_timestamp(self):
        """increment_reincidence seta last_reincidence_at timestamp."""
        mock_db = MagicMock()
        mock_select_result = MagicMock()
        mock_select_result.data = [{"reincidencia_count": 0}]

        select_chain = MagicMock()
        select_chain.eq.return_value.limit.return_value.execute.return_value = mock_select_result

        update_chain = MagicMock()
        update_chain.eq.return_value.execute.return_value = MagicMock()

        mock_db.table.return_value.select.return_value = select_chain
        mock_db.table.return_value.update.return_value = update_chain

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.increment_reincidence("corr-001")
            update_call = mock_db.table.return_value.update.call_args
            assert "last_reincidence_at" in update_call[0][0]
            # Timestamp deve ser uma string ISO
            assert isinstance(update_call[0][0]["last_reincidence_at"], str)

    def test_increment_reincidence_handles_missing_count(self):
        """increment_reincidence trata reincidencia_count faltando como 0."""
        mock_db = MagicMock()
        mock_select_result = MagicMock()
        mock_select_result.data = [{}]  # Sem reincidencia_count

        select_chain = MagicMock()
        select_chain.eq.return_value.limit.return_value.execute.return_value = mock_select_result

        update_chain = MagicMock()
        update_chain.eq.return_value.execute.return_value = MagicMock()

        mock_db.table.return_value.select.return_value = select_chain
        mock_db.table.return_value.update.return_value = update_chain

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            corrections_module.increment_reincidence("corr-001")
            update_call = mock_db.table.return_value.update.call_args
            # Deve incrementar 0 para 1
            assert update_call[0][0]["reincidencia_count"] == 1


class TestAutoArchiveCorrections:
    """Tests para auto_archive_corrections."""

    def test_auto_archive_corrections_db_not_connected(self):
        """auto_archive_corrections retorna 0 quando DB nao conectado."""
        with patch("src.core.database.corrections._get_client", return_value=None):
            result = corrections_module.auto_archive_corrections(30)
            assert result == 0

    def test_auto_archive_corrections_archives_old_items(self):
        """auto_archive_corrections arquiva itens sem reincidencia apos N dias."""
        mock_db = MagicMock()
        # Criar data 40 dias atras (deve ser arquivada com cutoff=30)
        old_date = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

        mock_select_result = MagicMock()
        mock_select_result.data = [
            {"correction_id": "corr-001", "last_reincidence_at": old_date, "created_at": old_date},
            {"correction_id": "corr-002", "last_reincidence_at": recent_date, "created_at": recent_date}
        ]

        select_chain = MagicMock()
        select_chain.eq.return_value.execute.return_value = mock_select_result

        update_chain = MagicMock()
        update_chain.eq.return_value.execute.return_value = MagicMock()

        mock_db.table.return_value.select.return_value = select_chain
        mock_db.table.return_value.update.return_value = update_chain

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            count = corrections_module.auto_archive_corrections(30)
            # Apenas corr-001 deve ser arquivada
            assert count == 1

    def test_auto_archive_corrections_uses_created_at_fallback(self):
        """auto_archive_corrections usa created_at se last_reincidence_at vazio."""
        mock_db = MagicMock()
        old_date = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()

        mock_select_result = MagicMock()
        mock_select_result.data = [
            {"correction_id": "corr-001", "last_reincidence_at": None, "created_at": old_date}
        ]

        select_chain = MagicMock()
        select_chain.eq.return_value.execute.return_value = mock_select_result

        update_chain = MagicMock()
        update_chain.eq.return_value.execute.return_value = MagicMock()

        mock_db.table.return_value.select.return_value = select_chain
        mock_db.table.return_value.update.return_value = update_chain

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            count = corrections_module.auto_archive_corrections(30)
            # Deve usar created_at para comparacao
            assert count == 1


class TestCorrectionAnalytics:
    """Tests para correction_analytics."""

    def test_correction_analytics_db_not_connected(self):
        """correction_analytics retorna erro quando DB nao conectado."""
        with patch("src.core.database.corrections._get_client", return_value=None):
            result = corrections_module.correction_analytics()
            assert "error" in result

    def test_correction_analytics_empty_corrections(self):
        """correction_analytics retorna estrutura correta com dados vazios."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            result = corrections_module.correction_analytics()
            assert result["total_active"] == 0
            assert result["reincidences_last_period"] == 0
            assert result["by_category"] == {}

    def test_correction_analytics_counts_active(self):
        """correction_analytics conta total de correcoes ativas."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"correction_id": "corr-001", "status": "ativa", "categoria": "resposta"},
            {"correction_id": "corr-002", "status": "ativa", "categoria": "formatacao"},
            {"correction_id": "corr-003", "status": "ativa", "categoria": "resposta"}
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            result = corrections_module.correction_analytics()
            assert result["total_active"] == 3

    def test_correction_analytics_counts_by_category(self):
        """correction_analytics agrupa por categoria."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"correction_id": "corr-001", "status": "ativa", "categoria": "resposta"},
            {"correction_id": "corr-002", "status": "ativa", "categoria": "formatacao"},
            {"correction_id": "corr-003", "status": "ativa", "categoria": "resposta"}
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            result = corrections_module.correction_analytics()
            assert result["by_category"]["resposta"] == 2
            assert result["by_category"]["formatacao"] == 1

    def test_correction_analytics_identifies_critical_reincident(self):
        """correction_analytics identifica correcoes criticas com reincidencia."""
        mock_db = MagicMock()
        recent_date = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()

        mock_result = MagicMock()
        mock_result.data = [
            {
                "correction_id": "corr-001",
                "status": "ativa",
                "categoria": "resposta",
                "severidade": "critica",
                "reincidencia": True,
                "reincidencia_count": 5,
                "last_reincidence_at": recent_date
            },
            {
                "correction_id": "corr-002",
                "status": "ativa",
                "categoria": "resposta",
                "severidade": "alta",
                "reincidencia": True,
                "reincidencia_count": 3,
                "last_reincidence_at": recent_date
            }
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            result = corrections_module.correction_analytics()
            # Apenas critica deve estar em critical_reincident
            assert len(result["critical_reincident"]) == 1
            assert result["critical_reincident"][0]["id"] == "corr-001"

    def test_correction_analytics_counts_recent_reincidences(self):
        """correction_analytics conta reincidencias nos ultimos N dias."""
        mock_db = MagicMock()
        recent_date = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        old_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()

        mock_result = MagicMock()
        mock_result.data = [
            {
                "correction_id": "corr-001",
                "status": "ativa",
                "categoria": "resposta",
                "severidade": "alta",
                "reincidencia": True,
                "reincidencia_count": 2,
                "last_reincidence_at": recent_date
            },
            {
                "correction_id": "corr-002",
                "status": "ativa",
                "categoria": "resposta",
                "severidade": "alta",
                "reincidencia": True,
                "reincidencia_count": 1,
                "last_reincidence_at": old_date
            }
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            result = corrections_module.correction_analytics(days=7)
            # Apenas reincidencia recente (< 7 dias)
            assert result["reincidences_last_period"] == 1

    def test_correction_analytics_truncates_regra_field(self):
        """correction_analytics trunca campo 'regra' para 100 chars."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        long_regra = "x" * 200
        mock_result.data = [
            {
                "correction_id": "corr-001",
                "status": "ativa",
                "categoria": "resposta",
                "severidade": "critica",
                "reincidencia": True,
                "reincidencia_count": 1,
                "last_reincidence_at": datetime.now(timezone.utc).isoformat(),
                "regra": long_regra
            }
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("src.core.database.corrections._get_client", return_value=mock_db):
            result = corrections_module.correction_analytics()
            if result["critical_reincident"]:
                assert len(result["critical_reincident"][0]["regra"]) <= 100


class TestSyncJsonToSupabase:
    """Tests para _sync_json_to_supabase."""

    def test_sync_json_to_supabase_db_not_connected(self):
        """_sync_json_to_supabase retorna False quando DB nao conectado."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "corrections.json")
            corrections_module._save_corrections_json(path, [{"id": "corr-001"}])

            with patch("src.core.database.corrections._get_client", return_value=None):
                result = corrections_module._sync_json_to_supabase(path)
                assert result is False

    def test_sync_json_to_supabase_empty_json(self):
        """_sync_json_to_supabase retorna True se JSON vazio."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "corrections.json")
            corrections_module._save_corrections_json(path, [])

            mock_db = MagicMock()
            with patch("src.core.database.corrections._get_client", return_value=mock_db):
                result = corrections_module._sync_json_to_supabase(path)
                assert result is True

    def test_sync_json_to_supabase_calls_save_for_each(self):
        """_sync_json_to_supabase chama save_correction para cada item."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "corrections.json")
            test_data = [
                {"id": "corr-001", "categoria": "resposta"},
                {"id": "corr-002", "categoria": "formatacao"}
            ]
            corrections_module._save_corrections_json(path, test_data)

            mock_db = MagicMock()
            with patch("src.core.database.corrections._get_client", return_value=mock_db), \
                 patch("src.core.database.corrections.save_correction", return_value=True) as mock_save:
                corrections_module._sync_json_to_supabase(path)
                # save_correction deve ser chamado 2 vezes
                assert mock_save.call_count == 2
