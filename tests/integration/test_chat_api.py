"""
tests/integration/test_chat_api.py — Testes de integracao do endpoint /chat.

Usa Flask test client com mocks.
Testa API mode, sandbox mode, autenticacao e validacao.

NOTA: Testes que passam pelo debounce path precisam de cuidado especial
porque event.wait() bloqueia. Usamos side_effect para executar o flush
sincronamente ao inves de esperar o timer gevent.
"""
import threading
import pytest
from unittest.mock import patch, MagicMock


def _make_sync_spawn_later(app):
    """
    Cria um side_effect para gevent.spawn_later que executa a funcao
    sincronamente em outra thread (simula o timer disparando imediatamente).
    """
    def sync_spawn_later(delay, func, *args, **kwargs):
        # Execute the function in a thread immediately
        t = threading.Thread(target=func, args=args, kwargs=kwargs)
        t.daemon = True
        t.start()
        mock_greenlet = MagicMock()
        mock_greenlet.kill = MagicMock()
        return mock_greenlet
    return sync_spawn_later


@pytest.mark.integration
class TestChatSandboxMode:
    """Testa o modo sandbox (sem auth)."""

    def test_sandbox_mode_basic(self, client, app, mock_claude):
        """POST sandbox com mensagem valida deve processar e retornar resposta."""
        with patch("src.api.chat.gevent") as mock_gevent:
            mock_gevent.spawn_later.side_effect = _make_sync_spawn_later(app)

            resp = client.post("/chat", json={
                "message": "Oi, quero saber sobre o curso",
                "session_id": "sandbox",
            })

            assert resp.status_code == 200
            data = resp.get_json()
            assert "status" in data
            # With sync flush, should get a real response
            assert data["status"] in ("success", "error")

    def test_sandbox_empty_message_returns_400(self, client):
        """Mensagem vazia no sandbox retorna 400."""
        resp = client.post("/chat", json={
            "message": "",
            "session_id": "sandbox",
        })

        assert resp.status_code == 400

    def test_sandbox_no_message_returns_400(self, client):
        """Sem campo message no sandbox retorna 400."""
        resp = client.post("/chat", json={"session_id": "sandbox"})

        assert resp.status_code == 400

    def test_sandbox_secret_command_escalate(self, client):
        """Comando secreto funciona no sandbox (bypass debounce)."""
        with patch("src.api.chat.escalation.handle_escalation"):
            resp = client.post("/chat", json={
                "message": "#transferindo-para-atendimento-dedicado",
                "session_id": "sandbox",
            })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "escalated"


@pytest.mark.integration
class TestChatApiMode:
    """Testa o modo API (com autenticacao)."""

    def test_api_mode_without_auth_returns_401(self, client):
        """POST API sem token retorna 401."""
        resp = client.post("/chat", json={
            "user_id": "user123",
            "message": "Oi",
            "channel": "api",
            "session_id": "session-123",
        })

        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Unauthorized"

    def test_api_mode_wrong_token_returns_401(self, client):
        """POST API com token errado retorna 401."""
        resp = client.post("/chat",
            json={
                "user_id": "user123",
                "message": "Oi",
                "channel": "api",
                "session_id": "session-123",
            },
            headers={"Authorization": "Bearer wrong-token"},
        )

        assert resp.status_code == 401

    def test_api_mode_with_auth(self, client, app, mock_claude):
        """POST API com Bearer token valido deve processar."""
        with patch("src.api.chat.gevent") as mock_gevent:
            mock_gevent.spawn_later.side_effect = _make_sync_spawn_later(app)

            resp = client.post("/chat",
                json={
                    "user_id": "user123",
                    "message": "Quero saber sobre o preparatorio",
                    "channel": "api",
                    "session_id": "session-api-auth",
                },
                headers={"Authorization": "Bearer test-secret-token"},
            )

            assert resp.status_code == 200
            data = resp.get_json()
            assert "status" in data

    def test_missing_message_returns_400(self, client):
        """POST API sem message retorna 400."""
        resp = client.post("/chat",
            json={
                "user_id": "user123",
                "channel": "api",
                "session_id": "session-123",
            },
            headers={"Authorization": "Bearer test-secret-token"},
        )

        assert resp.status_code == 400
        assert "message" in resp.get_json()["error"].lower()

    def test_missing_user_id_for_external_channel_returns_400(self, client):
        """Canal externo sem user_id retorna 400."""
        resp = client.post("/chat",
            json={
                "message": "Oi",
                "channel": "botmaker",
            },
            headers={"Authorization": "Bearer test-secret-token"},
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert "user_id" in data["error"].lower()

    def test_escalated_session_returns_escalated_status(self, client):
        """Sessao escalated retorna status=escalated_session."""
        with patch("src.api.chat.escalation.is_escalated", return_value=True):
            resp = client.post("/chat",
                json={
                    "user_id": "escalated-user",
                    "message": "Oi",
                    "channel": "api",
                    "session_id": "session-esc",
                },
                headers={"Authorization": "Bearer test-secret-token"},
            )

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "escalated_session"

    def test_secret_commands_work_via_chat(self, client):
        """Comandos secretos funcionam pelo /chat API mode."""
        with patch("src.api.chat.escalation.handle_escalation"):
            resp = client.post("/chat",
                json={
                    "user_id": "cmd-user",
                    "message": "#transferindo-para-atendimento-dedicado",
                    "channel": "api",
                    "session_id": "session-cmd",
                },
                headers={"Authorization": "Bearer test-secret-token"},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "escalated"
        assert data["command"] == "escalate"


@pytest.mark.integration
class TestChatReset:
    """Testa o endpoint /reset."""

    def test_reset_returns_ok(self, client):
        """POST /reset retorna status=ok."""
        resp = client.post("/reset", json={"session_id": "sandbox"})

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_reset_without_session_resets_all(self, client):
        """POST /reset sem session_id reseta tudo."""
        resp = client.post("/reset", json={})

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
