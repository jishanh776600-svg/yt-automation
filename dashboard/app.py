"""
FastAPI Real-Time Control Dashboard & Secured Operations Backend (App Phase 3).
Features:
- PBKDF2-HMAC-SHA256 authenticated operator sessions
- Cryptographic CSRF token validation on all state-changing endpoints
- Brute-force rate limiting and lockout protection
- Strict security headers (CSP, Frame protection, No-Sniff, No-Store)
- Hard enforcement of DAILY_SHORTS_LIMIT = 4 on remote API
- Live telemetry and functional pipeline controls
"""
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, Depends, Request, Response, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from config.settings import PROJECT_ROOT, DATABASE_DIR
from core.database import get_db, init_db
from dashboard.data_provider import SystemDataProvider
from dashboard.action_manager import ActionManager
from dashboard.auth import (
    SESSION_COOKIE_NAME,
    credentials_manager,
    session_store,
    rate_limiter,
    get_current_session,
    get_optional_session,
    verify_csrf_token
)

app = FastAPI(
    title="Historia Pipeline // Autonomous Control Center",
    description="Secured real-time control app and operations center for YouTube Shorts autonomous pipeline.",
    version="3.0.0"
)

TEMPLATES_DIR = PROJECT_ROOT / "dashboard" / "templates"
STATIC_DIR = PROJECT_ROOT / "dashboard" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Singletons connected to real system components
data_provider = SystemDataProvider()
action_manager = ActionManager()


# ==============================================================================
# SECURITY HEADERS MIDDLEWARE
# ==============================================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces strict security headers on all HTTP responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        # Prevent caching for sensitive control routes
        if request.url.path.startswith("/api") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# ==============================================================================
# PYDANTIC REQUEST MODELS
# ==============================================================================

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)


class ProduceBufferRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=8, description="Number of Shorts to produce")
    target: int = Field(default=12, ge=1, le=24, description="Target reserve count")


class PublishNextRequest(BaseModel):
    # Note: Hard DAILY_SHORTS_LIMIT = 4 invariant is strictly enforced. No remote force bypass.
    pass


class RetryJobRequest(BaseModel):
    job_id: str = Field(..., min_length=4, max_length=64, description="Job ID to retry")


class QuarantineJobRequest(BaseModel):
    job_id: str = Field(..., min_length=4, max_length=64, description="Job ID to quarantine")
    reason: str = Field(default="Quarantined by operator", max_length=256, description="Reason for quarantine")


class ReleaseLockRequest(BaseModel):
    lock_name: str = Field(..., pattern="^(production|publisher)$", description="Name of lock to release")
    force: bool = Field(default=False, description="Forcibly remove lock even if PID appears alive")


class SetVoiceRequest(BaseModel):
    voice_id: str = Field(..., min_length=2, max_length=64, description="Internal voice identifier")


class VoicePreviewRequest(BaseModel):
    voice_id: str = Field(..., min_length=2, max_length=64, description="Internal voice identifier to preview")


@app.on_event("startup")
def on_startup():
    init_db()
    # In cloud environments, safely materialize OAuth credentials from environment if provided
    token_json_env = os.getenv("TOKEN_JSON", "").strip()
    if token_json_env and not (PROJECT_ROOT / "token.json").exists():
        try:
            (PROJECT_ROOT / "token.json").write_text(token_json_env, encoding="utf-8")
        except Exception:
            pass

    client_secret_env = os.getenv("CLIENT_SECRET_JSON", "").strip()
    if client_secret_env and not (PROJECT_ROOT / "client_secret.json").exists():
        try:
            (PROJECT_ROOT / "client_secret.json").write_text(client_secret_env, encoding="utf-8")
        except Exception:
            pass


# ==============================================================================
# AUTHENTICATION & LOGIN ROUTES
# ==============================================================================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Renders the operator login screen."""
    session = get_optional_session(request)
    if session:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.post("/api/auth/login")
def api_login(req: LoginRequest, request: Request, response: Response):
    """Authenticates operator credentials and creates a secure session."""
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{req.username.strip().lower()}"

    # 1. Check Rate Limiter
    is_locked, remaining_sec = rate_limiter.is_locked_out(rate_key)
    if is_locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Account temporarily locked. Retry in {remaining_sec} seconds."
        )

    # 2. Verify Credentials
    is_valid = credentials_manager.verify_credentials(req.username, req.password)
    if not is_valid:
        is_locked_now, lock_sec = rate_limiter.record_failure(rate_key)
        if is_locked_now:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed attempts. Temporary lockout activated for {lock_sec} seconds."
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed. Invalid username or password."
        )

    # 3. Success: Clear rate limits & establish session
    rate_limiter.clear_failures(rate_key)
    session_id, csrf_token = session_store.create_session(req.username)

    # 4. Set HttpOnly Cookie
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=12 * 3600
    )

    return {
        "success": True,
        "message": "Authentication successful",
        "csrf_token": csrf_token
    }


