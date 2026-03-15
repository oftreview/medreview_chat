"""
core/llm.py — Interface com a API Claude (Anthropic).

Implementa:
  - Prompt Caching: o system prompt (~30K tokens) é cacheado globalmente
    entre todas as sessões. Tokens cacheados NÃO contam no rate limit de
    input e custam 90% menos. Cache TTL: 5 minutos (renovado a cada chamada).
  - Retry com backoff exponencial para resiliência contra erros transitórios.
"""

import time
from anthropic import Anthropic, APIError, APITimeoutError, RateLimitError
from core.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS

client = Anthropic(api_key=ANTHROPIC_API_KEY, timeout=30.0)

# ── Configuração de retry ────────────────────────────────────────────────────

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0          # segundos — delay inicial (dobra a cada tentativa)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


def call_claude(system_prompt: str, messages: list) -> str:
    """
    Chama a Claude API com Prompt Caching habilitado.

    O system_prompt é enviado como bloco com cache_control, permitindo que
    a Anthropic o cachie entre chamadas. Na primeira chamada, o cache é
    criado (cache_creation_input_tokens). Nas chamadas seguintes (dentro de
    5 minutos), o cache é reutilizado (cache_read_input_tokens) — esses
    tokens NÃO contam no rate limit de ITPM.

    Requisitos mínimos de tokens para cache:
      - Claude Sonnet 4.x: 1.024 tokens
      - Claude Haiku 4.5:  4.096 tokens
      - Claude Opus 4.x:   4.096 tokens
    Nosso system prompt (~30K tokens) excede todos esses limites.

    Args:
        system_prompt: Contexto completo do agente (product_info, objections, etc.)
        messages: Histórico da conversa [{"role": "user/assistant", "content": "..."}]

    Returns:
        Texto da resposta do Claude.

    Raises:
        Exception: se todas as tentativas falharem.
    """
    last_error = None

    # System prompt formatado para Prompt Caching:
    # Um bloco de texto com cache_control marca o conteúdo como cacheável.
    system_with_cache = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                system=system_with_cache,
                messages=messages,
            )

            # Log de métricas de cache para monitoramento
            usage = response.usage
            cache_created = getattr(usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0

            cache_status = "HIT" if cache_read > 0 else "MISS (created)" if cache_created > 0 else "NONE"
            print(
                f"[LLM] Cache: {cache_status} | "
                f"cached_read={cache_read} cached_write={cache_created} "
                f"input={input_tokens} output={output_tokens}",
                flush=True,
            )

            # Registra métricas para o dashboard
            try:
                from core.metrics import record_call
                record_call(
                    model=CLAUDE_MODEL,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read=cache_read,
                    cache_write=cache_created,
                )
            except Exception:
                pass  # Não bloqueia se métricas falharem

            return response.content[0].text

        except RateLimitError as e:
            last_error = e
            delay = _get_retry_delay(attempt, e)
            print(
                f"[LLM] Rate limit (429) — tentativa {attempt}/{MAX_RETRIES}, "
                f"retry em {delay:.1f}s",
                flush=True,
            )
            time.sleep(delay)

        except APITimeoutError as e:
            last_error = e
            delay = _get_retry_delay(attempt)
            print(
                f"[LLM] Timeout — tentativa {attempt}/{MAX_RETRIES}, "
                f"retry em {delay:.1f}s",
                flush=True,
            )
            time.sleep(delay)

        except APIError as e:
            last_error = e
            status = getattr(e, "status_code", None)

            if status in RETRYABLE_STATUS_CODES:
                delay = _get_retry_delay(attempt, e)
                print(
                    f"[LLM] Erro {status} — tentativa {attempt}/{MAX_RETRIES}, "
                    f"retry em {delay:.1f}s",
                    flush=True,
                )
                time.sleep(delay)
            else:
                # Erro não-retryable (400, 401, 403, etc.) — falha imediata
                print(
                    f"[LLM] Erro não-retryable {status}: {e}",
                    flush=True,
                )
                raise

    # Todas as tentativas falharam
    print(
        f"[LLM] Todas as {MAX_RETRIES} tentativas falharam. Último erro: {last_error}",
        flush=True,
    )
    raise last_error


def _get_retry_delay(attempt: int, error=None) -> float:
    """
    Calcula o delay de retry com backoff exponencial.

    Respeita o header Retry-After da API quando disponível (comum em 429).
    Caso contrário: 1s, 2s, 4s (base * 2^(attempt-1)).
    """
    # Verifica se a API sugeriu um tempo de espera
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
