"""
Authentication, Session Management, CSRF & Security Subsystem (App Phase 3).
Provides:
- PBKDF2-HMAC-SHA256 password hashing with cryptographic salt
- Secure HttpOnly session management with expiration
- Cryptographic CSRF token verification for state-changing endpoints
- Brute-force rate limiting and lockout protection
- FastAPI dependency injection for route protection
"""
import os
import time
import hmac
import hashlib
import secrets
import logging
import threading
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

# Default Admin Configuration from Environment (Never hardcoded in source)
DEFAULT_ADMIN_USER = os.getenv("DASHBOARD_ADMIN_USER") or os.getenv("ADMIN_USERNAME") or "admin"
DEFAULT_ADMIN_PASSWORD = os.getenv("DASHBOARD_ADMIN_PASSWORD", "")

SESSION_COOKIE_NAME = "historia_session_id"
SESSION_DURATION_HOURS = 12
PBKDF2_ITERATIONS = 600000


class PasswordHasher:
    """Secure password hashing using PBKDF2-HMAC-SHA256 with per-user cryptographic salts."""

    @staticmethod
    def hash_password(password: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
        """Hashes password using PBKDF2-HMAC-SHA256. Returns (hash_hex, salt_hex)."""
        if salt is None:
            salt = secrets.token_bytes(16)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS
        )
        return key.hex(), salt.hex()

    @staticmethod
    def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
        """Verifies candidate password in constant time to prevent timing attacks."""
        try:
            salt = bytes.fromhex(salt_hex)
            expected_hash = bytes.fromhex(hash_hex)
            computed_hash = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                PBKDF2_ITERATIONS
            )
            return hmac.compare_digest(computed_hash, expected_hash)
        except Exception as e:
            logger.warning(f"Password verification error: {e}")
            return False


class CredentialsManager:
    """Manages secure runtime storage of administrator credentials with fail-closed security."""

    def __init__(self):
        self.reload()

    def reload(self):
        """Reloads credentials from environment variables, failing closed if none configured."""
        self.username = os.getenv("DASHBOARD_ADMIN_USER") or os.getenv("ADMIN_USERNAME") or "admin"
        admin_pass = os.getenv("DASHBOARD_ADMIN_PASSWORD")
        password_hash = os.getenv("ADMIN_PASSWORD_HASH")

        self.hash_hex = None
        self.salt_hex = None
        self.is_configured = False

        if password_hash:
            # Parse format: e.g. "pbkdf2_sha256$iterations$salt$hash" or "salt$hash" or "salt:hash"
            parts = password_hash.split("$")
            if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
                # pbkdf2_sha256$iterations$salt$hash
                self.salt_hex = parts[2]
                self.hash_hex = parts[3]
                self.is_configured = True
            elif len(parts) == 2:
                self.salt_hex = parts[0]
                self.hash_hex = parts[1]
                self.is_configured = True
            elif ":" in password_hash:
                p_parts = password_hash.split(":")
                if len(p_parts) == 2:
                    self.salt_hex = p_parts[0]
                    self.hash_hex = p_parts[1]
                    self.is_configured = True
            else:
                logger.error("[AUTH_SECURITY] Unrecognized ADMIN_PASSWORD_HASH format.")
        elif admin_pass:
            self.hash_hex, self.salt_hex = PasswordHasher.hash_password(admin_pass)
            self.is_configured = True
        else:
            # FAIL CLOSED: No password or hash is configured.
            logger.warning("[AUTH_SECURITY] No admin password or hash configured. Dashboard login is disabled.")
            self.is_configured = False

    def verify_credentials(self, username: str, password: str) -> bool:
        """Verifies username and password in constant time. Fails closed if not configured."""
        if not self.is_configured or not self.hash_hex or not self.salt_hex:
            logger.warning("[AUTH_SECURITY] Login attempted but admin credentials are not configured. Rejection enforced.")
            return False
        if not username or not password:
            return False
        user_matches = hmac.compare_digest(username.strip(), self.username.strip())
        password_matches = PasswordHasher.verify_password(password, self.hash_hex, self.salt_hex)
        return user_matches and password_matches


