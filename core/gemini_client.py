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
    and automatic failover to secondary provider account on quota exhaustion.
    Remembers provider exhaustion for the session to prevent retry amplification on dead credentials.
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
            GEMINI_MODEL,
            GEMINI_MODEL_SECONDARY
        )
        self.api_key = api_key or GEMINI_API_KEY
        self.secondary_api_key = secondary_api_key or GEMINI_API_KEY_SECONDARY
        self.primary_model = GEMINI_MODEL
        self.secondary_model = secondary_model or GEMINI_MODEL_SECONDARY or GEMINI_MODEL
        self.rate_limiter = rate_limiter or get_shared_rate_limiter()
        self.sleeper = sleeper
        self._provider_lock = threading.Lock()
        self._exhausted_providers: set = set()
        self.active_provider = "primary"

    def mark_provider_exhausted(self, provider_name: str) -> None:
        """Marks a provider credential as quota-exhausted for this session."""
        with self._provider_lock:
            self._exhausted_providers.add(provider_name.lower())
            if provider_name.lower() == "primary":
                self.active_provider = "secondary"
            logger.warning(
                f"[GEMINI_PROVIDER] Provider '{provider_name.upper()}' marked EXHAUSTED for active session."
            )

    def is_provider_exhausted(self, provider_name: str) -> bool:
        """Returns True if the provider has already been marked quota-exhausted."""
        with self._provider_lock:
            return provider_name.lower() in self._exhausted_providers

    def reset_provider_status(self) -> None:
        """Resets provider exhaustion tracking (useful for test isolation and new daily cycles)."""
        with self._provider_lock:
            self._exhausted_providers.clear()
            self.active_provider = "primary"

    def _get_configured_providers(self, requested_model: Optional[str] = None) -> List[Dict[str, str]]:
        """Returns ordered list of configured, non-empty provider credentials."""
        providers = []
        if self.api_key:
            providers.append({
                "name": "primary",
                "api_key": self.api_key,
                "model": requested_model or self.primary_model
            })
        if self.secondary_api_key and self.secondary_api_key != self.api_key:
            providers.append({
                "name": "secondary",
                "api_key": self.secondary_api_key,
                "model": self.secondary_model or requested_model or self.primary_model
            })
        return providers

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
                msg = str(exc)
                msg_lower = msg.lower()
                is_transient, server_delay = is_retryable_exception(exc)
                is_429 = "429" in msg or "resource_exhausted" in msg_lower or "quota" in msg_lower
                is_daily_quota = (
                    "perday" in msg_lower or
                    "generaterequestsperday" in msg_lower or
                    "daily quota" in msg_lower or
                    "daily request" in msg_lower
                )

                if is_daily_quota:
                    from config.settings import GEMINI_FALLBACK_MODEL
                    if current_model != GEMINI_FALLBACK_MODEL and GEMINI_FALLBACK_MODEL:
                        logger.warning(
                            f"[GEMINI_FALLBACK] Daily quota exhausted for model '{current_model}' on {provider_name.upper()} provider. "
                            f"Switching immediately to fallback model '{GEMINI_FALLBACK_MODEL}'..."
                        )
                        current_model = GEMINI_FALLBACK_MODEL
                        continue
                    # Fail fast out of this provider on daily quota exhaustion
                    self.mark_provider_exhausted(provider_name)
                    raise GeminiQuotaExhaustedError(
                        f"Daily API quota exhausted on {provider_name.upper()} provider for model '{current_model}'"
                    ) from exc

                if not (is_transient or is_429):
                    # Permanent error (e.g. invalid argument, unrecoverable, prompt blocked) - do not retry or rotate
                    logger.error(f"[GEMINI_ERROR] Non-retryable error from Gemini API on {provider_name.upper()} provider: {exc}")
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
                    f"[GEMINI_RATE_LIMIT] 429/Transient failure on {provider_name.upper()} provider (attempt {attempt}/{max_retries}): {exc}. "
                    f"Backing off for {delay:.2f}s before retry..."
                )
                self.sleeper(delay)

        # Retries exhausted on this provider -> mark exhausted if 429/quota
        if is_429:
            self.mark_provider_exhausted(provider_name)
        err_summary = f"Gemini API rate limit / quota exhausted on {provider_name.upper()} provider after {max_retries} attempts"
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
        transparent secondary provider failover upon primary quota exhaustion.
        Skips previously exhausted providers to prevent retry amplification.
        """
        if not self.api_key and not self.secondary_api_key:
            raise ValueError("No GEMINI_API_KEY is configured.")

        all_providers = self._get_configured_providers(requested_model=model)
        if not all_providers:
            raise ValueError("No valid Gemini provider credentials available.")

        # Determine eligible providers (unexhausted first)
        available_providers = [p for p in all_providers if not self.is_provider_exhausted(p["name"])]

        if not available_providers:
            err_msg = "All configured Gemini providers exhausted daily API quotas."
            logger.error(f"[GEMINI_EXHAUSTED] {err_msg}")
            raise GeminiQuotaExhaustedError(err_msg)

        last_err = None

        for prov in available_providers:
            prov_name = prov["name"]
            prov_key = prov["api_key"]
            prov_model = prov["model"]

            self.active_provider = prov_name
            logger.info(f"[GEMINI_REQUEST] Dispatching request to provider '{prov_name.upper()}' (model: '{prov_model}')...")

            try:
                result = self._execute_request(
                    api_key=prov_key,
                    model=prov_model,
                    contents=contents,
                    max_retries=max_retries,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    provider_name=prov_name,
                    **kwargs
                )
                return result
            except GeminiQuotaExhaustedError as quota_err:
                last_err = quota_err
                self.mark_provider_exhausted(prov_name)
                # Check if another provider remains
                remaining = [p for p in all_providers if not self.is_provider_exhausted(p["name"])]
                if remaining:
                    logger.warning(
                        f"[GEMINI_FAILOVER] Provider '{prov_name.upper()}' quota exhausted. "
                        f"Failing over to provider '{remaining[0]['name'].upper()}'..."
                    )
                    continue
                else:
                    logger.error(
                        "[GEMINI_EXHAUSTED] ALL configured Gemini providers exhausted daily API quotas. Halting production cleanly."
                    )
                    raise GeminiQuotaExhaustedError(
                        "All configured Gemini providers exhausted daily API quotas."
                    ) from quota_err

        if last_err:
            raise last_err
        raise GeminiQuotaExhaustedError("All configured Gemini providers exhausted daily API quotas.")


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
