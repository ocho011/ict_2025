"""Backward compatibility re-export. Canonical: src.strategies.ict.detectors.killzones"""
from src.strategies.modules.detectors.killzones import (
    is_london_killzone,
    is_newyork_killzone,
    get_active_killzone,
    is_killzone_active,
    get_next_killzone,
    LONDON_KILLZONE_START,
    LONDON_KILLZONE_END,
    NY_AM_KILLZONE_START,
    NY_AM_KILLZONE_END,
    NY_PM_KILLZONE_START,
    NY_PM_KILLZONE_END,
)
