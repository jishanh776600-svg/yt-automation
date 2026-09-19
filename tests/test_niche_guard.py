"""
Targeted Verification Suite for Topic Discovery Niche Guard (Forgotten Files).
Validates that:
- Core channel niche stories (history, mysteries, vanishings, folklore, ancient enigmas, archaeology) are ACCEPTED.
- Modern academic science, oncology, genetics, aging, forestry, environmental studies, and press releases are REJECTED.
- Historical exceptions (ancient science/medical texts with genuine historical framing) are preserved.
- All 7 failure candidates from September 15-17 incident are strictly rejected.
- Curated historical seeds pass 100%.
- Gate 15 deduplication remains fully functional.
"""
import pytest
from core.database import get_db
from engines.topic_discovery import CURATED_HISTORICAL_SEEDS, TopicDiscoveryEngine
from intelligence.clustering import is_niche_compliant
from intelligence.niche_guard import NicheDecision, NicheGuard, NicheRejectionReason


# ==============================================================================
# 1. CORE CHANNEL NICHE ACCEPTANCE TESTS (Cases A - E)
# ==============================================================================

def test_case_a_historical_mystery_accepted():
    """Case A: Historical mystery candidate -> ACCEPT"""
    titles = [
        "The Mystery of the Mary Celeste: Abandoned in Calm Seas",
        "The Voynich Manuscript: An Unbreakable 600-Year-Old Cipher",
        "The Dancing Plague of 1518: The Mystery That Gripped Strasbourg",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is True, f"Expected {title} to be allowed, got: {decision.reason}"
        assert decision.niche_fit_score >= 70.0


def test_case_b_historical_disappearance_accepted():
    """Case B: Historical disappearance -> ACCEPT"""
    titles = [
        "The Disappearance of the Roanoke Colony: Vanished Without a Trace",
        "Flight 19: The Five Navy Bombers That Disappeared in the Bermuda Triangle",
        "Percy Fawcett and the Lost City of Z Disappearance",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is True, f"Expected {title} to be allowed, got: {decision.reason}"
        assert decision.niche_fit_score >= 70.0


def test_case_c_historical_folklore_accepted():
    """Case C: Historical folklore -> ACCEPT"""
    titles = [
        "The Legend of the Bell Witch of Adams, Tennessee",
        "The Spring-heeled Jack Mystery of Victorian London",
        "The Beast of Gévaudan: The 18th-Century Terror of France",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is True, f"Expected {title} to be allowed, got: {decision.reason}"
        assert decision.niche_fit_score >= 70.0


def test_case_d_archaeological_mystery_accepted():
    """Case D: Archaeological mystery -> ACCEPT"""
    titles = [
        "The Unexplained Acoustic Engineering of Göbekli Tepe",
        "The 2,000-Year-Old Antikythera Mechanism: Ancient World's First Computer",
        "The Hidden Chambers of the Great Pyramid of Giza",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is True, f"Expected {title} to be allowed, got: {decision.reason}"
        assert decision.niche_fit_score >= 70.0


def test_case_e_ancient_scientific_mystery_accepted():
    """Case E: Ancient scientific mystery -> ACCEPT"""
    titles = [
        "The mysterious 2,000-year-old treatment found in an ancient Roman medical text",
        "The Nanotechnology of the Roman Lycurgus Cup",
        "Ancient Roman concrete self-healing mystery solved after 2,000 years",
        "The medieval legend that claimed bats could extend human life",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is True, f"Expected {title} to be allowed as historical exception, got: {decision.reason}"
        assert decision.niche_fit_score >= 70.0


# ==============================================================================
# 2. MODERN ACADEMIC / SCIENCE REJECTION TESTS (Cases F - L)
# ==============================================================================

def test_case_f_modern_oncology_paper_rejected():
    """Case F: Modern oncology paper -> REJECT"""
    titles = [
        "New chemotherapy target identified in aggressive pancreatic cancer",
        "Study reveals how tumor microenvironments resist immunotherapy",
        "Targeted oncology trial shows survival gains in breast cancer patients",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is False, f"Expected {title} to be rejected"
        assert decision.rejection_code == NicheRejectionReason.MODERN_MEDICAL_RESEARCH.value


def test_case_g_modern_cancer_research_rejected():
    """Case G: Modern cancer research -> REJECT"""
    titles = [
        "Cancer is rising in younger adults and it's a terrifying puzzle",
        "Blood test detects 50 types of cancer before symptoms appear",
        "Researchers at Johns Hopkins discover new mechanism of metastasis",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is False, f"Expected {title} to be rejected"
        assert decision.rejection_code in (
            NicheRejectionReason.MODERN_MEDICAL_RESEARCH.value,
            NicheRejectionReason.PRESS_RELEASE_SCIENCE.value
        )


def test_case_h_modern_genetics_research_rejected():
    """Case H: Modern genetics research -> REJECT"""
    titles = [
        "Bat DNA reveals secret to long life without aging",
        "CRISPR gene editing corrects muscular dystrophy mutation in mice",
        "Scientists sequence genome of endangered mammal to understand cellular aging",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is False, f"Expected {title} to be rejected"
        assert decision.rejection_code == NicheRejectionReason.MODERN_GENETICS_RESEARCH.value


def test_case_i_modern_forestry_paper_rejected():
    """Case I: Modern forestry paper -> REJECT"""
    titles = [
        "Clearcutting boreal forests threatens bird populations",
        "Forest fragmentation accelerates biodiversity loss in tropical timber reserves",
        "New study documents soil degradation from industrial logging practices",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is False, f"Expected {title} to be rejected"
        assert decision.rejection_code in (
            NicheRejectionReason.MODERN_ENVIRONMENTAL_RESEARCH.value,
            NicheRejectionReason.PRESS_RELEASE_SCIENCE.value
        )


def test_case_j_modern_environmental_study_rejected():
    """Case J: Modern environmental study -> REJECT"""
    titles = [
        "NASA is turning plastic waste into edible cookies",
        "Microplastics found in deep ocean trenches and polar ice sheets",
        "Climate change study projects accelerating sea level rise by 2050",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is False, f"Expected {title} to be rejected"
        assert decision.rejection_code in (
            NicheRejectionReason.MODERN_ENVIRONMENTAL_RESEARCH.value,
            NicheRejectionReason.PRESS_RELEASE_SCIENCE.value
        )


def test_case_k_generic_academic_science_press_release_rejected():
    """Case K: Generic academic science press release -> REJECT"""
    titles = [
        "Researchers at MIT develop new room-temperature semiconductor",
        "Study led by Stanford scientists finds sleep deprivation impacts memory consolidation",
        "In a new paper published in Nature, physicists synthesize novel 2D material",
    ]
    for title in titles:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is False, f"Expected {title} to be rejected"
        assert decision.rejection_code in (
            NicheRejectionReason.PRESS_RELEASE_SCIENCE.value,
            NicheRejectionReason.MODERN_ACADEMIC_SCIENCE.value
        )


def test_case_l_modern_astronomy_rejected_unless_historical():
    """Case L: Modern astronomy research -> REJECT unless the story has strong historical/mystery framing"""
    # Modern astrophysics press release -> REJECT
    modern_astro = "Supermassive black hole winds can shut down star formation"
    dec_modern = NicheGuard.evaluate(modern_astro)
    assert dec_modern.is_allowed is False
    assert dec_modern.rejection_code == NicheRejectionReason.MODERN_ACADEMIC_SCIENCE.value

    # Historical astronomy mystery -> ACCEPT
    hist_astro = "The 1054 Supernova: How Ancient Chinese Astronomers Recorded the Birth of the Crab Nebula"
    dec_hist = NicheGuard.evaluate(hist_astro)
    assert dec_hist.is_allowed is True
    assert dec_hist.niche_fit_score >= 70.0


# ==============================================================================
# 3. REPRODUCTION OF SEPTEMBER 15-17 FAILURE CANDIDATES
# ==============================================================================

def test_september_failure_candidates_strictly_rejected():
    """
    Reproduces the exact 7 failure candidates that slipped through the pipeline
    and triggered the September 15-19 distribution collapse.
    Verifies that all 7 are now authoritatively rejected with exact rejection codes.
    """
    failure_cases = [
        (
            "NASA is turning plastic waste into edible cookies",
            NicheRejectionReason.MODERN_ENVIRONMENTAL_RESEARCH.value
        ),
        (
            "Cancer is rising in younger adults and it's a terrifying puzzle",
            NicheRejectionReason.MODERN_MEDICAL_RESEARCH.value
        ),
        (
            "Bat DNA reveals secret to long life without aging",
            NicheRejectionReason.MODERN_GENETICS_RESEARCH.value
        ),
        (
            "Clearcutting boreal forests threatens bird populations",
            NicheRejectionReason.MODERN_ENVIRONMENTAL_RESEARCH.value
        ),
        (
            "Supermassive black hole winds can shut down star formation",
            NicheRejectionReason.MODERN_ACADEMIC_SCIENCE.value
        ),
        (
            "UV light reveals possible camouflage on a 125-million-year-old crocodile",
            NicheRejectionReason.MODERN_ACADEMIC_SCIENCE.value
        ),
        (
            "Hidden immune organ in the skull may help fight brain cancer",
            NicheRejectionReason.MODERN_MEDICAL_RESEARCH.value
        ),
    ]

    for title, expected_code in failure_cases:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is False, f"Candidate '{title}' must be rejected!"
        assert decision.rejection_code == expected_code, (
            f"Candidate '{title}' expected rejection code {expected_code}, got {decision.rejection_code}"
        )
        assert decision.niche_fit_score == 0.0


# ==============================================================================
# 4. CURATED FALLBACK SEED CORPUS (Case M)
# ==============================================================================

def test_case_m_curated_fallback_seeds_accepted():
    """
    Case M: Fallback curated seeds -> ACCEPT
    Verifies that 100% of the CURATED_HISTORICAL_SEEDS pass the NicheGuard.
    """
    assert len(CURATED_HISTORICAL_SEEDS) >= 75, "Curated seed corpus must contain at least 75 seeds"
    for item in CURATED_HISTORICAL_SEEDS:
        decision = NicheGuard.evaluate(item["title"], item.get("summary", ""))
        assert decision.is_allowed is True, (
            f"Curated seed '{item['title']}' was rejected! Reason: {decision.reason}"
        )
        assert decision.niche_fit_score >= 50.0


# ==============================================================================
# 5. GEMINI AI DISCOVERY CANDIDATE VALIDATION (Case N)
# ==============================================================================

def test_case_n_gemini_discovery_candidate_niche_guard_rejection():
    """
    Case N: Gemini-discovered candidate with niche mismatch -> REJECT
    Verifies that off-niche suggestions generated by an AI model are caught and rejected.
    """
    ai_drift_candidates = [
        "New study reveals how microplastics cross the blood-brain barrier",
        "Astronomers find evidence of water vapor on super-Earth exoplanet",
        "Oncologists uncover how dormant cancer cells awaken after chemotherapy",
        "Quantum computer solves complex optimization problem in 3 minutes",
    ]
    for title in ai_drift_candidates:
        decision = NicheGuard.evaluate(title)
        assert decision.is_allowed is False, f"AI drift candidate '{title}' should have been rejected!"
        assert decision.rejection_code is not None


# ==============================================================================
# 6. GATE 15 DEDUPLICATION INTEGRITY (Case O)
# ==============================================================================

def test_case_o_gate_15_dedup_still_works():
    """
    Case O: Existing Gate 15 dedup still works
    Verifies that duplicate detection functions properly and is not disrupted by the niche guard.
    """
    engine = TopicDiscoveryEngine()
    db = next(get_db())

    # A topic already produced / published in database
    is_dup = engine.is_duplicate(db, "The London Beer Flood of 1814")
    assert is_dup is True, "Gate 15 must flag existing produced/published topic as duplicate"

    # A completely unique historical mystery
    unique_title = "The Lost Silver Bells of Valparaiso (1822)"
    is_not_dup = engine.is_duplicate(db, unique_title, "In 1822, five cathedral bells cast in silver disappeared during transit from Valparaiso.")
    assert is_not_dup is False, "Gate 15 must permit unique unseen topic"


# ==============================================================================
# 7. INTEGRATION WITH CLUSTERING GATE & SCORING
# ==============================================================================

def test_clustering_is_niche_compliant_delegation():
    """Verifies that intelligence/clustering.py is_niche_compliant delegates correctly."""
    ok, reason = is_niche_compliant("Cancer is rising in younger adults and it's a terrifying puzzle")
    assert ok is False
    assert "MODERN_MEDICAL_RESEARCH" in reason

    ok2, reason2 = is_niche_compliant("The Mystery of the Mary Celeste")
    assert ok2 is True
    assert "APPROVED_HISTORICAL_MYSTERY" in reason2


def test_calculate_topic_score_niche_gating():
    """Verifies that calculate_topic_score assigns 0.0 to non-compliant candidates."""
    engine = TopicDiscoveryEngine()

    bad_item = {
        "title": "Bat DNA reveals secret to long life without aging",
        "summary": "Scientists sequence bat DNA to discover longevity secrets.",
        "curiosity": 9.9,
        "visual_potential": 9.5,
        "historical_interest": 8.0,
        "storytelling": 9.0,
        "uniqueness": 9.5
    }
    score_bad = engine.calculate_topic_score(bad_item)
    assert score_bad == 0.0, f"Expected 0.0 score for out-of-niche topic, got: {score_bad}"

    good_item = {
        "title": "The Voynich Manuscript: An Unbreakable 600-Year-Old Cipher",
        "summary": "A 15th-century illustrated codex handwritten in an unknown script.",
        "curiosity": 9.8,
        "visual_potential": 9.0,
        "historical_interest": 9.5,
        "storytelling": 9.2,
        "uniqueness": 9.8
    }
    score_good = engine.calculate_topic_score(good_item)
    assert score_good >= 50.0, f"Expected score >= 50.0 for valid historical topic, got: {score_good}"
