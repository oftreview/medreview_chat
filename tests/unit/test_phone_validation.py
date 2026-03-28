"""
tests/unit/test_phone_validation.py — Testes de validacao e normalizacao de telefone.

Testa: format_phone (whatsapp.py), _normalize_phone e _PHONE_RE (webhooks.py)
Sem I/O, sem mocks.
"""
import pytest
import re
from src.core.whatsapp import format_phone


class TestFormatPhone:
    """Testes da funcao format_phone do modulo whatsapp."""

    def test_phone_with_ddi_unchanged(self):
        """Telefone ja com DDI 55 nao e alterado."""
        assert format_phone("5511999999999") == "5511999999999"

    def test_phone_without_ddi_adds_55(self):
        """Telefone sem DDI recebe prefixo 55."""
        assert format_phone("11999999999") == "5511999999999"

    def test_phone_with_whatsapp_suffix_stripped(self):
        """Sufixo @s.whatsapp.net e removido."""
        assert format_phone("5511999999999@s.whatsapp.net") == "5511999999999"

    def test_phone_with_cus_suffix_stripped(self):
        """Sufixo @c.us e removido."""
        assert format_phone("5511999999999@c.us") == "5511999999999"

    def test_phone_with_formatting_cleaned(self):
        """Caracteres de formatacao sao removidos."""
        assert format_phone("(11) 99999-9999") == "5511999999999"

    def test_phone_with_plus_sign(self):
        """Sinal de + e removido."""
        assert format_phone("+5511999999999") == "5511999999999"

    def test_phone_with_spaces(self):
        """Espacos sao removidos."""
        assert format_phone("55 11 99999 9999") == "5511999999999"


class TestNormalizePhone:
    """Testes da funcao _normalize_phone do modulo webhooks."""

    def test_normalize_removes_non_digits(self):
        """Remove caracteres nao-numericos."""
        from src.api.webhooks import _normalize_phone
        assert _normalize_phone("(11) 99999-9999") == "5511999999999"

    def test_normalize_strips_leading_zero(self):
        """Remove zero inicial."""
        from src.api.webhooks import _normalize_phone
        assert _normalize_phone("011999999999") == "5511999999999"

    def test_normalize_adds_ddi(self):
        """Adiciona DDI 55 se ausente."""
        from src.api.webhooks import _normalize_phone
        assert _normalize_phone("11999999999") == "5511999999999"

    def test_normalize_preserves_ddi(self):
        """Nao duplica DDI se ja presente."""
        from src.api.webhooks import _normalize_phone
        assert _normalize_phone("5511999999999") == "5511999999999"


class TestPhoneRegex:
    """Testes do regex _PHONE_RE para validacao de telefone brasileiro."""

    def test_valid_mobile_11_digits(self):
        """Celular valido: DDI(55) + DDD(2) + 9 digitos."""
        from src.api.webhooks import _PHONE_RE
        assert _PHONE_RE.match("5511999999999")

    def test_valid_landline_10_digits(self):
        """Fixo valido: DDI(55) + DDD(2) + 8 digitos."""
        from src.api.webhooks import _PHONE_RE
        assert _PHONE_RE.match("551199999999")

    def test_invalid_too_short(self):
        """Rejeita numeros muito curtos."""
        from src.api.webhooks import _PHONE_RE
        assert not _PHONE_RE.match("551199999")

    def test_invalid_too_long(self):
        """Rejeita numeros muito longos."""
        from src.api.webhooks import _PHONE_RE
        assert not _PHONE_RE.match("55119999999999")

    def test_invalid_without_ddi(self):
        """Rejeita numeros sem DDI 55."""
        from src.api.webhooks import _PHONE_RE
        assert not _PHONE_RE.match("11999999999")

    def test_invalid_alphanumeric(self):
        """Rejeita numeros com letras."""
        from src.api.webhooks import _PHONE_RE
        assert not _PHONE_RE.match("55abc99999999")


class TestParseIncoming:
    """Testes da funcao parse_incoming do whatsapp.py."""

    def test_valid_text_message_parsed(self):
        """Mensagem de texto valida e parseada corretamente."""
        from src.core.whatsapp import parse_incoming
        data = {
            "type": "ReceivedCallback",
            "fromMe": False,
            "phone": "5511999999999",
            "body": "Oi, quero saber mais",
            "senderName": "Joao",
        }
        result = parse_incoming(data)
        assert result is not None
        assert result["phone"] == "5511999999999"
        assert result["message"] == "Oi, quero saber mais"
        assert result["name"] == "Joao"

    def test_nested_text_message_parsed(self):
        """Mensagem com texto em text.message e parseada."""
        from src.core.whatsapp import parse_incoming
        data = {
            "type": "ReceivedCallback",
            "fromMe": False,
            "phone": "5511988888888",
            "text": {"message": "Qual o preco?"},
        }
        result = parse_incoming(data)
        assert result is not None
        assert result["message"] == "Qual o preco?"

    def test_from_me_returns_none(self):
        """Mensagens proprias sao ignoradas."""
        from src.core.whatsapp import parse_incoming
        data = {"type": "ReceivedCallback", "fromMe": True, "phone": "5511999999999", "body": "Oi"}
        assert parse_incoming(data) is None

    def test_non_received_type_returns_none(self):
        """Tipos que nao sao ReceivedCallback sao ignorados."""
        from src.core.whatsapp import parse_incoming
        data = {"type": "MessageStatusCallback", "fromMe": False, "phone": "5511999999999", "body": "Oi"}
        assert parse_incoming(data) is None

    def test_empty_body_returns_none(self):
        """Mensagem sem corpo retorna None."""
        from src.core.whatsapp import parse_incoming
        data = {"type": "ReceivedCallback", "fromMe": False, "phone": "5511999999999", "body": ""}
        assert parse_incoming(data) is None

    def test_no_phone_returns_none(self):
        """Mensagem sem telefone retorna None."""
        from src.core.whatsapp import parse_incoming
        data = {"type": "ReceivedCallback", "fromMe": False, "phone": "", "body": "Oi"}
        assert parse_incoming(data) is None
