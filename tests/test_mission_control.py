"""
Targeted Test Suite for AL-AMR Step 4: Mission Control Autonomous Control Plane & Web Application.

Verifies:
1. Operational state management & mode transitions (AUTONOMOUS, PAUSED, SAFE_MODE, NEEDS_REVIEW, etc.)
2. Safe queue pause & resume operations
3. Dynamic niche switching through ContentProfile & DiscoveryProfile synchronization
4. Safe job retry state transitions (FAILED/NEEDS_REVIEW -> QUEUED)
5. Safe job quarantine & cancellation
6. Non-bypassable safety boundary on batch production
7. Command Center live telemetry generation
8. 16-stage pipeline visualization derivation
9. Topic intelligence evidence gate evaluation (>= 2 domains -> VERIFIED, 1 domain -> INSUFFICIENT EVIDENCE)
10. Deep 16-stage job inspector
11. 6-quadrant system health matrix (Intelligence, AI, Production, Media, Storage, Publication)
12. Real-time audit event stream & category/severity filtering
13. SSE real-time streaming endpoint
14. REST API read endpoints integration
15. REST API mutation endpoints security & validation
16. HTML rendering & responsiveness verification (GET / and GET /mission-control)
17. AST architectural audit (zero hardcoded niche conditionals)
"""
import ast
import uuid
import unittest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.database import SessionLocal, get_db
from core.models import (
    Job, Topic, ScriptRecord, AssetRecord, RenderOutput, QAReport,
    UploadRecord, SourceRecord, ClaimRecord
)
from config.constants import JobState, DAILY_SHORTS_LIMIT
from core.content_profile import (
    get_active_profile, set_active_profile, get_profile_by_name,
    list_registered_profiles, CURRENT_AFFAIRS_PROFILE
)
from core.discovery_profile import get_active_discovery_profile
from dashboard.app import app
from dashboard.mission_control_service import (
    MissionControlService, mission_control_service, PIPELINE_STAGES
)
from dashboard.auth import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD


