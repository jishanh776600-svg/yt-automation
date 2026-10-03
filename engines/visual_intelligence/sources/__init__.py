"""
Visual Intelligence Sources Package.
Exposes all tier adapters with full rights, provenance, and capability guards.
"""
from .base import BaseSourceAdapter, VisualCandidate
from .pexels import PexelsAdapter
from .pixabay import PixabayAdapter
from .movie import MovieAdapter
from .editorial import EditorialAdapter
from .wikimedia import WikimediaAdapter
from .archive import ArchiveAdapter
from .official import OfficialAdapter
from .contextual import ContextualAdapter
ContextualGraphicAdapter = ContextualAdapter
from .reaction import ReactionAdapter
ReactionMemeAdapter = ReactionAdapter

from .nasa_svs import NasaSvsAdapter
from .procedural_3d_adapter import Procedural3DAdapter
from .youtube_adapter import YouTubeAdapter

__all__ = [
    "BaseSourceAdapter",
    "VisualCandidate",
    "NasaSvsAdapter",
    "Procedural3DAdapter",
    "YouTubeAdapter",
    "MovieAdapter",
    "PexelsAdapter",
    "PixabayAdapter",
    "EditorialAdapter",
    "WikimediaAdapter",
    "ArchiveAdapter",
    "OfficialAdapter",
    "ContextualAdapter",
    "ContextualGraphicAdapter",
    "ReactionAdapter",
    "ReactionMemeAdapter",
]
