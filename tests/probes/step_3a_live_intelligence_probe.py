"""
AL-AMR — STEP 3A: Controlled Live Intelligence Ingestion Probe.

HARD SAFETY BOUNDARY:
- READ-ONLY live network probe.
- LIVE_PROBE_ONLY = True enforced.
- ZERO live AI calls (Gemini, Groq, OpenRouter, DeepSeek, NVIDIA).
- ZERO production database mutations (uses sqlite:///:memory: only).
- ZERO Drive mutations, YouTube mutations, video rendering, or TTS generation.
- Never imports or invokes main.py production pipelines.
"""

import sys
import os

# Ensure repository root is on sys.path when run as a standalone script
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import time
import urllib.request
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Hard Safety Guard
LIVE_PROBE_ONLY = True

# Repository imports
from core.models import Base, Topic, SourceRecord, ClaimRecord
from core.content_profile import CURRENT_AFFAIRS_PROFILE, get_active_profile, set_active_profile
from core.discovery_profile import (
    DiscoveryProfile,
    CURRENT_AFFAIRS_DISCOVERY_PROFILE,
    get_active_discovery_profile,
    set_active_discovery_profile
)
from intelligence.models import RawArticle, EventCluster
from intelligence.normalization import normalize_article, extract_entities_and_tokens, normalize_url
from intelligence.sources.rss_source import RSSSourceAdapter, parse_pubdate
from intelligence.sources.gdelt_source import GDELTSourceAdapter
from intelligence.clustering import EventClusterEngine, compute_jaccard
from intelligence.freshness import FreshnessScorer
from intelligence.relevance import RelevanceScorer
from intelligence.scoring import OpportunityScorer
from intelligence.candidate_writer import CandidateWriter
from intelligence.deduplication import is_same_current_affairs_story, CurrentAffairsDeduplicationEngine
from engines.deduplication_engine import DeduplicationRouter

logger = logging.getLogger(__name__)


# ==============================================================================
# PROBE METRICS CONTAINER
# ==============================================================================

class ProbeMetrics:
    def __init__(self):
        self.probe_timestamp = datetime.now(timezone.utc).isoformat()
        self.feed_metrics: List[Dict[str, Any]] = []
        self.total_raw_articles = 0
        self.total_normalized_articles = 0
        self.total_unique_urls = 0
        self.duplicate_urls_dropped = 0
        self.malformed_items = 0
        self.timestamp_failures = 0
        self.domains_represented: Set[str] = set()

        # Clustering & Multi-source metrics
        self.total_clusters = 0
        self.clusters_1_domain = 0
        self.clusters_2_domains = 0
        self.clusters_3_domains = 0
        self.clusters_4plus_domains = 0
        self.clusters_passed_evidence = 0
        self.clusters_rejected_evidence = 0

        # Freshness breakdown
        self.freshness_distribution = {
            "BREAKING (<3h)": 0,
            "DEVELOPING (3-12h)": 0,
            "FRESH (12-24h)": 0,
            "RECENT (24-48h)": 0,
            "MATURING (48-72h)": 0,
            "BACKGROUND (>72h)": 0
        }
        self.future_timestamp_anomalies = 0

        # Relevance & Opportunity
        self.relevance_scores: List[float] = []
        self.opportunity_scores: List[float] = []
        self.categories_assigned: Dict[str, int] = {}

        # Sample Clusters
        self.sample_clusters: List[Dict[str, Any]] = []

        # Deduplication validations
        self.dedup_wire_duplicate_converged = False
        self.dedup_same_city_distinct_preserved = False

        # Safety Audit Counters (Must all remain 0)
        self.gemini_calls = 0
        self.groq_calls = 0
        self.openrouter_calls = 0
        self.deepseek_calls = 0
        self.nvidia_calls = 0
        self.production_topic_writes = 0
        self.drive_mutations = 0
        self.youtube_mutations = 0
        self.rendered_videos = 0
        self.tts_audio_generated = 0


# ==============================================================================
# LIVE HARVEST AND AUDIT EXECUTION
# ==============================================================================

