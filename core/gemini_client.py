"""
Centralized Gemini Client with Request Pacing & 429-Aware Backoff (Phase 10.7).
Enforces:
- 15 RPM constraint (minimum 4.0s inter-request pacing across all engines in production)
- Sliding window tracking to prevent bursts
- 429 RESOURCE_EXHAUSTED detection with Retry-After / retryDelay extraction
- Exponential backoff with jitter on transient failures
- Bounded retries and clean fail-safe reporting
"""
import os
import sys
import time
import random
import logging
import threading
from typing import Optional, Any, Dict, List, Callable

logger = logging.getLogger("GeminiClient")


class GeminiQuotaExhaustedError(RuntimeError):
    """Raised when Gemini API quota (429 RESOURCE_EXHAUSTED) is exhausted after all retries."""
    pass


def is_test_environment() -> bool:
    """Returns True if running under a test runner or TEST_MODE is explicitly enabled."""
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return True
    return os.getenv("TEST_MODE", "false").lower() == "true"


class GeminiRateLimiter:
    """
    Thread-safe request rate limiter ensuring calls respect Gemini free-tier limits.
    Default: 15 Requests Per Minute (RPM) -> minimum 4.0s spacing between calls in production.
    """
    def __init__(
        self,
        max_rpm: int = 15,
        min_interval: Optional[float] = None,
        sleeper: Callable[[float], None] = time.sleep
    ):
        self.max_rpm = max_rpm
        if min_interval is not None:
            self.min_interval = float(min_interval)
        else:
            self.min_interval = 0.0 if is_test_environment() else 4.0
        self.sleeper = sleeper
        self._lock = threading.Lock()
        self._last_request_time: float = 0.0
        self._request_history: List[float] = []

    def wait_for_slot(self) -> float:
        """
        Blocks until the next request slot is available.
        Returns the duration waited in seconds.
        """
        with self._lock:
            now = time.time()
            # 1. Prune history older than 60 seconds
            self._request_history = [t for t in self._request_history if now - t < 60.0]

            wait_needed = 0.0

            # 2. Check minimum interval from last request
            if self.min_interval > 0.0 and self._last_request_time > 0.0:
                elapsed_since_last = now - self._last_request_time
                if elapsed_since_last < self.min_interval:
                    wait_needed = max(wait_needed, self.min_interval - elapsed_since_last)

            # 3. Check sliding window count (max_rpm per 60s)
            if self.min_interval > 0.0 and len(self._request_history) >= self.max_rpm:
                oldest_in_window = self._request_history[0]
                window_wait = 60.0 - (now - oldest_in_window) + 0.1
                wait_needed = max(wait_needed, window_wait)

            scheduled_time = now + wait_needed
            self._last_request_time = scheduled_time
            self._request_history.append(scheduled_time)

        # Release lock before sleeping to avoid blocking other threads
        if wait_needed > 0.0:
            logger.info(
                f"[GEMINI_PACING] Pacing request: sleeping {wait_needed:.2f}s to respect {self.max_rpm} RPM limit..."
            )
            self.sleeper(wait_needed)

        return wait_needed

    def reset(self):
        """Resets the rate limiter state (useful for tests)."""
        with self._lock:
            self._last_request_time = 0.0
            self._request_history.clear()


