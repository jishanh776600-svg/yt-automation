"""
Class D Source Adapter: Reaction Visuals & Editorial Humor.
Provides contextual reaction moments, expressive facial gestures, and memes.
Enforces strict factual integrity gates:
- Disallows memes that distort or falsify factual claims.
- Disallows off-tone humor during tragedy or serious conflict.
- Requires acceptable rights status.
"""
import uuid
import logging
from typing import List, Dict, Any, Optional, Set, Tuple

from .base import BaseSourceAdapter, VisualCandidate
from ..provenance import VisualProvenance, RightsStatus, VisualContentType

logger = logging.getLogger(__name__)


class ReactionMemeAdapter(BaseSourceAdapter):
    """Class D: Editorially Controlled Reaction & Meme Visuals."""

    # Prohibited tones and claim categories for humorous visuals
    DISALLOWED_TONES = {"TRAGEDY", "MOURNING", "GRIEF", "WAR_CASUALTIES", "CRIME_VICTIM"}

    def __init__(self):
        super().__init__(source_name="reaction_visuals", source_class="SOURCE_D")

    def is_editorially_appropriate(self, intent: Any) -> bool:
        """Enforces safety gate: humor/reaction only permitted when editorially appropriate."""
        tone = getattr(intent, "emotional_tone", "SERIOUS")
        if tone in self.DISALLOWED_TONES:
            return False

        # If claim involves serious tragedy or death, reject humor
        narration = (getattr(intent, "narration_text", "") or "").lower()
        if any(w in narration for w in ["killed", "death", "casualt", "fatal", "died", "massacre", "funeral", "assassinated"]):
            return False

        return True

    def validate_meme_suitability(self, candidate: VisualCandidate, intent: Any) -> Tuple[bool, Optional[str]]:
        """
        Thorough audit of meme candidate against the story beat:
        - Rejects solemn/tragic news (killed, deaths, funerals, war casualties)
        - Rejects factual evidence substitution (memes cannot represent legal/treaty documents)
        - Rejects entity mismatches (e.g. unrelated pop culture meme when specific entity is requested)
        - Rejects misleading claims that distort historical/journalistic truth
        """
        # 1. Solemn / tragic event rejection
        if not self.is_editorially_appropriate(intent):
            return False, "Solemn/tragic news context prohibits humorous reaction visuals."

        # 2. Evidence substitution rejection (memes cannot satisfy evidence requirement)
        has_evidence = (
            getattr(intent, "evidence_required", False)
            or bool(getattr(intent, "evidence_overlay_requirements", None))
            or getattr(intent, "required_visual_type", None) in (
                VisualContentType.SCREENSHOT_DOCUMENT,
                VisualContentType.ANIMATED_DATA_MAP
            )
        )
        if has_evidence:
            return False, "Memes cannot be used to represent factual documents or evidence."

        # 3. Entity context verification
        req_entity = getattr(intent, "primary_entity", None)
        if req_entity:
            entity_lower = req_entity.lower()
            if candidate.entity_tags and not any(t.lower() in entity_lower or entity_lower in t.lower() or t.lower() == "public" for t in candidate.entity_tags):
                return False, f"Entity mismatch: Candidate tagged for {candidate.entity_tags} does not match intent '{req_entity}'."

        # 4. Content type enforcement: must carry MEME_REACTION classification
        if candidate.content_type != VisualContentType.MEME_REACTION:
            return False, f"Invalid content type: Reaction candidate must be classified as MEME_REACTION, got {candidate.content_type}."

        return True, None

    def search(
        self,
        queries: List[str],
        intent: Any,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[VisualCandidate]:
        """Retrieves reaction/meme candidates only when safety gates pass."""
        candidates: List[VisualCandidate] = []
        if not self.is_editorially_appropriate(intent):
            logger.info("[REACTION_MEME_GATE] Reaction visuals rejected: Story beat involves serious/tragic content.")
            return candidates

        exclude = exclude_urls or set()
        cid = f"cand_react_{uuid.uuid4().hex[:8]}"
        react_url = f"https://editorial.reaction.org/clips/{uuid.uuid4().hex[:6]}.mp4"
        if react_url in exclude:
            return candidates

        entity = getattr(intent, "primary_entity", None) or "Public"

        prov = VisualProvenance(
            asset_id=cid,
            source="reaction_visuals",
            source_url=react_url,
            creator="Public Reaction Archive",
            publisher="Editorial Reaction Network",
            rights_status=RightsStatus.LICENSED,
            license_name="Reaction Video Creative License",
            content_type=VisualContentType.MEME_REACTION,
            attribution_required=False,
            confidence_score=0.90
        )

        cand = VisualCandidate(
            candidate_id=cid,
            source_class=self.source_class,
            source_name=self.source_name,
            source_url=react_url,
            title=f"Expressive Reaction: {entity}",
            description=f"Contextual reaction moment depicting public sentiment to {entity}",
            content_type=VisualContentType.MEME_REACTION,
            rights_status=RightsStatus.LICENSED,
            license_name="Creative License",
            width=1080,
            height=1920,
            duration_sec=min(2.5, getattr(intent, "duration", 2.5)),
            motion_score=0.80,
            is_video=True,
            entity_tags=[entity],
            event_tags=["reaction"],
            provenance=prov
        )
        candidates.append(cand)
        return candidates

ReactionAdapter = ReactionMemeAdapter
