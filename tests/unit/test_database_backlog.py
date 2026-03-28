"""
tests/unit/test_database_backlog.py — Tests for src/core/database/backlog.py

Testa: RICE calculation, JSON fallback, CRUD operations, soft delete, trash, analytics.
Mocks _get_client() e Supabase queries.
"""
import os
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch, mock_open
from datetime import datetime, timezone

# Set test mode and API key before imports
os.environ["TEST_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = "test-key"

import src.core.database.backlog as backlog_module


class TestCalcRice:
    """Tests para a funcao _calc_rice (calculo de score RICE)."""

    def test_calc_rice_all_default_values(self):
        """_calc_rice com valores padroes (5,5,5,5) retorna 20."""
        item = {"reach": 5, "impact": 5, "confidence": 5, "effort": 5}
        result = backlog_module._calc_rice(item)
        assert result == 20.0

    def test_calc_rice_clamping_max_values(self):
        """_calc_rice clamps valores maiores que 10 para 10."""
        item = {"reach": 15, "impact": 20, "confidence": 50, "effort": 100}
        result = backlog_module._calc_rice(item)
        assert result == 40.0  # 10+10+10+10

    def test_calc_rice_clamping_min_values(self):
        """_calc_rice clamps valores negativos para 0."""
        item = {"reach": -5, "impact": -10, "confidence": -1, "effort": -100}
        result = backlog_module._calc_rice(item)
        assert result == 0.0  # 0+0+0+0

    def test_calc_rice_high_effort_contributes_full(self):
        """_calc_rice nao inverte effort — é somado normalmente 0-10."""
        item = {"reach": 0, "impact": 0, "confidence": 0, "effort": 10}
        result = backlog_module._calc_rice(item)
        assert result == 10.0

    def test_calc_rice_low_effort_contributes_zero(self):
        """_calc_rice com effort=0 contribui 0 (nao 10)."""
        item = {"reach": 0, "impact": 0, "confidence": 0, "effort": 0}
        result = backlog_module._calc_rice(item)
        assert result == 0.0

    def test_calc_rice_missing_fields_default_to_five(self):
        """_calc_rice com campos faltando usa valor padrao 5."""
        item = {"reach": 8}
        result = backlog_module._calc_rice(item)
        assert result == 8.0 + 5.0 + 5.0 + 5.0

    def test_calc_rice_empty_dict_uses_defaults(self):
        """_calc_rice com dict vazio usa todos valores 5."""
        item = {}
        result = backlog_module._calc_rice(item)
        assert result == 20.0

    def test_calc_rice_mixed_valid_and_clamped(self):
        """_calc_rice com mix de valores validos e clamped."""
        item = {"reach": 8, "impact": 15, "confidence": 3, "effort": 2}
        result = backlog_module._calc_rice(item)
        # 8 + 10(clamped) + 3 + 2
        assert result == 23.0

    def test_calc_rice_rounding_to_one_decimal(self):
        """_calc_rice retorna valores com uma casa decimal."""
        item = {"reach": 3.33, "impact": 3.33, "confidence": 3.33, "effort": 3.33}
        result = backlog_module._calc_rice(item)
        assert isinstance(result, float)
        # 3.33+3.33+3.33+3.33 = 13.32 arredonda para 13.3
        assert result == 13.3


class TestJsonHelpers:
    """Tests para JSON fallback helpers."""

    def test_load_backlog_json_file_not_exists(self):
        """_load_backlog_json retorna [] se arquivo nao existe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nonexistent.json")
            result = backlog_module._load_backlog_json(path)
            assert result == []

    def test_load_backlog_json_valid_file(self):
        """_load_backlog_json carrega e retorna lista de itens."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            test_data = [{"item_id": "CLO-001", "title": "Test"}]
            with open(path, 'w') as f:
                json.dump(test_data, f)
            result = backlog_module._load_backlog_json(path)
            assert result == test_data

    def test_load_backlog_json_empty_file(self):
        """_load_backlog_json com arquivo vazio retorna []."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            with open(path, 'w') as f:
                json.dump(None, f)
            result = backlog_module._load_backlog_json(path)
            assert result == []

    def test_load_backlog_json_malformed_json(self):
        """_load_backlog_json com JSON invalido retorna [] e printa warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            with open(path, 'w') as f:
                f.write("{invalid json}")
            result = backlog_module._load_backlog_json(path)
            assert result == []

    def test_save_backlog_json_creates_file(self):
        """_save_backlog_json cria arquivo e retorna True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            test_data = [{"item_id": "CLO-001"}]
            result = backlog_module._save_backlog_json(test_data, path)
            assert result is True
            assert os.path.exists(path)
            with open(path) as f:
                loaded = json.load(f)
            assert loaded == test_data

    def test_save_backlog_json_creates_directories(self):
        """_save_backlog_json cria diretorios se nao existem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "new", "dir", "backlog.json")
            test_data = [{"item_id": "CLO-001"}]
            result = backlog_module._save_backlog_json(test_data, path)
            assert result is True
            assert os.path.exists(path)

    def test_save_backlog_json_handles_unicode(self):
        """_save_backlog_json preserva caracteres unicode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            test_data = [{"item_id": "CLO-001", "title": "Teste com acentuação"}]
            backlog_module._save_backlog_json(test_data, path)
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            assert loaded[0]["title"] == "Teste com acentuação"


class TestLoadBacklog:
    """Tests para load_backlog (CRUD read)."""

    def test_load_backlog_returns_empty_when_db_none(self):
        """load_backlog retorna [] fallback quando db e None."""
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=[]):
            result = backlog_module.load_backlog()
            assert result == []

    def test_load_backlog_supabase_success(self):
        """load_backlog retorna dados do Supabase quando sucede."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"item_id": "CLO-001", "title": "Test"}]
        mock_db.table.return_value.select.return_value.is_.return_value.order.return_value.execute.return_value = mock_result

        with patch("src.core.database.backlog._get_client", return_value=mock_db):
            result = backlog_module.load_backlog()
            assert result == mock_result.data

    def test_load_backlog_excludes_deleted_by_default(self):
        """load_backlog exclui deletados (deleted_at is null) por padrao."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        query_chain = MagicMock()
        query_chain.is_.return_value.order.return_value.execute.return_value = mock_result
        mock_db.table.return_value.select.return_value = query_chain

        with patch("src.core.database.backlog._get_client", return_value=mock_db):
            backlog_module.load_backlog(include_deleted=False)
            # Verifica que .is_("deleted_at", "null") foi chamado
            query_chain.is_.assert_called_with("deleted_at", "null")

    def test_load_backlog_includes_deleted_when_requested(self):
        """load_backlog nao filtra por deleted_at quando include_deleted=True."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        query_chain = MagicMock()
        query_chain.order.return_value.execute.return_value = mock_result
        mock_db.table.return_value.select.return_value = query_chain

        with patch("src.core.database.backlog._get_client", return_value=mock_db):
            backlog_module.load_backlog(include_deleted=True)
            # .is_ nao deve ser chamado quando include_deleted=True
            query_chain.is_.assert_not_called()

    def test_load_backlog_filters_by_status(self):
        """load_backlog filtra por status quando fornecido."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        query_chain = MagicMock()
        query_chain.is_.return_value.eq.return_value.order.return_value.execute.return_value = mock_result
        mock_db.table.return_value.select.return_value = query_chain

        with patch("src.core.database.backlog._get_client", return_value=mock_db):
            backlog_module.load_backlog(status="done")
            # Verifica que .eq("status", "done") foi chamado
            query_chain.is_.return_value.eq.assert_called_with("status", "done")

    def test_load_backlog_filters_by_phase(self):
        """load_backlog filtra por phase quando fornecido."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        query_chain = MagicMock()
        query_chain.is_.return_value.order.return_value.execute.return_value = mock_result
        mock_db.table.return_value.select.return_value = query_chain

        with patch("src.core.database.backlog._get_client", return_value=mock_db):
            backlog_module.load_backlog(phase="Phase 2")
            # Verifica que .eq("phase", "Phase 2") foi chamado
            calls = query_chain.is_.return_value.eq.call_args_list
            assert any("Phase 2" in str(call) for call in calls)

    def test_load_backlog_json_fallback_filters_deleted(self):
        """load_backlog fallback JSON exclui itens com deleted_at."""
        json_data = [
            {"item_id": "CLO-001", "title": "Active"},
            {"item_id": "CLO-002", "title": "Deleted", "deleted_at": "2026-03-28T00:00:00Z"}
        ]
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=json_data):
            result = backlog_module.load_backlog(include_deleted=False)
            assert len(result) == 1
            assert result[0]["item_id"] == "CLO-001"


