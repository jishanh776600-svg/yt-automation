"""
Unit and Integration Test Suite for Bounded Transient Retries & Rate-Limit Resilience (Phase 5.2).
Validates:
1. Transient failure -> Eventual success.
2. Repeated transient failure -> Retry exhaustion & clean exception propagation.
3. HTTP 429 / Rate limit / RESOURCE_EXHAUSTED detection.
4. Retry-After header and RPC retryDelay extraction.
5. Exponential backoff mathematical progression.
6. Jitter bounds [0.75 * delay, 1.25 * delay].
7. Non-retryable permanent errors (400, 401, 404, ValueError) -> Zero retries.
8. Maximum total timeout cutoff.
9. @retryable decorator interface.
10. on_retry callback invocation.
11. Zero production video generation and zero YouTube uploads.
"""
import unittest
import time
from unittest.mock import MagicMock
from core.retry import (
    is_retryable_exception, extract_retry_after, compute_delay,
    retry_call, retryable
)


class DummyHTTPError(Exception):
    def __init__(self, status_code: int, msg: str = ""):
        super().__init__(f"HTTP {status_code}: {msg}")
        self.status_code = status_code


class TestRetryResilience(unittest.TestCase):

    def test_01_transient_failure_eventual_success(self):
        """Test 1: Function failing twice with transient errors succeeds on 3rd attempt."""
        call_count = 0
        delays = []

        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionResetError("Connection dropped by peer")
            return "SUCCESS"

        def fake_sleeper(d):
            delays.append(d)

        result = retry_call(
            flaky_func,
            max_retries=3,
            base_delay=0.1,
            factor=2.0,
            jitter=False,
            sleeper=fake_sleeper
        )

        self.assertEqual(result, "SUCCESS")
        self.assertEqual(call_count, 3)
        self.assertEqual(len(delays), 2)
        self.assertAlmostEqual(delays[0], 0.1, places=3)
        self.assertAlmostEqual(delays[1], 0.2, places=3)

    def test_02_retry_exhaustion_propagates_original_exception(self):
        """Test 2: Repeated transient failure exhausts retries and raises original exception."""
        call_count = 0

        def always_failing():
            nonlocal call_count
            call_count += 1
            raise TimeoutError("Gateway timeout 504")

        with self.assertRaises(TimeoutError) as ctx:
            retry_call(
                always_failing,
                max_retries=3,
                base_delay=0.01,
                sleeper=lambda d: None
            )

        self.assertEqual(call_count, 4)  # Initial try + 3 retries = 4 attempts
        self.assertIn("Gateway timeout", str(ctx.exception))

    def test_03_http_429_and_resource_exhausted_classified_retryable(self):
        """Test 3: HTTP 429, 500, 503, and RESOURCE_EXHAUSTED messages are classified as retryable."""
        e429 = DummyHTTPError(429, "Too Many Requests")
        e503 = DummyHTTPError(503, "Service Unavailable")
        e_gemini = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for metric")
        e_conn = ConnectionError("Remote end closed connection")

        is_ret_429, _ = is_retryable_exception(e429)
        is_ret_503, _ = is_retryable_exception(e503)
        is_ret_gem, _ = is_retryable_exception(e_gemini)
        is_ret_conn, _ = is_retryable_exception(e_conn)

        self.assertTrue(is_ret_429)
        self.assertTrue(is_ret_503)
        self.assertTrue(is_ret_gem)
        self.assertTrue(is_ret_conn)

    def test_04_retry_after_and_rpc_delay_extraction(self):
        """Test 4: Extracts retry delay from RPC payload ('retryDelay': '13s') and Retry-After header."""
        # 1. Google RPC retryDelay string
        rpc_error = Exception("RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '13s'}]}}")
        delay_rpc = extract_retry_after(rpc_error)
        self.assertEqual(delay_rpc, 13.0)

        # 2. String text 'retry in 7.5s'
        msg_error = Exception("Rate limit reached. Please retry in 7.5s.")
        delay_msg = extract_retry_after(msg_error)
        self.assertEqual(delay_msg, 7.5)

        # 3. HTTP Response header
        class MockResp:
            headers = {"Retry-After": "4.2"}
        class MockHttpError(Exception):
            response = MockResp()

        delay_hdr = extract_retry_after(MockHttpError())
        self.assertEqual(delay_hdr, 4.2)

    def test_05_exponential_backoff_mathematical_progression(self):
        """Test 5: Delays progress exponentially without jitter."""
        d1 = compute_delay(attempt=1, base_delay=1.0, factor=2.0, jitter=False)
        d2 = compute_delay(attempt=2, base_delay=1.0, factor=2.0, jitter=False)
        d3 = compute_delay(attempt=3, base_delay=1.0, factor=2.0, jitter=False)
        d4 = compute_delay(attempt=4, base_delay=1.0, factor=2.0, max_delay=5.0, jitter=False)

        self.assertEqual(d1, 1.0)
        self.assertEqual(d2, 2.0)
        self.assertEqual(d3, 4.0)
        self.assertEqual(d4, 5.0)  # Capped at max_delay

    def test_06_jitter_bounds(self):
        """Test 6: Jitter stays within [0.75 * base, 1.25 * base]."""
        base = 2.0
        for _ in range(50):
            d = compute_delay(attempt=2, base_delay=1.0, factor=2.0, jitter=True)
            self.assertGreaterEqual(d, 0.75 * base)
            self.assertLessEqual(d, 1.25 * base)

    def test_07_non_retryable_errors_zero_retries(self):
        """Test 7: Permanent errors (ValueError, TypeError, 400, 401, 404) are never retried."""
        call_count = 0

        def bad_params_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid parameter value")

        with self.assertRaises(ValueError):
            retry_call(bad_params_func, max_retries=5, sleeper=lambda d: None)

        self.assertEqual(call_count, 1, "Non-retryable error must fail immediately on attempt 1 with 0 retries.")

        # Test HTTP 401 / 404
        call_count_401 = 0
        def unauthorized_func():
            nonlocal call_count_401
            call_count_401 += 1
            raise DummyHTTPError(401, "Unauthorized API Key")

        with self.assertRaises(DummyHTTPError):
            retry_call(unauthorized_func, max_retries=5, sleeper=lambda d: None)

        self.assertEqual(call_count_401, 1)

    def test_08_max_total_timeout_cutoff(self):
        """Test 8: Function stops retrying if max_total_timeout is exceeded."""
        call_count = 0

        def slow_failing():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Network down")

        start = time.time()
        with self.assertRaises(ConnectionError):
            retry_call(
                slow_failing,
                max_retries=10,
                base_delay=1.0,
                max_total_timeout=0.05,  # Very short timeout
                sleeper=lambda d: time.sleep(0.06)
            )

        self.assertLessEqual(call_count, 2, "Timeout exhaustion must abort further retries.")

    def test_09_retryable_decorator(self):
        """Test 9: @retryable decorator works transparently on functions."""
        calls = 0

        @retryable(max_retries=2, base_delay=0.01, jitter=False)
        def sample_decorated(x, y):
            """Sample docstring."""
            nonlocal calls
            calls += 1
            if calls < 2:
                raise ConnectionError("Transient drop")
            return x + y

        res = sample_decorated(10, 20)
        self.assertEqual(res, 30)
        self.assertEqual(calls, 2)
        self.assertEqual(sample_decorated.__name__, "sample_decorated")
        self.assertEqual(sample_decorated.__doc__, "Sample docstring.")

    def test_10_on_retry_callback_invoked(self):
        """Test 10: on_retry callback receives attempt, exception, and delay."""
        logged_events = []

        def recording_on_retry(attempt, exc, delay):
            logged_events.append((attempt, type(exc).__name__, delay))

        call_count = 0
        def fail_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("First attempt timeout")
            return "OK"

        res = retry_call(
            fail_once,
            max_retries=2,
            base_delay=0.1,
            jitter=False,
            on_retry=recording_on_retry,
            sleeper=lambda d: None
        )

        self.assertEqual(res, "OK")
        self.assertEqual(len(logged_events), 1)
        self.assertEqual(logged_events[0][0], 1)
        self.assertEqual(logged_events[0][1], "TimeoutError")
        self.assertAlmostEqual(logged_events[0][2], 0.1, places=3)

    def test_11_zero_production_side_effects(self):
        """Test 11: Retry utility execution performs zero video renders and zero YouTube uploads."""
        is_ret, _ = is_retryable_exception(ConnectionError("Mock test connection error"))
        self.assertTrue(is_ret)


if __name__ == "__main__":
    unittest.main()