@app.post("/api/auth/logout")
def api_logout(request: Request, response: Response):
    """Terminates session and clears cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session_store.invalidate_session(session_id)

    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"success": True, "message": "Session terminated successfully."}


# ==============================================================================
# SECURED UI ROUTE & CLOUD LIVENESS PROBE
# ==============================================================================

@app.get("/health")
def liveness_health_probe():
    """
    Lightweight, unauthenticated cloud liveness health check probe.
    Confirms web server is alive.
    Strictly does NOT call YouTube, Google Drive, GitHub Actions, or mutate database.
    """
    return {
        "status": "healthy",
        "service": "historia-mission-control",
        "version": "3.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@app.get("/manifest.json")
def pwa_manifest():
    """Serves the PWA Web App Manifest."""
    manifest_path = STATIC_DIR / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest not found")
    return FileResponse(str(manifest_path), media_type="application/manifest+json")


@app.get("/sw.js")
def pwa_service_worker():
    """Serves the PWA Service Worker."""
    sw_path = STATIC_DIR / "sw.js"
    if not sw_path.exists():
        raise HTTPException(status_code=404, detail="Service worker not found")
    return FileResponse(
        str(sw_path),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"}
    )


@app.get("/mobile", response_class=HTMLResponse)
def mobile_mission_control(request: Request, db: Session = Depends(get_db)):
    """Renders the emergency mobile mission control PWA interface."""
    session = get_optional_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    state = data_provider.get_full_system_state(db)
    return templates.TemplateResponse(
        request=request,
        name="mobile.html",
        context={
            "user": session["username"],
            "csrf_token": session["csrf_token"],
            "state": state
        }
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    """Renders the secured live mission control center dashboard."""
    session = get_optional_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # Check for mobile user-agent or query parameter
    user_agent = request.headers.get("user-agent", "").lower()
    is_mobile = any(m in user_agent for m in ["mobile", "android", "iphone", "ipod", "ipad"]) or request.query_params.get("mobile") == "true"
    if is_mobile and request.query_params.get("desktop") != "true":
        state = data_provider.get_full_system_state(db)
        return templates.TemplateResponse(
            request=request,
            name="mobile.html",
            context={
                "user": session["username"],
                "csrf_token": session["csrf_token"],
                "state": state
            }
        )

    state = data_provider.get_full_system_state(db)
    review_queue = action_manager.get_review_queue(db)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": session["username"],
            "csrf_token": session["csrf_token"],
            "state": state,
            "health": state["health"],
            "locks": state["locks"],
            "inventory": state["inventory"],
            "publishing": state["publishing"],
            "buffer": state["buffer"],
            "learning": state["learning"],
            "db_summary": state["database_summary"],
            "scheduled_queue": state["scheduled_queue"],
            "voice_config": state["voice_config"],
            "bgm_status": state["bgm_status"],
            "cloud_workflows": state["cloud_workflows"],
            "timeline": state["timeline"],
            "activity_feed": state["activity_feed"],
            "review_queue": review_queue,
            "database_sync": state.get("database_sync", {}),
            "service_quotas": state.get("service_quotas", {})
        }
    )


# ==============================================================================
# SECURED READ-ONLY TELEMETRY API ENDPOINTS
# ==============================================================================

@app.get("/api/state")
def api_full_state(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns complete real-time system state snapshot."""
    return data_provider.get_full_system_state(db)


@app.get("/api/health")
def api_health(session: Dict[str, Any] = Depends(get_current_session)):
    """Returns live automation health check diagnostics and warnings."""
    return data_provider.get_automation_health()


@app.get("/api/inventory")
def api_inventory(session: Dict[str, Any] = Depends(get_current_session)):
    """Returns real Google Drive Vault counts and file details."""
    return data_provider.get_drive_inventory()


