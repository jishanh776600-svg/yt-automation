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


class DeepSeekResponse:
    """Wrapper to maintain exact interface compatibility with google.genai response objects."""
    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:
        snippet = (self.text[:40] + "...") if len(self.text) > 40 else self.text
        return f"<DeepSeekResponse text={snippet!r}>"


class GroqResponse:
    """Wrapper to maintain exact interface compatibility with google.genai response objects."""
    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:
        snippet = (self.text[:40] + "...") if len(self.text) > 40 else self.text
        return f"<GroqResponse text={snippet!r}>"


class OpenRouterResponse:
    """Wrapper to maintain exact interface compatibility with google.genai response objects."""
    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:
        snippet = (self.text[:40] + "...") if len(self.text) > 40 else self.text
        return f"<OpenRouterResponse text={snippet!r}>"


class GeminiClient:
    """
    Unified AI Client providing centralized rate limiting, 429-aware backoff,
    and automatic failover across Gemini Primary -> Gemini Secondary -> Groq -> OpenRouter.
    Remembers provider exhaustion for the session to prevent retry amplification on dead credentials.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        secondary_api_key: Optional[str] = None,
        secondary_model: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
        openrouter_api_key: Optional[str] = None,
        openrouter_model: Optional[str] = None,
        deepseek_api_key: Optional[str] = None,
        deepseek_model: Optional[str] = None,
        rate_limiter: Optional[GeminiRateLimiter] = None,
        sleeper: Callable[[float], None] = time.sleep
    ):
        from config.settings import (
            GEMINI_API_KEY,
            GEMINI_API_KEY_SECONDARY,
            GEMINI_MODEL,
            GEMINI_MODEL_SECONDARY,
            GROQ_API_KEY,
            GROQ_MODEL,
            OPENROUTER_API_KEY,
            OPENROUTER_MODEL,
            DEEPSEEK_API_KEY,
            DEEPSEEK_MODEL
        )
        self.api_key = api_key if api_key is not None else GEMINI_API_KEY
        self.secondary_api_key = secondary_api_key if secondary_api_key is not None else GEMINI_API_KEY_SECONDARY
        self.groq_api_key = groq_api_key if groq_api_key is not None else GROQ_API_KEY
        self.openrouter_api_key = openrouter_api_key if openrouter_api_key is not None else OPENROUTER_API_KEY
        self.deepseek_api_key = deepseek_api_key if deepseek_api_key is not None else DEEPSEEK_API_KEY
        self.primary_model = GEMINI_MODEL
        self.secondary_model = secondary_model or GEMINI_MODEL_SECONDARY or GEMINI_MODEL
        self.groq_model = groq_model or GROQ_MODEL or "llama-3.1-8b-instant"
        self.openrouter_model = openrouter_model or OPENROUTER_MODEL or "meta-llama/llama-3.3-70b-instruct"
        self.deepseek_model = deepseek_model or DEEPSEEK_MODEL or "deepseek-v4-pro"
        self.rate_limiter = rate_limiter or get_shared_rate_limiter()
        self.sleeper = sleeper
        self._provider_lock = threading.Lock()
        self._exhausted_providers: set = set()
        self.active_provider = "primary"

    def mark_provider_exhausted(self, provider_name: str) -> None:
        """Marks a provider credential as quota-exhausted for this session."""
        with self._provider_lock:
            self._exhausted_providers.add(provider_name.lower())
            logger.warning(
                f"[AI_PROVIDER] Provider '{provider_name.upper()}' marked EXHAUSTED for active session."
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

    def _get_configured_providers(self, requested_model: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns ordered list of configured, non-empty provider credentials: Primary -> Secondary -> Groq -> OpenRouter -> DeepSeek."""
        providers = []
        if self.api_key:
            providers.append({
                "name": "primary",
                "type": "gemini",
                "api_key": self.api_key,
                "model": requested_model or self.primary_model
            })
        if self.secondary_api_key and self.secondary_api_key != self.api_key:
            providers.append({
                "name": "secondary",
                "type": "gemini",
                "api_key": self.secondary_api_key,
                "model": self.secondary_model or requested_model or self.primary_model
            })
        if self.groq_api_key:
            providers.append({
                "name": "groq",
                "type": "groq",
                "api_key": self.groq_api_key,
                "model": self.groq_model
            })
        if self.openrouter_api_key:
            providers.append({
                "name": "openrouter",
                "type": "openrouter",
                "api_key": self.openrouter_api_key,
                "model": self.openrouter_model
            })
        if self.deepseek_api_key:
            providers.append({
                "name": "deepseek",
                "type": "deepseek",
                "api_key": self.deepseek_api_key,
                "model": self.deepseek_model
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
        """Executes API call for a specific Gemini provider account with pacing and bounded backoff."""
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

    def _execute_deepseek_request(
        self,
        api_key: str,
        model: str,
        contents: Any,
        max_retries: int = 3,
        base_delay: Optional[float] = None,
        max_delay: float = 60.0,
        **kwargs
    ) -> DeepSeekResponse:
        """Executes API call to DeepSeek OpenAI-compatible chat completion endpoint with pacing and backoff."""
        import json
        import urllib.request
        from urllib.error import HTTPError, URLError
        from config.settings import DEEPSEEK_BASE_URL

        is_test = is_test_environment()
        if base_delay is None:
            base_delay = 0.05 if is_test else 2.0

        endpoint = DEEPSEEK_BASE_URL or "https://api.bluesminds.com/v1/chat/completions"

        # Format user prompt
        if isinstance(contents, str):
            user_prompt = contents
        elif isinstance(contents, list):
            user_prompt = "\n\n".join(str(c) for c in contents)
        else:
            user_prompt = str(contents)

        payload_dict = {
            "model": model,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "stream": False
        }
        payload_bytes = json.dumps(payload_dict).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "AL-AMR-DeepSeek-Client/1.0"
        }

        last_exception = None

        for attempt in range(1, max_retries + 1):
            self.rate_limiter.wait_for_slot()

            try:
                req = urllib.request.Request(endpoint, data=payload_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=45.0) as resp:
                    resp_body = resp.read().decode("utf-8")
                    data = json.loads(resp_body)
                    choices = data.get("choices", [])
                    if not choices:
                        raise ValueError(f"DeepSeek returned empty choices: {resp_body[:200]}")
                    text_content = choices[0].get("message", {}).get("content", "")
                    return DeepSeekResponse(text=text_content)
            except HTTPError as http_err:
                last_exception = http_err
                code = http_err.code
                try:
                    err_body = http_err.read().decode("utf-8", errors="ignore")
                except Exception:
                    err_body = ""
                err_lower = err_body.lower()

                # Quota / Balance Exhaustion / 429 / 402
                is_quota_or_balance = (
                    code == 429 or
                    code == 402 or
                    "insufficient balance" in err_lower or
                    "balance" in err_lower or
                    "quota" in err_lower or
                    "rate limit" in err_lower
                )

                if is_quota_or_balance:
                    self.mark_provider_exhausted("deepseek")
                    logger.warning(
                        f"[DEEPSEEK_EXHAUSTED] DeepSeek API quota/balance exhausted (HTTP {code}): {err_body[:200]}"
                    )
                    raise GeminiQuotaExhaustedError(
                        f"DeepSeek API quota or balance exhausted (HTTP {code})"
                    ) from http_err

                # Non-retryable 4xx errors (e.g. 400 Bad Request, 401 Invalid Key, 403 Forbidden)
                if 400 <= code < 500:
                    self.mark_provider_exhausted("deepseek")
                    logger.error(f"[DEEPSEEK_AUTH_FAIL] DeepSeek client error (HTTP {code}). Marking provider exhausted permanently for session: {err_body[:200]}")
                    raise GeminiQuotaExhaustedError(f"DeepSeek API error (HTTP {code}): {err_body[:200]}") from http_err

                # Transient 5xx server errors
                if attempt >= max_retries:
                    break

                raw_delay = base_delay * (2 ** (attempt - 1))
                jitter = 0.01 if is_test else random.uniform(0.5, 1.5)
                delay = min(max_delay, raw_delay) + jitter
                logger.warning(
                    f"[DEEPSEEK_RETRY] Transient failure from DeepSeek (attempt {attempt}/{max_retries}, HTTP {code}). Retrying in {delay:.2f}s..."
                )
                self.sleeper(delay)

            except (URLError, TimeoutError, ConnectionError, OSError) as net_err:
                last_exception = net_err
                if attempt >= max_retries:
                    break
                raw_delay = base_delay * (2 ** (attempt - 1))
                jitter = 0.01 if is_test else random.uniform(0.5, 1.5)
                delay = min(max_delay, raw_delay) + jitter
                logger.warning(
                    f"[DEEPSEEK_NET_RETRY] Network connection error to DeepSeek (attempt {attempt}/{max_retries}): {net_err}. Retrying in {delay:.2f}s..."
                )
                self.sleeper(delay)

            except Exception as unk_err:
                logger.error(f"[DEEPSEEK_ERROR] Unhandled error calling DeepSeek: {unk_err}")
                raise unk_err

        # All retries exhausted on DeepSeek
        self.mark_provider_exhausted("deepseek")
        err_msg = f"DeepSeek API retries exhausted after {max_retries} attempts: {last_exception}"
        logger.error(f"[DEEPSEEK_EXHAUSTED] {err_msg}")
        raise GeminiQuotaExhaustedError(err_msg) from last_exception

    def _execute_groq_request(
        self,
        api_key: str,
        model: str,
        contents: Any,
        max_retries: int = 3,
        base_delay: Optional[float] = None,
        max_delay: float = 60.0,
        **kwargs
    ) -> GroqResponse:
        """Executes API call to Groq OpenAI-compatible chat completion endpoint with pacing and fail-fast backoff."""
        import json
        import urllib.request
        from urllib.error import HTTPError, URLError
        from config.settings import GROQ_BASE_URL

        is_test = is_test_environment()
        if base_delay is None:
            base_delay = 0.05 if is_test else 2.0

        endpoint = GROQ_BASE_URL or "https://api.groq.com/openai/v1/chat/completions"

        # Format user prompt
        if isinstance(contents, str):
            user_prompt = contents
        elif isinstance(contents, list):
            user_prompt = "\n\n".join(str(c) for c in contents)
        else:
            user_prompt = str(contents)

        payload_dict: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "stream": False
        }

        # Structured JSON mode support when requested by engine
        if kwargs.get("response_mime_type") == "application/json" or kwargs.get("response_format") == "json":
            payload_dict["response_format"] = {"type": "json_object"}

        payload_bytes = json.dumps(payload_dict).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "AL-AMR-Groq-Client/1.0"
        }

        last_exception = None

        for attempt in range(1, max_retries + 1):
            self.rate_limiter.wait_for_slot()

            try:
                req = urllib.request.Request(endpoint, data=payload_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=45.0) as resp:
                    resp_body = resp.read().decode("utf-8")
                    data = json.loads(resp_body)
                    choices = data.get("choices", [])
                    if not choices:
                        raise ValueError(f"Groq returned empty choices: {resp_body[:200]}")
                    text_content = choices[0].get("message", {}).get("content", "")
                    return GroqResponse(text=text_content)
            except HTTPError as http_err:
                last_exception = http_err
                code = http_err.code
                try:
                    err_body = http_err.read().decode("utf-8", errors="ignore")
                except Exception:
                    err_body = ""
                err_lower = err_body.lower()

                # Quota / Rate-limit / 429
                is_quota_or_rate_limit = (
                    code == 429 or
                    "rate limit" in err_lower or
                    "quota" in err_lower or
                    "tokens per minute" in err_lower or
                    "requests per minute" in err_lower
                )

                if is_quota_or_rate_limit:
                    self.mark_provider_exhausted("groq")
                    logger.warning(
                        f"[GROQ_EXHAUSTED] Groq API quota/rate limit exhausted (HTTP {code}). Marking provider exhausted."
                    )
                    raise GeminiQuotaExhaustedError(
                        f"Groq API quota or rate limit exhausted (HTTP {code})"
                    ) from http_err

                # Non-retryable 4xx client errors (e.g. 401 Unauthorized, 403 Forbidden)
                if 400 <= code < 500:
                    self.mark_provider_exhausted("groq")
                    logger.error(
                        f"[GROQ_AUTH_FAIL] Groq client error (HTTP {code}). Marking provider exhausted permanently for session: {err_body[:200]}"
                    )
                    raise GeminiQuotaExhaustedError(f"Groq client authentication error (HTTP {code})") from http_err

                # Transient 5xx server errors
                if attempt >= max_retries:
                    break

                raw_delay = base_delay * (2 ** (attempt - 1))
                jitter = 0.01 if is_test else random.uniform(0.5, 1.5)
                delay = min(max_delay, raw_delay) + jitter
                logger.warning(
                    f"[GROQ_RETRY] Transient failure from Groq (attempt {attempt}/{max_retries}, HTTP {code}). Retrying in {delay:.2f}s..."
                )
                self.sleeper(delay)

            except (URLError, TimeoutError, ConnectionError, OSError) as net_err:
                last_exception = net_err
                if attempt >= max_retries:
                    break
                raw_delay = base_delay * (2 ** (attempt - 1))
                jitter = 0.01 if is_test else random.uniform(0.5, 1.5)
                delay = min(max_delay, raw_delay) + jitter
                logger.warning(
                    f"[GROQ_NET_RETRY] Network connection error to Groq (attempt {attempt}/{max_retries}): {net_err}. Retrying in {delay:.2f}s..."
                )
                self.sleeper(delay)

            except Exception as unk_err:
                logger.error(f"[GROQ_ERROR] Unhandled error calling Groq: {unk_err}")
                raise unk_err

        # All retries exhausted on Groq
        self.mark_provider_exhausted("groq")
        err_msg = f"Groq API retries exhausted after {max_retries} attempts: {last_exception}"
        logger.error(f"[GROQ_EXHAUSTED] {err_msg}")
        raise GeminiQuotaExhaustedError(err_msg) from last_exception

    def _execute_openrouter_request(
        self,
        api_key: str,
        model: str,
        contents: Any,
        max_retries: int = 3,
        base_delay: Optional[float] = None,
        max_delay: float = 60.0,
        **kwargs
    ) -> OpenRouterResponse:
        """
        Executes a single chat completion request against OpenRouter REST API using standard-library urllib.
        Fails fast on 401/403 (invalid key) and 429 (rate/credit limit), marking provider exhausted.
        """
        import json
        import urllib.request
        from urllib.error import HTTPError, URLError

        from config.settings import OPENROUTER_BASE_URL, TEST_MODE

        url = OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1/chat/completions"
        effective_model = self.openrouter_model or model or "meta-llama/llama-3.3-70b-instruct:free"

        prompt_text = ""
        if isinstance(contents, str):
            prompt_text = contents
        elif isinstance(contents, list):
            prompt_text = "\n".join([str(c) for c in contents])
        else:
            prompt_text = str(contents)

        payload_dict = {
            "model": effective_model,
            "messages": [
                {"role": "user", "content": prompt_text}
            ],
            "temperature": 0.7
        }

        # Check if caller requested structured JSON
        if kwargs.get("response_mime_type") == "application/json" or "json" in prompt_text.lower()[:100]:
            payload_dict["response_format"] = {"type": "json_object"}

        payload_bytes = json.dumps(payload_dict).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/jishanh776600-svg/yt-automation",
            "X-Title": "AL AMR Autonomous Pipeline",
            "User-Agent": "AL-AMR-OpenRouter-Client/1.0"
        }

        is_test = TEST_MODE or "pytest" in sys.modules
        base_delay = 0.05 if is_test else (base_delay if base_delay is not None else 2.0)
        last_exception = None

        for attempt in range(1, max_retries + 1):
            req = urllib.request.Request(url, data=payload_bytes, headers=headers, method="POST")
            try:
                self.rate_limiter.wait_for_slot()
                timeout = 10.0 if is_test else 45.0
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    raw_body = response.read().decode("utf-8")
                    data = json.loads(raw_body)
                    choices = data.get("choices", [])
                    if not choices:
                        raise GeminiQuotaExhaustedError(f"OpenRouter response missing choices: {raw_body}")
                    content = choices[0].get("message", {}).get("content", "")
                    return OpenRouterResponse(text=content)

            except HTTPError as http_err:
                last_exception = http_err
                code = http_err.code
                err_body = http_err.read().decode("utf-8", errors="ignore")

                # HTTP 401 / 403: Authentication or forbidden failure - fail fast immediately
                if code in (401, 403):
                    self.mark_provider_exhausted("openrouter")
                    logger.error(
                        f"[OPENROUTER_AUTH_FAIL] OpenRouter client authentication error (HTTP {code}). "
                        f"Marking provider exhausted permanently for session: {err_body}"
                    )
                    raise GeminiQuotaExhaustedError(
                        f"OpenRouter client authentication error (HTTP {code})"
                    ) from http_err

                # HTTP 429: Rate limit or quota exhausted - fail fast and rotate immediately
                if code == 429:
                    self.mark_provider_exhausted("openrouter")
                    logger.warning(
                        f"[OPENROUTER_QUOTA_FAIL] OpenRouter rate/quota limit reached (HTTP 429). "
                        f"Marking provider exhausted permanently for session: {err_body}"
                    )
                    raise GeminiQuotaExhaustedError(
                        "OpenRouter daily quota or rate limit exhausted (HTTP 429)"
                    ) from http_err

                # HTTP 400 / 404: Invalid model or payload error
                if code in (400, 404):
                    self.mark_provider_exhausted("openrouter")
                    logger.error(
                        f"[OPENROUTER_REQ_FAIL] OpenRouter request error (HTTP {code}). "
                        f"Marking provider exhausted: {err_body}"
                    )
                    raise GeminiQuotaExhaustedError(
                        f"OpenRouter request error (HTTP {code}): {err_body}"
                    ) from http_err

                if attempt >= max_retries:
                    break

                raw_delay = base_delay * (2 ** (attempt - 1))
                jitter = 0.01 if is_test else random.uniform(0.5, 1.5)
                delay = min(max_delay, raw_delay) + jitter
                logger.warning(
                    f"[OPENROUTER_RETRY] Transient failure from OpenRouter (attempt {attempt}/{max_retries}, HTTP {code}). Retrying in {delay:.2f}s..."
                )
                self.sleeper(delay)

            except (URLError, TimeoutError, ConnectionError, OSError) as net_err:
                last_exception = net_err
                if attempt >= max_retries:
                    break
                raw_delay = base_delay * (2 ** (attempt - 1))
                jitter = 0.01 if is_test else random.uniform(0.5, 1.5)
                delay = min(max_delay, raw_delay) + jitter
                logger.warning(
                    f"[OPENROUTER_NET_RETRY] Network connection error to OpenRouter (attempt {attempt}/{max_retries}): {net_err}. Retrying in {delay:.2f}s..."
                )
                self.sleeper(delay)

            except Exception as unk_err:
                logger.error(f"[OPENROUTER_ERROR] Unhandled error calling OpenRouter: {unk_err}")
                raise unk_err

        # All retries exhausted on OpenRouter
        self.mark_provider_exhausted("openrouter")
        err_msg = f"OpenRouter API retries exhausted after {max_retries} attempts: {last_exception}"
        logger.error(f"[OPENROUTER_EXHAUSTED] {err_msg}")
        raise GeminiQuotaExhaustedError(err_msg) from last_exception

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
        Executes text generation across configured AI providers:
        Primary Gemini -> Secondary Gemini -> Groq -> OpenRouter -> DeepSeek.
        Skips previously exhausted providers to prevent retry amplification.
        """
        all_providers = self._get_configured_providers(requested_model=model)
        if not all_providers:
            raise ValueError("No valid AI provider credentials (GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, DEEPSEEK_API_KEY) configured.")

        # Determine eligible providers (unexhausted first)
        available_providers = [p for p in all_providers if not self.is_provider_exhausted(p["name"])]

        if not available_providers:
            err_msg = "All configured AI providers (PRIMARY, SECONDARY, GROQ, OPENROUTER, DEEPSEEK) exhausted daily API quotas."
            logger.error(f"[AI_EXHAUSTED] {err_msg}")
            raise GeminiQuotaExhaustedError(err_msg)

        last_err = None

        for prov in available_providers:
            prov_name = prov["name"]
            prov_type = prov.get("type", "gemini")
            prov_key = prov["api_key"]
            prov_model = prov["model"]

            self.active_provider = prov_name
            logger.info(f"[AI_REQUEST] Dispatching request to provider '{prov_name.upper()}' (model: '{prov_model}')...")

            try:
                if prov_type == "groq":
                    result = self._execute_groq_request(
                        api_key=prov_key,
                        model=prov_model,
                        contents=contents,
                        max_retries=max_retries,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        **kwargs
                    )
                elif prov_type == "openrouter":
                    result = self._execute_openrouter_request(
                        api_key=prov_key,
                        model=prov_model,
                        contents=contents,
                        max_retries=max_retries,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        **kwargs
                    )
                elif prov_type == "deepseek":
                    result = self._execute_deepseek_request(
                        api_key=prov_key,
                        model=prov_model,
                        contents=contents,
                        max_retries=max_retries,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        **kwargs
                    )
                else:
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
                    next_prov = remaining[0]["name"].upper()
                    logger.warning(
                        f"[AI_FAILOVER] Provider '{prov_name.upper()}' quota/balance exhausted. "
                        f"Switching immediately to {next_prov} provider account (model: '{remaining[0]['model']}')..."
                    )
                    continue
                else:
                    logger.error(
                        "[AI_EXHAUSTED] All configured AI providers exhausted daily API quotas. Halting production cleanly."
                    )
                    raise GeminiQuotaExhaustedError(
                        "All configured AI providers exhausted daily API quotas."
                    ) from quota_err

        if last_err:
            raise last_err
        raise GeminiQuotaExhaustedError("All configured AI providers exhausted daily API quotas.")


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
    secondary_model: Optional[str] = None,
    groq_api_key: Optional[str] = None,
    groq_model: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
    openrouter_model: Optional[str] = None,
    deepseek_api_key: Optional[str] = None,
    deepseek_model: Optional[str] = None
) -> GeminiClient:
    global _SHARED_CLIENT
    with _INIT_LOCK:
        if _SHARED_CLIENT is None or api_key or secondary_api_key or groq_api_key or openrouter_api_key or deepseek_api_key:
            client = GeminiClient(
                api_key=api_key,
                secondary_api_key=secondary_api_key,
                secondary_model=secondary_model,
                groq_api_key=groq_api_key,
                groq_model=groq_model,
                openrouter_api_key=openrouter_api_key,
                openrouter_model=openrouter_model,
                deepseek_api_key=deepseek_api_key,
                deepseek_model=deepseek_model
            )
            if not api_key and not secondary_api_key and not groq_api_key and not openrouter_api_key and not deepseek_api_key:
                _SHARED_CLIENT = client
            return client
        return _SHARED_CLIENT
