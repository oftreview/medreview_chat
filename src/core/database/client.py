"""
Connection singleton + health check + is_enabled.
Manages Supabase client initialization and connection status.
"""
import uuid
import time
from src.config import SUPABASE_URL, SUPABASE_KEY

_client = None
_connection_error = None


def _get_client():
    """Inicializa o cliente Supabase (lazy, singleton)."""
    global _client, _connection_error
    if _client is not None:
        return _client

    if not SUPABASE_URL or not SUPABASE_KEY:
        _connection_error = "SUPABASE_URL ou SUPABASE_KEY não configurados"
        return None

    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        _connection_error = None
        print("[DB] Supabase conectado.", flush=True)
    except Exception as e:
        _connection_error = str(e)
        print(f"[DB ERROR] Falha ao conectar Supabase: {e}", flush=True)
        _client = None

    return _client


def get_connection_status() -> dict:
    """Retorna status da conexão para health checks."""
    return {
        "enabled": is_enabled(),
        "connected": _client is not None,
        "error": _connection_error,
    }


def is_enabled() -> bool:
    """Retorna True se o Supabase está configurado."""
    return bool(SUPABASE_URL and SUPABASE_KEY)


def health_check() -> dict:
    """
    Testa conexão real com o Supabase: leitura + escrita + delete.
    Retorna dict com status detalhado.
    """
    result = {
        "enabled": is_enabled(),
        "connected": False,
        "read": False,
        "write": False,
        "delete": False,
        "error": None,
        "latency_ms": None,
    }

    if not is_enabled():
        result["error"] = "SUPABASE_URL ou SUPABASE_KEY não configurados"
        return result

    db = _get_client()
    if db is None:
        result["error"] = _connection_error or "Cliente não inicializado"
        return result

    start = time.time()

    # Teste de escrita
    test_id = f"_healthcheck_{uuid.uuid4().hex[:8]}"
    try:
        db.table("conversations").insert({
            "user_id": test_id,
            "role": "system",
            "content": "health_check_probe",
            "message_type": "system",
            "channel": "healthcheck",
        }).execute()
        result["write"] = True
    except Exception as e:
        result["error"] = f"Write failed: {e}"
        result["latency_ms"] = round((time.time() - start) * 1000)
        return result

    # Teste de leitura
    try:
        read_result = (
            db.table("conversations")
            .select("user_id")
            .eq("user_id", test_id)
            .limit(1)
            .execute()
        )
        result["read"] = len(read_result.data or []) > 0
    except Exception as e:
        result["error"] = f"Read failed: {e}"

    # Cleanup — remove o registro de teste
    try:
        db.table("conversations").delete().eq("user_id", test_id).execute()
        result["delete"] = True
    except Exception as e:
        result["error"] = f"Delete failed: {e}"

    result["connected"] = result["read"] and result["write"]
    result["latency_ms"] = round((time.time() - start) * 1000)

    return result
