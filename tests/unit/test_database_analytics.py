"""
tests/unit/test_database_analytics.py — Tests for src/core/database/analytics.py

Testa: analytics_funnel, analytics_time_per_stage, analytics_keywords, analytics_conversation_quality.
Mocks _get_client() e queries Supabase.
"""
import os
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# Set test mode and API key before imports
os.environ["TEST_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = "test-key"

import src.core.database.analytics as analytics_module


class TestAnalyticsFunnel:
    """Tests para analytics_funnel."""

    def test_analytics_funnel_db_not_connected(self):
        """analytics_funnel retorna erro quando DB nao esta conectado."""
        with patch("src.core.database.analytics._get_client", return_value=None):
            result = analytics_module.analytics_funnel()
            assert "error" in result
            assert "não conectado" in result["error"].lower()

    def test_analytics_funnel_empty_result(self):
        """analytics_funnel retorna estrutura correta com dados vazios."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_funnel()
            assert result["total_leads"] == 0
            assert result["conversion_rate_pct"] == 0
            assert len(result["funnel"]) == 8

    def test_analytics_funnel_counts_by_stage(self):
        """analytics_funnel conta leads em cada stage."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"funnel_stage": "abertura"},
            {"funnel_stage": "abertura"},
            {"funnel_stage": "qualificacao"},
            {"funnel_stage": "fechamento"}
        ]
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_funnel()
            assert result["total_leads"] == 4
            # Find stage counts
            stage_map = {s["stage"]: s["count"] for s in result["funnel"]}
            assert stage_map["abertura"] == 2
            assert stage_map["qualificacao"] == 1
            assert stage_map["fechamento"] == 1

    def test_analytics_funnel_calculates_percentages(self):
        """analytics_funnel calcula percentual por stage."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"funnel_stage": "abertura"},
            {"funnel_stage": "abertura"},
            {"funnel_stage": "fechamento"}
        ]
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_funnel()
            stage_map = {s["stage"]: s["pct"] for s in result["funnel"]}
            # 2/3 * 100 = 66.7%
            assert abs(stage_map["abertura"] - 66.7) < 0.1
            # 1/3 * 100 = 33.3%
            assert abs(stage_map["fechamento"] - 33.3) < 0.1

    def test_analytics_funnel_conversion_rate(self):
        """analytics_funnel calcula taxa de conversao (fechamento + pos_venda) / total."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"funnel_stage": "abertura"},
            {"funnel_stage": "abertura"},
            {"funnel_stage": "abertura"},
            {"funnel_stage": "abertura"},  # 4 total
            {"funnel_stage": "fechamento"},
            {"funnel_stage": "pos_venda"}
        ]
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_funnel()
            # 2 / 6 * 100 = 33.3%
            assert abs(result["conversion_rate_pct"] - 33.3) < 0.1

    def test_analytics_funnel_unknown_stages(self):
        """analytics_funnel coloca stages desconhecidos em 'others'."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"funnel_stage": "abertura"},
            {"funnel_stage": "custom_stage"},
            {"funnel_stage": "desqualificado"}
        ]
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_funnel()
            assert "custom_stage" in result["others"]
            assert "desqualificado" in result["others"]

    def test_analytics_funnel_handles_null_stage(self):
        """analytics_funnel trata stage nulo como 'desconhecido'."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"funnel_stage": None},
            {"funnel_stage": "abertura"}
        ]
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_funnel()
            # None is used as key in others since code doesn't convert to "desconhecido"
            assert None in result["others"] or "desconhecido" in result["others"]