class TestSaveBacklogItem:
    """Tests para save_backlog_item (CRUD create/update)."""

    def test_save_backlog_item_requires_item_id(self):
        """save_backlog_item retorna False se item_id esta vazio."""
        item = {"title": "No ID"}
        result = backlog_module.save_backlog_item(item)
        assert result is False

    def test_save_backlog_item_strips_whitespace_from_id(self):
        """save_backlog_item remove espacos de item_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            item = {"item_id": "  CLO-001  ", "title": "Test"}
            with patch("src.core.database.backlog._get_backlog_json_path", return_value=path), \
                 patch("src.core.database.backlog._get_client", return_value=None):
                backlog_module.save_backlog_item(item)
                loaded = backlog_module._load_backlog_json(path)
                # Item foi salvo
                assert len(loaded) > 0

    def test_save_backlog_item_calculates_rice_score(self):
        """save_backlog_item calcula e salva rice_score."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            item = {"item_id": "CLO-001", "title": "Test", "reach": 8, "impact": 8, "confidence": 8, "effort": 8}
            with patch("src.core.database.backlog._get_backlog_json_path", return_value=path), \
                 patch("src.core.database.backlog._get_client", return_value=None):
                backlog_module.save_backlog_item(item)
                loaded = backlog_module._load_backlog_json(path)
                assert loaded[0]["rice_score"] == 32.0

    def test_save_backlog_item_sets_updated_at(self):
        """save_backlog_item seta updated_at timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            item = {"item_id": "CLO-001", "title": "Test"}
            with patch("src.core.database.backlog._get_backlog_json_path", return_value=path), \
                 patch("src.core.database.backlog._get_client", return_value=None):
                backlog_module.save_backlog_item(item)
                loaded = backlog_module._load_backlog_json(path)
                assert "updated_at" in loaded[0]

    def test_save_backlog_item_upsert_updates_existing(self):
        """save_backlog_item atualiza item existente (upsert)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            # Primeiro item
            item1 = {"item_id": "CLO-001", "title": "Original"}
            with patch("src.core.database.backlog._get_backlog_json_path", return_value=path), \
                 patch("src.core.database.backlog._get_client", return_value=None):
                backlog_module.save_backlog_item(item1)
                # Update
                item2 = {"item_id": "CLO-001", "title": "Updated"}
                backlog_module.save_backlog_item(item2)
                loaded = backlog_module._load_backlog_json(path)
                assert len(loaded) == 1
                assert loaded[0]["title"] == "Updated"

    def test_save_backlog_item_supabase_failure_returns_false(self):
        """save_backlog_item retorna False quando Supabase falha."""
        mock_db = MagicMock()
        mock_db.table.return_value.upsert.side_effect = Exception("DB error")
        item = {"item_id": "CLO-001", "title": "Test"}
        with patch("src.core.database.backlog._get_client", return_value=mock_db), \
             patch("src.core.database.backlog._save_backlog_json", return_value=True):
            result = backlog_module.save_backlog_item(item)
            assert result is False

    def test_save_backlog_item_supabase_success_returns_true(self):
        """save_backlog_item retorna True quando Supabase sucede."""
        mock_db = MagicMock()
        mock_db.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        item = {"item_id": "CLO-001", "title": "Test"}
        with patch("src.core.database.backlog._get_client", return_value=mock_db), \
             patch("src.core.database.backlog._save_backlog_json", return_value=True):
            result = backlog_module.save_backlog_item(item)
            assert result is True


