"""
Visual Intelligence Sources Package.
Exposes all tier adapters with full rights, provenance, and capability guards.
"""
from .base import BaseSourceAdapter, VisualCandidate
from .pexels import PexelsAdapter
from .editorial import EditorialAdapter
from .wikimedia import WikimediaAdapter
from .archive import ArchiveAdapter
from .official import OfficialAdapter
from .contextual import ContextualAdapter
ContextualGraphicAdapter = ContextualAdapter
from .reaction import ReactionAdapter
ReactionMemeAdapter = ReactionAdapter

__all__ = [
    "BaseSourceAdapter",
    "VisualCandidate",
    "PexelsAdapter",
    "EditorialAdapter",
    "WikimediaAdapter",
    "ArchiveAdapter",
    "OfficialAdapter",
    "ContextualAdapter",
    "ContextualGraphicAdapter",
    "ReactionAdapter",
    "ReactionMemeAdapter",
]