class TestMissionControl(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        login_res = cls.client.post("/api/auth/login", json={
            "username": DEFAULT_ADMIN_USER,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        cls.csrf_token = login_res.json().get("csrf_token", "")
        cls.auth_headers = {
            "X-CSRF-Token": cls.csrf_token
        }
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        set_active_profile(None)

    def setUp(self):
        self.service = MissionControlService()

    # ==========================================================================
    # 1. OPERATIONAL STATE MANAGEMENT
    # ==========================================================================

    def test_01_operational_mode_transitions(self):
        """Test 1: Verifies operational state starts in AUTONOMOUS and safely transitions."""
        state = self.service.get_operational_state()
        self.assertEqual(state["mode"], "AUTONOMOUS")
        self.assertFalse(state["queue_paused"])

        # Transition to PAUSED
        res_pause = self.service.set_operational_mode("PAUSED", reason="Routine operator inspection")
        self.assertEqual(res_pause["mode"], "PAUSED")
        self.assertTrue(res_pause["queue_paused"])

        # Transition to SAFE_MODE
        res_safe = self.service.set_operational_mode("SAFE_MODE")
        self.assertEqual(res_safe["mode"], "SAFE_MODE")

        # Transition to NEEDS_REVIEW
        res_review = self.service.set_operational_mode("NEEDS_REVIEW", reason="QA failure detected")
        self.assertEqual(res_review["mode"], "NEEDS_REVIEW")
        self.assertTrue(res_review["queue_paused"])

        # Reject invalid mode
        with self.assertRaises(ValueError):
            self.service.set_operational_mode("HYPER_DRIVE")

    # ==========================================================================
    # 2. QUEUE PAUSE & RESUME
    # ==========================================================================

    def test_02_queue_pause_and_resume(self):
        """Test 2: Verifies queue pause and resume controls emit audit events."""
        res_p = self.service.pause_queue(reason="Test pause")
        self.assertTrue(res_p["queue_paused"])

        events = self.service.get_audit_events(limit=5, category="SYSTEM")
        self.assertTrue(any("PAUSED" in e["message"] for e in events))

        res_r = self.service.resume_queue(reason="Test resume")
        self.assertFalse(res_r["queue_paused"])
        events = self.service.get_audit_events(limit=5, category="SYSTEM")
        self.assertTrue(any("RESUMED" in e["message"] for e in events))

    # ==========================================================================
    # 3. DYNAMIC NICHE SWITCHING
    # ==========================================================================

    def test_03_dynamic_niche_switching(self):
        """Test 3: Verifies multi-niche switching across registered profiles."""
        niches = self.service.get_available_niches()
        niche_names = [n["name"] for n in niches]
        self.assertIn("CURRENT_AFFAIRS", niche_names)
        self.assertIn("HISTORICAL", niche_names)
        self.assertIn("SPACE_TECHNOLOGY", niche_names)
        self.assertIn("FINANCIAL_MARKETS", niche_names)

        # Switch to SPACE_TECHNOLOGY
        res = self.service.switch_niche("SPACE_TECHNOLOGY")
        self.assertEqual(res["active_niche"], "SPACE_TECHNOLOGY")
        self.assertEqual(get_active_profile().name, "SPACE_TECHNOLOGY")
        self.assertEqual(get_active_discovery_profile().name, "SPACE_TECHNOLOGY")

        # Switch back to CURRENT_AFFAIRS
        res2 = self.service.switch_niche("CURRENT_AFFAIRS")
        self.assertEqual(res2["active_niche"], "CURRENT_AFFAIRS")
        self.assertEqual(get_active_profile().name, "CURRENT_AFFAIRS")

        # Reject unregistered niche
        with self.assertRaises(ValueError):
            self.service.switch_niche("FANTASY_REALM")

    # ==========================================================================
    # 4. SAFE JOB RETRY TRANSITION
    # ==========================================================================

    def test_04_safe_job_retry(self):
        """Test 4: Verifies failed or reviewed job can be safely retried."""
        topic = Topic(
            id=f"top_retry_{uuid.uuid4().hex[:8]}",
            title="Retry Test Topic",
            summary="Documented crisis escalation breakdown.",
            category="Crisis",
            score=77.0,
            status="APPROVED"
        )
        job = Job(
            id=f"job_retry_{uuid.uuid4().hex[:8]}",
            topic_id=topic.id,
            state=JobState.FAILED.value,
            error_message="Simulated rendering timeout",
            retry_count=1
        )
        self.db.add(topic)
        self.db.add(job)
        self.db.commit()

        # Retry job
        res = self.service.retry_job(self.db, job_id=job.id)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["new_state"], JobState.QUEUED.value)
        self.assertEqual(res["retry_count"], 2)

        refreshed_job = self.db.query(Job).filter(Job.id == job.id).first()
        self.assertEqual(refreshed_job.state, JobState.QUEUED.value)
        self.assertIsNone(refreshed_job.error_message)

    # ==========================================================================
    # 5. SAFE JOB QUARANTINE & CANCEL
    # ==========================================================================

    def test_05_job_quarantine_and_cancel(self):
        """Test 5: Verifies job quarantine to NEEDS_REVIEW and cancellation to FAILED."""
        topic = Topic(
            id=f"top_qc_{uuid.uuid4().hex[:8]}",
            title="Quarantine Cancel Topic",
            summary="Strategic defense treaty analysis.",
            category="Defense",
            score=82.0,
            status="APPROVED"
        )
        job = Job(
            id=f"job_qc_{uuid.uuid4().hex[:8]}",
            topic_id=topic.id,
            state=JobState.SCRIPT_READY.value,
            retry_count=0
        )
        self.db.add(topic)
        self.db.add(job)
        self.db.commit()

        # Quarantine
        q_res = self.service.quarantine_job(self.db, job_id=job.id, reason="Fact check disputed")
        self.assertEqual(q_res["new_state"], JobState.NEEDS_REVIEW.value)

        # Cancel
        c_res = self.service.cancel_job(self.db, job_id=job.id, reason="Topic obsolete")
        self.assertEqual(c_res["new_state"], JobState.FAILED.value)

    # ==========================================================================
    # 6. NON-BYPASSABLE SAFETY BOUNDARY ON BATCH PRODUCTION
    # ==========================================================================

    def test_06_batch_production_safety_gate(self):
        """Test 6: Verifies production batch rejects dispatch while queue is paused."""
        self.service.pause_queue(reason="Safety test")
        with self.assertRaises(RuntimeError):
            self.service.trigger_autonomous_batch(self.db, count=1, force_dry_run=True)

    # ==========================================================================
    # 7. COMMAND CENTER TELEMETRY GENERATION
    # ==========================================================================

    def test_07_command_center_telemetry(self):
        """Test 7: Verifies Command Center cockpit telemetry aggregation from real DB."""
        telemetry = self.service.get_command_center_telemetry(self.db)
        self.assertIn("active_niche", telemetry)
        self.assertIn("operational_state", telemetry)
        self.assertIn("queue_size", telemetry)
        self.assertIn("jobs_running", telemetry)
        self.assertIn("jobs_completed", telemetry)
        self.assertIn("jobs_failed", telemetry)
        self.assertIn("topics_discovered", telemetry)
        self.assertIn("provider_status", telemetry)
        self.assertIn("feed_health", telemetry)
        self.assertIn("next_scheduled_publication", telemetry)
        self.assertEqual(telemetry["daily_limit"], DAILY_SHORTS_LIMIT)

    # ==========================================================================
    # 8. 16-STAGE PIPELINE VISUALIZATION
    # ==========================================================================

    def test_08_pipeline_visualization_stages(self):
        """Test 8: Verifies 16-stage pipeline visualization maps canonical stages accurately."""
        pipe = self.service.get_pipeline_visualization(self.db)
        self.assertEqual(len(pipe["stages"]), 16)
        stage_names = [s["name"] for s in pipe["stages"]]
        self.assertEqual(stage_names, PIPELINE_STAGES)
        for s in pipe["stages"]:
            self.assertIn(s["status"], ["pending", "running", "completed", "failed", "blocked", "skipped"])

    # ==========================================================================
    # 9. TOPIC INTELLIGENCE EVIDENCE GATE EVALUATION
    # ==========================================================================

    def test_09_topic_intelligence_evidence_gate(self):
        """Test 9: Verifies >= 2 independent publisher domains -> VERIFIED, 1 domain -> INSUFFICIENT EVIDENCE."""
        t_verified = Topic(
            id=f"top_ver_{uuid.uuid4().hex[:8]}",
            title="Verified Consensus Event",
            summary="Multi-source verified diplomatic summit report.",
            category="Diplomacy",
            score=89.0,
            status="APPROVED"
        )
        t_unverified = Topic(
            id=f"top_unver_{uuid.uuid4().hex[:8]}",
            title="Single Source Event",
            summary="Single wire report uncorroborated.",
            category="Diplomacy",
            score=65.0,
            status="PENDING"
        )
        self.db.add_all([t_verified, t_unverified])
        self.db.flush()

        # Add 2 sources to verified topic
        s1 = SourceRecord(
            topic_id=t_verified.id,
            source_name="bbc.co.uk",
            source_url="https://bbc.co.uk/news/world-1",
            source_type="primary"
        )
        s2 = SourceRecord(
            topic_id=t_verified.id,
            source_name="aljazeera.com",
            source_url="https://aljazeera.com/news/world-1",
            source_type="primary"
        )
        # Add 1 source to unverified topic
        s3 = SourceRecord(
            topic_id=t_unverified.id,
            source_name="npr.org",
            source_url="https://npr.org/news/single-1",
            source_type="primary"
        )
        self.db.add_all([s1, s2, s3])
        self.db.commit()

        intel = self.service.get_topic_intelligence(self.db, limit=20)
        verified_entry = next((e for e in intel["topics"] if e["id"] == t_verified.id), None)
        unverified_entry = next((e for e in intel["topics"] if e["id"] == t_unverified.id), None)

        self.assertIsNotNone(verified_entry)
        self.assertEqual(verified_entry["evidence_status"], "VERIFIED")
        self.assertGreaterEqual(len(verified_entry["publisher_domains"]), 2)

        self.assertIsNotNone(unverified_entry)
        self.assertEqual(unverified_entry["evidence_status"], "INSUFFICIENT EVIDENCE")
        self.assertEqual(len(unverified_entry["publisher_domains"]), 1)

    # ==========================================================================
    # 10. DEEP 16-STAGE JOB INSPECTOR
    # ==========================================================================

    def test_10_job_inspector_details(self):
        """Test 10: Verifies full 16-stage inspection of a production job."""
        t = Topic(
            id=f"top_insp_{uuid.uuid4().hex[:8]}",
            title="Inspector Full Lifecycle Topic",
            summary="Propulsion milestone deep-dive.",
            category="Defense",
            score=94.0,
            status="APPROVED"
        )
        j = Job(
            id=f"job_insp_{uuid.uuid4().hex[:8]}",
            topic_id=t.id,
            state=JobState.PUBLISHED.value
        )
        self.db.add_all([t, j])
        self.db.flush()

        script = ScriptRecord(
            id=f"scr_{uuid.uuid4().hex[:8]}",
            topic_id=t.id,
            full_text="In 2026, satellite telemetry confirmed a major aerospace propulsion milestone.",
            word_count=52,
            hook="Satellite telemetry confirmed a major aerospace propulsion milestone.",
            context="Orbital dynamics tests underway.",
            escalation="Propulsion anomaly resolved.",
            reveal="The mission achieved precise orbit.",
            loop_twist="Leading to next phase.",
            estimated_duration_sec=52.0,
            status="APPROVED"
        )
        qa = QAReport(
            job_id=j.id,
            passed=True,
            resolution_ok=True,
            duration_ok=True,
            audio_ok=True,
            captions_ok=True,
            license_ok=True,
            policy_ok=True
        )
        upload = UploadRecord(
            id=f"up_{uuid.uuid4().hex[:8]}",
            job_id=j.id,
            youtube_video_id="TEST_VID_1234",
            title="Inspector Full Lifecycle Video",
            description="Detailed lifecycle investigation.",
            status="PUBLISHED",
            published_at=datetime.now(timezone.utc)
        )
        self.db.add_all([script, qa, upload])
        self.db.commit()

        inspector = self.service.get_job_inspector(self.db, job_id=j.id)
        self.assertEqual(inspector["job"]["id"], j.id)
        self.assertEqual(inspector["topic"]["title"], t.title)
        self.assertIsNotNone(inspector["script"])
        self.assertEqual(inspector["script"]["word_count"], 52)
        self.assertEqual(inspector["script"]["critic_verdict"], "PASSED")
        self.assertIsNotNone(inspector["qa"])
        self.assertTrue(inspector["qa"]["passed"])
        self.assertIsNotNone(inspector["upload"])
        self.assertEqual(inspector["upload"]["youtube_video_id"], "TEST_VID_1234")

    # ==========================================================================
    # 11. 6-QUADRANT SYSTEM HEALTH
    # ==========================================================================

    def test_11_system_health_matrix(self):
        """Test 11: Verifies 6-quadrant operational health matrix."""
        health = self.service.get_system_health(self.db)
        self.assertEqual(health["verdict"], "NOMINAL")
        sub = health["subsystems"]
        self.assertIn("intelligence", sub)
        self.assertIn("ai_providers", sub)
        self.assertIn("production", sub)
        self.assertIn("media", sub)
        self.assertIn("storage", sub)
        self.assertIn("publication", sub)
        self.assertEqual(sub["intelligence"]["status"], "HEALTHY")
        self.assertEqual(sub["media"]["tts_engine"], "Kokoro (af_bella default)")

    # ==========================================================================
    # 12. AUDIT EVENT STREAM & FILTERING
    # ==========================================================================

    def test_12_audit_event_stream_and_filtering(self):
        """Test 12: Verifies structured audit event logging and category/severity filtering."""
        self.service.log_event(category="DISCOVERY", message="96 articles harvested", severity="INFO")
        self.service.log_event(category="EVIDENCE", message="Rejected candidate: 1 publisher", severity="WARN")
        self.service.log_event(category="QA", message="Render passed QA: 91/100", severity="SUCCESS")
        self.service.log_event(category="FAILURE", message="Provider timeout", severity="ERROR")

        disc_events = self.service.get_audit_events(category="DISCOVERY")
        self.assertTrue(all(e["category"] == "DISCOVERY" for e in disc_events))

        err_events = self.service.get_audit_events(severity="ERROR")
        self.assertTrue(all(e["severity"] == "ERROR" for e in err_events))

    # ==========================================================================
    # 13. SSE REAL-TIME STREAMING ENDPOINT
    # ==========================================================================

    def test_13_sse_stream_endpoint(self):
        """Test 13: Verifies subscribe_event_stream yields initial connected event and event broadcast."""
        import asyncio

        async def _run_stream_test():
            gen = self.service.subscribe_event_stream()
            first_event = await gen.asend(None)
            self.assertIn("event: connected", first_event)
            self.assertIn("AUTONOMOUS", first_event)

            # Log an event and verify next yield receives it
            self.service.log_event(category="TEST", message="Live stream test message", severity="INFO")
            second_event = await gen.asend(None)
            self.assertIn("audit_event", second_event)
            self.assertIn("Live stream test message", second_event)
            await gen.aclose()

        asyncio.run(_run_stream_test())

    # ==========================================================================
    # 14. REST API READ ENDPOINTS
    # ==========================================================================

    def test_14_api_read_endpoints(self):
        """Test 14: Verifies all mission-control read endpoints respond with HTTP 200."""
        endpoints = [
            "/api/mission-control/state",
            "/api/mission-control/pipeline",
            "/api/mission-control/queue",
            "/api/mission-control/topics",
            "/api/mission-control/health",
            "/api/mission-control/events",
            "/api/mission-control/niches"
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Endpoint {ep} failed with {res.status_code}")
            data = res.json()
            self.assertIsInstance(data, dict, f"Endpoint {ep} did not return a JSON object")

    # ==========================================================================
    # 15. REST API MUTATION ENDPOINTS
    # ==========================================================================

    def test_15_api_mutation_endpoints(self):
        """Test 15: Verifies controlled mutation endpoints with CSRF token."""
        # 1. Mode Change
        res_mode = self.client.post("/api/mission-control/actions/mode", json={"mode": "SAFE_MODE"}, headers=self.auth_headers)
        self.assertEqual(res_mode.status_code, 200)
        self.assertEqual(res_mode.json()["mode"], "SAFE_MODE")

        # 2. Queue Pause
        res_pause = self.client.post("/api/mission-control/actions/queue/pause", json={"reason": "Test pause"}, headers=self.auth_headers)
        self.assertEqual(res_pause.status_code, 200)
        self.assertTrue(res_pause.json()["queue_paused"])

        # 3. Queue Resume
        res_resume = self.client.post("/api/mission-control/actions/queue/resume", json={"reason": "Test resume"}, headers=self.auth_headers)
        self.assertEqual(res_resume.status_code, 200)
        self.assertFalse(res_resume.json()["queue_paused"])

        # 4. Switch Niche
        res_niche = self.client.post("/api/mission-control/actions/niche", json={"niche": "CURRENT_AFFAIRS"}, headers=self.auth_headers)
        self.assertEqual(res_niche.status_code, 200)
        self.assertEqual(res_niche.json()["active_niche"], "CURRENT_AFFAIRS")

        # Restore Autonomous Mode
        self.client.post("/api/mission-control/actions/mode", json={"mode": "AUTONOMOUS"}, headers=self.auth_headers)

    # ==========================================================================
    # 16. HTML RENDERING & RESPONSIVENESS
    # ==========================================================================

    def test_16_html_dashboard_rendering(self):
        """Test 16: Verifies GET / and GET /mission-control render HTML with required operational elements."""
        res_root = self.client.get("/")
        self.assertEqual(res_root.status_code, 200)
        self.assertIn("AL AMR", res_root.text)
        self.assertIn("01_READY", res_root.text)
        self.assertIn("MISSION CONTROL", res_root.text)
        self.assertIn("16-STAGE PRODUCTION PIPELINE", res_root.text)
        self.assertIn("prefers-reduced-motion", res_root.text)

        res_mc = self.client.get("/mission-control")
        self.assertEqual(res_mc.status_code, 200)
        self.assertIn("AL AMR", res_mc.text)
        self.assertIn("TOPIC INTELLIGENCE", res_mc.text)

    # ==========================================================================
    # 17. AST ARCHITECTURAL AUDIT
    # ==========================================================================

    def test_17_ast_architectural_audit(self):
        """Test 17: Verifies zero hardcoded niche conditionals in mission control code."""
        files_to_check = [
            "dashboard/mission_control_service.py",
            "dashboard/mission_control_routes.py"
        ]
        forbidden_niche_names = ["CURRENT_AFFAIRS", "HISTORICAL", "SPACE_TECHNOLOGY", "FINANCIAL_MARKETS"]

        for file_path in files_to_check:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=file_path)

            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    test_dump = ast.dump(node.test)
                    for fn in forbidden_niche_names:
                        pattern = f"Constant(value='{fn}')"
                        self.assertNotIn(
                            pattern,
                            test_dump,
                            f"Hardcoded niche conditional '{fn}' found in {file_path} at line {node.lineno}"
                        )


if __name__ == "__main__":
    unittest.main()
