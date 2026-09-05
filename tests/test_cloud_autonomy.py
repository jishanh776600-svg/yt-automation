r"""
Tests for 100% Cloud Autonomy of the AL-AMR System.
Verifies:
1. Zero hardcoded personal filesystem paths (e.g. C:\Users) in production configuration.
2. Complete absence of local browser/GUI/Antigravity dependencies in production code.
3. Phase 1 & 2 components operate entirely via standard headless HTTP/ONNX/SQLite.
4. requirements.txt contains all necessary production dependencies for cloud runners.
5. GitHub Actions workflows use correct cloud configurations and enforce production invariants.
"""
import inspect
import sys
from pathlib import Path
import pytest

from config import settings, constants


def test_production_settings_paths_are_relative():
    """Verify all production directory paths in settings are derived from PROJECT_ROOT."""
    project_root = settings.PROJECT_ROOT
    assert project_root.is_absolute()
    assert str(project_root) != ""

    for attr in [
        "DATA_DIR", "DATABASE_DIR", "TOPICS_DIR", "RESEARCH_DIR",
        "SCRIPTS_DIR", "STORYBOARDS_DIR", "ASSETS_CACHE_DIR", "VOICE_DIR",
        "CAPTIONS_DIR", "RENDERS_DIR", "PUBLISHED_DIR", "LOGS_DIR",
        "ASSETS_DIR", "MUSIC_DIR", "SFX_DIR", "FONTS_DIR", "LOCKS_DIR"
    ]:
        p = getattr(settings, attr)
        assert isinstance(p, Path)
        # Ensure path is a child of project_root
        assert str(p).startswith(str(project_root)), f"{attr} ({p}) is not relative to PROJECT_ROOT ({project_root})"


def test_no_antigravity_or_browser_in_production_modules():
    """Verify production modules do not import or require Antigravity, local browsers, or dev tools."""
    production_modules = [
        "sources.news_ingestion",
        "sources.extractor",
        "sources.gdelt_adapter",
        "sources.rss_sources",
        "intelligence.clustering",
        "intelligence.verification",
        "intelligence.event_card",
        "intelligence.freshness",
        "intelligence.scoring",
        "intelligence.deduplication",
        "engines.topic_discovery",
        "engines.script_engine",
        "core.database",
        "core.database_sync",
    ]

    prohibited_terms = ["antigravity", "selenium", "playwright", "pyppeteer", "pyautogui", "keyboard"]

    for mod_name in production_modules:
        mod = sys.modules.get(mod_name)
        if mod is None:
            __import__(mod_name)
            mod = sys.modules[mod_name]

        source_code = inspect.getsource(mod).lower()
        for term in prohibited_terms:
            assert f"import {term}" not in source_code, f"Found 'import {term}' in {mod_name}"
            assert f"from {term}" not in source_code, f"Found 'from {term}' in {mod_name}"


def test_requirements_txt_contains_phase1_and_phase2_deps():
    """Verify requirements.txt includes fastembed, trafilatura, and feedparser."""
    req_path = settings.PROJECT_ROOT / "requirements.txt"
    assert req_path.exists()
    content = req_path.read_text(encoding="utf-8").lower()

    assert "feedparser" in content, "feedparser missing from requirements.txt"
    assert "trafilatura" in content, "trafilatura missing from requirements.txt"
    assert "fastembed" in content, "fastembed missing from requirements.txt"


def test_github_workflow_produce_buffer_voice_lock():
    """Verify produce_buffer.yml enforces af_sarah as the default voice."""
    wf_path = settings.PROJECT_ROOT / ".github" / "workflows" / "produce_buffer.yml"
    assert wf_path.exists()
    content = wf_path.read_text(encoding="utf-8")

    assert "default: 'af_sarah'" in content, "produce_buffer.yml does not default active_voice to af_sarah"
    assert "default: 'af_bella'" not in content, "produce_buffer.yml still contains af_bella default"


def test_github_workflows_run_headless():
    """Verify GitHub Actions workflows specify ubuntu-latest and headless installations."""
    workflows = [
        settings.PROJECT_ROOT / ".github" / "workflows" / "autopilot.yml",
        settings.PROJECT_ROOT / ".github" / "workflows" / "produce_buffer.yml",
        settings.PROJECT_ROOT / ".github" / "workflows" / "harvest_analytics.yml",
    ]

    for wf in workflows:
        assert wf.exists(), f"Workflow {wf.name} not found"
        content = wf.read_text(encoding="utf-8")
        assert "runs-on: ubuntu-latest" in content
        assert "pip install -r requirements.txt" in content


def test_phase1_and_phase2_zero_desktop_dependency():
    """Verify NewsIngestionService and EventClusterEngine don't depend on user's Desktop folder."""
    from sources.news_ingestion import NewsIngestionService
    from intelligence.clustering import EventClusterEngine
    from intelligence.event_card import EventCard

    # Inspect source code of these classes
    for cls in [NewsIngestionService, EventClusterEngine, EventCard]:
        source = inspect.getsource(cls).lower()
        assert "desktop" not in source, f"Class {cls.__name__} references 'desktop' in source code"


def test_sfx_remains_permanently_disabled_in_production():
    """Verify production BGM/SFX invariants."""
    from config.settings import APPROVED_PRODUCTION_VOICES
    from engines.visual_intelligence.voice_policy import VoiceVariationPolicy
    policy = VoiceVariationPolicy()
    decision = policy.select_voice_and_delivery(
        category="geopolitics", title="Crisis Update", script_text="Forces advanced."
    )
    assert decision.bgm_policy == "NONE"
    assert decision.voice_id == "af_sarah"
    assert "af_sarah" in APPROVED_PRODUCTION_VOICES