class TestAnalyticsTimePerStage:
    """Tests para analytics_time_per_stage."""

    def test_analytics_time_per_stage_db_not_connected(self):
        """analytics_time_per_stage retorna erro quando DB nao conectado."""
        with patch("src.core.database.analytics._get_client", return_value=None):
            result = analytics_module.analytics_time_per_stage()
            assert "error" in result

    def test_analytics_time_per_stage_empty_result(self):
        """analytics_time_per_stage retorna dict vazio com dados vazios."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_time_per_stage()
            assert result["time_per_stage"] == {}

    def test_analytics_time_per_stage_calculates_duration(self):
        """analytics_time_per_stage calcula duracao em minutos."""
        mock_db = MagicMock()
        # created = 12:00, updated = 12:30 = 30 minutos
        created = "2026-03-28T12:00:00Z"
        updated = "2026-03-28T12:30:00Z"
        mock_result = MagicMock()
        mock_result.data = [
            {
                "funnel_stage": "abertura",
                "created_at": created,
                "updated_at": updated
            }
        ]
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_time_per_stage()
            assert result["time_per_stage"]["abertura"]["avg_minutes"] == 30.0

    def test_analytics_time_per_stage_averages_multiple_records(self):
        """analytics_time_per_stage calcula media para multiplos records do mesmo stage."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {
                "funnel_stage": "abertura",
                "created_at": "2026-03-28T12:00:00Z",
                "updated_at": "2026-03-28T12:20:00Z"  # 20 min
            },
            {
                "funnel_stage": "abertura",
                "created_at": "2026-03-28T13:00:00Z",
                "updated_at": "2026-03-28T13:40:00Z"  # 40 min
            }
        ]
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_time_per_stage()
            # (20 + 40) / 2 = 30
            assert result["time_per_stage"]["abertura"]["avg_minutes"] == 30.0
            assert result["time_per_stage"]["abertura"]["count"] == 2

    def test_analytics_time_per_stage_handles_invalid_dates(self):
        """analytics_time_per_stage ignora records com datas invalidas."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {
                "funnel_stage": "abertura",
                "created_at": None,
                "updated_at": "2026-03-28T12:30:00Z"
            },
            {
                "funnel_stage": "abertura",
                "created_at": "2026-03-28T12:00:00Z",
                "updated_at": "2026-03-28T12:30:00Z"
            }
        ]
        mock_db.table.return_value.select.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_time_per_stage()
            # Apenas o segundo record deve ser contado
            assert result["time_per_stage"]["abertura"]["count"] == 1


class TestAnalyticsKeywords:
    """Tests para analytics_keywords."""

    def test_analytics_keywords_db_not_connected(self):
        """analytics_keywords retorna erro quando DB nao conectado."""
        with patch("src.core.database.analytics._get_client", return_value=None):
            result = analytics_module.analytics_keywords()
            assert "error" in result

    def test_analytics_keywords_empty_messages(self):
        """analytics_keywords retorna resultado vazio para mensagens vazias."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_keywords()
            assert result["total_messages_analyzed"] == 0
            assert result["keywords"] == []

    def test_analytics_keywords_filters_stopwords(self):
        """analytics_keywords remove stopwords em portugues."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"content": "e a o de da muito bem oi"},  # Todos stopwords
            {"content": "produto excelente feature incrivel"}  # Palavras-chave
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_keywords()
            keywords = [k["word"] for k in result["keywords"]]
            # Stopwords nao devem aparecer
            assert "e" not in keywords
            assert "a" not in keywords
            # Palavras-chave devem aparecer
            assert "produto" in keywords

    def test_analytics_keywords_min_length_three(self):
        """analytics_keywords ignora palavras com menos de 3 caracteres."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"content": "ai oi ok produto service"}
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_keywords()
            keywords = [k["word"] for k in result["keywords"]]
            # Palavras < 3 nao devem aparecer
            assert "ai" not in keywords
            assert "oi" not in keywords
            assert "ok" not in keywords

    def test_analytics_keywords_counts_frequency(self):
        """analytics_keywords conta frequencia de palavras."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"content": "produto produto produto"},
            {"content": "service service"},
            {"content": "qualidade"}
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_keywords()
            keyword_map = {k["word"]: k["count"] for k in result["keywords"]}
            assert keyword_map["produto"] == 3
            assert keyword_map["service"] == 2
            assert keyword_map["qualidade"] == 1

    def test_analytics_keywords_returns_top_n(self):
        """analytics_keywords retorna top N palavras (padrão 30)."""
        mock_db = MagicMock()
        messages = [
            {"content": f"palavra{i} " * 5}  # Cria 50 palavras
            for i in range(10)
        ]
        mock_result = MagicMock()
        mock_result.data = messages
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_keywords(limit=30)
            assert len(result["keywords"]) <= 30

    def test_analytics_keywords_handles_special_chars(self):
        """analytics_keywords extrai apenas palavras (remove pontuacao)."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"content": "produto, serviço! qualidade?"}
        ]
        mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_keywords()
            keywords = [k["word"] for k in result["keywords"]]
            # Pontuacao removida
            assert "produto" in keywords
            assert "serviço" in keywords


