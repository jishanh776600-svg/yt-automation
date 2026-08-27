"""
FastAPI Real-Time Dashboard.
Displays active pipeline jobs, state transitions, review queue, free quota tracking,
and the Continuous Learning & Intelligence Loop.
"""
from pathlib import Path
from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from config.settings import PROJECT_ROOT, DATABASE_DIR
from core.database import get_db, init_db
from core.models import Job, Topic, AssetRecord, QAReport, UploadRecord, JobLog, ContentPattern, VideoAnalysisRecord, ExperimentRecord, PerformanceSnapshot

app = FastAPI(title="History Shorts Intelligence Dashboard")

TEMPLATES_DIR = PROJECT_ROOT / "dashboard" / "templates"
STATIC_DIR = PROJECT_ROOT / "dashboard" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.updated_at.desc()).limit(20).all()
    topics = db.query(Topic).order_by(Topic.created_at.desc()).limit(10).all()
    uploads = db.query(UploadRecord).order_by(UploadRecord.created_at.desc()).limit(10).all()
    qa_reports = db.query(QAReport).order_by(QAReport.created_at.desc()).limit(10).all()
    patterns = db.query(ContentPattern).order_by(ContentPattern.composite_effectiveness_score.desc()).all()
    analyses = db.query(VideoAnalysisRecord).order_by(VideoAnalysisRecord.analyzed_at.desc()).limit(10).all()
    experiments = db.query(ExperimentRecord).order_by(ExperimentRecord.created_at.desc()).limit(10).all()

    # Calculate statistics
    total_jobs = db.query(Job).count()
    needs_review_count = db.query(Job).filter(Job.state == "NEEDS_REVIEW").count()
    published_count = len(uploads)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "jobs": jobs,
            "topics": topics,
            "uploads": uploads,
            "qa_reports": qa_reports,
            "patterns": patterns,
            "analyses": analyses,
            "experiments": experiments,
            "total_jobs": total_jobs,
            "needs_review_count": needs_review_count,
            "published_count": published_count,
        }
    )


@app.get("/api/status")
def api_status(db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.updated_at.desc()).limit(10).all()
    patterns = db.query(ContentPattern).order_by(ContentPattern.composite_effectiveness_score.desc()).limit(5).all()
    return {
        "status": "online",
        "total_jobs": db.query(Job).count(),
        "active_jobs": [j.id for j in jobs if j.state not in ["PUBLISHED", "FAILED"]],
        "top_patterns": [{"key": p.pattern_key, "score": p.composite_effectiveness_score, "confidence": p.confidence} for p in patterns]
    }