class GeminiClient:
    """
    Wrapper around Google GenAI client providing centralized rate limiting, 429-aware backoff,
    and automatic fail-fast fallback to secondary independent provider account on quota exhaustion.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        secondary_api_key: Optional[str] = None,
        secondary_model: Optional[str] = None,
        rate_limiter: Optional[GeminiRateLimiter] = None,
        sleeper: Callable[[float], None] = time.sleep
    ):
        from config.settings import (
            GEMINI_API_KEY,
            GEMINI_API_KEY_SECONDARY,
            GEMINI_MODEL_SECONDARY
        )
        self.api_key = api_key or GEMINI_API_KEY
        self.secondary_api_key = secondary_api_key or GEMINI_API_KEY_SECONDARY
        self.secondary_model = secondary_model or GEMINI_MODEL_SECONDARY
        self.rate_limiter = rate_limiter or get_shared_rate_limiter()
        self.sleeper = sleeper
        self.active_provider = "primary"

    def _execute_request(
        self,
        api_key: str,
        model: str,
        contents: Any,
        max_retries: int = 3,
        base_delay: Optional[float] = None,
        max_delay: float = 60.0,
        provider_name: str = "primary",
        **kwargs
    ) -> Any:
        """Executes API call for a specific provider account with pacing and bounded backoff."""
        from core.retry import is_retryable_exception

        is_test = is_test_environment()
        if base_delay is None:
            base_delay = 0.05 if is_test else 4.0

        current_model = model
        last_exception = None

        for attempt in range(1, max_retries + 1):
            # 1. Acquire paced slot before firing request
            self.rate_limiter.wait_for_slot()

            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=current_model,
                    contents=contents,
                    **kwargs
                )
                return response
            except Exception as exc:
                last_exception = exc
                is_transient, server_delay = is_retryable_exception(exc)
                msg = str(exc)
                is_429 = "429" in msg or "resource_exhausted" in msg.lower() or "quota" in msg.lower()
                is_daily_quota = "perday" in msg.lower() or "generaterequestsperday" in msg.lower()

                if is_daily_quota:
                    from config.settings import GEMINI_FALLBACK_MODEL
                    if current_model != GEMINI_FALLBACK_MODEL and GEMINI_FALLBACK_MODEL:
                        logger.warning(
                            f"[GEMINI_FALLBACK] Daily quota exhausted for model '{current_model}' on {provider_name} provider. "
                            f"Switching immediately to fallback model '{GEMINI_FALLBACK_MODEL}'..."
                        )
                        current_model = GEMINI_FALLBACK_MODEL
                        continue
                    # Fail fast out of this provider on daily quota exhaustion
                    raise GeminiQuotaExhaustedError(
                        f"Daily API quota exhausted on {provider_name} provider for model '{current_model}'"
                    ) from exc

                if not (is_transient or is_429):
                    # Permanent error (e.g. invalid argument, unrecoverable) - do not retry
                    logger.error(f"[GEMINI_ERROR] Non-retryable error from Gemini API on {provider_name} provider: {exc}")
                    raise exc

                if attempt >= max_retries:
                    break

                # Compute backoff delay
                if server_delay and server_delay > 0:
                    delay = server_delay + (0.01 if is_test else random.uniform(0.5, 1.5))
                else:
                    raw = base_delay * (2 ** (attempt - 1))
                    jitter = 0.01 if is_test else random.uniform(0.5, 1.5)
                    delay = min(max_delay, raw) + jitter

                logger.warning(
                    f"[GEMINI_RATE_LIMIT] 429/Transient failure on {provider_name} provider (attempt {attempt}/{max_retries}): {exc}. "
                    f"Backing off for {delay:.2f}s before retry..."
                )
                self.sleeper(delay)

        err_summary = f"Gemini API rate limit / quota exhausted on {provider_name} provider after {max_retries} attempts"
        logger.error(f"[GEMINI_EXHAUSTED] {err_summary}")
        raise GeminiQuotaExhaustedError(err_summary) from last_exception

    def generate_content(
        self,
        model: str,
        contents: Any,
        max_retries: int = 3,
        base_delay: Optional[float] = None,
        max_delay: float = 60.0,
        **kwargs
    ) -> Any:
        """
        Executes models.generate_content with rate limiting, exponential backoff, and
        transparent secondary provider fallback upon primary daily quota exhaustion.
        """
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        # Attempt 1: Primary Gemini Provider
        try:
            return self._execute_request(
                api_key=self.api_key,
                model=model,
                contents=contents,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                provider_name="primary",
                **kwargs
            )
        except GeminiQuotaExhaustedError as primary_quota_err:
            # Check if an independent secondary Gemini credential is configured
            if self.secondary_api_key and self.secondary_api_key != self.api_key:
                sec_model = self.secondary_model or model
                logger.warning(
                    f"[GEMINI_FALLBACK] Primary Gemini provider quota exhausted. "
                    f"Switching immediately to SECONDARY Gemini provider account (model: '{sec_model}')..."
                )
                self.active_provider = "secondary"

                try:
                    return self._execute_request(
                        api_key=self.secondary_api_key,
                        model=sec_model,
                        contents=contents,
                        max_retries=max_retries,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        provider_name="secondary",
                        **kwargs
                    )
                except GeminiQuotaExhaustedError as sec_quota_err:
                    logger.error(
                        "[GEMINI_EXHAUSTED] ALL configured Gemini providers (primary & secondary) "
                        "exhausted daily API quotas. Halting production cleanly."
                    )
                    raise GeminiQuotaExhaustedError(
                        "All configured Gemini providers exhausted daily API quotas."
                    ) from sec_quota_err

            # No secondary provider available; re-raise primary quota error
            raise primary_quota_err


_SHARED_LIMITER: Optional[GeminiRateLimiter] = None
_SHARED_CLIENT: Optional[GeminiClient] = None
_INIT_LOCK = threading.RLock()


def get_shared_rate_limiter() -> GeminiRateLimiter:
    global _SHARED_LIMITER
    with _INIT_LOCK:
        if _SHARED_LIMITER is None:
            _SHARED_LIMITER = GeminiRateLimiter()
        return _SHARED_LIMITER


def get_gemini_client(
    api_key: Optional[str] = None,
    secondary_api_key: Optional[str] = None,
    secondary_model: Optional[str] = None
) -> GeminiClient:
    global _SHARED_CLIENT
    with _INIT_LOCK:
        if _SHARED_CLIENT is None or api_key or secondary_api_key:
            client = GeminiClient(
                api_key=api_key,
                secondary_api_key=secondary_api_key,
                secondary_model=secondary_model
            )
            if not api_key and not secondary_api_key:
                _SHARED_CLIENT = client
            return client
        return _SHARED_CLIENT
