"""
src/core/wild_memory_context.py — Wild Memory Context Injection (Fase 3).

Recupera observations relevantes do Wild Memory e constrói um briefing
para injetar no system prompt do agente. Preserva o prompt cache da
Anthropic usando blocos de sistema separados.

PRINCÍPIOS DE SEGURANÇA:
- Nunca lança exceção pro caller (tudo wrapped em try/except)
- Timeout de 5s para retrieval (não atrasa a resposta)
- Se Wild Memory não está disponível, retorna None
- Controlado pela env var WILD_MEMORY_CONTEXT=true
- Métricas de latência e hit/miss para monitoramento

USO:
    from src.core.wild_memory_context import context_injector
    briefing = context_injector.get_context(session_id, user_message)
    # briefing é uma string formatada ou None
"""

from __future__ import annotations

import os
import time
import threading
from typing import Optional


# ── Config ──────────────────────────────────────────────────────────────────

def _is_context_enabled() -> bool:
    """Check if context injection is enabled via env var."""
    return os.getenv("WILD_MEMORY_CONTEXT", "").lower() in ("true", "1", "yes")


RETRIEVAL_TIMEOUT_SECONDS = 5.0
MAX_OBSERVATIONS = 8


# ── Metrics ─────────────────────────────────────────────────────────────────

