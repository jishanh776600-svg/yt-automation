---
aliases:
  - Multi-Agent AI Council
  - AI Council
tags:
  - intelligence
  - council
  - llm
last_updated: 2026-09-07
---

# Multi-Agent AI Council Architecture

> **Status:** `[LIVE & VERIFIED]`  
> **Council Composition:** DeepSeek (Hook/Framing), Kimi K3 (Retention/Pacing), Nemotron (Factual Integrity/Visual Feasibility), Gemini (Lead Synthesis) `[CODE VERIFIED]`.  

---

## 1. Specialized Multi-Agent Roles

AL-AMR does not rely on a single monolithic LLM. Script drafting and review is distributed across specialized AI agents:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MULTI-AGENT AI COUNCIL                              │
├─────────────────────┬───────────────────┬───────────────────────────────────┤
│ Agent Name          │ Primary Model     │ Specialized Mandate               │
├─────────────────────┼───────────────────┼───────────────────────────────────┤
│ **Hook Specialist** │ DeepSeek-Chat     │ Crafting the 1.5s jarring opening │
│                     │                   │ contradiction and emotional hook  │
├─────────────────────┼───────────────────┼───────────────────────────────────┤
│ **Retention Editor**│ Kimi K3           │ Pacing, rhythm, word economy, and │
│                     │                   │ curiosity gaps between beats      │
├─────────────────────┼───────────────────┼───────────────────────────────────┤
│ **Fact & Visual QA**│ Nvidia Nemotron   │ Historical authenticity, physical │
│                     │                   │ artifacts, visual feasibility     │
├─────────────────────┼───────────────────┼───────────────────────────────────┤
│ **Lead Synthesizer**│ Google Gemini     │ Final 5-beat JSON unification and │
│                     │ 2.0 Flash / Pro   │ strict 58-72 word validation      │
└─────────────────────┴───────────────────┴───────────────────────────────────┘
```

---

## 2. Failover Cascade

If any secondary provider API is unreachable or rate-limited:
1. `DeepSeek` / `Kimi` / `Nemotron` failures fallback to internal Gemini multi-persona evaluation.
2. If Gemini Primary fails, secondary key `GEMINI_API_KEY_SECONDARY` is engaged.
3. If all external LLM calls fail, the system fails closed gracefully without producing broken scripts `[CODE VERIFIED]`.