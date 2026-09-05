---
aliases:
  - Script Engine
  - Retention Scripting
tags:
  - scripting
  - quality
  - pacing
last_updated: 2026-09-05
---

# 05 — High-Retention Journalistic Scripting

> **Status:** `[CANONICAL SPECIFICATION]`  
> **Scope:** Word count constraints, 5-beat retention anatomy, anti-cliché enforcement, and duration calibration.

---

## 1. Script Craftsmanship Standards

Short-form mobile video retention requires extreme density. The viewer's finger is perpetually ready to swipe. Every word must justify its existence.

```
+---------------------------------------------------------------------------------------------------+
| SCRIPT TARGET CONSTRAINTS                                                                         |
+---------------------------------------------------------------------------------------------------+
| • Exact Word Count    : Strictly 62 to 70 words (optimal: 66 words)                               |
| • Target Duration     : 22.0s to 25.0s (canonical target: 23.2s)                                  |
| • Speech Cadence      : 2.7 to 3.0 words / second                                                 |
| • Scene Beat Density  : 9 to 12 visual beats (target: 10 scenes, ~2.3s per cut)                   |
| • Sentence Pauses     : 0.08s sentence break, 0.03s clause break                                   |
| • Post-Process Silence: Capped at <= 100ms via silence compression chain                          |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. The 5-Beat Narrative Progression

Every script is structured across 5 distinct narrative movements:

```
[0.0s - 2.5s]  BEAT 1: THE HOOK        --> Direct sensory / physical anomaly (10-12 words)
[2.5s - 7.5s]  BEAT 2: CONTEXT         --> Tangible physical setting & documented discovery (12-14 words)
[7.5s - 13.0s] BEAT 3: COMPLICATION    --> Why standard explanations failed (14-16 words)
[13.0s - 18.5s]BEAT 4: PHYSICAL DETAIL --> Exact measurement, specimen, or artifact (14-16 words)
[18.5s - 23.2s]BEAT 5: PAYOFF / REVEAL --> The haunting twist or scientific implication (12-14 words)
```

### Beat 1: The Curiosity Hook (First 1–2 Seconds)
- **Goal:** Stop the scroll instantly.
- **Rule:** Never introduce the channel, the date, or the creator. Never say *"Did you know?"* or *"Today we look at..."*.
- **Example:** *"Inside an abandoned gold mine in South Dakota, physicists detected an impossible atomic signal."*

### Beat 2: Grounded Context (2.5s – 7.5s)
- **Goal:** Establish reality and authenticity.
- **Rule:** Mention specific physical locations, institutions, or researchers.

### Beat 3: The Escalating Complication (7.5s – 13.0s)
- **Goal:** Deepen the mystery; prove this wasn't a simple mistake.
- **Rule:** Show that conventional explanations collapsed.

### Beat 4: Physical Evidence & Details (13.0s – 18.5s)
- **Goal:** Provide concrete sensory evidence for the real-footage engine to illustrate.
- **Rule:** Use concrete nouns: core samples, sonar scans, satellite coordinates, titanium cylinders, fossilized teeth.

### Beat 5: The Payoff / Reveal (18.5s – 23.2s)
- **Goal:** Satisfy the initial curiosity while leaving a lingering psychological resonance.
- **Rule:** End on a definitive, memorable punchline. Never trail off with generic calls to action (*"like and subscribe"* is strictly banned).

---

## 3. Anti-Cliché & Editorial Quality Gates

The `JournalisticScriptEngine` deterministically rejects scripts containing any of the following patterns:

```
┌───────────────────────────────────────┬───────────────────────────────────────┐
│ BANNED AI PHRASING (REJECTED)         │ ACCEPTABLE DIRECT FACT (APPROVED)     │
├───────────────────────────────────────┼───────────────────────────────────────┤
│ "In a world where..."                 │ Direct statement of the event         │
│ "Little did they know..."             │ Documented sequence of actions        │
│ "Experts were completely baffled..."  │ "Geologists recorded 14 unexplained..."│
│ "It turns out that..."                │ State the finding directly            │
│ "This changes everything we know..."  │ State the exact paradigm shift        │
│ "Today, incredible news emerged..."   │ Start with the subject itself         │
└───────────────────────────────────────┴───────────────────────────────────────┘
```

---

## 4. Architectural Links
- Master Overview: [[00 - Master Dashboard|AL-AMR Dashboard]]
- Council Synthesis: [[04 - AI Council|AI Council]]
- Narration Pacing: [[06 - Audio & Voice|Audio & Voice]]
- Visual Directing: [[07 - Visual System|Visual System]]