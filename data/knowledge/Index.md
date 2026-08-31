# AL AMR // Autonomous YouTube Shorts Production Brain

*Obsidian Knowledge Vault — Operational Intelligence & System Standards*
*Last Synchronized: 2026-08-31 15:36:24 UTC*

---

## 🏛 Core System Invariants
- **Canonical Voice**: `af_bella` (Kokoro-v1.0 ONNX, American English Female)
- **Daily Publishing Limit**: `3` Shorts/day
- **Target Reserve Buffer**: `6` verified Shorts in Drive `01_READY`
- **Publishing Slots (UTC)**: `06:00 UTC`, `11:00 UTC`, `15:00 UTC`
- **Target Duration**: `21.0s – 25.0s` (with mandatory 0.6s outro breathing margin)
- **Target Resolution**: `1080x1920` (9:16 vertical)
- **Target Master Loudness**: `-14.0 LUFS` (Broadcast window: `-17.0` to `-11.0` LUFS)

---

## 🧠 Provider Failover Hierarchy
1. **Gemini Primary** (`gemini-3.6-flash`)
2. **Gemini Secondary** (Backup Google GenAI credential)
3. **Groq** (`groq/compound-mini` via high-speed REST)
4. **OpenRouter** (`meta-llama/llama-3.3-70b-instruct:free` fallback)
5. **Bounded Clean Failure** (Zero corrupt outputs or infinite retry storms)

---

## 🗺 Knowledge Graph & Operational Workflow
```
[[Topics/topic_lifecycle|01. Topics]]
       │
       ▼
[[Research/historical_grounding|02. Research & Fact Verification]]
       │
       ▼
[[Scripts/retention_architecture|03. Retention Scripting]] ──► [[Voice/af_bella_canonical|Voice Engine]]
       │                                                                 │
       ▼                                                                 │
[[Visuals/composition_rules|04. Visual Composition]] ◄──────────────────┘
       │
       ├──────────────► [[BGM/acoustic_standards|BGM Acoustic Standards]]
       ├──────────────► [[SFX/sfx_integration|SFX Director]]
       │
       ▼
[[Production/pipeline_rules|05. Production & Reserve Buffer]] ──► [[Decisions/provider_chain|AI Providers]]
       │                                                      ──► [[Failures/quarantine_policy|Quarantine Policy]]
       ▼
[[Performance/publishing_and_telemetry|06. Published Videos & Telemetry]]
       │
       ▼
[[Learning/strategy_insights|07. Closed-Loop Learning & Strategy Weights]]
       │
       └──────────────► [[System/operating_invariants|Channel Baseline & Invariants]]
```

---

## 📂 Domain Index
- [[Topics/topic_lifecycle|Topic Discovery & Deduplication]]
- [[Research/historical_grounding|Historical Research & Fact Grounding]]
- [[Scripts/retention_architecture|5-Stage Retention Scripting]]
- [[Voice/af_bella_canonical|Canonical Voice: af_bella]]
- [[Visuals/composition_rules|Visual Composition & Directing]]
- [[BGM/acoustic_standards|BGM Loudness & Fingerprint Verification]]
- [[SFX/sfx_integration|SFX Punctuation & Audio Risers]]
- [[Production/pipeline_rules|6-Stage Production Pipeline]]
- [[Performance/publishing_and_telemetry|Publishing Slots & Telemetry Data Truth]]
- [[Learning/strategy_insights|Closed-Loop Performance Learning]]
- [[Decisions/provider_chain|AI Provider Failover Architecture]]
- [[Failures/quarantine_policy|Poison-Pill Quarantine & Safe Recovery]]
- [[System/operating_invariants|System Invariants & Durable Backup]]