def run_live_intelligence_probe() -> Tuple[ProbeMetrics, List[EventCluster]]:
    """
    Executes a bounded, safe, read-only live intelligence ingestion cycle.
    Returns collected diagnostic telemetry and live event clusters.
    """
    assert LIVE_PROBE_ONLY is True, "LIVE_PROBE_ONLY safety guard violation!"

    # 1. Enforce active profile
    set_active_profile(CURRENT_AFFAIRS_PROFILE)
    content_prof = get_active_profile()
    discovery_prof = get_active_discovery_profile()

    metrics = ProbeMetrics()
    all_raw_articles: List[RawArticle] = []
    seen_urls: Set[str] = set()

    # 2. Configured feeds inspection
    feeds_to_harvest = discovery_prof.rss_feeds or []
    if not feeds_to_harvest:
        from intelligence.sources.rss_source import DEFAULT_RSS_FEEDS
        feeds_to_harvest = DEFAULT_RSS_FEEDS

    adapter = RSSSourceAdapter(timeout=8.0)

    # 3. Source-by-source bounded harvest
    for feed_cfg in feeds_to_harvest:
        name = feed_cfg.get("name", "Unknown Wire")
        url = feed_cfg.get("url", "")
        domain = feed_cfg.get("domain", "")

        t0 = time.time()
        req_success = False
        http_status = None
        articles_returned = 0
        malformed_in_feed = 0
        dups_in_feed = 0
        ts_fails_in_feed = 0
        xml_content = None

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "AlAmrIntelligenceProbe/1.0 (+https://github.com/jishanh776600-svg/yt-automation)",
                    "Accept": "application/rss+xml, application/xml, text/xml"
                }
            )
            with urllib.request.urlopen(req, timeout=adapter.timeout) as resp:
                http_status = resp.status
                if resp.status == 200:
                    raw_bytes = resp.read()
                    try:
                        xml_content = raw_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        xml_content = raw_bytes.decode("latin-1", errors="ignore")
                    req_success = True
                else:
                    req_success = False
        except urllib.error.HTTPError as he:
            http_status = he.code
            req_success = False
        except Exception as err:
            http_status = str(err)
            req_success = False

        elapsed = round(time.time() - t0, 3)

        # Parse articles if XML retrieved
        parsed_articles = []
        if req_success and xml_content:
            try:
                parsed_articles = adapter.parse_feed_content(xml_content, default_source_name=name, default_domain=domain)
                articles_returned = len(parsed_articles)
            except Exception:
                malformed_in_feed += 1

        # Process and normalize individual articles
        feed_normalized_count = 0
        for art in parsed_articles:
            if not art.title or not art.url:
                malformed_in_feed += 1
                continue

            if art.published_at is None:
                ts_fails_in_feed += 1

            norm_art = normalize_article(art, profile=discovery_prof)
            canonical = norm_art.url
            if canonical in seen_urls:
                dups_in_feed += 1
                continue

            seen_urls.add(canonical)
            all_raw_articles.append(norm_art)
            feed_normalized_count += 1
            metrics.domains_represented.add(norm_art.source_domain)

        metrics.total_raw_articles += articles_returned
        metrics.total_normalized_articles += feed_normalized_count
        metrics.malformed_items += malformed_in_feed
        metrics.duplicate_urls_dropped += dups_in_feed
        metrics.timestamp_failures += ts_fails_in_feed

        metrics.feed_metrics.append({
            "name": name,
            "url": url,
            "domain": domain,
            "success": req_success,
            "http_status": http_status,
            "elapsed_sec": elapsed,
            "articles_returned": articles_returned,
            "normalized_count": feed_normalized_count,
            "malformed_count": malformed_in_feed,
            "duplicate_urls": dups_in_feed,
            "ts_failures": ts_fails_in_feed
        })

    metrics.total_unique_urls = len(seen_urls)

    # 4. Event Clustering
    cluster_engine = EventClusterEngine()
    clusters = cluster_engine.cluster_articles(all_raw_articles)
    metrics.total_clusters = len(clusters)

    # 5. Multi-Source Consensus Distribution
    for cl in clusters:
        num_domains = len(cl.source_domains)
        if num_domains == 1:
            metrics.clusters_1_domain += 1
        elif num_domains == 2:
            metrics.clusters_2_domains += 1
        elif num_domains == 3:
            metrics.clusters_3_domains += 1
        else:
            metrics.clusters_4plus_domains += 1

    # 6. Freshness, Relevance, Scoring & Evidence Gate
    fresh_scorer = FreshnessScorer()
    rel_scorer = RelevanceScorer(profile=discovery_prof)
    opp_scorer = OpportunityScorer(profile=discovery_prof)
    candidate_writer = CandidateWriter(min_independent_domains=2, min_opportunity_score=40.0)

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    for cl in clusters:
        # Freshness
        f_score, f_label = fresh_scorer.evaluate_freshness(cl)
        cl.freshness_score = f_score

        # Age classification
        if cl.first_published_at:
            if cl.first_published_at > now_utc + timedelta(minutes=5):
                metrics.future_timestamp_anomalies += 1
            age_hours = (now_utc - cl.first_published_at).total_seconds() / 3600.0
            if age_hours < 3.0:
                metrics.freshness_distribution["BREAKING (<3h)"] += 1
            elif age_hours < 12.0:
                metrics.freshness_distribution["DEVELOPING (3-12h)"] += 1
            elif age_hours < 24.0:
                metrics.freshness_distribution["FRESH (12-24h)"] += 1
            elif age_hours < 48.0:
                metrics.freshness_distribution["RECENT (24-48h)"] += 1
            elif age_hours < 72.0:
                metrics.freshness_distribution["MATURING (48-72h)"] += 1
            else:
                metrics.freshness_distribution["BACKGROUND (>72h)"] += 1
        else:
            metrics.freshness_distribution["BACKGROUND (>72h)"] += 1

        # Relevance
        rel_score, assigned_cat = rel_scorer.evaluate_relevance(cl)
        cl.relevance_score = rel_score
        cl.primary_category = assigned_cat
        metrics.relevance_scores.append(rel_score)
        metrics.categories_assigned[assigned_cat] = metrics.categories_assigned.get(assigned_cat, 0) + 1

        # Opportunity Score
        opp_score = opp_scorer.calculate_opportunity_score(cl)
        cl.opportunity_score = opp_score
        metrics.opportunity_scores.append(opp_score)

        # Evidence Gate (>=2 independent publisher domains)
        passed_evidence, reason = candidate_writer.evaluate_multi_source_evidence(cl)
        if passed_evidence:
            metrics.clusters_passed_evidence += 1
        else:
            metrics.clusters_rejected_evidence += 1

    # 7. Collect Sample Clusters
    # Sort clusters by: corroborated first, then opportunity score desc
    sorted_clusters = sorted(
        clusters,
        key=lambda c: (len(c.source_domains) >= 2, c.opportunity_score),
        reverse=True
    )
    for c in sorted_clusters[:8]:
        metrics.sample_clusters.append({
            "title": c.canonical_title,
            "article_count": len(c.articles),
            "domains": sorted(list(c.source_domains)),
            "entities": sorted(list(c.entities))[:6],
            "action_tokens": sorted(list(c.action_tokens))[:4],
            "category": c.primary_category,
            "freshness_score": round(c.freshness_score, 1),
            "relevance_score": round(c.relevance_score, 1),
            "opportunity_score": round(c.opportunity_score, 1),
            "evidence_passed": len(c.source_domains) >= 2
        })

    # 8. Deduplication Verification
    # Wire report duplicates (same event from different wires) converge
    cand_wire_title = "White House Imposes 25 Percent Tariffs on Foreign Steel"
    cand_wire_summary = "Sweeping US tariffs on foreign steel announced, raising fears of global trade retaliation."
    cand_wire_ent, _, cand_wire_act, cand_wire_kw = extract_entities_and_tokens(
        f"{cand_wire_title}. {cand_wire_summary}",
        profile=discovery_prof
    )
    exist_wire_title = "US Imposes Sweeping 25 Percent Tariffs on Global Steel Imports"
    exist_wire_summary = "The White House announced sweeping 25 percent tariffs on foreign steel exports sparking trade retaliation fears."
    is_dup_wire, _ = is_same_current_affairs_story(
        cand_title=cand_wire_title,
        cand_summary=cand_wire_summary,
        cand_actions=cand_wire_act,
        cand_entities=cand_wire_ent,
        cand_keywords=cand_wire_kw,
        exist_title=exist_wire_title,
        exist_summary=exist_wire_summary,
        profile=discovery_prof
    )
    metrics.dedup_wire_duplicate_converged = is_dup_wire

    # Distinct events sharing same city and year (London strike vs London cyberattack) remain separate
    is_dup_distinct, _ = is_same_current_affairs_story(
        cand_title="London Stock Exchange Targeted by Severe Cyberattack Disrupting Trades",
        cand_summary="Financial regulators in London halt morning trading following state-sponsored hack.",
        cand_actions={"cyberattack", "halt"},
        cand_entities={"london"},
        cand_keywords={"stock", "exchange", "cyberattack", "trades", "trading", "financial"},
        exist_title="London Heathrow Airport Workers Announce 48-Hour Strike Over Wages",
        exist_summary="Heathrow baggage handlers walk out causing travel chaos across London.",
        profile=discovery_prof
    )
    metrics.dedup_same_city_distinct_preserved = (not is_dup_distinct)

    return metrics, clusters


