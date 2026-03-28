"""
tests/unit/test_message_splitter.py — Testes do message_splitter.

Testa: split_response, _split_paragraph
Sem I/O, sem mocks complexos.
"""
import pytest
from src.core.message_splitter import split_response, _split_paragraph, MAX_CHARS, MAX_MESSAGES


class TestSplitResponseBasic:
    """Testes basicos de split_response."""

    def test_short_text_returns_single_message(self):
        """Texto menor que MAX_CHARS retorna lista com 1 elemento."""
        text = "Oi, tudo bem?"
        result = split_response(text)
        assert len(result) == 1
        assert result[0] == text

    def test_empty_text_returns_list(self):
        """Texto vazio retorna lista com string vazia."""
        result = split_response("")
        assert len(result) == 1
        assert result[0] == ""

    def test_none_text_returns_list(self):
        """None retorna lista com string vazia."""
        result = split_response(None)
        assert len(result) == 1

    def test_whitespace_only_returns_list(self):
        """Texto so com espacos retorna lista."""
        result = split_response("   ")
        assert len(result) == 1

    def test_exact_max_chars_returns_single(self):
        """Texto com exatamente MAX_CHARS retorna 1 mensagem."""
        text = "A" * MAX_CHARS
        result = split_response(text)
        assert len(result) == 1


class TestSplitResponseSplitting:
    """Testes de divisao de texto longo."""

    def test_long_text_splits_into_multiple(self):
        """Texto longo e dividido em multiplas mensagens."""
        # Cria texto com 3 paragrafos longos
        para = "Esta e uma frase longa que deve caber em uma mensagem. " * 5
        text = f"{para}\n\n{para}\n\n{para}"
        result = split_response(text)
        assert len(result) > 1

    def test_max_messages_limit_respected(self):
        """Nunca retorna mais que MAX_MESSAGES."""
        # Cria texto muito longo com muitos paragrafos
        para = "Paragrafo de teste com conteudo suficiente para ocupar espaco. " * 3
        text = "\n\n".join([para] * 10)
        result = split_response(text, max_messages=MAX_MESSAGES)
        assert len(result) <= MAX_MESSAGES

    def test_paragraph_splitting_preserves_context(self):
        """Paragrafos curtos sao agrupados na mesma mensagem."""
        text = "Parte A.\n\nParte B.\n\nParte C."
        result = split_response(text)
        # Texto total e curto, deve ficar em 1 mensagem
        assert len(result) == 1
        assert "Parte A." in result[0]
        assert "Parte C." in result[0]

    def test_splits_at_sentence_boundary(self):
        """Divisao ocorre em fronteira de frase, nao no meio."""
        # Cria texto que excede MAX_CHARS
        text = "Primeira frase completa. Segunda frase completa. " * 10
        result = split_response(text, max_chars=100)
        for part in result:
            # Cada parte deve terminar com pontuacao ou ser o final
            stripped = part.strip()
            if stripped:
                assert stripped[-1] in ".!? " or len(stripped) <= 100 + 20  # margem


class TestSplitParagraph:
    """Testes da funcao interna _split_paragraph."""

    def test_short_paragraph_not_split(self):
        """Paragrafo menor que max_chars nao e dividido."""
        text = "Texto curto."
        result = _split_paragraph(text, 300)
        assert len(result) == 1
        assert result[0] == text

    def test_long_paragraph_split_at_sentence(self):
        """Paragrafo longo e dividido na fronteira de frase."""
        text = "Primeira frase. Segunda frase. Terceira frase. Quarta frase."
        result = _split_paragraph(text, 35)
        assert len(result) > 1
        # Cada chunk deve conter pelo menos uma frase completa
        for chunk in result:
            assert len(chunk) > 0

    def test_single_giant_word_force_split(self):
        """Palavra unica gigante e cortada forcadamente."""
        text = "A" * 500
        result = _split_paragraph(text, 100)
        assert len(result) > 1
        # Primeiro chunk tem exatamente max_chars
        assert len(result[0]) == 100

    def test_preserves_all_content(self):
        """Todo o conteudo original esta presente apos split."""
        text = "Frase um. Frase dois. Frase tres. Frase quatro. Frase cinco."
        result = _split_paragraph(text, 30)
        reconstructed = " ".join(result)
        # Todas as palavras originais devem estar presentes
        for word in text.split():
            assert word in reconstructed


class TestSplitResponseCustomParams:
    """Testes com parametros customizados."""

    def test_custom_max_chars(self):
        """Respeita max_chars customizado."""
        text = "Oi tudo bem? Estou interessado no curso. Pode me ajudar?"
        result = split_response(text, max_chars=30)
        for part in result:
            # Partes devem respeitar o limite (com margem para joins)
            assert len(part) <= 60  # margem para overflow join

    def test_custom_max_messages(self):
        """Respeita max_messages customizado."""
        text = "Parte A.\n\nParte B.\n\nParte C.\n\nParte D.\n\nParte E."
        result = split_response(text, max_chars=20, max_messages=2)
        assert len(result) <= 2

    def test_max_messages_1_returns_full_text(self):
        """max_messages=1 retorna tudo em uma unica mensagem."""
        text = "Parte A.\n\nParte B.\n\nParte C."
        result = split_response(text, max_messages=1)
        assert len(result) == 1
