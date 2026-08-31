# AI Provider Hierarchy & Failover Architecture

## Failover Sequence
$$\text{Gemini Primary} \longrightarrow \text{Gemini Secondary} \longrightarrow \text{Groq} \longrightarrow \text{OpenRouter} \longrightarrow \text{Clean Failure}$$

## Provider Specifications
1. **Gemini Primary**: Google GenAI `gemini-3.6-flash` (High quality, primary LLM).
2. **Gemini Secondary**: Google GenAI secondary project credential.
3. **Groq**: Ultra-low latency `groq/compound-mini` via standard REST API.
4. **OpenRouter**: `meta-llama/llama-3.3-70b-instruct:free` fallback adapter.
5. **Clean Failure**: Bounded fail-fast without infinite retry amplification.

## Deprecated Providers
- **DeepSeek**: Permanently deprecated and removed from active provider chains.