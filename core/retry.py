"""
Centralized Transient Failure & Bounded Retry Utility (Phase 5.2).
Provides:
  - Explicit classification of retryable vs non-retryable exceptions.
  - Exponential backoff with jitter to prevent thundering herd.
  - Strict maximum retry counts and total elapsed time limits.
  - HTTP 429 rate limit & Retry-After / quota delay extraction.
  - Decorator (@retryable) and functional (retry_call) interfaces.
"""
import re
import time
import random
import logging
from functools import wraps
from typing import Callable, Any, Tuple, Optional, Type, Sequence, Union

logger = logging.getLogger(__name__)

# Default retry settings
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_FACTOR = 2.0
DEFAULT_MAX_TOTAL_TIMEOUT = 120.0

# HTTP Status codes classification
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 507, 529, 408}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 405, 409, 410, 411, 412, 413, 422}

# Text patterns indicating transient or rate-limit failures
TRANSIENT_TEXT_PATTERNS = [
    r"429",
    r"resource_exhausted",
    r"too many requests",
    r"rate limit",
    r"ratelimit",
    r"quota exceeded",
    r"service unavailable",
    r"gateway timeout",
    r"connection reset",
    r"connection refused",
    r"broken pipe",
    r"socket timeout",
    r"timed? out",
    r"temporarily unavailable",
    r"remote end closed connection",
    r"server disconnected"
]


def extract_retry_after(exc: Exception) -> Optional[float]:
    """
    Attempts to extract retry delay from HTTP headers or error payload:
    1. 'Retry-After' header from requests / googleapiclient HTTP responses.
    2. Google RPC RetryInfo 'retryDelay' string (e.g. '13s', '5.2s').
    3. Error message text containing retry suggestions.
    """
    # 1. Inspect response headers if available (requests, urllib, googleapiclient)
    response = getattr(exc, "response", None) or getattr(exc, "resp", None)
    if response:
        headers = getattr(response, "headers", {})
        if hasattr(headers, "get"):
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after:
                try:
                    return float(retry_after)
                except (ValueError, TypeError):
                    pass

    # 2. Inspect error text for Google RPC / Gemini retryDelay (e.g. 'retryDelay': '13s')
    msg = str(exc)
    delay_match = re.search(r"['\"]?retryDelay['\"]?:\s*['\"]?([0-9\.]+)s?['\"]?", msg, re.IGNORECASE)
    if delay_match:
        try:
            return float(delay_match.group(1))
        except (ValueError, TypeError):
            pass

    # 3. Look for "retry in Xs" or "retry after Xs"
    retry_in_match = re.search(r"retry in ([0-9\.]+)s", msg, re.IGNORECASE)
    if retry_in_match:
        try:
            return float(retry_in_match.group(1))
        except (ValueError, TypeError):
            pass

    return None


def is_retryable_exception(exc: Exception) -> Tuple[bool, Optional[float]]:
    """
    Evaluates whether an exception is transient and safe to retry.
    Returns (is_retryable, retry_after_seconds).
    """
    retry_after = extract_retry_after(exc)
    exc_type_name = type(exc).__name__
    exc_msg = str(exc).lower()

    # 1. Permanent programming or validation errors (Never retry)
    if isinstance(exc, (TypeError, ValueError, KeyError, IndexError, AttributeError, AssertionError, NotImplementedError)):
        return False, None

    # 2. Check HTTP status code if present
    status_code = None
    if hasattr(exc, "status_code"):
        status_code = exc.status_code
    elif hasattr(exc, "code"):
        status_code = exc.code
    elif hasattr(exc, "resp") and hasattr(exc.resp, "status"):
        status_code = exc.resp.status
    elif hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        status_code = exc.response.status_code

    if status_code is not None:
        try:
            status_code = int(status_code)
            if status_code in RETRYABLE_STATUS_CODES:
                return True, retry_after
            if status_code in NON_RETRYABLE_STATUS_CODES:
                # Special Google API edge-case: 403 with quotaExceeded reason
                if status_code == 403 and any(k in exc_msg for k in ["quotaexceeded", "ratelimitexceeded", "user_rate_limit"]):
                    return True, retry_after
                return False, None
        except (ValueError, TypeError):
            pass

    # 3. Standard Network / Socket / Timeout Exceptions (Always retry)
    transient_types = (
        TimeoutError,
        ConnectionError,
        ConnectionResetError,
        ConnectionRefusedError,
        ConnectionAbortedError
    )
    if isinstance(exc, transient_types):
        return True, retry_after

    # 4. Check for known SDK exception types by name
    if any(k in exc_type_name for k in [
        "Timeout", "ConnectError", "ConnectionError", "RemoteDisconnected",
        "ResourceExhausted", "ServiceUnavailable", "TooManyRequests",
        "DeadlineExceeded", "InternalServerError"
    ]):
        return True, retry_after

    # 5. Regex / Pattern scan over error message
    for pattern in TRANSIENT_TEXT_PATTERNS:
        if re.search(pattern, exc_msg, re.IGNORECASE):
            return True, retry_after

    # Default to False for unknown errors to prevent runaway loops
    return False, None


