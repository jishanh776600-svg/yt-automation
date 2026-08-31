# Closed-Loop Strategy Learning & Analytics

## Analytics Architecture
- **Source**: Authorized YouTube Data API v3 & YouTube Analytics API ([[Performance/publishing_and_telemetry|Telemetry]]).
- **Snapshot Immutability**: Time-series `PerformanceSnapshot` records stored at 24h, 48h, 7d intervals.
- **Data Truth Invariant**: Missing or unsupported API metrics are recorded as `None` (UNAVAILABLE), never fabricated as `0.0`.

## Current Baseline Status
- **Mature Videos Analyzed**: `0`
- **Channel Performance Baseline**: `50.0 / 100`

## Evidence Thresholds
- **Insufficient Evidence**: $N < 3$ (No strategy weight adjustment)
- **Weak Signal**: $N = 3 - 4$ (Damped adjustment $\pm 10\%$)
- **Usable Signal**: $N \ge 5$ (Full strategy weight adjustment bounded in $[0.20, 2.00]$)

## Strategy Feedback Loop
Top-performing hook archetypes and pacing attributes are compiled into the [[Scripts/retention_architecture|Script Generation]] prompt.