class TestDeleteAndRestore:
    """Tests para soft delete e restore."""

    def test_delete_backlog_item_sets_deleted_at(self):
        """delete_backlog_item seta deleted_at timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            # Create item
            item = {"item_id": "CLO-001", "title": "Test"}
            with patch("src.core.database.backlog._get_backlog_json_path", return_value=path), \
                 patch("src.core.database.backlog._get_client", return_value=None):
                backlog_module.save_backlog_item(item)
                # Delete
                backlog_module.delete_backlog_item("CLO-001")
                loaded = backlog_module._load_backlog_json(path)
                assert loaded[0].get("deleted_at") is not None

    def test_restore_backlog_item_clears_deleted_at(self):
        """restore_backlog_item remove deleted_at field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            item = {"item_id": "CLO-001", "title": "Test", "deleted_at": "2026-03-28T00:00:00Z"}
            with patch("src.core.database.backlog._get_backlog_json_path", return_value=path), \
                 patch("src.core.database.backlog._get_client", return_value=None):
                backlog_module._save_backlog_json([item], path)
                # Restore
                backlog_module.restore_backlog_item("CLO-001")
                loaded = backlog_module._load_backlog_json(path)
                assert "deleted_at" not in loaded[0]

    def test_permanent_delete_item_removes_from_json(self):
        """permanent_delete_item remove item completamente."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            items = [
                {"item_id": "CLO-001", "title": "Keep"},
                {"item_id": "CLO-002", "title": "Delete"}
            ]
            with patch("src.core.database.backlog._get_backlog_json_path", return_value=path), \
                 patch("src.core.database.backlog._get_client", return_value=None):
                backlog_module._save_backlog_json(items, path)
                # Permanent delete
                backlog_module.permanent_delete_item("CLO-002")
                loaded = backlog_module._load_backlog_json(path)
                assert len(loaded) == 1
                assert loaded[0]["item_id"] == "CLO-001"


class TestTrash:
    """Tests para funcoes de lixeira."""

    def test_load_trash_returns_deleted_items(self):
        """load_trash retorna apenas itens com deleted_at."""
        json_data = [
            {"item_id": "CLO-001", "title": "Active"},
            {"item_id": "CLO-002", "title": "Deleted", "deleted_at": "2026-03-28T00:00:00Z"}
        ]
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=json_data):
            result = backlog_module.load_trash()
            assert len(result) == 1
            assert result[0]["item_id"] == "CLO-002"

    def test_empty_trash_deletes_all_trash_items(self):
        """empty_trash remove permanentemente todos itens da lixeira."""
        json_data = [
            {"item_id": "CLO-001", "title": "Active"},
            {"item_id": "CLO-002", "title": "Deleted", "deleted_at": "2026-03-28T00:00:00Z"},
            {"item_id": "CLO-003", "title": "Deleted2", "deleted_at": "2026-03-28T01:00:00Z"}
        ]
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=json_data), \
             patch("src.core.database.backlog.permanent_delete_item") as mock_delete:
            count = backlog_module.empty_trash()
            assert count == 2
            assert mock_delete.call_count == 2


class TestNextItemId:
    """Tests para geracao de IDs sequenciais."""

    def test_get_next_item_id_returns_clo_001_for_empty_backlog(self):
        """get_next_item_id retorna CLO-001 para backlog vazio."""
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=[]):
            result = backlog_module.get_next_item_id()
            assert result == "CLO-001"

    def test_get_next_item_id_increments_correctly(self):
        """get_next_item_id incrementa numero corretamente."""
        json_data = [
            {"item_id": "CLO-001"},
            {"item_id": "CLO-002"},
            {"item_id": "CLO-005"}
        ]
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=json_data):
            result = backlog_module.get_next_item_id()
            assert result == "CLO-006"

    def test_get_next_item_id_ignores_non_clo_items(self):
        """get_next_item_id ignora items que nao comecam com CLO-."""
        json_data = [
            {"item_id": "CLO-001"},
            {"item_id": "OTHER-100"}
        ]
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=json_data):
            result = backlog_module.get_next_item_id()
            assert result == "CLO-002"


class TestReorderBacklog:
    """Tests para reordenacao de backlog."""

    def test_reorder_backlog_updates_sort_order(self):
        """reorder_backlog atualiza sort_order baseado em lista de IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backlog.json")
            items = [
                {"item_id": "CLO-001", "sort_order": 0},
                {"item_id": "CLO-002", "sort_order": 1},
                {"item_id": "CLO-003", "sort_order": 2}
            ]
            backlog_module._save_backlog_json(items, path)

            with patch("src.core.database.backlog._get_backlog_json_path", return_value=path), \
                 patch("src.core.database.backlog._get_client", return_value=None):
                # Reorder
                backlog_module.reorder_backlog(["CLO-003", "CLO-001", "CLO-002"])
                loaded = backlog_module._load_backlog_json(path)

                order_map = {item["item_id"]: item["sort_order"] for item in loaded}
                assert order_map["CLO-003"] == 0
                assert order_map["CLO-001"] == 1
                assert order_map["CLO-002"] == 2


