"""
Mission Control API Router & Real-Time Endpoints (AL-AMR Step 4).
Exposes authenticated read operations and safe controlled mutations.
"""
import os
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from core.database import get_db
from dashboard.auth import (
    get_current_session,
    get_optional_session,
    verify_csrf_token
)
from dashboard.mission_control_service import mission_control_service

router = APIRouter(prefix="/api/mission-control", tags=["Mission Control"])


# ==============================================================================
# REQUEST SCHEMAS
# ==============================================================================

class OperationalModeRequest(BaseModel):
    mode: str = Field(..., description="AUTONOMOUS, PAUSED, SAFE_MODE, NEEDS_REVIEW, STOPPED, ERROR")
    reason: Optional[str] = Field(default="", description="Operator rationale for mode change")


class SwitchNicheRequest(BaseModel):
    niche: str = Field(..., description="Target niche profile name (e.g. CURRENT_AFFAIRS, HISTORICAL, SPACE_TECHNOLOGY, FINANCIAL_MARKETS)")


class QueueActionRequest(BaseModel):
    reason: Optional[str] = Field(default="Operator queue action", description="Rationale for queue pause/resume")


class JobActionRequest(BaseModel):
    job_id: str = Field(..., description="Target job UUID")
    reason: Optional[str] = Field(default="Operator action", description="Rationale for quarantine/cancel")


class ProduceBatchRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=5, description="Number of Shorts to produce")
    dry_run: bool = Field(default=True, description="Enforce dry-run safety boundary (default True)")


# ==============================================================================
# READ ENDPOINTS (TELEMETRY & OBSERVABILITY)
# ==============================================================================

@router.get("/state")
def get_state(
    db: Session = Depends(get_db),
    session: Optional[Dict[str, Any]] = Depends(get_optional_session)
):
    """Returns top-level operational state and Command Center telemetry."""
    op_state = mission_control_service.get_operational_state()
    telemetry = mission_control_service.get_command_center_telemetry(db)
    return {
        "operational_state": op_state,
        "telemetry": telemetry
    }


@router.get("/pipeline")
def get_pipeline(
    job_id: Optional[str] = None,
    db: Session = Depends(get_db),
    session: Optional[Dict[str, Any]] = Depends(get_optional_session)
):
    """Returns 16-stage pipeline visualization status."""
    return mission_control_service.get_pipeline_visualization(db, job_id=job_id)


@router.get("/queue")
def get_queue(
    limit: int = 50,
    db: Session = Depends(get_db),
    session: Optional[Dict[str, Any]] = Depends(get_optional_session)
):
    """Returns production queue list with stage and retry details."""
    return mission_control_service.get_production_queue(db, limit=limit)


@router.get("/topics")
def get_topics(
    limit: int = 50,
    db: Session = Depends(get_db),
    session: Optional[Dict[str, Any]] = Depends(get_optional_session)
):
    """Returns topic intelligence with multi-source consensus evidence status."""
    return mission_control_service.get_topic_intelligence(db, limit=limit)


@router.get("/jobs/{job_id}")
def get_job_details(
    job_id: str,
    db: Session = Depends(get_db),
    session: Optional[Dict[str, Any]] = Depends(get_optional_session)
):
    """Returns comprehensive 16-stage job inspection."""
    try:
        return mission_control_service.get_job_inspector(db, job_id=job_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/health")
def get_health(
    db: Session = Depends(get_db),
    session: Optional[Dict[str, Any]] = Depends(get_optional_session)
):
    """Returns operational health matrix across all 6 subsystems."""
    return mission_control_service.get_system_health(db)


@router.get("/events")
def get_events(
    limit: int = 50,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    session: Optional[Dict[str, Any]] = Depends(get_optional_session)
):
    """Returns filterable real-time audit event stream."""
    return {
        "events": mission_control_service.get_audit_events(limit=limit, category=category, severity=severity)
    }


@router.get("/niches")
def get_niches(session: Optional[Dict[str, Any]] = Depends(get_optional_session)):
    """Returns all dynamically registered niches."""
    return {
        "niches": mission_control_service.get_available_niches()
    }


@router.get("/runtime")
def get_runtime_status(session: Optional[Dict[str, Any]] = Depends(get_optional_session)):
    """Returns authoritative autonomous runtime worker status and telemetry."""
    return mission_control_service.get_runtime_status()


@router.get("/stream")
async def get_realtime_stream(request: Request):
    """
    Server-Sent Events (SSE) live streaming endpoint.
    Emits real-time state changes, stage transitions, and audit events.
    """
    return StreamingResponse(
        mission_control_service.subscribe_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ==============================================================================
# MUTATION ENDPOINTS (SAFE CONTROLLED OPERATIONS)
# ==============================================================================

@router.post("/actions/mode")
def set_mode(
    req: OperationalModeRequest,
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """Sets system operational mode (AUTONOMOUS, PAUSED, SAFE_MODE, etc.)."""
    try:
        return mission_control_service.set_operational_mode(mode=req.mode, reason=req.reason)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/actions/niche")
def switch_niche(
    req: SwitchNicheRequest,
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """Dynamically switches active niche profile."""
    try:
        operator = session.get("username", "operator")
        return mission_control_service.switch_niche(niche_name=req.niche, operator=operator)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/actions/queue/pause")
def pause_queue(
    req: QueueActionRequest,
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """Safely pauses the production queue."""
    return mission_control_service.pause_queue(reason=req.reason or "Paused by operator")


@router.post("/actions/queue/resume")
def resume_queue(
    req: QueueActionRequest,
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """Safely resumes the production queue."""
    return mission_control_service.resume_queue(reason=req.reason or "Resumed by operator")


@router.post("/actions/job/retry")
def retry_job(
    req: JobActionRequest,
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """Safely retries a failed or reviewed job by resetting state to QUEUED."""
    try:
        operator = session.get("username", "operator")
        return mission_control_service.retry_job(db=db, job_id=req.job_id, operator=operator)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/actions/job/quarantine")
def quarantine_job(
    req: JobActionRequest,
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """Quarantines a job to NEEDS_REVIEW state."""
    try:
        return mission_control_service.quarantine_job(db=db, job_id=req.job_id, reason=req.reason or "Quarantined by operator")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/actions/job/cancel")
def cancel_job(
    req: JobActionRequest,
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """Cancels a job, setting state to FAILED."""
    try:
        return mission_control_service.cancel_job(db=db, job_id=req.job_id, reason=req.reason or "Cancelled by operator")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/actions/produce")
def produce_batch(
    req: ProduceBatchRequest,
    db: Session = Depends(get_db),
    session: Dict[str, Any] = Depends(get_current_session),
    csrf_valid: bool = Depends(verify_csrf_token)
):
    """
    Triggers an autonomous production batch.
    Enforces dry-run safety boundary by default to prevent unauthorized external mutations.
    """
    try:
        return mission_control_service.trigger_autonomous_batch(
            db=db,
            count=req.count,
            force_dry_run=req.dry_run
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