class ContextMetrics:
    """Thread-safe metrics para monitoramento do context injection."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_requests: int = 0
        self.total_hits: int = 0          # briefing com observations
        self.total_misses: int = 0        # sem observations (lead novo)
        self.total_errors: int = 0
        self.total_timeouts: int = 0
        self.last_error: Optional[str] = None
        self.avg_retrieval_ms: float = 0.0
        self._retrieval_times: list[float] = []

    def record_hit(self, duration_ms: float, obs_count: int):
        with self._lock:
            self.total_requests += 1
            self.total_hits += 1
            self._record_time(duration_ms)

    def record_miss(self, duration_ms: float):
        with self._lock:
            self.total_requests += 1
            self.total_misses += 1
            self._record_time(duration_ms)

    def record_error(self, error: str):
        with self._lock:
            self.total_requests += 1
            self.total_errors += 1
            self.last_error = error

    def record_timeout(self):
        with self._lock:
            self.total_requests += 1
            self.total_timeouts += 1

    def _record_time(self, duration_ms: float):
        self._retrieval_times.append(duration_ms)
        if len(self._retrieval_times) > 100:
            self._retrieval_times = self._retrieval_times[-100:]
        self.avg_retrieval_ms = sum(self._retrieval_times) / len(self._retrieval_times)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "total_requests": self.total_requests,
                "total_hits": self.total_hits,
                "total_misses": self.total_misses,
                "total_errors": self.total_errors,
                "total_timeouts": self.total_timeouts,
                "last_error": self.last_error,
                "avg_retrieval_ms": round(self.avg_retrieval_ms, 1),
            }


# ── Context Injector ────────────────────────────────────────────────────────

class WildMemoryContextInjector:
    """
    Recupera observations do Wild Memory e constrói briefing.

    NUNCA afeta o fluxo principal se falhar:
    - get_context() retorna None em caso de erro
    - Timeout de 5s para retrieval
    - Métricas de latência para monitoramento
    """

    def __init__(self):
        self._wild_memory = None
        self._init_attempted: bool = False
        self._enabled: bool = False
        self.metrics = ContextMetrics()

    def _lazy_init(self) -> bool:
        """Inicializa Wild Memory na primeira chamada."""
        if self._init_attempted:
            return self._wild_memory is not None

        self._init_attempted = True

        if not _is_context_enabled():
            print("[WILD CONTEXT] Desabilitado (WILD_MEMORY_CONTEXT != true)", flush=True)
            return False

        try:
            from wild_memory.init_medreview import get_wild_memory, get_status
            self._wild_memory = get_wild_memory()

            if self._wild_memory is None:
                status = get_status()
                print(
                    f"[WILD CONTEXT] Wild Memory não disponível: {status.get('error', 'unknown')}",
                    flush=True,
                )
                return False

            self._enabled = True
            print("[WILD CONTEXT] Context injection ATIVO", flush=True)
            return True

        except Exception as e:
            print(f"[WILD CONTEXT] Erro na inicialização: {e}", flush=True)
            self.metrics.record_error(f"init: {e}")
            return False

    def get_context(
        self,
        session_id: str,
        user_message: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Recupera contexto de memória para a sessão atual.

        Returns:
            String com briefing formatado, ou None se indisponível.
            NUNCA lança exceção. Timeout de 5s.
        """
        try:
            if not self._lazy_init():
                return None

            effective_user_id = user_id or session_id
            start = time.time()

            # Run retrieval with timeout
            result = [None]
            error = [None]

            def _retrieve():
                try:
                    result[0] = self._build_briefing(
                        effective_user_id, user_message
                    )
                except Exception as e:
                    error[0] = e

            t = threading.Thread(target=_retrieve, daemon=True)
            t.start()
            t.join(timeout=RETRIEVAL_TIMEOUT_SECONDS)

            duration_ms = (time.time() - start) * 1000

            if t.is_alive():
                # Timeout — don't wait
                self.metrics.record_timeout()
                print(
                    f"[WILD CONTEXT] Timeout ({RETRIEVAL_TIMEOUT_SECONDS}s) "
                    f"session={session_id[:8]}...",
                    flush=True,
                )
                return None

            if error[0]:
                self.metrics.record_error(f"retrieve: {error[0]}")
                print(
                    f"[WILD CONTEXT] Erro no retrieval: {error[0]}",
                    flush=True,
                )
                return None

            briefing = result[0]
            if briefing:
                obs_count = briefing.count("[obs:")
                self.metrics.record_hit(duration_ms, obs_count)
                print(
                    f"[WILD CONTEXT] HIT session={session_id[:8]}... "
                    f"obs={obs_count} time={duration_ms:.0f}ms",
                    flush=True,
                )
            else:
                self.metrics.record_miss(duration_ms)
                print(
                    f"[WILD CONTEXT] MISS session={session_id[:8]}... "
                    f"(lead novo, sem observations) time={duration_ms:.0f}ms",
                    flush=True,
                )

            return briefing

        except Exception as e:
            self.metrics.record_error(f"get_context: {e}")
            print(f"[WILD CONTEXT] Erro em get_context(): {e}", flush=True)
            return None

    def _build_briefing(
        self,
        user_id: str,
        user_message: str,
    ) -> Optional[str]:
        """
        Constrói briefing usando retrieval do Wild Memory.
        Roda em thread separada (chamada por get_context).
        """
        import asyncio

        wm = self._wild_memory
        if wm is None:
            return None

        async def _async_retrieve():
            # Extract entities from the current message
            ner_entities = wm.ner.extract(user_message)
            entity_ids = wm.ner.to_entity_ids(ner_entities)

            # Generate embedding for semantic search
            msg_emb = wm.embedding_cache.embed(user_message)

            # Retrieve relevant observations (5-signal combined score)
            observations = await wm.observations.retrieve(
                agent_id="closi-sales",
                user_id=user_id,
                goal=user_message,  # Use message as goal for retrieval
                entities=entity_ids,
                search_query=user_message,
                limit=MAX_OBSERVATIONS,
                min_decay=0.3,
            )

            if not observations:
                return None

            # Build structured briefing (zero LLM, template-based)
            briefing_text, used_ids = wm.briefing_builder.build(
                observations=observations,
            )

            # Wrap in Portuguese context for the agent
            return (
                f"# MEMÓRIA DO LEAD (Wild Memory)\n"
                f"As informações abaixo foram coletadas em conversas anteriores "
                f"com este lead. Use para manter continuidade e NÃO repetir "
                f"informações já fornecidas.\n\n"
                f"{briefing_text}\n\n"
                f"IMPORTANTE: Se alguma informação do briefing já foi mencionada "
                f"nesta conversa, NÃO repita. Apenas referencie se o lead perguntar."
            )

        # Run async in new loop (safe from gevent conflicts)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_async_retrieve())
        except RuntimeError:
            # Event loop conflict — try ThreadPoolExecutor
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._run_in_loop, _async_retrieve)
                return future.result(timeout=RETRIEVAL_TIMEOUT_SECONDS)
        finally:
            try:
                loop.close()
            except Exception:
                pass

    @staticmethod
    def _run_in_loop(coro_fn):
        """Run async coroutine in a brand new event loop."""
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro_fn())
        finally:
            loop.close()

    def get_status(self) -> dict:
        """Retorna status completo do context injection para health check."""
        return {
            "enabled": _is_context_enabled(),
            "initialized": self._init_attempted,
            "active": self._enabled,
            "metrics": self.metrics.to_dict(),
        }


# ── Singleton global ────────────────────────────────────────────────────────
context_injector = WildMemoryContextInjector()