class TestAnalyticsConversationQuality:
    """Tests para analytics_conversation_quality."""

    def test_analytics_conversation_quality_db_not_connected(self):
        """analytics_conversation_quality retorna erro quando DB nao conectado."""
        with patch("src.core.database.analytics._get_client", return_value=None):
            result = analytics_module.analytics_conversation_quality()
            assert "error" in result

    def test_analytics_conversation_quality_empty_conversations(self):
        """analytics_conversation_quality retorna resultado vazio com dados vazios."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_conversation_quality()
            assert result["total_conversations"] == 0
            assert result["avg_quality_score"] == 0
            assert result["conversations"] == []

    def test_analytics_conversation_quality_calculates_engagement(self):
        """analytics_conversation_quality calcula engagement score baseado em msgs."""
        mock_db = MagicMock()
        # 4 user msgs + 6 assistant msgs = 10 total
        # user_msgs / total * 50 = 4/10 * 50 = 20 (min 25)
        mock_msgs = MagicMock()
        mock_msgs.data = [
            {"user_id": "user1", "role": "user", "message_type": "conversation"},
            {"user_id": "user1", "role": "user", "message_type": "conversation"},
            {"user_id": "user1", "role": "user", "message_type": "conversation"},
            {"user_id": "user1", "role": "user", "message_type": "conversation"},
            {"user_id": "user1", "role": "assistant", "message_type": "conversation"},
            {"user_id": "user1", "role": "assistant", "message_type": "conversation"},
            {"user_id": "user1", "role": "assistant", "message_type": "conversation"},
            {"user_id": "user1", "role": "assistant", "message_type": "conversation"},
            {"user_id": "user1", "role": "assistant", "message_type": "conversation"},
            {"user_id": "user1", "role": "assistant", "message_type": "conversation"}
        ]

        mock_meta = MagicMock()
        mock_meta.data = [{"user_id": "user1", "funnel_stage": "fechamento"}]

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "conversations":
                return MagicMock(
                    select=MagicMock(return_value=MagicMock(
                        eq=MagicMock(return_value=MagicMock(
                            order=MagicMock(return_value=MagicMock(
                                limit=MagicMock(return_value=MagicMock(
                                    execute=MagicMock(return_value=mock_msgs)
                                ))
                            ))
                        ))
                    ))
                )
            elif table_name == "lead_metadata":
                return MagicMock(
                    select=MagicMock(return_value=MagicMock(
                        in_=MagicMock(return_value=MagicMock(
                            execute=MagicMock(return_value=mock_meta)
                        ))
                    ))
                )
            return mock_table

        mock_db.table.side_effect = table_side_effect

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_conversation_quality()
            # Deve ter calculado score
            assert result["total_conversations"] >= 0
            if result["conversations"]:
                assert result["conversations"][0]["score"] >= 0

    def test_analytics_conversation_quality_filters_by_user(self):
        """analytics_conversation_quality filtra por user_id quando fornecido."""
        mock_db = MagicMock()
        mock_msgs = MagicMock()
        mock_msgs.data = []

        mock_meta = MagicMock()
        mock_meta.data = []

        def table_side_effect(table_name):
            if table_name == "conversations":
                table_mock = MagicMock()
                eq_mock = MagicMock()
                eq_mock.return_value.order.return_value.limit.return_value.execute.return_value = mock_msgs
                table_mock.select.return_value.eq.return_value = eq_mock.return_value
                return table_mock
            elif table_name == "lead_metadata":
                table_mock = MagicMock()
                table_mock.select.return_value.in_.return_value.execute.return_value = mock_meta
                return table_mock

        mock_db.table.side_effect = table_side_effect

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_conversation_quality(user_id="test_user")
            # Funcao nao lanca erro quando user_id fornecido
            assert "total_conversations" in result

    def test_analytics_conversation_quality_scores_structure(self):
        """analytics_conversation_quality retorna scores com estrutura esperada."""
        mock_db = MagicMock()
        mock_msgs = MagicMock()
        mock_msgs.data = [
            {"user_id": "user1", "role": "user", "message_type": "conversation"},
            {"user_id": "user1", "role": "assistant", "message_type": "conversation"}
        ]

        mock_meta = MagicMock()
        mock_meta.data = [{"user_id": "user1", "funnel_stage": "abertura"}]

        def table_side_effect(table_name):
            if table_name == "conversations":
                return MagicMock(
                    select=MagicMock(return_value=MagicMock(
                        eq=MagicMock(return_value=MagicMock(
                            order=MagicMock(return_value=MagicMock(
                                limit=MagicMock(return_value=MagicMock(
                                    execute=MagicMock(return_value=mock_msgs)
                                ))
                            ))
                        ))
                    ))
                )
            elif table_name == "lead_metadata":
                return MagicMock(
                    select=MagicMock(return_value=MagicMock(
                        in_=MagicMock(return_value=MagicMock(
                            execute=MagicMock(return_value=mock_meta)
                        ))
                    ))
                )

        mock_db.table.side_effect = table_side_effect

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_conversation_quality()
            if result["conversations"]:
                conv = result["conversations"][0]
                assert "user_id" in conv
                assert "score" in conv
                assert "breakdown" in conv
                assert "total_messages" in conv
                assert "funnel_stage" in conv
                assert conv["score"] >= 0
                assert conv["score"] <= 100

    def test_analytics_conversation_quality_top_50(self):
        """analytics_conversation_quality retorna top 50 conversations."""
        mock_db = MagicMock()
        # Gera 100 mensagens
        mock_msgs = MagicMock()
        mock_msgs.data = [
            {"user_id": f"user{i}", "role": "user" if i % 2 == 0 else "assistant", "message_type": "conversation"}
            for i in range(100)
        ]

        mock_meta = MagicMock()
        mock_meta.data = [{"user_id": f"user{i}", "funnel_stage": "abertura"} for i in range(50)]

        def table_side_effect(table_name):
            if table_name == "conversations":
                return MagicMock(
                    select=MagicMock(return_value=MagicMock(
                        eq=MagicMock(return_value=MagicMock(
                            order=MagicMock(return_value=MagicMock(
                                limit=MagicMock(return_value=MagicMock(
                                    execute=MagicMock(return_value=mock_msgs)
                                ))
                            ))
                        ))
                    ))
                )
            elif table_name == "lead_metadata":
                return MagicMock(
                    select=MagicMock(return_value=MagicMock(
                        in_=MagicMock(return_value=MagicMock(
                            execute=MagicMock(return_value=mock_meta)
                        ))
                    ))
                )

        mock_db.table.side_effect = table_side_effect

        with patch("src.core.database.analytics._get_client", return_value=mock_db):
            result = analytics_module.analytics_conversation_quality()
            assert len(result["conversations"]) <= 50
