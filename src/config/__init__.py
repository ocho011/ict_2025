"""Configuration module for ICT trading strategy."""

from src.config.ict_profiles import (
    ICTProfile,
    compare_profiles,
    get_profile_info,
    get_profile_parameters,
    list_all_profiles,
    load_profile_from_name,
)
from src.config.symbol_config import (
    SymbolConfig,
    TradingConfigHierarchical,
    VALID_STRATEGIES,
    VALID_INTERVALS,
    VALID_MARGIN_TYPES,
)

__all__ = [
    # ICT Profiles
    "ICTProfile",
    "get_profile_parameters",
    "get_profile_info",
    "load_profile_from_name",
    "list_all_profiles",
    "compare_profiles",
    # Per-Symbol Configuration (Issue #18)
    "SymbolConfig",
    "TradingConfigHierarchical",
    "VALID_STRATEGIES",
    "VALID_INTERVALS",
    "VALID_MARGIN_TYPES",
]
