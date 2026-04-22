"""
core/llm.py — Interface com a API de LLM via OpenRouter.

Usa o SDK `openai` apontando para o endpoint OpenAI-compatible do OpenRouter,
permitindo roteamento para múltiplos modelos (Anthropic, OpenAI, Google, etc.)
através de uma única API key.

Implementa:
  - Retry com backoff exponencial para resiliência contra erros transitórios.
  - Registro de métricas (input/output tokens) por chamada.
"""

import time
from openai import OpenAI, APIError, APITimeoutError, RateLimitError
from src.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_SITE_URL,
    OPENROUTER_APP_NAME,
    MAX_TOKENS,
)
from src.core.logger import log_chat

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    timeout=30.0,
    default_headers={
        "HTTP-Referer": OPENROUTER_SITE_URL,
        "X-Title": OPENROUTER_APP_NAME,
    },
)

# ── Configuração de retry ────────────────────────────────────────────────────

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0          # segundos — delay inicial (dobra a cada tentativa)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


def call_claude(system_prompt: str, messages: list, memory_context: str = None) -> str:
    """
    Chama o LLM via OpenRouter usando a API OpenAI-compatible.

    Args:
        system_prompt: Contexto completo do agente (product_info, objections, etc.)
        messages: Histórico da conversa [{"role": "user/assistant", "content": "..."}]
        memory_context: (Fase 3) Briefing do Wild Memory — concatenado ao system prompt.

    Returns:
        Texto da resposta do modelo.

    Raises:
        Exception: se todas as tentativas falharem.
    """
    last_error = None

    full_system = system_prompt
    if memory_context:
        full_system = f"{system_prompt}\n\n{memory_context}"

    full_messages = [{"role": "system", "content": full_system}, *messages]
    sys_len = len(full_system)
    hist_len = len(messages)

    for attempt in range(1, MAX_RETRIES + 1):
        log_chat(
            "LLM_CALL",
            "Enviando request",
            model=OPENROUTER_MODEL,
            attempt=f"{attempt}/{MAX_RETRIES}",
            sys_chars=sys_len,
            hist_msgs=hist_len,
        )
        _t0 = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=OPENROUTER_MODEL,
                max_tokens=MAX_TOKENS,
                messages=full_messages,
            )
            _dt = time.monotonic() - _t0

            usage = response.usage
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0

            log_chat(
                "LLM_OK",
                "Resposta recebida",
                model=OPENROUTER_MODEL,
                input=input_tokens,
                output=output_tokens,
                dur=f"{_dt:.2f}s",
                attempt=f"{attempt}/{MAX_RETRIES}",
            )

            try:
                from src.core.metrics import record_call
                record_call(
                    model=OPENROUTER_MODEL,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            except Exception:
                pass  # Não bloqueia se métricas falharem

            return response.choices[0].message.content

        except RateLimitError as e:
            _dt = time.monotonic() - _t0
            last_error = e
            delay = _get_retry_delay(attempt, e)
            log_chat(
                "LLM_RETRY",
                "Rate limit (429)",
                attempt=f"{attempt}/{MAX_RETRIES}",
                dur=f"{_dt:.2f}s",
                backoff=f"{delay:.1f}s",
            )
            time.sleep(delay)

        except APITimeoutError as e:
            _dt = time.monotonic() - _t0
            last_error = e
            delay = _get_retry_delay(attempt)
            log_chat(
                "LLM_RETRY",
                "Timeout",
                attempt=f"{attempt}/{MAX_RETRIES}",
                dur=f"{_dt:.2f}s",
                backoff=f"{delay:.1f}s",
            )
            time.sleep(delay)

        except APIError as e:
            _dt = time.monotonic() - _t0
            last_error = e
            status = getattr(e, "status_code", None)

            if status in RETRYABLE_STATUS_CODES:
                delay = _get_retry_delay(attempt, e)
                log_chat(
                    "LLM_RETRY",
                    f"APIError status={status}",
                    attempt=f"{attempt}/{MAX_RETRIES}",
                    dur=f"{_dt:.2f}s",
                    backoff=f"{delay:.1f}s",
                    err=str(e)[:150],
                )
                time.sleep(delay)
            else:
                log_chat(
                    "LLM_FAIL",
                    f"Erro não-retryable status={status}",
                    dur=f"{_dt:.2f}s",
                    err=str(e)[:200],
                )
                raise

    log_chat(
        "LLM_FAIL",
        f"Todas as {MAX_RETRIES} tentativas falharam",
        last_err=str(last_error)[:200],
    )
    raise last_error


def _get_retry_delay(attempt: int, error=None) -> float:
    """
    Calcula o delay de retry com backoff exponencial.

    Respeita o header Retry-After da API quando disponível (comum em 429).
    Caso contrário: 1s, 2s, 4s (base * 2^(attempt-1)).
    """
    if error is not None:
        retry_after = getattr(error, "headers", {})
        if hasattr(retry_after, "get"):
            suggested = retry_after.get("retry-after")
            if suggested:
                try:
                    return float(suggested)
                except (ValueError, TypeError):
                    pass

    return RETRY_BASE_DELAY * (2 ** (attempt - 1))
