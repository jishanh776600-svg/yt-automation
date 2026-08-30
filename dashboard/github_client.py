"""
GitHub Actions Remote Workflow Dispatcher (App Phase 7.2).
Provides secure, isolated server-side dispatching of existing GitHub Actions workflows
for the Emergency Mobile Control App when CLOUD_MODE is active.

Invariants:
- STRICT whitelisting: ONLY produce_buffer.yml, autopilot.yml, and harvest_analytics.yml.
- Zero client-side leakage: GITHUB_PAT exists only in server memory and is NEVER serialized.
- Clearly distinguishes DISPATCH_ACCEPTED from WORKFLOW_COMPLETED.
- Safe error classification across 401, 403, 404, 409, 422, 429, 5xx, and network timeouts.
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from config.settings import (
    GITHUB_PAT,
    GITHUB_REPOSITORY_OWNER,
    GITHUB_REPOSITORY_NAME,
    GITHUB_REF
)

logger = logging.getLogger("GitHubWorkflowDispatcher")

ALLOWED_WORKFLOWS = {
    "produce_buffer.yml": "01 Buffer Producer",
    "autopilot.yml": "02 YouTube Autopilot Publisher",
    "harvest_analytics.yml": "03 Analytics Harvester"
}


class GitHubWorkflowDispatcher:
    """
    Client for triggering configured GitHub Actions workflows via GitHub REST API.
    """

    def __init__(
        self,
        pat: Optional[str] = None,
        owner: Optional[str] = None,
        repo: Optional[str] = None,
        default_ref: Optional[str] = None,
        timeout_sec: float = 10.0
    ):
        self._pat = pat if pat is not None else (GITHUB_PAT or os.getenv("GITHUB_PAT", ""))
        self.owner = owner if owner is not None else (GITHUB_REPOSITORY_OWNER or os.getenv("GITHUB_REPOSITORY_OWNER", ""))
        self.repo = repo if repo is not None else (GITHUB_REPOSITORY_NAME or os.getenv("GITHUB_REPOSITORY_NAME", ""))
        self.default_ref = default_ref if default_ref is not None else (GITHUB_REF or os.getenv("GITHUB_REF", "main"))
        self.timeout_sec = timeout_sec

        # Auto-detect from GITHUB_REPOSITORY (e.g. "owner/repo" in GitHub runner)
        if (not self.owner or not self.repo) and os.getenv("GITHUB_REPOSITORY"):
            parts = os.getenv("GITHUB_REPOSITORY", "").split("/")
            if len(parts) == 2:
                self.owner = self.owner or parts[0]
                self.repo = self.repo or parts[1]

    def _mask_pat(self) -> str:
        """Returns diagnostic masked representation of PAT status."""
        if not self._pat:
            return "NOT_CONFIGURED"
        if len(self._pat) <= 8:
            return "***"
        return f"{self._pat[:4]}...{self._pat[-4:]}"

    def dispatch_workflow(
        self,
        workflow_file: str,
        ref: Optional[str] = None,
        inputs: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Dispatches a whitelisted GitHub Actions workflow using workflow_dispatch.
        """
        now_str = datetime.utcnow().isoformat() + "Z"

        # 1. Security Check: Strict Whitelist Validation
        if workflow_file not in ALLOWED_WORKFLOWS:
            logger.error(f"[SECURITY] Unauthorized workflow dispatch attempt: '{workflow_file}'")
            return {
                "success": False,
                "status": "DISPATCH_REJECTED",
                "action": "DISPATCH_REJECTED",
                "workflow": workflow_file,
                "error": f"Workflow '{workflow_file}' is not in authorized whitelist.",
                "dispatch_requested_at": now_str,
                "status_code": 400
            }

        # 2. Configuration Validation
        if not self._pat:
            logger.warning("[GITHUB_DISPATCH] Dispatch failed: GITHUB_PAT is not configured.")
            return {
                "success": False,
                "status": "DISPATCH_FAILED",
                "action": "DISPATCH_FAILED",
                "workflow": workflow_file,
                "error": "Server-side GitHub Personal Access Token (GITHUB_PAT) is not configured.",
                "dispatch_requested_at": now_str,
                "status_code": 500
            }

        if not self.owner or not self.repo:
            logger.warning("[GITHUB_DISPATCH] Dispatch failed: Repository owner or name missing.")
            return {
                "success": False,
                "status": "DISPATCH_FAILED",
                "action": "DISPATCH_FAILED",
                "workflow": workflow_file,
                "error": "GitHub repository owner or name not configured (GITHUB_REPOSITORY_OWNER / GITHUB_REPOSITORY_NAME).",
                "dispatch_requested_at": now_str,
                "status_code": 500
            }

        target_ref = ref or self.default_ref or "main"
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/actions/workflows/{workflow_file}/dispatches"
        payload = {"ref": target_ref}
        if inputs:
            payload["inputs"] = inputs

        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._pat}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Historia-Mission-Control-Dispatcher",
            "Content-Type": "application/json"
        }

        req = Request(url, data=data_bytes, headers=headers, method="POST")

        try:
            with urlopen(req, timeout=self.timeout_sec) as resp:
                status_code = resp.getcode()
                # GitHub returns 204 No Content for successful workflow_dispatch
                if status_code in (200, 204):
                    logger.info(f"[GITHUB_DISPATCH] Successfully dispatched '{workflow_file}' on {self.owner}/{self.repo} (ref: {target_ref})")
                    return {
                        "success": True,
                        "status": "DISPATCH_ACCEPTED",
                        "action": "DISPATCH_ACCEPTED",
                        "workflow": workflow_file,
                        "workflow_name": ALLOWED_WORKFLOWS[workflow_file],
                        "repository": f"{self.owner}/{self.repo}",
                        "ref": target_ref,
                        "message": f"Cloud workflow '{ALLOWED_WORKFLOWS[workflow_file]}' dispatch queued successfully on GitHub Actions.",
                        "dispatch_requested_at": now_str,
                        "status_code": status_code
                    }
                else:
                    return {
                        "success": False,
                        "status": "DISPATCH_FAILED",
                        "action": "DISPATCH_FAILED",
                        "workflow": workflow_file,
                        "error": f"Unexpected GitHub API response code: {status_code}",
                        "dispatch_requested_at": now_str,
                        "status_code": status_code
                    }

        except HTTPError as http_err:
            code = http_err.code
            err_msg = ""
            try:
                raw_err = http_err.read().decode("utf-8")
                err_json = json.loads(raw_err)
                err_msg = err_json.get("message", "")
            except Exception:
                err_msg = str(http_err)

            logger.error(f"[GITHUB_DISPATCH_ERROR] GitHub API returned {code}: {err_msg}")

            friendly_errors = {
                401: "GitHub Authentication Failed. Invalid GITHUB_PAT token.",
                403: "GitHub Permission Denied. GITHUB_PAT lacks 'actions:write' permission or rate limit hit.",
                404: f"GitHub Resource Not Found. Verify repository '{self.owner}/{self.repo}' and workflow '{workflow_file}'.",
                409: "GitHub Workflow Conflict. Repository actions may be disabled.",
                422: f"GitHub Validation Failed. Invalid branch ref '{target_ref}'.",
                429: "GitHub API Rate Limit Exceeded. Please wait before retrying.",
                500: "GitHub Actions internal service error. Please retry shortly.",
                502: "GitHub Bad Gateway. GitHub services temporarily degraded.",
                503: "GitHub Service Unavailable. GitHub Actions is experiencing downtime."
            }

            error_summary = friendly_errors.get(code, f"GitHub API error ({code}): {err_msg}")

            return {
                "success": False,
                "status": "DISPATCH_FAILED",
                "action": "DISPATCH_FAILED",
                "workflow": workflow_file,
                "error": error_summary,
                "dispatch_requested_at": now_str,
                "status_code": code
            }

        except URLError as url_err:
            logger.error(f"[GITHUB_DISPATCH_NETWORK_ERROR] {url_err}")
            return {
                "success": False,
                "status": "DISPATCH_FAILED",
                "action": "DISPATCH_FAILED",
                "workflow": workflow_file,
                "error": f"Network error connecting to GitHub API: {url_err.reason}",
                "dispatch_requested_at": now_str,
                "status_code": 503
            }

        except Exception as generic_err:
            logger.error(f"[GITHUB_DISPATCH_EXCEPTION] {generic_err}")
            return {
                "success": False,
                "status": "DISPATCH_FAILED",
                "action": "DISPATCH_FAILED",
                "workflow": workflow_file,
                "error": f"Unexpected error during workflow dispatch: {str(generic_err)}",
                "dispatch_requested_at": now_str,
                "status_code": 500
            }

    def get_workflow_runs(self, workflow_file: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Queries GitHub Actions API for recent runs of a specific workflow."""
        if not self._pat or not self.owner or not self.repo:
            return []

        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/actions/workflows/{workflow_file}/runs?per_page={limit}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._pat}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Historia-Mission-Control-Dispatcher"
        }
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("workflow_runs", [])
        except Exception as e:
            logger.warning(f"Error querying GitHub workflow runs for '{workflow_file}': {e}")
            return []

    def get_active_workflow_run(self, workflow_file: str) -> Optional[Dict[str, Any]]:
        """Checks if any run for the given workflow is currently queued or in progress."""
        runs = self.get_workflow_runs(workflow_file, limit=5)
        for run in runs:
            if run.get("status") in ("queued", "in_progress", "requested", "waiting"):
                return run
        return None

    def get_workflow_run_jobs(self, run_id: int) -> Dict[str, Any]:
        """Fetches job and step execution details for granular progress reporting."""
        if not self._pat or not self.owner or not self.repo:
            return {"jobs": [], "step_summary": {}}

        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/actions/runs/{run_id}/jobs"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._pat}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Historia-Mission-Control-Dispatcher"
        }
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                jobs = data.get("jobs", [])
                completed_steps = 0
                total_steps = 0
                current_step_name = "Queued"

                for j in jobs:
                    for s in j.get("steps", []):
                        total_steps += 1
                        if s.get("status") == "completed":
                            completed_steps += 1
                        elif s.get("status") == "in_progress":
                            current_step_name = s.get("name", "In Progress")

                return {
                    "jobs": jobs,
                    "step_summary": {
                        "completed_steps": completed_steps,
                        "total_steps": total_steps,
                        "current_step": current_step_name
                    }
                }
        except Exception as e:
            logger.warning(f"Error fetching jobs for run {run_id}: {e}")
            return {"jobs": [], "step_summary": {}}

    def get_latest_workflow_run(self, workflow_file: str) -> Optional[Dict[str, Any]]:
        """Fetches the most recent workflow run metadata and active step details."""
        runs = self.get_workflow_runs(workflow_file, limit=1)
        if not runs:
            return None
        latest = runs[0]
        run_id = latest["id"]
        details = self.get_workflow_run_jobs(run_id)
        latest["jobs"] = details.get("jobs", [])
        latest["step_summary"] = details.get("step_summary", {})
        return latest

    def dispatch_produce_buffer(
        self,
        ref: Optional[str] = None,
        target_buffer: int = 6,
        batch_count: int = 0,
        active_voice: Optional[str] = None
    ) -> Dict[str, Any]:
        """Triggers produce_buffer.yml (01 Buffer Producer) with target parameters and active voice."""
        inputs = {
            "target_buffer": str(target_buffer),
            "batch_count": str(batch_count)
        }
        if active_voice:
            inputs["active_voice"] = str(active_voice)
        return self.dispatch_workflow("produce_buffer.yml", ref=ref, inputs=inputs)

    def dispatch_autopilot(self, ref: Optional[str] = None) -> Dict[str, Any]:
        """Triggers autopilot.yml (02 YouTube Autopilot Publisher)."""
        return self.dispatch_workflow("autopilot.yml", ref=ref)

    def dispatch_harvest_analytics(self, ref: Optional[str] = None) -> Dict[str, Any]:
        """Triggers harvest_analytics.yml (03 Analytics Harvester)."""
        return self.dispatch_workflow("harvest_analytics.yml", ref=ref)