class SessionStore:
    """Thread-safe in-memory authenticated session store."""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_session(self, username: str, duration_hours: int = SESSION_DURATION_HOURS) -> Tuple[str, str]:
        """Creates a new session and returns (session_id, csrf_token)."""
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_hex(32)
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=duration_hours)

        with self._lock:
            self._sessions[session_id] = {
                "username": username,
                "created_at": now,
                "expires_at": expires_at,
                "csrf_token": csrf_token
            }
            # Clean up stale sessions
            self._purge_expired_locked()

        return session_id, csrf_token

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves active session if valid and unexpired."""
        if not session_id:
            return None

        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            if datetime.utcnow() > session["expires_at"]:
                del self._sessions[session_id]
                return None

            return dict(session)

    def invalidate_session(self, session_id: str) -> bool:
        """Removes session from store on logout."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def _purge_expired_locked(self):
        """Purges expired sessions while lock is held."""
        now = datetime.utcnow()
        expired_keys = [k for k, s in self._sessions.items() if s["expires_at"] < now]
        for k in expired_keys:
            del self._sessions[k]


class LoginRateLimiter:
    """Rate limiter preventing brute-force login attempts."""

    def __init__(self, max_attempts: int = 5, window_sec: int = 300, lockout_sec: int = 900):
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self.lockout_sec = lockout_sec
        self._attempts: Dict[str, List[float]] = {}
        self._lockouts: Dict[str, float] = {}
        self._lock = threading.Lock()

    def record_failure(self, client_key: str) -> Tuple[bool, int]:
        """
        Records a failed attempt. Returns (is_locked_out, seconds_remaining).
        """
        now = time.time()
        with self._lock:
            # Check existing lockout
            if client_key in self._lockouts:
                remaining = int(self._lockouts[client_key] - now)
                if remaining > 0:
                    return True, remaining
                else:
                    del self._lockouts[client_key]

            # Record attempt
            if client_key not in self._attempts:
                self._attempts[client_key] = []
            
            # Prune attempts outside window
            self._attempts[client_key] = [t for t in self._attempts[client_key] if now - t < self.window_sec]
            self._attempts[client_key].append(now)

            if len(self._attempts[client_key]) >= self.max_attempts:
                lockout_until = now + self.lockout_sec
                self._lockouts[client_key] = lockoutout = lockout_until
                return True, self.lockout_sec

            return False, 0

    def is_locked_out(self, client_key: str) -> Tuple[bool, int]:
        """Checks if client is currently locked out."""
        now = time.time()
        with self._lock:
            if client_key in self._lockouts:
                remaining = int(self._lockouts[client_key] - now)
                if remaining > 0:
                    return True, remaining
                else:
                    del self._lockouts[client_key]
            return False, 0

    def clear_failures(self, client_key: str):
        """Clears failed attempts upon successful login."""
        with self._lock:
            self._attempts.pop(client_key, None)
            self._lockouts.pop(client_key, None)


# Global Singleton Security Services
credentials_manager = CredentialsManager()
session_store = SessionStore()
rate_limiter = LoginRateLimiter(max_attempts=5, window_sec=300, lockout_sec=900)


# ==============================================================================
# FASTAPI DEPENDENCIES & GUARDS
# ==============================================================================

def get_current_session(request: Request) -> Dict[str, Any]:
    """
    FastAPI dependency that enforces authentication.
    Returns session dict if valid; raises HTTP 401 Unauthorized for API requests.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Missing session cookie."
        )

    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid or expired. Please log in again."
        )

    return session


def get_optional_session(request: Request) -> Optional[Dict[str, Any]]:
    """Returns active session or None without raising exception."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    return session_store.get_session(session_id)


def verify_csrf_token(request: Request, session: Dict[str, Any] = Depends(get_current_session)) -> bool:
    """
    FastAPI dependency verifying CSRF token for state-changing POST requests.
    Checks X-CSRF-Token header against active session.
    """
    token = request.headers.get("X-CSRF-Token")
    if not token:
        # Also check form/query param if submitted as form
        token = request.query_params.get("csrf_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF verification failed: Missing X-CSRF-Token header."
        )

    expected = session.get("csrf_token", "")
    if not hmac.compare_digest(token.strip(), expected.strip()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF verification failed: Token mismatch."
        )

    return True
