"""Backward compatibility re-export. Canonical: src.strategies.ict.detectors.liquidity"""
from src.strategies.modules.detectors.liquidity import (
    find_equal_highs,
    find_equal_lows,
    calculate_premium_discount,
    is_in_premium,
    is_in_discount,
    detect_liquidity_sweep,
    find_liquidity_voids,
    get_liquidity_draw,
)
