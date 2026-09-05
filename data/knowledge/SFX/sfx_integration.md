# SFX Punctuation & Audio Design

> [!WARNING]
> **SUPERSEDED & PERMANENTLY DISABLED IN PRODUCTION**  
> Sound effects (whooshes, risers, impacts, booms) have been **permanently disabled** in the AL-AMR production pipeline. Production audio utilizes voiceover narration ducked over subtle BGM only.  
> **Master Reference:** [[06 - Audio & Voice|Audio & Voice Architecture]]

---

## Historical Context (Preserved for Reference)
- **Former Roles:**
  - Risers: Anticipation during escalation.
  - Impacts: Punctuation at reveals.
  - Whooshes: Scene transitions.
- **Decommissioning Rationale:** Synthetic SFX distracted from the authentic documentary tone and degraded dialogue intelligibility on mobile devices.
- **Current Enforcement:** `has_sfx = False` hard-coded across renderer configurations and workflows.