"""
src/core/wild_memory_lifecycle.py — Wild Memory Lifecycle Hooks (Fase 4).

Gerencia eventos do ciclo de vida das conversas:
- Escalação → registra feedback signal + distilação completa
- Reset/fim de sessão → distilação completa antes de limpar
- TTL expirado → distilação de sessões que expiraram
- Manutenção diária → decay, stale marking, cache cleanup

PRINCÍPIOS DE SEGURANÇA:
- Nunca lança exceção pro caller (tudo wrapped em try/except)
- Nunca bloqueia a thread principal (fire-and-forget)
- Se Wild Memory não está disponível, retorna silenciosamente
- Controlado pela env var WILD_MEMORY_SHADOW=true (mesmo da Fase 2)

USO:
    from src.core.wild_memory_lifecycle import lifecycle
    lifecycle.on_escalation(session_id, user_id, metadata)
    lifecycle.on_session_end(session_id, user_id, reason="reset")
    lifecycle.run_daily_maintenance()
"""

from __future__ import annotations

import os
import time
import threading
from typing import Optional


# ── Config ──────────────────────────────────────────────────────────────────

def _is_enabled() -> bool:
    """Lifecycle hooks are enabled when shadow mode is enabled."""
    return os.getenv("WILD_MEMORY_SHADOW", "").lower() in ("true", "1", "yes")


# ── Metrics ─────────────────────────────────────────────────────────────────