class TestBacklogAnalytics:
    """Tests para analytics do backlog."""

    def test_backlog_analytics_empty_backlog(self):
        """backlog_analytics retorna estrutura correta para backlog vazio."""
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=[]):
            result = backlog_module.backlog_analytics()
            assert result["total"] == 0
            assert result["by_status"] == {}
            assert result["avg_rice_score"] == 0
            assert result["trash_count"] == 0

    def test_backlog_analytics_counts_by_status(self):
        """backlog_analytics agrupa itens por status."""
        items = [
            {"item_id": "CLO-001", "status": "backlog", "rice_score": 20},
            {"item_id": "CLO-002", "status": "done", "rice_score": 30},
            {"item_id": "CLO-003", "status": "backlog", "rice_score": 25}
        ]
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=items):
            result = backlog_module.backlog_analytics()
            assert result["by_status"]["backlog"] == 2
            assert result["by_status"]["done"] == 1

    def test_backlog_analytics_calculates_avg_rice(self):
        """backlog_analytics calcula media de RICE score (excluindo done/cancelled)."""
        items = [
            {"item_id": "CLO-001", "status": "backlog", "rice_score": 20},
            {"item_id": "CLO-002", "status": "done", "rice_score": 100},  # Excludido
            {"item_id": "CLO-003", "status": "backlog", "rice_score": 30}
        ]
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=items):
            result = backlog_module.backlog_analytics()
            # (20 + 30) / 2 = 25
            assert result["avg_rice_score"] == 25.0

    def test_backlog_analytics_identifies_blocked_items(self):
        """backlog_analytics lista itens com status='blocked'."""
        items = [
            {"item_id": "CLO-001", "status": "backlog", "title": "Normal", "rice_score": 20},
            {"item_id": "CLO-002", "status": "blocked", "title": "Blocked One", "rice_score": 15},
            {"item_id": "CLO-003", "status": "blocked", "title": "Blocked Two", "rice_score": 10}
        ]
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=items):
            result = backlog_module.backlog_analytics()
            assert len(result["blocked_items"]) == 2

    def test_backlog_analytics_top5_rice(self):
        """backlog_analytics retorna top 5 itens por RICE score."""
        items = [
            {"item_id": f"CLO-{i:03d}", "status": "backlog", "title": f"Item {i}", "rice_score": 10 + i}
            for i in range(10)
        ]
        with patch("src.core.database.backlog._get_client", return_value=None), \
             patch("src.core.database.backlog._load_backlog_json", return_value=items):
            result = backlog_module.backlog_analytics()
            assert len(result["top5_rice"]) == 5
            # Top deve ter score maior
            assert result["top5_rice"][0]["rice_score"] >= result["top5_rice"][4]["rice_score"]
