"""
src/core/async_bridge.py — Bridge entre gevent (sync) e asyncio (async).

Resolve o conflito "Cannot run the event loop while another loop is running"
que ocorre quando múltiplas sessões tentam criar event loops asyncio
simultaneamente em ambiente gevent.

SOLUÇÃO: Uma única thread permanente com seu próprio event loop asyncio.
Todas as operações async são submetidas para essa thread via run_async().

PRINCÍPIOS:
- Thread-safe: múltiplas goroutines/threads podem chamar run_async() ao mesmo tempo
- Nunca bloqueia indefinidamente: timeout configurável
- Nunca propaga exceções fatais: caller recebe None ou a exceção original
- Lazy init: thread só é criada na primeira chamada

USO:
    from src.core.async_bridge import run_async

    # Em qualquer lugar que precise rodar código async:
    result = run_async(my_coroutine(), timeout=5.0)
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Optional
from concurrent.futures import Future


# ── Worker Thread ──────────────────────────────────────────────────────────

_loop: Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread] = None
_lock = threading.Lock()


def _start_worker():
    """Inicia a thread worker com event loop dedicado (lazy, thread-safe)."""
    global _loop, _thread

    if _thread is not None and _thread.is_alive():
        return

    with _lock:
        # Double-check após adquirir lock
        if _thread is not None and _thread.is_alive():
            return

        _loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        _thread = threading.Thread(
            target=_run_loop,
            daemon=True,
            name="async-bridge-worker",
        )
        _thread.start()
        print("[ASYNC BRIDGE] Worker thread iniciada", flush=True)


def run_async(coro, timeout: float = 10.0) -> Any:
    """
    Executa uma coroutine no event loop dedicado e retorna o resultado.

    Thread-safe: pode ser chamada de múltiplas threads/greenlets ao mesmo tempo.
    Cada chamada é independente e não interfere nas outras.

    Args:
        coro: Coroutine a executar (ex: wm.observations.retrieve(...))
        timeout: Timeout máximo em segundos (default: 10s)

    Returns:
        O resultado da coroutine.

    Raises:
        A mesma exceção que a coroutine levantaria.
        TimeoutError se exceder o timeout.
    """
    _start_worker()

    if _loop is None or _loop.is_closed():
        raise RuntimeError("Async bridge event loop não disponível")

    # Submete a coroutine para o event loop da worker thread.
    # asyncio.run_coroutine_threadsafe é thread-safe por design.
    future = asyncio.run_coroutine_threadsafe(coro, _loop)

    try:
        return future.result(timeout=timeout)
    except Exception:
        # Cancela a coroutine se ainda estiver rodando
        future.cancel()
        raise


def is_alive() -> bool:
    """Verifica se a worker thread está ativa."""
    return _thread is not None and _thread.is_alive()


def get_status() -> dict:
    """Retorna status da bridge para health checks."""
    return {
        "alive": is_alive(),
        "loop_running": _loop is not None and _loop.is_running() if _loop else False,
    }
