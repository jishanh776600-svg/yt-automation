# 05 — Analytics & Learning Engine

> **Status:** `[VERIFIED & OPERATIONAL]`  
> **Scope:** YouTube Analytics OAuth integration, telemetry harvesting, 24h maturation gate, and UCB1 closed-loop learning.  

---

## 1. YouTube Analytics Integration

- **OAuth Scopes**:
  - `https://www.googleapis.com/auth/youtube.upload`
  - `https://www.googleapis.com/auth/youtube`
  - `https://www.googleapis.com/auth/drive`
  - `https://www.googleapis.com/auth/yt-analytics.readonly`
- **GCP Project Number**: `1044637695745`
- **GCP API**: `youtubeanalytics.googleapis.com` (Enabled and verified).
- **Telemetry Query Endpoint**: `youtubeAnalytics.reports().query()`

---

## 2. Real Channel Telemetry Baseline

Harvested and verified via live authenticated Google API query:

| Telemetry Metric | Measured Production Value | Verification Status |
|---|---|---|
| **Average View Duration (AVD)** | **`17.0 seconds`** | `[VERIFIED LIVE HTTP 200]` |
| **Average Percentage Viewed (APV)** | **`75.46%`** | `[VERIFIED LIVE HTTP 200]` |
| **Estimated Minutes Watched** | **`956 minutes`** | `[VERIFIED LIVE HTTP 200]` |
| **Last-30-Day Total Views** | **`7,763 views`** | `[VERIFIED LIVE HTTP 200]` |
| **Top Performing Mature Video** | `Daeg9NaLuvY` (*"The Halifax Explosion of 1917"*) | `[VERIFIED LIVE HTTP 200]` |

---

## 3. Closed-Loop Learning & UCB1 Reinforcement Engine

- **Engine**: [`engines/learning_engine.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/learning_engine.py)
- **24-Hour Maturation Gate**: Videos with $	ext{age} < 24	ext{ hours}$ are classified as `MATURING` and excluded from strategy updates to prevent premature bias from early impression noise.
- **Evidence Thresholds**:
  - $N < 3	ext{ videos}$: `INSUFFICIENT_EVIDENCE` $\implies$ Zero weight adjustment.
  - $N = 3–4	ext{ videos}$: `WEAK_EVIDENCE` $\implies$ Damped conservative update ($lpha = 0.05$).
  - $N \ge 5	ext{ videos}$: `USABLE_EVIDENCE` $\implies$ Full empirical UCB1 weight update.
- **Mathematical Weight Bounds**: Strategy weights are strictly clamped to $[0.20, 2.00]$ to prevent algorithmic drift or over-specialization.