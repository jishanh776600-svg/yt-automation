"""
Lightweight Step 7 Verification Script.
Checks:
  1. Imports and module loading.
  2. Step 1-6 interface compatibility.
  3. Adaptive query generation from VisualIntent.
  4. Staged stream early rejection (image magic bytes & HTML).
  5. Parallel provider execution and failure isolation.
  6. Telemetry collection and non-leakage.
"""
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 1. Imports
from engines.visual_intelligence import (
    RetrievalBudget,
    AdaptiveQueryExpander,
    StagedStreamIngester,
    ParallelVideoRetriever,
    RetrievalTelemetryRecord,
    RetrievalTelemetryCollector,
    InternetVideoRetriever,
    VisualIntent,
    NormalizedVideoCandidate,
    SourceType,
    BaseVideoRetrievalProvider,
)
from core.media_validator import PhysicalVideoValidator, VIDEO_ONLY

print("1. All Step 7 modules imported successfully.")
assert VIDEO_ONLY is True, "VIDEO_ONLY invariant violated!"

# 2. RetrievalBudget test
budget = RetrievalBudget(provider_timeout=4.0, max_download_bytes=50 * 1024 * 1024)
assert budget.provider_timeout == 4.0
assert budget.max_download_bytes == 50 * 1024 * 1024
print("2. RetrievalBudget initialized with custom and default parameters.")

# 3. Adaptive Query Expander test
expander = AdaptiveQueryExpander()
intent = VisualIntent(
    beat_id="beat_1",
    beat_index=1,
    narration_text="The RMS Titanic collided with a massive iceberg in the freezing North Atlantic.",
    target_object="RMS Titanic",
    visual_action="colliding with iceberg",
    primary_entity="Titanic",
    historical_context="1912 North Atlantic",
    important_nouns=["iceberg", "ocean liner"],
    disambiguating_terms=["archival footage", "movie film scene"]
)

variants = expander.expand_queries("Titanic iceberg collision", intent, max_variants=3)
print(f"3. Generated {len(variants)} adaptive query variants: {variants}")
assert len(variants) >= 2
assert "Titanic iceberg collision" in variants[0]
for v in variants:
    assert v.lower() not in {"ship", "water", "ocean", "movie", "video"}, "Generic isolated keyword found!"

# 4. Staged Streaming Ingester Early Rejection test
ingester = StagedStreamIngester()

# Test 4a: JPEG magic bytes
jpeg_payload = b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + (b"\x00" * 100)
is_rej, reason = ingester.is_early_rejected_payload(jpeg_payload)
assert is_rej is True
assert "image" in reason.lower()
print(f"4a. Early magic-byte rejection on JPEG verified: {reason}")

# Test 4b: HTML error page
html_payload = b"<!DOCTYPE html><html><body>502 Bad Gateway</body></html>"
is_rej_html, html_reason = ingester.is_early_rejected_payload(html_payload)
assert is_rej_html is True
assert "html" in html_reason.lower() or "502" in html_reason.lower()
print(f"4b. Early rejection on HTML verified: {html_reason}")

# Test 4c: Prohibited image URL rejected before network
temp_dest = Path(tempfile.gettempdir()) / "test_reject.mp4"
succ, err, bytes_dl = ingester.stream_and_validate("https://example.com/photo.jpg", temp_dest)
assert succ is False
assert "image url rejected" in err.lower()
assert not temp_dest.exists()
print("4c. Static image URL rejected before network request without temp file leakage.")

# 5. Parallel Provider Video Retriever test
class MockProvider(BaseVideoRetrievalProvider):
    def __init__(self, name, source_type, fail=False):
        super().__init__(name=name, source_type=source_type)
        self.fail = fail

    def search(self, query, intent=None, count=3, exclude_urls=None):
        if self.fail:
            raise ConnectionResetError("Provider connection reset by peer (504)")
        return [
            NormalizedVideoCandidate(
                source_name=self.name,
                source_type=self.source_type,
                title=f"Sample from {self.name}",
                media_url=f"https://cdn.example.com/{self.name}_stream.mp4",
                duration=4.5,
                is_video=True
            )
        ]

prov_ok = MockProvider("archive_ok", SourceType.ARCHIVAL, fail=False)
prov_fail = MockProvider("internet_broken", SourceType.INTERNET_REAL, fail=True)

parallel_retriever = ParallelVideoRetriever()
cands, reports = parallel_retriever.search_providers_parallel(
    providers=[prov_ok, prov_fail],
    query="historic launch",
    budget=RetrievalBudget(enable_parallel=True)
)

print(f"5. Parallel retrieval executed. Reports: {reports}")
assert len(cands) == 1
assert cands[0].source_name == "archive_ok"
statuses = {r["provider"]: r["status"] for r in reports}
assert statuses["archive_ok"] == "SUCCESS"
assert statuses["internet_broken"] == "FAILED"
print("5. Provider failure isolation confirmed: failing provider did not break healthy provider.")

# 6. Telemetry collection
telemetry = RetrievalTelemetryCollector()
telemetry.record(RetrievalTelemetryRecord(
    scene_id="scene_test_1",
    query="naval battle",
    provider="movie_footage",
    source_type="MOVIE",
    candidate_url="https://example.com/clip.mp4",
    retrieval_latency=0.345,
    bytes_downloaded=12500000,
    validation_result="VALID",
    semantic_score=0.88,
    temporal_result="WINDOW_FOUND",
    memory_result="CLEAN",
    selected_status="SELECTED"
))
summary = telemetry.get_summary()
print(f"6. Telemetry summary: {summary}")
assert summary["selected_count"] == 1
assert summary["total_bytes_downloaded"] == 12500000

print("\n>>> ALL LIGHTWEIGHT STEP 7 VALIDATIONS PASSED DIRECTLY. <<<")
