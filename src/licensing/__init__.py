"""ライセンス（アクティベート）"""

from src.licensing.codec import LicenseError, LicenseInfo, normalize_name
from src.licensing.manager import LicenseManager, LicenseState

__all__ = ["LicenseError", "LicenseInfo", "LicenseManager", "LicenseState", "normalize_name"]
