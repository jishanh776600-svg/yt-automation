"""
License Tracker and Commercial Rights Verification Engine.
Strictly verifies that every asset used in a video has verified commercial use rights ($0 cost).
"""
import logging
from typing import List, Tuple
from core.models import AssetRecord
from config.constants import LicenseType

logger = logging.getLogger(__name__)


class LicenseTracker:
    """Tracks and validates license metadata for all project assets."""

    APPROVED_COMMERCIAL_LICENSES = {
        LicenseType.PEXELS_LICENSE.value,
        LicenseType.PUBLIC_DOMAIN_CC0.value,
        LicenseType.YOUTUBE_AUDIO_LIBRARY.value,
        LicenseType.APACHE_2_0.value,
        LicenseType.MIT.value,
        LicenseType.AI_GENERATED_OPEN.value,
    }

    @classmethod
    def verify_asset(cls, asset: AssetRecord) -> Tuple[bool, str]:
        """
        Verifies if an asset is safe and legally permitted for commercial YouTube monetization at $0 cost.
        Returns: (is_valid, reason)
        """
        if not asset:
            return False, "Asset record is None"

        if not asset.commercial_use:
            return False, f"Asset {asset.id} explicitly marked commercial_use=False"

        if asset.license == LicenseType.UNKNOWN.value:
            return False, f"Asset {asset.id} has UNKNOWN license status. Verification failed."

        if asset.license not in cls.APPROVED_COMMERCIAL_LICENSES:
            return False, f"Asset {asset.id} has unapproved license: {asset.license}"

        return True, "Verified for commercial use"

    @classmethod
    def verify_job_assets(cls, assets: List[AssetRecord]) -> Tuple[bool, List[str]]:
        """
        Verifies all assets used in a video render.
        Returns (all_valid, list_of_failure_reasons).
        """
        failures = []
        if not assets:
            return False, ["No assets associated with job"]

        for asset in assets:
            valid, reason = cls.verify_asset(asset)
            if not valid:
                failures.append(reason)

        return len(failures) == 0, failures