def compute_delay(
    attempt: int,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    factor: float = DEFAULT_FACTOR,
    jitter: bool = True,
    retry_after: Optional[float] = None
) -> float:
    """
    Calculates exponential backoff delay with jitter and respects server Retry-After.
    Formula: min(max_delay, base_delay * factor^(attempt - 1)) + jitter
    """
    raw_delay = base_delay * (factor ** (attempt - 1))
    capped_delay = min(max_delay, raw_delay)

    if jitter:
        # Full jitter between 0.75 * delay and 1.25 * delay
        actual_delay = random.uniform(0.75 * capped_delay, 1.25 * capped_delay)
    else:
        actual_delay = capped_delay

    if retry_after is not None and retry_after > 0:
        actual_delay = max(actual_delay, retry_after)

    return min(max_delay, max(0.01, actual_delay))


def retry_call(
    func: Callable[..., Any],
    args: Optional[Sequence[Any]] = None,
    kwargs: Optional[dict] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    factor: float = DEFAULT_FACTOR,
    max_total_timeout: float = DEFAULT_MAX_TOTAL_TIMEOUT,
    jitter: bool = True,
    retryable_exceptions: Optional[Sequence[Type[Exception]]] = None,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    custom_logger: Optional[logging.Logger] = None,
    sleeper: Callable[[float], None] = time.sleep
) -> Any:
    """
    Executes a callable with bounded exponential backoff on transient failures.
    """
    log = custom_logger or logger
    args = args or ()
    kwargs = kwargs or {}
    start_time = time.time()

    attempt = 1
    while True:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            # 1. Determine if exception is retryable
            if retryable_exceptions:
                is_retryable = isinstance(exc, tuple(retryable_exceptions))
                retry_after = extract_retry_after(exc)
            else:
                is_retryable, retry_after = is_retryable_exception(exc)

            func_name = getattr(func, "__name__", str(func))

            if not is_retryable:
                log.debug(f"[NON-RETRYABLE] '{func_name}' encountered permanent error {type(exc).__name__}: {exc}")
                raise exc

            # 2. Check retry bounds
            if attempt > max_retries:
                log.warning(f"[RETRY EXHAUSTED] '{func_name}' failed after {max_retries} retries ({type(exc).__name__}: {exc})")
                raise exc

            elapsed = time.time() - start_time
            if elapsed >= max_total_timeout:
                log.warning(f"[TIMEOUT EXHAUSTED] '{func_name}' exceeded max timeout ({elapsed:.1f}s >= {max_total_timeout:.1f}s)")
                raise exc

            # 3. Calculate delay
            delay = compute_delay(
                attempt=attempt,
                base_delay=base_delay,
                max_delay=max_delay,
                factor=factor,
                jitter=jitter,
                retry_after=retry_after
            )

            # Cap delay to not exceed total timeout
            if elapsed + delay > max_total_timeout:
                delay = max(0.01, max_total_timeout - elapsed)

            log.info(
                f"[RETRY {attempt}/{max_retries}] '{func_name}' transient failure ({type(exc).__name__}). "
                f"Backing off for {delay:.2f}s... (Elapsed: {elapsed:.1f}s)"
            )

            if on_retry:
                try:
                    on_retry(attempt, exc, delay)
                except Exception as cb_err:
                    log.debug(f"on_retry callback warning: {cb_err}")

            sleeper(delay)
            attempt += 1


def retryable(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    factor: float = DEFAULT_FACTOR,
    max_total_timeout: float = DEFAULT_MAX_TOTAL_TIMEOUT,
    jitter: bool = True,
    retryable_exceptions: Optional[Sequence[Type[Exception]]] = None,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    custom_logger: Optional[logging.Logger] = None
):
    """
    Decorator for wrapping functions in bounded transient retry logic.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return retry_call(
                func=func,
                args=args,
                kwargs=kwargs,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                factor=factor,
                max_total_timeout=max_total_timeout,
                jitter=jitter,
                retryable_exceptions=retryable_exceptions,
                on_retry=on_retry,
                custom_logger=custom_logger
            )
        return wrapper
    return decorator
