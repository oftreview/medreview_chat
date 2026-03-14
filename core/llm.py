"""
core/llm.py — Interface com a API Claude (Anthropic).

Implementa retry com backoff exponencial para resiliência contra
erros transitórios (rate limit, timeout, erros de servidor).
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
    Chama a Claude API com o system prompt e histórico de mensagens.
    Retorna o texto da resposta.

    Retry automático com backoff exponencial em caso de:
      - Rate limit (429)
      - Erro de servidor (500, 502, 503)
      - Sobrecarga (529)
      - Timeout de rede

    Raises:
        Exception: se todas as tentativas falharem, propaga o último erro
                   para que o caller (app.py) retorne a fallback message.
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=messages,
            )
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
