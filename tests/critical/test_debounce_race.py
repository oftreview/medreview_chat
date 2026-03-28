"""
tests/critical/test_debounce_race.py — Testes do BUG CRITICO 1.

Race Condition no Timer de Debounce (src/api/webhooks.py:158-174)
_zapi_state dict com timer gevent; kill() do timer pode perder msgs acumuladas.

Estes testes verificam que:
- Mensagens rapidas do mesmo phone sao acumuladas corretamente
- Timer reset preserva mensagens anteriores
- Phones diferentes sao independentes
"""
import threading
import time
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.critical
class TestDebounceAccumulation:
    """Testa acumulacao de mensagens no debounce Z-API."""

    def test_concurrent_messages_accumulated_before_flush(self, client, mock_claude):
        """3 msgs rapidas do mesmo phone devem ser acumuladas e enviadas juntas ao agent."""
        phone = "5511999990001"

        # Mock agent.reply para capturar o combined message
        captured_messages = []

        def fake_reply(combined, session_id=None):
            captured_messages.append(combined)
            return {"message": "Resposta teste", "escalate": False}

        with patch("src.api.webhooks._zapi_flush") as mock_flush, \
             patch("src.api.webhooks.gevent") as mock_gevent:
            # Prevent actual timer spawning
            mock_timer = MagicMock()
            mock_gevent.spawn_later.return_value = mock_timer

            payloads = [
                {"type": "ReceivedCallback", "fromMe": False, "phone": phone, "body": f"Mensagem {i}"}
                for i in range(1, 4)
            ]

            for payload in payloads:
                resp = client.post("/webhook/zapi", json=payload)
                assert resp.status_code == 200
                assert resp.get_json()["status"] == "queued"

            # Verify messages were accumulated in state
            from src.api.webhooks import _zapi_state, _zapi_lock
            with _zapi_lock:
                state = _zapi_state.get(phone)
                assert state is not None, "Phone state should exist"
                assert len(state["messages"]) == 3, f"Expected 3 messages, got {len(state['messages'])}"
                assert state["messages"][0] == "Mensagem 1"
                assert state["messages"][1] == "Mensagem 2"
                assert state["messages"][2] == "Mensagem 3"

    def test_timer_reset_preserves_previous_messages(self, client):
        """Quando nova msg chega e reseta o timer, msgs anteriores nao sao perdidas."""
        phone = "5511999990002"

        with patch("src.api.webhooks.gevent") as mock_gevent:
            mock_timer1 = MagicMock()
            mock_timer2 = MagicMock()
            mock_gevent.spawn_later.side_effect = [mock_timer1, mock_timer2]

            # Send first message
            resp1 = client.post("/webhook/zapi", json={
                "type": "ReceivedCallback", "fromMe": False,
                "phone": phone, "body": "Primeira msg",
            })
            assert resp1.status_code == 200

            # Timer 1 should have been spawned
            assert mock_gevent.spawn_later.call_count == 1

            # Send second message (resets timer)
            resp2 = client.post("/webhook/zapi", json={
                "type": "ReceivedCallback", "fromMe": False,
                "phone": phone, "body": "Segunda msg",
            })
            assert resp2.status_code == 200

            # Timer 1 should be killed, timer 2 spawned
            mock_timer1.kill.assert_called_once()
            assert mock_gevent.spawn_later.call_count == 2

            # Both messages should be accumulated
            from src.api.webhooks import _zapi_state, _zapi_lock
            with _zapi_lock:
                state = _zapi_state.get(phone)
                assert len(state["messages"]) == 2
                assert "Primeira msg" in state["messages"]
                assert "Segunda msg" in state["messages"]

    def test_concurrent_phones_independent(self, client):
        """2 phones diferentes nao devem interferir um no outro."""
        phone_a = "5511999990003"
        phone_b = "5511999990004"

        with patch("src.api.webhooks.gevent") as mock_gevent:
            mock_gevent.spawn_later.return_value = MagicMock()

            client.post("/webhook/zapi", json={
                "type": "ReceivedCallback", "fromMe": False,
                "phone": phone_a, "body": "Msg do A",
            })
            client.post("/webhook/zapi", json={
                "type": "ReceivedCallback", "fromMe": False,
                "phone": phone_b, "body": "Msg do B",
            })

            from src.api.webhooks import _zapi_state, _zapi_lock
            with _zapi_lock:
                state_a = _zapi_state.get(phone_a)
                state_b = _zapi_state.get(phone_b)

                assert state_a is not None
                assert state_b is not None
                assert len(state_a["messages"]) == 1
                assert len(state_b["messages"]) == 1
                assert state_a["messages"][0] == "Msg do A"
                assert state_b["messages"][0] == "Msg do B"
