# AL-AMR — STEP 7: CONTROLLED LIVE-CLOUD CANARY

## Executive Summary

This milestone establishes the **Controlled Production Canary** layer for AL-AMR, providing an opt-in, strictly bounded execution mode that proves the autonomous runtime can safely execute exactly **ONE** real end-to-end Short against the real cloud environment (Google Drive `01_READY`), while preserving every existing safety invariant and hard boundary.

> [!IMPORTANT]
> **VERIFICATION SEPARATION DECLARATION**
> 1. **Automated Test Verification**: Complete (50 passing unit and integration tests across Steps 4–7). All tests ran under mock/sandboxed capability gates with zero external mutations, zero live AI tokens consumed, zero local video renders, zero TTS generation, and zero cloud Drive/YouTube operations.
> 2. **Canary System Readiness**: Fully implemented, verified, hardened, and locked behind explicit opt-in flags (`--canary` CLI argument or `AUTONOMOUS_CANARY_MODE=true` environment variable).
> 3. **Actual Live-Cloud Execution**: **NONE**. In accordance with core workflow rules, no live canary was executed automatically. The canary mechanism is primed and awaiting explicit operator trigger.

---

## Architectural Implementation

### 1. Opt-In Canary Capability Mode (`ExecutionCapabilities.live_canary()`)
To ensure complete isolation between default autonomous operations and canary verification, a dedicated capability profile was created in [`engines/orchestrator.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/orchestrator.py#L136-L152):

```python
@classmethod
def live_canary(cls) -> "ExecutionCapabilities":
    """
    Controlled live-cloud canary capability (Step 7):
    Permits real AI generation, TTS, local composition, and Drive 01_READY deposit.
    STRICTLY PROHIBITS YouTube publishing and automatic scheduling.
    """
    return cls(
        allow_network_read=True,
        allow_ai=True,
        allow_tts=True,
        allow_render=True,
        allow_drive_write=True,
        allow_youtube_write=False,
        allow_schedule=False
    )
```

**Non-Bypassable Safety Invariant**: Under all circumstances during canary execution, `allow_youtube_write` and `allow_schedule` are hard-coded to `False`. The canary job strictly ends in Google Drive `01_READY` in `READY_TO_UPLOAD` status and will never mutate YouTube production inventory.

---

### 2. The 8 Pre-Flight Safety Gates

Before any production activity begins, [`run_preflight_gates(db)`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/runtime/service.py#L684-L850) in `AutonomousRuntimeService` evaluates 8 non-negotiable safety conditions:

| Gate # | Gate Identifier | Condition Checked | Failure Behavior |
|:---|:---|:---|:---|
| **1** | `process_lock` | Verifies `ProcessLock('autonomous_worker')` is available or held by current process. | Aborts immediately, preventing race conditions or parallel workers. |
| **2** | `queue_interlock` | Mission Control queue is NOT paused and operational mode is NOT `PAUSED`, `SAFE_MODE`, `STOPPED`, `ERROR`, or `NEEDS_REVIEW`. | Halts immediately; respects manual operator intervention. |
| **3** | `ai_providers` | Verifies presence of at least one unexhausted AI credential across the deterministic cascade: `Gemini Primary -> Gemini Secondary -> Groq -> OpenRouter` (DeepSeek excluded). | Prevents initiating a run that would fail mid-scripting. |
| **4** | `drive_vault` | Google Drive vault is reachable and authoritative `01_READY` subfolder is verified. | Fails closed if remote vault hierarchy is missing or inaccessible. |
| **5** | `youtube_state` | Authoritative YouTube schedule/publication state is readable via `PublicationScheduler.get_authoritative_schedule_state()`. | Ensures publication capacity and slot state can be read accurately. |
| **6** | `reserve_state` | Authoritative Google Drive reserve count is readable via `reconcile_reserve()`. | Ensures baseline stock can be measured before production. |
| **7** | `daily_limit` | Verified publication count for today is strictly below `DAILY_SHORTS_LIMIT` (3 Shorts/day). | Prevents exceeding quota limits. |
| **8** | `canary_consumed` | Verifies `_canary_consumed` is `False`. | Prohibits re-running canary multiple times in a single worker session. |

If **ANY** gate fails:
- Production is aborted immediately.
- The failure reason and gate name are logged to the Mission Control audit stream.
- The process lock is released cleanly in a guaranteed `finally` block.
- Telemetry records `status: "PREFLIGHT_FAILED"`.
- No retries are attempted.

---

### 3. Canary Execution Lifecycle & Cloud Confirmation

Once pre-flight checks pass:
1. **Idempotent Resumption**: Discovers any in-flight production job interrupted by a prior crash or termination (`RESEARCHING`, `SCRIPTING`, `VOICE_GENERATING`, `EDITING`, `QA`) and resumes it from its exact intermediate stage rather than duplicating work.
2. **Fresh Production**: If no in-flight job exists, selects the highest-scoring approved topic that has not yet been produced, or discovers and ranks 1 fresh candidate topic.
3. **15-Stage Pipeline**: Runs the complete canonical production pipeline:
   `DISCOVER -> FILTER -> RANK -> SELECT -> RESEARCH -> SCRIPT -> CRITIC -> VISUAL PLAN -> ASSETS -> TTS -> AUDIO -> RENDER -> QA -> VAULT`.
4. **Cloud Confirmation Gate**:
   - Locates the deposited video in Google Drive `01_READY`.
   - Validates the artifact against `is_valid_ready_short()` rules (file exists, readable, non-empty, valid MP4 container, valid metadata mapping to active non-published job).
   - Authoritatively reconciles the cloud reserve via `reconcile_reserve()`.
   - In live mode (`allow_drive_write=True`), if the file is not verified in `01_READY` or ready stock does not increment, the run fails closed with `CLOUD_CONFIRMATION_FAILED`. **Never claims success from local state alone.**
5. **Database State Reconciliation**: Transitions job state to `READY_TO_UPLOAD` in database to match the cloud state.
6. **Clean Termination**: Marks `_canary_consumed = True`, emits structured audit events to Mission Control, flushes heartbeat telemetry, cleanly releases the worker lock, and terminates. **Zero automatic refills; zero automatic publishing.**

---

### 4. Telemetry and Mission Control Integration

Canary execution state is exposed in real time across three separate observability channels:

1. **Mission Control Audit Log**: Structured events logged under category `CANARY` with severity `INFO`, `SUCCESS`, or `ERROR`.
2. **Persistent Heartbeat (`worker_state.json`)**:
   ```json
   {
     "pid": 1234,
     "status": "ONLINE",
     "canary_mode": true,
     "canary_consumed": true,
     "canary_telemetry": {
       "status": "SUCCESS",
       "job_id": "job_canary_...",
       "topic_title": "...",
       "verified_in_ready": true,
       "post_canary_reserve": 1,
       "drive_file_id": "..."
     }
   }
   ```
3. **CLI Feedback**: Clear terminal status reporting indicating pre-flight gate results, stage progression, Drive file ID, and reserve reconciliation count.

---

## Verification & Test Results

All 4 test suites covering Step 4 (Mission Control), Step 5 (Autonomous Runtime), Step 6 (Cloud Production Validation), and Step 7 (Controlled Live-Cloud Canary) pass with **100% success (50 passed, 0 failed)**:

```
============================= test session starts =============================
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_01_canary_mode_explicit_opt_in_required PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_02_canary_enforces_single_production_job PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_03_canary_prohibits_automatic_refill PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_04_preflight_queue_paused_or_safemode_rejection PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_05_preflight_daily_publication_limit_rejection PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_06_preflight_worker_lock_held_rejection PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_07_canary_cannot_be_rerun_in_same_session PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_08_canary_idempotent_in_flight_resumption PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_09_canary_requires_cloud_confirmation_when_live PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_10_canary_prohibits_automatic_youtube_publishing PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_11_canary_audit_telemetry_and_heartbeat PASSED
tests/test_controlled_live_canary.py::TestControlledLiveCanary::test_12_ast_niche_agnostic_compliance PASSED
================= 12 passed in 93.91s ==================

tests/test_cloud_production_validation.py (Step 6): 11 passed in 35.27s
tests/test_autonomous_runtime.py (Step 5): 10 passed in 63.59s
tests/test_mission_control.py (Step 4): 17 passed in 10.44s
================= Total: 50 passed, 0 failed, 0 regressions =================
```

---

## AST Niche-Agnostic Architectural Audit

Automated Abstract Syntax Tree (AST) validation (`test_12_ast_niche_agnostic_compliance`) was performed across all new and modified components:
- `runtime/service.py`
- `runtime/config.py`
- `runtime/cli.py`
- `engines/orchestrator.py`

**Audit Finding**: Zero hardcoded niche literals or conditional branches detected. Content persona logic is 100% dynamically supplied via active `ContentProfile` and `DiscoveryProfile`.

---

## Operator Runbook for Executing the Live Canary

When human operators choose to execute the real live canary in production:

### 1. Ensure Environment Prerequisites
Verify credentials in `.env`:
- `GEMINI_API_KEY` (and optional `GEMINI_API_KEY_SECONDARY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`)
- Valid Google Drive OAuth token in `credentials/token.json`
- `FFMPEG` and `IMAGEMAGICK` available in system PATH

### 2. Launch Canary Command
Execute either through the standalone runtime CLI:
```bash
python -m runtime.cli --canary
```
Or via the main entrypoint:
```bash
python main.py --canary
```

### 3. Expected Operator Experience
1. **Pre-flight verification**: All 8 safety gates pass with green checks.
2. **Sequential production**: The 15 stages progress one by one (`DISCOVER` through `RENDER`).
3. **Automated QA gate**: Strict audio and visual QA verified.
4. **Cloud deposit**: Upload to Google Drive `01_READY` with verified file ID.
5. **Confirmation**: Cloud reserve reconciled (`1/6 verified Shorts`).
6. **Clean exit**: Process lock released; worker shuts down. **No YouTube upload; no refill.**
