"""
Base Source Adapter Interface and Candidate Contracts.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Set
from ..models import VisualCandidate, VisualIntent, VisualProvenance, RightsStatus, VisualContentType

__all__ = ["BaseSourceAdapter", "VisualCandidate"]


class BaseSourceAdapter(ABC):
    """Abstract contract for all visual source acquisition adapters."""

    def __init__(self, source_name: str, source_class: str):
        self.source_name = source_name
        self.source_class = source_class

    @abstractmethod
    def search(
        self,
        queries: List[str],
        intent: VisualIntent,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[VisualCandidate]:
        """Searches adapter for candidates meeting beat visual intent."""
        pass
