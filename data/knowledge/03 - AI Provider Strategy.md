# 03 — AI Provider Strategy

> **Status:** `[VERIFIED & OPERATIONAL]`  
> **Scope:** Multi-provider cascading failover hierarchy, rate limits, token economics, and DeepSeek exclusion policy.  

---

## 1. Provider Failover Hierarchy

AL AMR operates a resilient 5-tier provider cascade. If a higher-priority provider encounters rate limits (HTTP 429), timeouts, or API errors, execution seamlessly cascades to the next tier:

```
+---------------------------------------------------------------------------------------------------+
| PROVIDER CASCADING HIERARCHY                                                                      |
+---------------------------------------------------------------------------------------------------+
| Tier 1: Gemini Primary     --> Model: gemini-2.5-flash (Google AI Studio API Key)                 |
|           │ (on HTTP 429 / Quota / Timeout)                                                       |
|           ▼                                                                                       |
| Tier 2: Gemini Secondary   --> Model: gemini-2.5-flash (Secondary Backup Google Credential)        |
|           │ (on Failure)                                                                          |
|           ▼                                                                                       |
| Tier 3: Groq               --> Model: llama-3.3-70b-versatile (High-speed LPU inference)          |
|           │ (on Failure)                                                                          |
|           ▼                                                                                       |
| Tier 4: OpenRouter         --> Model: meta-llama/llama-3.3-70b-instruct:free (Open router free)  |
|           │ (on Failure)                                                                          |
|           ▼                                                                                       |
| Tier 5: Curated Fallback   --> Pre-verified deterministic historical seeds & scripts ($0 API cost)|
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Policy on DeepSeek

> [!IMPORTANT]
> **EXPLICIT ARCHITECTURAL INVARIANT: DEEPSEEK IS NOT USED**
> - DeepSeek is **NOT** integrated into AL AMR.
> - DeepSeek is **NOT** purchased.
> - DeepSeek API keys are **NOT** configured in repository secrets or local environment variables.
> - DeepSeek dependencies are **NOT** included in `requirements.txt`.
> - DeepSeek is classified strictly as an extreme theoretical last-resort provider that will only be considered if all primary, secondary, tertiary, and open-source routes fail permanently and there is genuinely no viable alternative.
> - Verified by unit test: `test_09_no_deepseek_dependency` in `test_step27_producer_cycle_and_reserve_refill_root_cause.py`.

---

## 3. Verified API Token Economics (Gemini 2.5 Flash)

Measured across real production script generation, fact verification, and storyboard planning:

| Metric | Measured Usage / Short | Official Pricing (Gemini 2.5 Flash) | Cost / Short |
|---|---|---|---|
| **Input Tokens** | $\sim 1,800	ext{ tokens}$ | $\$0.075	ext{ / 1,000,000 tokens}$ | $\$0.000135$ |
| **Output Tokens** | $\sim 1,200	ext{ tokens}$ | $\$0.300	ext{ / 1,000,000 tokens}$ | $\$0.000360$ |
| **Total Inference Cost** | $\sim 3,000	ext{ tokens}$ | — | **`$0.000495` / Short** |
| **TTS Narration Cost** | Local Kokoro-82M ONNX | Local CPU / Offline | **`$0.000000`** |
| **Visual Asset Cost** | Wikimedia + Pollinations + Pexels | Public Domain / CC0 / Open API | **`$0.000000`** |
| **Total Production Cost**| — | — | **`< $0.0005` / Short** |

*Economic Conclusion:* 1,000 fully rendered, QA-verified Shorts can be produced for approximately **`$0.50` total AI spend**.