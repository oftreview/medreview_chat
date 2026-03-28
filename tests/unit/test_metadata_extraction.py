"""
tests/unit/test_metadata_extraction.py — Testes de extracao de metadados [META].

Testa: _extract_metadata do sales_agent.py
Sem I/O, sem mocks.
"""
import pytest
from src.agent.sales_agent import _extract_metadata


class TestExtractMetadata:
    """Testes da funcao _extract_metadata."""

    def test_no_meta_tag_returns_original(self):
        """Texto sem [META] retorna texto original e dict vazio."""
        text = "Oi, tudo bem? Posso te ajudar com o curso R1."
        clean, meta = _extract_metadata(text)
        assert clean == text
        assert meta == {}

    def test_valid_meta_tag_extracted(self):
        """[META] valido e extraido corretamente."""
        text = "Resposta do agente.\n\n[META] stage=qualificacao | especialidade=clinica_medica"
        clean, meta = _extract_metadata(text)
        assert "stage" in meta
        assert meta["stage"] == "qualificacao"
        assert meta["especialidade"] == "clinica_medica"

    def test_clean_text_excludes_meta(self):
        """Texto limpo nao contem a linha [META]."""
        text = "Resposta do agente.\n\n[META] stage=descoberta"
        clean, meta = _extract_metadata(text)
        assert "[META]" not in clean
        assert "Resposta do agente." in clean

    def test_multiple_pipe_separated_fields(self):
        """Multiplos campos separados por | sao parseados."""
        text = "OK.\n[META] stage=negociacao | prova=usp | ano_prova=2027 | motivo_escalacao=nenhum"
        clean, meta = _extract_metadata(text)
        assert meta["stage"] == "negociacao"
        assert meta["prova"] == "usp"
        assert meta["ano_prova"] == "2027"
        assert meta["motivo_escalacao"] == "nenhum"

    def test_desconhecido_value_becomes_none(self):
        """Valor 'desconhecido' e armazenado como None."""
        text = "Resposta.\n[META] stage=descoberta | especialidade=desconhecido"
        clean, meta = _extract_metadata(text)
        assert meta["stage"] == "descoberta"
        assert meta["especialidade"] is None

    def test_meta_at_end_of_text(self):
        """[META] no final do texto e extraido."""
        text = "Primeira parte da resposta.\n\nSegunda parte.\n[META] stage=fechamento"
        clean, meta = _extract_metadata(text)
        assert meta["stage"] == "fechamento"
        assert "Primeira parte" in clean
        assert "Segunda parte" in clean

    def test_preserves_response_before_meta(self):
        """Todo o texto antes de [META] e preservado."""
        text = "Linha 1.\nLinha 2.\nLinha 3.\n[META] stage=teste"
        clean, meta = _extract_metadata(text)
        assert "Linha 1." in clean
        assert "Linha 2." in clean
        assert "Linha 3." in clean

    def test_empty_value_ignored(self):
        """Campos com valor vazio sao ignorados."""
        text = "OK.\n[META] stage=teste | campo_vazio="
        clean, meta = _extract_metadata(text)
        assert "stage" in meta
        assert "campo_vazio" not in meta

    def test_meta_pattern_regex_matches(self):
        """Regex META_PATTERN encontra a linha [META]."""
        from src.agent.sales_agent import META_PATTERN
        text = "Resposta.\n[META] stage=x | prova=y"
        match = META_PATTERN.search(text)
        assert match is not None
        assert "stage=x" in match.group(1)