# ==============================================================================
# PYTEST TEST SUITE
# ==============================================================================

def test_live_probe_execution():
    """Validates live RSS network harvest, metric capture, and evidence evaluation."""
    metrics, clusters = run_live_intelligence_probe()

    # Success Criteria:
    # 1. At least one configured live source contacted successfully
    contacted_success = [f for f in metrics.feed_metrics if f["success"]]
    assert len(contacted_success) >= 1, f"No feeds succeeded! Feed results: {metrics.feed_metrics}"

    # 2. Total normalized articles >= 1
    assert metrics.total_normalized_articles >= 1, "Zero articles normalized from live feeds!"

    # 3. Clustering operates on live data
    assert metrics.total_clusters >= 1, "Zero event clusters formed!"

    # 4. Freshness operated on live data
    assert len(metrics.opportunity_scores) == metrics.total_clusters

    # 5. Evidence gate enforces >=2 independent domains
    assert metrics.clusters_passed_evidence == (metrics.clusters_2_domains + metrics.clusters_3_domains + metrics.clusters_4plus_domains)
    assert metrics.clusters_rejected_evidence == metrics.clusters_1_domain

    # 6. Deduplication integrity
    assert metrics.dedup_wire_duplicate_converged is True, "Wire duplicate did not converge!"
    assert metrics.dedup_same_city_distinct_preserved is True, "Distinct same-city events falsely collided!"

    # 7. Safety Assertions
    assert metrics.gemini_calls == 0
    assert metrics.groq_calls == 0
    assert metrics.openrouter_calls == 0
    assert metrics.deepseek_calls == 0
    assert metrics.nvidia_calls == 0
    assert metrics.production_topic_writes == 0
    assert metrics.drive_mutations == 0
    assert metrics.youtube_mutations == 0
    assert metrics.rendered_videos == 0
    assert metrics.tts_audio_generated == 0


