"""Backward compatibility re-export. Canonical: src.strategies.ict.detectors.fvg"""
from src.strategies.modules.detectors.fvg import (
    detect_bullish_fvg,
    detect_bearish_fvg,
    is_fvg_filled,
    get_fvg_levels,
    update_fvg_status,
    find_nearest_fvg,
    get_entry_zone,
    detect_all_fvg,
)
