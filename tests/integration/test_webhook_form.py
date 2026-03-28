"""
tests/integration/test_webhook_form.py — Testes de integracao do webhook Form.

Usa Flask test client com mocks de servicos externos.
Testa o fluxo completo de recebimento de leads via formulario.
"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def clear_form_rate_limit():
    """Limpa estado de rate limit do form antes de cada teste."""
    try:
        from src.api.webhooks import _form_rate_store, _form_rate_lock
        with _form_rate_lock:
            _form_rate_store.clear()
    except ImportError:
        pass
    yield
    try:
        from src.api.webhooks import _form_rate_store, _form_rate_lock
        with _form_rate_lock:
            _form_rate_store.clear()
    except ImportError:
        pass


@pytest.mark.integration
class TestWebhookFormValid:
    """Testa payloads validos do Form webhook."""

    def test_valid_form_returns_200(self, client, sample_form_payload):
        """Form valido retorna status=ok."""
        with patch("src.api.webhooks.send_message", return_value=True):
            resp = client.post("/webhook/form", json=sample_form_payload)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "phone" in data
        assert data["message_sent"] is True

    def test_phone_normalization(self, client):
        """Telefone sem DDI e normalizado para 55+DDD+numero."""
        resp = client.post("/webhook/form", json={
            "name": "Maria",
            "phone": "11999998888",
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["phone"] == "5511999998888"

    def test_phone_with_formatting(self, client):
        """Telefone com formatacao e aceito."""
        resp = client.post("/webhook/form", json={
            "name": "Jose",
            "phone": "(11) 99999-8888",
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["phone"] == "5511999998888"

    def test_alternative_phone_fields(self, client):
        """Campos alternativos de telefone sao aceitos."""
        for field in ["celular", "telefone", "whatsapp"]:
            resp = client.post("/webhook/form", json={
                "name": "Lead",
                field: "11999997777",
            })

            assert resp.status_code == 200, f"Field '{field}' should be accepted"
            assert resp.get_json()["status"] == "ok"

    def test_alternative_name_fields(self, client):
        """Campos alternativos de nome sao aceitos."""
        resp = client.post("/webhook/form", json={
            "nome": "Carlos Souza",
            "phone": "11999996666",
        })

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


@pytest.mark.integration
class TestWebhookFormErrors:
    """Testa erros e validacao do Form webhook."""

    def test_missing_phone_returns_400(self, client):
        """Payload sem telefone retorna 400."""
        resp = client.post("/webhook/form", json={"name": "Sem Telefone"})

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"
        assert "phone" in data["error"].lower()

    def test_invalid_phone_returns_400(self, client):
        """Telefone invalido (muito curto) retorna 400."""
        resp = client.post("/webhook/form", json={
            "name": "Lead",
            "phone": "123",
        })

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"

    def test_form_rate_limit_returns_429(self, client):
        """6+ requests do mesmo IP retorna 429."""
        # The form rate limit is 5 per minute (default FORM_RATE_LIMIT=5)
        # We need to clear any state first
        from src.api.webhooks import _form_rate_store, _form_rate_lock
        with _form_rate_lock:
            _form_rate_store.clear()

        for i in range(5):
            resp = client.post("/webhook/form", json={
                "name": f"Lead {i}",
                "phone": f"1199999{i:04d}",
            })
            assert resp.status_code == 200, f"Request {i+1} should succeed"

        # 6th request should be rate limited
        resp = client.post("/webhook/form", json={
            "name": "Lead Blocked",
            "phone": "11999990006",
        })
        assert resp.status_code == 429
        data = resp.get_json()
        assert data["status"] == "error"

    def test_empty_payload_returns_400(self, client):
        """Payload vazio retorna 400 (sem phone)."""
        resp = client.post("/webhook/form", json={})

        assert resp.status_code == 400
