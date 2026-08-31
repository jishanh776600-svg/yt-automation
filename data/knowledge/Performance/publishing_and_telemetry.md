# Publishing Slots & Telemetry Data Truth

## Automated Scheduling
- **Daily Limit**: Strictly `3` Shorts/day.
- **Publishing Slots (UTC)**: `06:00 UTC`, `11:00 UTC`, `15:00 UTC`.
- **Target Reserve Buffer**: `6` Shorts maintained in `01_READY`.

## Telemetry Data Truth
- **YouTube Data API v3**: Public statistics (views, likes, comments).
- **YouTube Analytics API**: Retention percentage (APV), average view duration (AVD), watch time.
- **Unavailable vs Zero**: Metrics not yet available from API are stored as `None` (UNAVAILABLE), never fabricated as `0.0`.
- **Downstream Optimization**: Ingested by [[Learning/strategy_insights|Learning Engine]].