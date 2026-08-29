"""
Test suite initialization.
Configures test-mode environment variables so tests do not rely on production secrets.
"""
import os

# Ensure clean test fixture for dashboard auth if not provided
if not os.getenv("DASHBOARD_ADMIN_PASSWORD") and not os.getenv("ADMIN_PASSWORD_HASH"):
    os.environ["DASHBOARD_ADMIN_PASSWORD"] = "TestOnlyMockPassword_2026!LocalTestFixture"
