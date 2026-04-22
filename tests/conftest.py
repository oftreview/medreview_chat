"""
tests/conftest.py — Fixtures compartilhadas do Closi AI test suite.

Fornece:
- app: Flask app configurada para testes
- client: Flask test client
- mock_claude: Respostas Claude deterministicas
- mock_zapi: Z-API send_message mockado
- mock_supabase: Cliente Supabase mockado
- mock_database: Modulo database completo mockado
- sample payloads para webhooks
- clean_debounce_state: limpa estado de debounce entre testes
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# ── Garante imports de src.* ─────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Modo de teste: delays curtos, sem chamadas externas ──────────────────────
os.environ["TEST_MODE"] = "true"
os.environ["SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_KEY"] = "test-key-not-real"
os.environ["OPENROUTER_API_KEY"] = "test-key-not-real"
os.environ["ZAPI_INSTANCE_ID"] = ""
os.environ["ZAPI_TOKEN"] = ""
os.environ["ZAPI_CLIENT_TOKEN"] = ""
os.environ["HUBSPOT_ACCESS_TOKEN"] = ""
os.environ["HUBSPOT_ENABLED"] = "false"
os.environ["SUPERVISOR_PHONE"] = ""
os.environ["API_SECRET_TOKEN"] = "test-secret-token"
os.environ["RESPONSE_DELAY_SECONDS"] = "1"


# ── Flask App ────────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    """Flask app configurada para testes."""
    # Mock database e servicos externos ANTES de importar app
    with patch("src.core.database.client._get_client", return_value=MagicMock()), \
         patch("src.core.database.save_message", return_value=True), \
         patch("src.core.database.load_conversation_history", return_value=[]), \
         patch("src.core.database.load_messages_legacy", return_value=[]), \
         patch("src.core.database.create_session", return_value="test-session-uuid"), \
         patch("src.core.database.save_raw_incoming", return_value=True), \
         patch("src.core.database.upsert_lead", return_value=True), \
         patch("src.core.database.save_lead_metadata", return_value=True), \
         patch("src.core.database.update_lead_status", return_value=True), \
         patch("src.core.database.save_escalation", return_value=True), \
         patch("src.core.database.resolve_escalation_record", return_value=True), \
         patch("src.core.database.update_session_status", return_value=True), \
         patch("src.core.database.get_connection_status", return_value={"enabled": False}), \
         patch("src.core.database.health_check", return_value={"enabled": False, "connected": False}), \
         patch("src.core.whatsapp.send_message", return_value=True), \
         patch("src.core.llm.client"):
        from src.app import create_app
        application = create_app()
        application.config["TESTING"] = True
        yield application


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


# ── Mocks de Servicos ────────────────────────────────────────────────────────

@pytest.fixture
def mock_claude(mocker):
    """Mock da API LLM (via OpenRouter) com respostas deterministicas."""
    mock = mocker.patch("src.core.llm.client.chat.completions.create")

    # Shape OpenAI-compatible: response.choices[0].message.content + response.usage
    message = type("Message", (), {"content": "Resposta padrao do agente para testes."})()
    choice = type("Choice", (), {"message": message})()
    usage = type("Usage", (), {
        "prompt_tokens": 100,
        "completion_tokens": 50,
    })()
    response = type("Response", (), {"choices": [choice], "usage": usage})()
    mock.return_value = response
    return mock


@pytest.fixture
def mock_zapi(mocker):
    """Mock do Z-API send_message."""
    return mocker.patch("src.core.whatsapp.send_message", return_value=True)


@pytest.fixture
def mock_supabase(mocker):
    """Mock do cliente Supabase singleton."""
    mock_client = MagicMock()
    mocker.patch("src.core.database.client._get_client", return_value=mock_client)
    return mock_client


@pytest.fixture
def mock_database(mocker):
    """Mock completo do modulo src.core.database."""
    mocks = {
        "save_message": mocker.patch("src.core.database.save_message", return_value=True),
        "load_conversation_history": mocker.patch("src.core.database.load_conversation_history", return_value=[]),
        "load_messages_legacy": mocker.patch("src.core.database.load_messages_legacy", return_value=[]),
        "create_session": mocker.patch("src.core.database.create_session", return_value="test-session-uuid"),
        "save_raw_incoming": mocker.patch("src.core.database.save_raw_incoming", return_value=True),
        "upsert_lead": mocker.patch("src.core.database.upsert_lead", return_value=True),
        "save_lead_metadata": mocker.patch("src.core.database.save_lead_metadata", return_value=True),
        "update_lead_status": mocker.patch("src.core.database.update_lead_status", return_value=True),
        "save_escalation": mocker.patch("src.core.database.save_escalation", return_value=True),
        "resolve_escalation_record": mocker.patch("src.core.database.resolve_escalation_record", return_value=True),
        "update_session_status": mocker.patch("src.core.database.update_session_status", return_value=True),
    }
    return mocks


# ── Debounce State Cleanup ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_debounce_state():
    """Limpa estado de debounce antes e depois de cada teste."""
    # Limpa antes do teste
    try:
        from src.api.webhooks import _zapi_state, _zapi_lock
        import threading
        with _zapi_lock:
            _zapi_state.clear()
    except ImportError:
        pass

    try:
        from src.api.chat import _chat_state, _chat_lock
        with _chat_lock:
            _chat_state.clear()
    except ImportError:
        pass

    yield

    # Limpa depois do teste
    try:
        from src.api.webhooks import _zapi_state, _zapi_lock
        with _zapi_lock:
            _zapi_state.clear()
    except ImportError:
        pass

    try:
        from src.api.chat import _chat_state, _chat_lock
        with _chat_lock:
            _chat_state.clear()
    except ImportError:
        pass


# ── Sample Payloads ──────────────────────────────────────────────────────────

@pytest.fixture
def sample_zapi_payload():
    """Payload tipico de webhook Z-API."""
    return {
        "type": "ReceivedCallback",
        "fromMe": False,
        "phone": "5511999999999",
        "body": "Quero saber mais sobre o curso R1",
    }


@pytest.fixture
def sample_form_payload():
    """Payload tipico de webhook do Quill Forms."""
    return {
        "name": "Joao Silva",
        "phone": "11999999999",
    }
