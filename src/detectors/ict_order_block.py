"""Backward compatibility re-export. Canonical: src.strategies.ict.detectors.order_block"""
from src.strategies.modules.detectors.order_block import (
    calculate_average_range,
    identify_bullish_ob,
    identify_bearish_ob,
    validate_ob_strength,
    get_ob_zone,
    filter_obs_by_strength,
    find_nearest_ob,
    detect_all_ob,
)
