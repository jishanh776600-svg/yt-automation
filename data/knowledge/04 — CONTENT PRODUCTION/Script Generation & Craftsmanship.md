---
aliases:
  - Script Generation
  - Script Craftsmanship
  - Narrative Architecture
tags:
  - production
  - scripts
  - editorial
last_updated: 2026-09-07
---

# Script Generation & Craftsmanship

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** High-retention narrative structure, word-count constraints, conversational human framing, and anti-cliché defense `[CODE VERIFIED]`.

---

## 1. The 5-Beat Narrative Arc

Every AL-AMR script follows a mathematically structured 5-beat rhythm designed to maximize completion rate and Average Percentage Viewed (APV) `[CODE VERIFIED]`:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       5-BEAT HIGH-RETENTION SCRIPT                          │
├─────────┬──────────────────────┬─────────────┬──────────────────────────────┤
│ Beat    │ Name                 │ Word Target │ Narrative Function           │
├─────────┼──────────────────────┼─────────────┼──────────────────────────────┤
│ Beat 1  │ The Jarring Hook     │ 10–14 words │ Shocking contradiction/event │
│ Beat 2  │ The Escalation       │ 12–16 words │ Context, stakes, absurdity   │
│ Beat 3  │ The Physical Evidence│ 12–16 words │ Documented artifacts/records │
│ Beat 4  │ The Bizarre Climax   │ 14–18 words │ The unbelievable resolution  │
│ Beat 5  │ The Lingering Chasm  │ 8–12 words  │ Lingering historical mystery │
├─────────┼──────────────────────┼─────────────┼──────────────────────────────┤
│ TOTAL   │ Complete Script      │ 58–72 words │ Runtime: 22.0s – 25.0s       │
└─────────┴──────────────────────┴─────────────┴──────────────────────────────┘
```

---

## 2. Hard Editorial Quality Gates

Implemented in `engines/script_critic.py` and `intelligence/council.py`:
- **Word Count Ceiling:** Rejects any script $<58$ or $>72$ words `[CODE VERIFIED]`.
- **Hook Timing:** The hook must occur within the first 1.5 seconds. Scripts starting with filler ("In this video...", "Did you know...", "Have you ever wondered...") are rejected immediately `[CODE VERIFIED]`.
- **Anti-AI Cliché Defense:** Rejects scripts containing generic AI phrases:
  - *"A testament to human ingenuity"*
  - *"History is stranger than fiction"*
  - *"Leaves us with more questions than answers"*
  - *"In a world where..."*
  - *"Today, we explore..."* `[CODE VERIFIED]`.
- **Conversational Tone:** Written for natural human voice delivery ("Tell me what happened"), prioritizing active voice and physical verbs `[LIVE VERIFIED]`.