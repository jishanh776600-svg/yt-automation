---
aliases:
  - AI Council
  - Multi-Agent Council
tags:
  - ai
  - intelligence
  - quality
last_updated: 2026-09-05
---

# 04 — Multi-Agent AI Council Architecture

> **Status:** `[LIVE & INTEGRATED]`  
> **Scope:** Tripartite AI Council roles, synthesis algorithms, genuine deliberation invariants, and the Council Quality Gate.

---

## 1. Council Philosophy & Purpose

A single LLM writing an entire video script often suffers from generic explainer habits: predictable rhetorical openings, clichéd transitions ("little did they know"), vague factual claims, and weak endings. 

AL-AMR solves this through a **Tripartite AI Council** of specialized, competing model personas that review, critique, and shape every script before voice synthesis:

```
                    ┌─────────────────────────────────────────┐
                    │            RAW TOPIC / EVENT            │
                    └────────────────────┬────────────────────┘
                                         │
                 ┌───────────────────────┼───────────────────────┐
                 ▼                       ▼                       ▼
    ┌─────────────────────────┐ ┌─────────────────┐ ┌─────────────────────────┐
    │     DEEPSEEK CHAIR      │ │  KIMI K3 CHAIR  │ │     NEMOTRON CHAIR      │
    ├─────────────────────────┤ ├─────────────────┤ ├─────────────────────────┤
    │ • Counter-intuitive hook│ │ • Retention     │ │ • Factual integrity     │
    │ • Curiosity gap framing │ │ • Swipe-risk    │ │ • Physical evidence     │
    │ • Narrative progression │ │ • Pacing audit  │ │ • Visual feasibility   │
    └────────────┬────────────┘ └────────┬────────┘ └────────────┬────────────┘
                 │                       │                       │
                 └───────────────────────┼───────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │      COUNCIL SYNTHESIS & DRAFTING       │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │       COUNCIL QUALITY GATE AUDIT        │
                    ├─────────────────────────────────────────┤
                    │ • 62-70 words verified                  │
                    │ • Zero AI clichés                       │
                    │ • Curiosity hook in first 1-2s          │
                    │ • No generic news openings ("Today...") │
                    └────────────────────┬────────────────────┘
                                         │
                           ┌─────────────┴─────────────┐
                           ▼                           ▼
                     [PASS >= 7.5]               [FAIL < 7.5]
                           │                           │
                           ▼                           ▼
                     Proceed to TTS              Rewrite or Reject
```

---

## 2. Council Roles & Specializations

### 1. DeepSeek: The Narrative & Framing Chair
- **Core Mission:** Hook velocity and counter-intuitive perspective.
- **Responsibility:** Identifies the single most surprising element of the discovery. Transforms mundane facts into high-curiosity propositions without fabricating information.
- **Key Directive:** *"Eliminate encyclopedic introductions. Start directly inside the anomaly."*

### 2. Kimi K3: The Retention & Pacing Chair
- **Core Mission:** Anti-swipe mechanics and narrative momentum.
- **Responsibility:** Audits the beat-by-beat progression. Detects informational lulls where a mobile viewer might swipe away.
- **Key Directive:** *"Every sentence must introduce new, concrete information. No repetitive phrasing or filler transitions."*

### 3. Nemotron: The Factual Integrity & Visual Feasibility Chair
- **Core Mission:** Grounding in physical reality and visual retrieval viability.
- **Responsibility:** Verifies that claims represent documented facts. Ensures every narration beat corresponds to tangible physical objects, places, or phenomena that can be illustrated with real imagery.
- **Key Directive:** *"Reject abstract assertions. Ground the narrative in dates, artifacts, locations, and physical observations."*

---

## 3. The Genuine Deliberation Invariant

> [!IMPORTANT]
> **ARCHITECTURAL INVARIANT: GENUINE COUNCIL INFLUENCE**  
> Council outputs must genuinely shape the final script. Calling AI models for cosmetic logging is strictly prohibited. If any Council chair raises a critical objection (e.g. factual doubt from Nemotron or swipe risk from Kimi), the script must either integrate the recommended rewrite or be rejected fail-closed.

---

## 4. Council Quality Gate Specification

Implemented in [`intelligence/ai_council.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/intelligence/ai_council.py) and [`intelligence/journalistic_script.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/intelligence/journalistic_script.py):

| Criterion | Rejection Threshold | Passing Standard |
|---|---|---|
| **Word Count** | < 62 or > 70 words | Strictly 62 to 70 words |
| **Duration Calibration** | < 22.0s or > 25.0s | 22.0s to 25.0s (Target: ~23.2s) |
| **Banned Clichés** | Contains phrases like *"in a world where"*, *"little did they know"*, *"it turns out"*, *"experts were baffled"* | Zero detected clichés |
| **Generic Openings** | Begins with *"Today..."*, *"Recently..."*, *"In recent news..."* | Hook starts directly with physical anomaly |
| **Composite Score** | < 7.5 / 10.0 | >= 7.5 / 10.0 required for production deposit |

---

## 5. Architectural Links
- System Overview: [[00 - Master Dashboard|AL-AMR Dashboard]]
- Script Implementation: [[05 - Script Engine|Script Engine]]
- Content Strategy: [[02 - Content Strategy|Content Strategy]]
- QA System: [[13 - QA & Testing|QA System]]