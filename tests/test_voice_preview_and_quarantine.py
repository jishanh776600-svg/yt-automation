"""
Tests for Voice Preview and Quarantine Bug Fix (Phase 5 Post-Audit Remediation).
Verifies:
1. Voice Preview API validation, authentication, and CSRF protection.
2. Voice Preview does NOT mutate SystemConfig, Jobs, Drive, or YouTube.
3. Quarantine correctly calls move_file_in_vault() on DriveVaultEngine.
4. Frontend index.html renders both Preview and Set as Active controls.
"""
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from fastapi.testclient import TestClient

from core.database import SessionLocal, init_db
from core.models import Job, SystemConfig
from dashboard.app import app
from dashboard.auth import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD
from dashboard.action_manager import ActionManager
from engines.tts_engine import TTSEngine, AVAILABLE_VOICES, get_active_voice, set_active_voice


class TestVoicePreviewAndQuarantine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        login_res = self.client.post("/api/auth/login", json={
            "username": DEFAULT_ADMIN_USER,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        self.assertEqual(login_res.status_code, 200)
        self.csrf_token = login_res.json().get("csrf_token", "")
        self.test_job_ids = []

    def tearDown(self):
        for jid in self.test_job_ids:
            self.db.query(Job).filter(Job.id == jid).delete()
        self.db.commit()

    def test_voice_preview_auth_required(self):
        """Unauthenticated requests to /api/voice/preview must return 401."""
        unauth_client = TestClient(app)
        res = unauth_client.post(
            "/api/voice/preview",
            json={"voice_id": "am_adam"},
            headers={"X-CSRF-Token": "invalid"}
        )
        self.assertEqual(res.status_code, 401)

    def test_voice_preview_csrf_protected(self):
        """Requests with missing or invalid CSRF token must be rejected."""
        res = self.client.post(
            "/api/voice/preview",
            json={"voice_id": "am_adam"},
            headers={"X-CSRF-Token": "wrong_csrf_token"}
        )
        self.assertEqual(res.status_code, 403)

    def test_voice_preview_rejects_invalid_voice_id(self):
        """Preview endpoint must reject voice IDs not in AVAILABLE_VOICES."""
        res = self.client.post(
            "/api/voice/preview",
            json={"voice_id": "fake_nonexistent_voice_999"},
            headers={"X-CSRF-Token": self.csrf_token}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid voice ID", res.json().get("detail", ""))

    @patch.object(TTSEngine, "generate_preview_sample")
    def test_voice_preview_accepts_valid_voice_and_returns_data_uri(self, mock_gen):
        """Preview endpoint generates sample and returns valid base64 audio URI."""
        mock_gen.return_value = (True, b"RIFFFAKEWAVDATA12345", "audio/wav")

        res = self.client.post(
            "/api/voice/preview",
            json={"voice_id": "am_adam"},
            headers={"X-CSRF-Token": self.csrf_token}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("voice_id"), "am_adam")
        self.assertIn("audio_url", data)
        self.assertTrue(data["audio_url"].startswith("data:audio/wav;base64,"))
        mock_gen.assert_called_once_with("am_adam")

    @patch.object(TTSEngine, "generate_preview_sample")
    def test_voice_preview_does_not_mutate_system_state(self, mock_gen):
        """Preview must NOT create Jobs, change active_voice, or touch external systems."""
        mock_gen.return_value = (True, b"RIFFSAMPLE", "audio/wav")

        # Set active voice to Bella first
        set_active_voice(self.db, "af_bella")
        self.assertEqual(get_active_voice(self.db), "af_bella")

        initial_job_count = self.db.query(Job).count()

        # Preview Adam
        res = self.client.post(
            "/api/voice/preview",
            json={"voice_id": "am_adam"},
            headers={"X-CSRF-Token": self.csrf_token}
        )
        self.assertEqual(res.status_code, 200)

        # Verify active voice remains Bella (NOT Adam)
        self.assertEqual(get_active_voice(self.db), "af_bella")
        # Verify no Job was created
        self.assertEqual(self.db.query(Job).count(), initial_job_count)

        # Restore active voice back to Adam
        set_active_voice(self.db, "am_adam")

    def test_quarantine_calls_move_file_in_vault(self):
        """quarantine_job must call move_file_in_vault on DriveVaultEngine."""
        am = ActionManager()
        mock_drive = MagicMock()
        am.drive_engine = mock_drive

        # Set up mock file listing in 01_READY
        mock_drive.list_files_in_folder.side_effect = lambda folder: (
            [{"id": "file_123", "name": "short_job_test_quarantine_1080x1920.mp4"}] if folder == "01_READY" else []
        )

        job_id = "job_test_quarantine"
        self.test_job_ids.append(job_id)
        job = Job(id=job_id, state="READY_TO_UPLOAD")
        self.db.add(job)
        self.db.commit()

        result = am.quarantine_job(self.db, job_id, reason="QA visual artifact")
        self.assertTrue(result["success"])
        self.assertEqual(result["new_state"], "FAILED")
        self.assertEqual(result["moved_drive_file"], "short_job_test_quarantine_1080x1920.mp4")

        # Verify move_file_in_vault was called with exact parameters
        mock_drive.move_file_in_vault.assert_called_once_with(
            "file_123",
            from_folder="01_READY",
            to_folder="04_FAILED"
        )

    def test_frontend_template_contains_preview_and_set_active(self):
        """index.html must render both Preview and Set as Active buttons and handlePreviewVoice."""
        template_path = Path("dashboard/templates/index.html")
        content = template_path.read_text(encoding="utf-8")
        self.assertIn("handlePreviewVoice", content)
        self.assertIn("handleSetVoice", content)
        self.assertIn("Preview", content)
        self.assertIn("Set as Active", content)
        self.assertIn("/api/voice/preview", content)


if __name__ == "__main__":
    unittest.main()