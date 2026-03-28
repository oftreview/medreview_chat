"""
tests/unit/test_llm_retry.py — Testes da logica de retry do LLM.

Testa: _get_retry_delay, constantes de retry
Sem chamadas reais a API, sem I/O.
"""
import pytest
from src.core.llm import (
    _get_retry_delay,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    RETRYABLE_STATUS_CODES,
)


class TestRetryDelay:
    """Testes do calculo de delay de retry."""

    def test_exponential_backoff_attempt_1(self):
        """Primeira tentativa: base delay (1s)."""
        delay = _get_retry_delay(1)
        assert delay == RETRY_BASE_DELAY * 1  # 1.0

    def test_exponential_backoff_attempt_2(self):
        """Segunda tentativa: 2x base delay (2s)."""
        delay = _get_retry_delay(2)
        assert delay == RETRY_BASE_DELAY * 2  # 2.0

    def test_exponential_backoff_attempt_3(self):
        """Terceira tentativa: 4x base delay (4s)."""
        delay = _get_retry_delay(3)
        assert delay == RETRY_BASE_DELAY * 4  # 4.0

    def test_retry_after_header_respected(self):
        """Respeita header Retry-After quando presente."""
        # Simula erro com headers
        error = type("FakeError", (), {
            "headers": {"retry-after": "5.0"}
        })()
        delay = _get_retry_delay(1, error)
        assert delay == 5.0

    def test_retry_after_invalid_falls_back(self):
        """Header Retry-After invalido cai no backoff padrao."""
        error = type("FakeError", (), {
            "headers": {"retry-after": "invalid"}
        })()
        delay = _get_retry_delay(1, error)
        assert delay == RETRY_BASE_DELAY  # Fallback

    def test_retry_after_missing_header(self):
        """Erro sem header Retry-After usa backoff padrao."""
        error = type("FakeError", (), {"headers": {}})()
        delay = _get_retry_delay(2, error)
        assert delay == RETRY_BASE_DELAY * 2

    def test_error_without_headers_attr(self):
        """Erro sem atributo headers usa backoff padrao."""
        error = type("FakeError", (), {})()
        delay = _get_retry_delay(1, error)
        assert delay == RETRY_BASE_DELAY

    def test_none_error_uses_backoff(self):
        """Error=None usa backoff padrao."""
        delay = _get_retry_delay(2, None)
        assert delay == RETRY_BASE_DELAY * 2


class TestRetryConstants:
    """Testes das constantes de retry."""

    def test_max_retries_is_positive(self):
        """MAX_RETRIES deve ser positivo."""
        assert MAX_RETRIES > 0

    def test_max_retries_reasonable(self):
        """MAX_RETRIES nao deve ser excessivo."""
        assert MAX_RETRIES <= 10

    def test_base_delay_positive(self):
        """RETRY_BASE_DELAY deve ser positivo."""
        assert RETRY_BASE_DELAY > 0

    def test_retryable_status_codes_contains_429(self):
        """429 (rate limit) deve ser retryable."""
        assert 429 in RETRYABLE_STATUS_CODES

    def test_retryable_status_codes_contains_500(self):
        """500 (server error) deve ser retryable."""
        assert 500 in RETRYABLE_STATUS_CODES

    def test_retryable_status_codes_contains_529(self):
        """529 (overloaded) deve ser retryable."""
        assert 529 in RETRYABLE_STATUS_CODES

    def test_retryable_does_not_contain_400(self):
        """400 (bad request) NAO deve ser retryable."""
        assert 400 not in RETRYABLE_STATUS_CODES

    def test_retryable_does_not_contain_401(self):
        """401 (unauthorized) NAO deve ser retryable."""
        assert 401 not in RETRYABLE_STATUS_CODES