class LifecycleMetrics:
    """Thread-safe metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_escalations: int = 0
        self.total_session_ends: int = 0
        self.total_maintenance_runs: int = 0
        self.total_errors: int = 0
        self.last_error: Optional[str] = None
        self.last_maintenance_at: Optional[float] = None

    def record_escalation(self):
        with self._lock:
            self.total_escalations += 1

    def record_session_end(self):
        with self._lock:
            self.total_session_ends += 1

    def record_maintenance(self):
        with self._lock:
            self.total_maintenance_runs += 1
            self.last_maintenance_at = time.time()

    def record_error(self, error: str):
        with self._lock:
            self.total_errors += 1
            self.last_error = error

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "total_escalations": self.total_escalations,
                "total_session_ends": self.total_session_ends,
                "total_maintenance_runs": self.total_maintenance_runs,
                "total_errors": self.total_errors,
                "last_error": self.last_error,
                "last_maintenance_at": self.last_maintenance_at,
            }


# ── Lifecycle Manager ───────────────────────────────────────────────────────

class WildMemoryLifecycle:
    """
    Gerencia eventos de lifecycle das conversas no Wild Memory.

    Eventos:
    - on_escalation: lead foi escalado → feedback signal + full distillation
    - on_session_end: sessão terminou → full distillation
    - run_daily_maintenance: cron diário → decay + stale + cleanup
    """

    def __init__(self):
        self._wild_memory = None
        self._init_attempted: bool = False
        self._enabled: bool = False
        self.metrics = LifecycleMetrics()

    def _lazy_init(self) -> bool:
        """Inicializa Wild Memory na primeira chamada."""
        if self._init_attempted:
            return self._wild_memory is not None

        self._init_attempted = True

        if not _is_enabled():
            return False

        try:
            from wild_memory.init_medreview import get_wild_memory
            self._wild_memory = get_wild_memory()
            if self._wild_memory is not None:
                self._enabled = True
                print("[WILD LIFECYCLE] Lifecycle hooks ATIVOS", flush=True)
            return self._wild_memory is not None
        except Exception as e:
            self.metrics.record_error(f"init: {e}")
            return False

    # ── Event Hooks ─────────────────────────────────────────────────────────

    def on_escalation(
        self,
        session_id: str,
        user_id: str,
        metadata: Optional[dict] = None,
    ):
        """
        Lead foi escalado para humano.
        Registra feedback signal + dispara distilação completa em background.
        """
        try:
            if not self._lazy_init():
                return

            self.metrics.record_escalation()

            t = threading.Thread(
                target=self._process_escalation,
                args=(session_id, user_id, metadata),
                daemon=True,
                name=f"wild-escalation-{session_id[:8]}",
            )
            t.start()

        except Exception as e:
            self.metrics.record_error(f"on_escalation: {e}")
            print(f"[WILD LIFECYCLE] Erro em on_escalation(): {e}", flush=True)

    def on_session_end(
        self,
        session_id: str,
        user_id: str,
        reason: str = "reset",
        messages: Optional[list] = None,
    ):
        """
        Sessão terminou (reset, TTL, ou fim natural).
        Dispara distilação completa em background.
        """
        try:
            if not self._lazy_init():
                return

            self.metrics.record_session_end()

            t = threading.Thread(
                target=self._process_session_end,
                args=(session_id, user_id, reason, messages),
                daemon=True,
                name=f"wild-session-end-{session_id[:8]}",
            )
            t.start()

        except Exception as e:
            self.metrics.record_error(f"on_session_end: {e}")
            print(f"[WILD LIFECYCLE] Erro em on_session_end(): {e}", flush=True)

    def run_daily_maintenance(self) -> dict:
        """
        Manutenção diária síncrona (chamada via endpoint /api/wild-memory/cron).
        Roda: decay → stale marking → cache cleanup → session cleanup.
        Returns dict com resultados.
        """
        results = {
            "status": "skipped",
            "decay_affected": 0,
            "stale_marked": 0,
            "cache_cleaned": False,
        }

        try:
            if not self._lazy_init():
                results["status"] = "disabled"
                return results

            import asyncio
            wm = self._wild_memory

            async def _maintenance():
                r = {}
                # 1. Ant Decay: reduz decay_score de todas observations ativas
                try:
                    decay_result = wm.db.rpc("apply_daily_decay", {
                        "decay_rate": wm.config.decay.daily_rate
                    }).execute()
                    r["decay_affected"] = decay_result.data if decay_result.data else 0
                except Exception as e:
                    r["decay_error"] = str(e)

                # 2. Mark stale: marca observations com decay < threshold
                try:
                    stale_result = wm.db.rpc("mark_stale_observations", {
                        "decay_threshold": wm.config.decay.stale_threshold
                    }).execute()
                    r["stale_marked"] = stale_result.data if stale_result.data else 0
                except Exception as e:
                    r["stale_error"] = str(e)

                # 3. Cache cleanup: remove semantic cache entries expiradas
                try:
                    await wm.semantic_cache.cleanup_expired()
                    r["cache_cleaned"] = True
                except Exception as e:
                    r["cache_error"] = str(e)

                # 4. Session log cleanup: remove session logs expirados
                try:
                    await wm.session_logger.cleanup_expired()
                    r["sessions_cleaned"] = True
                except Exception as e:
                    r["sessions_error"] = str(e)

                return r

            # Run in new loop (safe from gevent)
            loop = asyncio.new_event_loop()
            try:
                r = loop.run_until_complete(_maintenance())
            except RuntimeError:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    r = pool.submit(self._run_in_loop, _maintenance).result(timeout=60)
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

            results.update(r)
            results["status"] = "ok"
            self.metrics.record_maintenance()

            print(
                f"[WILD LIFECYCLE] Manutenção diária: decay={r.get('decay_affected', 0)} "
                f"stale={r.get('stale_marked', 0)} cache={r.get('cache_cleaned', False)}",
                flush=True,
            )

        except Exception as e:
            results["status"] = "error"
            results["error"] = str(e)
            self.metrics.record_error(f"maintenance: {e}")
            print(f"[WILD LIFECYCLE] Erro na manutenção: {e}", flush=True)

        return results

    # ── Internal Processing ─────────────────────────────────────────────────

    def _process_escalation(
        self, session_id: str, user_id: str, metadata: Optional[dict]
    ):
        """Processa escalação em background."""
        try:
            import asyncio
            wm = self._wild_memory
            if wm is None:
                return

            async def _record():
                # 1. Record feedback signal
                motivo = (metadata or {}).get("motivo_escalacao", "nao_especificado")
                stage = (metadata or {}).get("stage", "desconhecido")

                await self._save_feedback_signal(
                    wm, session_id, user_id,
                    signal_type="handoff_request",
                    reward_score=-0.3,  # Escalação é sinal negativo (lead não converteu)
                    action_taken=f"escalation:{motivo}",
                    context={"stage": stage, "motivo": motivo},
                )

                # 2. End session in Wild Memory (full distillation + reflection)
                try:
                    await wm.end_session("closi-sales", user_id, session_id)
                except Exception as e:
                    # end_session pode falhar se session não existe no WM
                    print(f"[WILD LIFECYCLE] end_session warning: {e}", flush=True)

            self._run_in_new_loop(lambda: _record())

            print(
                f"[WILD LIFECYCLE] Escalação processada session={session_id[:8]}... "
                f"user={user_id[:8]}...",
                flush=True,
            )

        except Exception as e:
            self.metrics.record_error(f"process_escalation: {e}")
            print(f"[WILD LIFECYCLE] Erro processando escalação: {e}", flush=True)

    def _process_session_end(
        self, session_id: str, user_id: str,
        reason: str, messages: Optional[list]
    ):
        """Processa fim de sessão em background."""
        try:
            import asyncio
            wm = self._wild_memory
            if wm is None:
                return

            async def _end():
                # Record feedback signal based on reason
                signal_map = {
                    "reset": ("task_completion", 0.0),
                    "ttl_expired": ("abandonment", -0.1),
                    "escalated": ("handoff_request", -0.3),
                    "completed": ("task_completion", 0.5),
                }
                signal_type, reward = signal_map.get(reason, ("task_completion", 0.0))

                await self._save_feedback_signal(
                    wm, session_id, user_id,
                    signal_type=signal_type,
                    reward_score=reward,
                    action_taken=f"session_end:{reason}",
                    context={"reason": reason},
                )

                # Full distillation of remaining messages
                if messages and len(messages) >= 2:
                    try:
                        await wm.distiller.distill_and_save(
                            agent_id="closi-sales",
                            user_id=user_id,
                            conversation=messages[-10:],  # Last 10 messages
                            session_id=session_id,
                            conflict_resolver=wm.conflict_resolver,
                            flush_mode=True,
                        )
                    except Exception as e:
                        print(f"[WILD LIFECYCLE] Distillation warning: {e}", flush=True)

            self._run_in_new_loop(lambda: _end())

            print(
                f"[WILD LIFECYCLE] Session end processado session={session_id[:8]}... "
                f"reason={reason}",
                flush=True,
            )

        except Exception as e:
            self.metrics.record_error(f"process_session_end: {e}")
            print(f"[WILD LIFECYCLE] Erro processando session end: {e}", flush=True)

    async def _save_feedback_signal(
        self, wm, session_id, user_id,
        signal_type, reward_score, action_taken, context
    ):
        """Salva feedback signal no Supabase."""
        try:
            wm.db.table("feedback_signals").insert({
                "agent_id": "closi-sales",
                "user_id": user_id,
                "session_id": session_id,
                "signal_type": signal_type,
                "reward_score": reward_score,
                "action_taken": action_taken,
                "context_snapshot": context,
                "source": "system",
            }).execute()
        except Exception as e:
            print(f"[WILD LIFECYCLE] Feedback signal error: {e}", flush=True)

    @staticmethod
    def _run_in_new_loop(fn):
        """Run async function in a new event loop."""
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(fn())
        finally:
            loop.close()

    @staticmethod
    def _run_in_loop(coro_fn):
        """Run async coroutine in a brand new event loop (for ThreadPoolExecutor)."""
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro_fn())
        finally:
            loop.close()

    def get_status(self) -> dict:
        """Retorna status do lifecycle manager."""
        return {
            "enabled": _is_enabled(),
            "active": self._enabled,
            "metrics": self.metrics.to_dict(),
        }


# ── Singleton global ────────────────────────────────────────────────────────
lifecycle = WildMemoryLifecycle()