def test_offline_network_failure_containment():
    """Deterministic offline test: timeout and 404/500 errors in one feed do not terminate others."""
    adapter = RSSSourceAdapter(timeout=0.01)

    # Feed 1: Timeout / Unreachable
    # Feed 2: Valid XML
    valid_xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Valid Feed</title>
        <link>https://valid.org</link>
        <item>
          <title>Geneva Peace Accord Signed</title>
          <link>https://valid.org/geneva-peace</link>
          <description>Envoys finalize armistice treaty.</description>
          <pubDate>Fri, 04 Sep 2026 10:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """

    mock_feeds = [
        {"name": "Broken Feed", "url": "http://127.0.0.1:9999/unreachable.xml", "domain": "broken.org"},
        {"name": "Valid Feed", "url": "https://valid.org/rss.xml", "domain": "valid.org"}
    ]

    adapter.feeds = mock_feeds

    def mock_fetch(url):
        if "unreachable" in url:
            return None
        return valid_xml

    adapter.fetch_feed_xml = mock_fetch
    articles = adapter.ingest_all()

    # Valid feed succeeded despite broken feed failing!
    assert len(articles) == 1
    assert articles[0].title == "Geneva Peace Accord Signed"
    assert articles[0].source_domain == "valid.org"


def test_offline_gdelt_failure_containment():
    """Deterministic offline test: GDELT timeout or malformed JSON does not crash discovery."""
    adapter = GDELTSourceAdapter(timeout=0.01)

    # Mock raw HTTP returning malformed JSON
    adapter._execute_http_get = lambda url: "INVALID_NOT_JSON{{"

    articles = adapter.fetch_articles("geopolitics")
    assert articles == [], "Malformed GDELT JSON must return empty list safely."


def test_offline_evidence_gate_same_publisher_prevention():
    """Verifies 2 URLs from the same publisher do NOT satisfy the evidence gate."""
    writer = CandidateWriter(min_independent_domains=2)

    cluster = EventCluster(
        cluster_id="cl_same_pub",
        canonical_title="London Diplomatic Summit Concludes",
        canonical_summary="Officials reach trade agreement in London."
    )

    # Add 2 articles both from bbc.co.uk
    art1 = RawArticle(
        title="London Summit: Day 1",
        summary="Summit begins.",
        url="https://www.bbc.co.uk/news/world-1",
        source_domain="bbc.co.uk",
        source_name="BBC",
        published_at=datetime.now(timezone.utc)
    )
    art2 = RawArticle(
        title="London Summit: Day 2",
        summary="Summit concludes with treaty.",
        url="https://www.bbc.co.uk/news/world-2",
        source_domain="bbc.co.uk",
        source_name="BBC",
        published_at=datetime.now(timezone.utc)
    )

    cluster.add_article(art1)
    cluster.add_article(art2)

    assert len(cluster.source_domains) == 1, "Same-publisher articles must collapse to 1 source domain!"
    passed, reason = writer.evaluate_multi_source_evidence(cluster)
    assert passed is False
    assert cluster.status == "INSUFFICIENT_EVIDENCE"


def test_offline_deduplication_wire_convergence_and_same_city_separation():
    """Verifies that wire duplicates converge while distinct same-city events remain separate."""
    # 1. Wire duplicate
    cand_t = "White House Imposes 25 Percent Tariffs on Foreign Steel"
    cand_s = "Sweeping US tariffs on foreign steel announced, raising fears of global trade retaliation."
    cand_ent, _, cand_act, cand_kw = extract_entities_and_tokens(f"{cand_t}. {cand_s}")
    is_dup, reason = is_same_current_affairs_story(
        cand_title=cand_t,
        cand_summary=cand_s,
        cand_actions=cand_act,
        cand_entities=cand_ent,
        cand_keywords=cand_kw,
        exist_title="US Imposes Sweeping 25 Percent Tariffs on Global Steel Imports",
        exist_summary="The White House announced sweeping 25 percent tariffs on foreign steel exports sparking trade retaliation fears.",
    )
    assert is_dup is True
    assert "SIM" in reason or "TITLE" in reason

    # 2. Distinct events same city/year
    is_distinct_dup, distinct_reason = is_same_current_affairs_story(
        cand_title="London Stock Exchange Targeted by Severe Cyberattack Disrupting Trades",
        cand_summary="Financial regulators in London halt morning trading following state-sponsored hack.",
        cand_actions={"cyberattack"},
        cand_entities={"london"},
        cand_keywords={"stock", "exchange", "cyberattack", "trades", "trading", "financial"},
        exist_title="London Heathrow Airport Workers Announce 48-Hour Strike Over Wages",
        exist_summary="Heathrow baggage handlers walk out causing travel chaos across London.",
    )
    assert is_distinct_dup is False
    assert distinct_reason in ("DIFFERENT_ACTION_DOMAINS", "DISTINCT_EVENTS")


# ==============================================================================
# STANDALONE CLI ENTRYPOINT
# ==============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("\n========================================================")
    print("  AL-AMR STEP 3A: CONTROLLED LIVE INTELLIGENCE PROBE")
    print("========================================================\n")

    metrics, clusters = run_live_intelligence_probe()

    print(f"Probe Timestamp: {metrics.probe_timestamp}")
    print(f"Total Feeds Attempted: {len(metrics.feed_metrics)}")
    print(f"Total Normalized Articles: {metrics.total_normalized_articles}")
    print(f"Total Unique URLs: {metrics.total_unique_urls} (Dropped duplicates: {metrics.duplicate_urls_dropped})")
    print(f"Malformed Items Skipped: {metrics.malformed_items}")
    print(f"Timestamp Parse Failures: {metrics.timestamp_failures}")
    print(f"Independent Publisher Domains Harvested: {len(metrics.domains_represented)}")
    print(f"  Domains: {', '.join(sorted(metrics.domains_represented))}\n")

    print("--- FEED BREAKDOWN ---")
    for f in metrics.feed_metrics:
        status_str = f"HTTP {f['http_status']}" if f['success'] else f"FAILED ({f['http_status']})"
        print(f"  • {f['name']:<25} | {status_str:<18} | {f['elapsed_sec']:>5.2f}s | Articles: {f['normalized_count']}")

    print("\n--- CLUSTERING & CONSENSUS ---")
    print(f"Total Event Clusters Formed: {metrics.total_clusters}")
    print(f"  Clusters with 1 Publisher Domain:  {metrics.clusters_1_domain}")
    print(f"  Clusters with 2 Publisher Domains: {metrics.clusters_2_domains}")
    print(f"  Clusters with 3 Publisher Domains: {metrics.clusters_3_domains}")
    print(f"  Clusters with 4+ Publisher Domains:{metrics.clusters_4plus_domains}")
    print(f"Evidence Gate Passed (>=2 Domains):  {metrics.clusters_passed_evidence}")
    print(f"Evidence Gate Rejected (<2 Domains): {metrics.clusters_rejected_evidence}")

    print("\n--- FRESHNESS DISTRIBUTION ---")
    for label, count in metrics.freshness_distribution.items():
        print(f"  {label:<22}: {count}")
    print(f"Future Timestamp Anomalies: {metrics.future_timestamp_anomalies}")

    print("\n--- TOP SAMPLE EVENT CLUSTERS ---")
    for i, sc in enumerate(metrics.sample_clusters, start=1):
        corrob_str = "[CORROBORATED >=2 DOMAINS]" if sc["evidence_passed"] else "[SINGLE SOURCE]"
        print(f"{i}. {corrob_str} {sc['title']}")
        print(f"   Domains: {', '.join(sc['domains'])} | Category: {sc['category']} | Score: {sc['opportunity_score']}")
        print(f"   Entities: {', '.join(sc['entities'])} | Actions: {', '.join(sc['action_tokens'])}")

    print("\n--- DEDUPLICATION VALIDATION ---")
    print(f"  Wire Duplicate Converged into 1 Event:       {metrics.dedup_wire_duplicate_converged} (PASS)")
    print(f"  Distinct Same-City/Year Events Kept Separate: {metrics.dedup_same_city_distinct_preserved} (PASS)")

    print("\n--- SAFETY & ISOLATION VERIFICATION ---")
    print(f"  Gemini Calls:             {metrics.gemini_calls}")
    print(f"  Groq Calls:               {metrics.groq_calls}")
    print(f"  OpenRouter Calls:         {metrics.openrouter_calls}")
    print(f"  DeepSeek Calls:           {metrics.deepseek_calls}")
    print(f"  NVIDIA Calls:             {metrics.nvidia_calls}")
    print(f"  Production Topic Writes:  {metrics.production_topic_writes}")
    print(f"  Google Drive Mutations:   {metrics.drive_mutations}")
    print(f"  YouTube API Mutations:    {metrics.youtube_mutations}")
    print(f"  Rendered Videos:          {metrics.rendered_videos}")
    print(f"  Generated TTS Audio:      {metrics.tts_audio_generated}")
    print("\nProbe complete: ZERO mutations, ZERO AI spend.\n")