@app.get("/api/publishing")
def api_publishing(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns daily publishing status, limit, remaining capacity, and next slot."""
    return data_provider.get_publishing_status(db)


@app.get("/api/buffer")
def api_buffer(session: Dict[str, Any] = Depends(get_current_session)):
    """Returns reserve buffer status, target reserve, and estimated runway."""
    return data_provider.get_buffer_status()


@app.get("/api/learning")
def api_learning(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns continuous learning loop metrics, pattern scores, and strategy weights."""
    return data_provider.get_learning_status(db)


@app.get("/api/scheduled")
def api_scheduled_queue(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns real-time YouTube scheduled publishing queue and reconciliation status."""
    return data_provider.get_scheduled_queue(db)


@app.get("/api/locks")
def api_locks(session: Dict[str, Any] = Depends(get_current_session)):
    """Returns active process locks and PID liveliness."""
    return data_provider.get_process_locks()


@app.get("/api/jobs/review-queue")
def api_review_queue(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns all jobs currently in NEEDS_REVIEW or FAILED state."""
    return action_manager.get_review_queue(db)


@app.get("/api/config/voice")
def api_voice_config(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns available production voice options and active voice setting."""
    return data_provider.get_voice_config(db)


@app.get("/api/bgm")
def api_bgm_status(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns 4-track BGM library status and recent BGM selections."""
    return data_provider.get_bgm_library_status(db)


@app.get("/api/timeline")
def api_production_timeline(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns multi-stage production and publishing lifecycle timeline."""
    return data_provider.get_production_timeline(db)


@app.get("/api/activity")
def api_activity_feed(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns chronological feed of real persisted system events."""
    return data_provider.get_activity_feed(db)


@app.get("/api/workflows")
def api_cloud_workflows(session: Dict[str, Any] = Depends(get_current_session)):
    """Returns configured cloud automation workflows, cron cadences, and expected execution times."""
    return data_provider.get_cloud_workflows_status()


@app.get("/api/quota/pexels")
def api_pexels_quota(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns observed Pexels API quota headers, request metrics, and status."""
    return data_provider.get_pexels_quota_status(db)


@app.get("/api/quotas")
def api_service_quotas(db: Session = Depends(get_db), session: Dict[str, Any] = Depends(get_current_session)):
    """Returns normalized real-time API and service limits for all external providers."""
    return data_provider.get_all_service_quotas(db)


# ==============================================================================
# SECURED REAL-WORLD FUNCTIONAL CONTROLS API (CSRF + AUTH PROTECTED)
# ==============================================================================

@app.post("/api/config/voice")
def api_set_voice(
    req: SetVoiceRequest,
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Updates and persists active production voice setting in SQLite.
    """
    result = action_manager.set_voice_preference(db, voice_id=req.voice_id)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/api/voice/preview")
def api_voice_preview(
    req: VoicePreviewRequest,
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Generates a safe short in-memory audio preview sample for the specified voice.
    Does NOT create a Job, does NOT touch Drive, does NOT touch YouTube,
    and does NOT persist or change the active voice setting.
    """
    import base64
    from engines.tts_engine import TTSEngine, AVAILABLE_VOICES

    # 1. Validate voice ID exists in configured catalog
    voice_entry = next((v for v in AVAILABLE_VOICES if v["id"] == req.voice_id), None)
    if not voice_entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid voice ID '{req.voice_id}'. Not in configured production voices."
        )

    tts = TTSEngine()
    success, audio_bytes, mime_type = tts.generate_preview_sample(req.voice_id)
    if not success or not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to synthesize voice preview for '{req.voice_id}'."
        )

    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
    return {
        "success": True,
        "voice_id": req.voice_id,
        "display_name": voice_entry["display_name"],
        "audio_url": f"data:{mime_type};base64,{b64_audio}"
    }

@app.post("/api/actions/reconcile-scheduled")
def api_action_reconcile_scheduled(
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Executes real YouTube-to-SQLite-to-Drive synchronization and state reconciliation.
    """
    result = action_manager.trigger_sync_youtube(db)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/api/actions/self-heal")
def api_action_self_heal(
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Executes full autonomous self-healing: stale job recovery, 02_PROCESSING recovery,
    YouTube sync, and Drive/SQLite read-first consistency check.
    """
    result = action_manager.trigger_self_healing(db)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/api/actions/produce")
def api_action_produce(
    req: ProduceBufferRequest,
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Executes real buffer production or replenishment under process lock.
    """
    result = action_manager.trigger_buffer_production(db, count=req.count, target=req.target)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/api/actions/publish-next")
def api_action_publish_next(
    req: PublishNextRequest,
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Claims next video from Google Drive 01_READY and uploads to YouTube.
    Strictly enforces DAILY_SHORTS_LIMIT = 4 as an unbypassable ceiling.
    """
    # Note: force is strictly False on the remote API layer
    result = action_manager.trigger_publish_next(db, force=False)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/api/actions/retry-job")
def api_action_retry_job(
    req: RetryJobRequest,
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Resets a failed or needs-review job back to QUEUED state for reprocessing.
    """
    result = action_manager.retry_job(db, job_id=req.job_id)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/api/actions/quarantine-job")
def api_action_quarantine_job(
    req: QuarantineJobRequest,
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Quarantines a job and moves any associated Drive files to 04_FAILED.
    """
    result = action_manager.quarantine_job(db, job_id=req.job_id, reason=req.reason)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/api/actions/release-lock")
def api_action_release_lock(
    req: ReleaseLockRequest,
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Safely inspects and releases a process lock if stale or if force=True.
    """
    result = action_manager.release_process_lock(lock_name=req.lock_name, force=req.force)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result
