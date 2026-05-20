"""Browser package — undetected_chromedriver wrappers and stealth patches.

The minimal driver lives in :mod:`.driver` and is used by enrichment (M4).
The full per-worker pool with profile cloning lives in :mod:`.pool` (M7).
"""

from __future__ import annotations

from .stealth import STEALTH_JS, apply_stealth

__all__ = ["STEALTH_JS", "apply_stealth"]
