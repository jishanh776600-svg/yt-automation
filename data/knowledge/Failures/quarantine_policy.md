# Poison-Pill Quarantine & Safe Recovery

## Quarantine Rules
- Any artifact failing QA, audio checks, or publishing verification is quarantined to Google Drive `04_FAILED`.
- Corrupt files, test artifacts, and zero-byte files are strictly excluded from inventory count.
- The reserve buffer only counts verified, valid `.mp4` files in `01_READY`.
- Governed by [[Production/pipeline_rules|Pipeline Rules]].