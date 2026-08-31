# Poison-Pill Quarantine & Safe Recovery

## Quarantine Architecture
- **Automatic Isolation**: Any candidate failing QA, acoustic analysis, narration completeness, or publication safety is moved immediately to Google Drive `04_FAILED`.
- **Zero-Pollution Invariant**: Corrupt files, test artifacts, and zero-byte files are strictly excluded from inventory counts and never returned to `01_READY`.
- **Clean Failure Boundaries**:
  1. *Research Failure*: Fact verification shortfall $\to$ Topic retired, not looped indefinitely.
  2. *Narration Timing Failure*: Voice duration exceeding $\text{video\_duration} - 0.6\text{s}$ $\to$ Render rejected, quarantined.
  3. *Provider Exhaustion*: All fallbacks failed (Gemini $\to$ Groq $\to$ OpenRouter) $\to$ Clean fail-fast with `ALL_AI_PROVIDERS_EXHAUSTED`.
  4. *Publishing Safety Rejection*: Metadata mismatch or invalid container $\to$ Claimed asset moved from `02_PROCESSING` to `04_FAILED`.
- Governed by [[Production/pipeline_rules|Pipeline Rules]] and [[Learning/strategy_insights|Learning Engine]].