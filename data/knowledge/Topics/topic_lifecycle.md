# Topic Discovery & Deduplication Lifecycle

## Discovery Strategy
AL AMR autonomously discovers compelling historical events, bizarre historical paradoxes, and turning points.

## Semantic Deduplication
- **Method**: Cosine similarity against historical topic vectors + exact title collision detection.
- **Novelty Rule**: Topics with similarity > 0.85 against existing library entries are rejected.
- **Workflow Link**: Once approved, topics proceed to [[Research/historical_grounding|Historical Grounding]].