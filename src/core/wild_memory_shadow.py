"""
src/core/wild_memory_shadow.py — Wild Memory Shadow Mode (Fase 2).

Observa mensagens do agente SEM alterar respostas.
Roda distilação e NER em background (fire-and-forget).
Controlado pela env var WILD_MEMORY_SHADOW=true.

PRINCÍPIOS DE SEGURANÇA:
- Nunca lança exceção pro caller (tudo wrapped em try/except)
- Nunca bloqueia a thread principal
- Nunca altera o fluxo de resposta do agente
- Se Wild Memory não está disponível, simplesmente desliga
- Métricas de observação pra gente monitorar sem afetar produção

USO:
    from src.core.wild_memory_shadow import shadow
    shadow.observe(session_id, user_message, assistant_response)
"""

from __future__ import annotations

import os
import time
import threading
from typing import Optional


# ── Config ──────────────────────────────────────────────────────────────────

def _is_shadow_enabled() -> bool:
    """Check if shadow mode is enabled via env var."""
    return os.getenv("WILD_MEMORY_SHADOW", "").lower() in ("true", "1", "yes")


# ── Metrics ─────────────────────────────────────────────────────────────────

class ShadowMetrics:
    """Thread-safe metrics para monitoramento do shadow mode."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_observed: int = 0
        self.total_distilled: int = 0
        self.total_skipped: int = 0
        self.total_errors: int = 0
        self.last_error: Optional[str] = None
        self.last_observation_at: Optional[float] = None
        self.last_distillation_at: Optional[float] = None
        self.avg_distill_ms: float = 0.0
        self._distill_times: list[float] = []

    def record_observation(self):
        with self._lock:
            self.total_observed += 1
            self.last_observation_at = time.time()

    def record_distillation(self, duration_ms: float):
        with self._lock:
            self.total_distilled += 1
            self.last_distillation_at = time.time()
            self._distill_times.append(duration_ms)
            # Keep only last 100 for avg
            if len(self._distill_times) > 100:
                self._distill_times = self._distill_times[-100:]
            self.avg_distill_ms = sum(self._distill_times) / len(self._distill_times)

    def record_skip(self):
        with self._lock:
            self.total_skipped += 1

    def record_error(self, error: str):
        with self._lock:
            self.total_errors += 1
            self.last_error = error

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "total_observed": self.total_observed,
                "total_distilled": self.total_distilled,
                "total_skipped": self.total_skipped,
                "total_errors": self.total_errors,
                "last_error": self.last_error,
                "last_observation_at": self.last_observation_at,
                "last_distillation_at": self.last_distillation_at,
                "avg_distill_ms": round(self.avg_distill_ms, 1),
            }


# ── Shadow Observer ─────────────────────────────────────────────────────────

class WildMemoryShadow:
    """
    Shadow observer — captura mensagens e roda Wild Memory em background.

    NUNCA afeta o fluxo principal:
    - observe() retorna imediatamente
    - Processamento é feito em thread daemon
    - Erros são apenas logados (nunca propagados)
    """

    def __init__(self):
        self._wild_memory = None
        self._init_attempted: bool = False
        self._enabled: bool = False
        self.metrics = ShadowMetrics()
        self._ner = None

    def _lazy_init(self) -> bool:
        """
        Inicializa Wild Memory na primeira chamada.
        Retorna True se disponível.
        """
        if self._init_attempted:
            return self._wild_memory is not None

        self._init_attempted = True

        if not _is_shadow_enabled():
            print("[WILD SHADOW] Desabilitado (WILD_MEMORY_SHADOW != true)", flush=True)
            return False

        try:
            from wild_memory.init_medreview import get_wild_memory, get_status
            self._wild_memory = get_wild_memory()

            if self._wild_memory is None:
                status = get_status()
                print(
                    f"[WILD SHADOW] Wild Memory não disponível: {status.get('error', 'unknown')}",
                    flush=True,
                )
                return False

            # Grab NER for entity extraction metrics
            self._ner = self._wild_memory.ner
            self._enabled = True
            print("[WILD SHADOW] Shadow mode ATIVO — observando mensagens", flush=True)
            return True

        except Exception as e:
            print(f"[WILD SHADOW] Erro na inicialização: {e}", flush=True)
            self.metrics.record_error(f"init: {e}")
            return False

    def observe(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        user_id: Optional[str] = None,
    ):
        """
        Observa um par mensagem/resposta em background.
        RETORNA IMEDIATAMENTE — nunca bloqueia o caller.
        """
        try:
            if not self._lazy_init():
                return

            self.metrics.record_observation()

            # Fire-and-forget em thread daemon
            t = threading.Thread(
                target=self._process_observation,
                args=(session_id, user_message, assistant_response, user_id),
                daemon=True,
                name=f"wild-shadow-{session_id[:8]}",
            )
            t.start()

        except Exception as e:
            # NUNCA propaga exceção para o agente
            self.metrics.record_error(f"observe: {e}")
            print(f"[WILD SHADOW] Erro em observe(): {e}", flush=True)

    def _process_observation(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        user_id: Optional[str],
    ):
        """
        Processa observação em background thread.
        Roda: gate check → NER → distillation.
        """
        start = time.time()
        effective_user_id = user_id or session_id

        try:
            wm = self._wild_memory
            if wm is None:
                return

            # ── Step 1: Distillation Gate (deve destilar?) ──
            should_distill = wm.distill_gate.should_distill(
                user_message, assistant_response
            )

            if not should_distill:
                self.metrics.record_skip()
                print(
                    f"[WILD SHADOW] Gate: SKIP session={session_id[:8]}... "
                    f"(msg muito curta ou trivial)",
                    flush=True,
                )
                return

            # ── Step 2: NER extraction (para métricas) ──
            entities = []
            if self._ner:
                try:
                    entities = self._ner.extract(user_message + " " + assistant_response)
                except Exception:
                    pass

            # ── Step 3: Distillation (async → sync bridge) ──
            import asyncio

            async def _distill():
                await wm.distiller.distill_and_save(
                    agent_id="closi-sales",
                    user_id=effective_user_id,
                    conversation=[
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": assistant_response},
                    ],
                    session_id=session_id,
                    conflict_resolver=wm.conflict_resolver,
                )

            # Run async distillation in a new event loop
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_distill())
            finally:
                loop.close()

            duration_ms = (time.time() - start) * 1000
            self.metrics.record_distillation(duration_ms)

            entity_summary = ", ".join(e.get("text", str(e)) if isinstance(e, dict) else str(e) for e in entities[:5])
            print(
                f"[WILD SHADOW] Distilled session={session_id[:8]}... "
                f"entities=[{entity_summary}] "
                f"time={duration_ms:.0f}ms",
                flush=True,
            )

        except Exception as e:
            self.metrics.record_error(f"process: {e}")
            print(f"[WILD SHADOW] Erro no processamento: {e}", flush=True)

    def get_status(self) -> dict:
        """Retorna status completo do shadow mode para health check."""
        return {
            "enabled": _is_shadow_enabled(),
            "initialized": self._init_attempted,
            "active": self._enabled,
            "wild_memory_available": self._wild_memory is not None,
            "metrics": self.metrics.to_dict(),
        }


# ── Singleton global ────────────────────────────────────────────────────────
shadow = WildMemoryShadow()
