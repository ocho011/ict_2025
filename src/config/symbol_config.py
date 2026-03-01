"""
Per-Symbol Strategy Configuration (Issue #18).

This module provides hierarchical configuration support for per-symbol
trading strategies, enabling different strategies and parameters per symbol.

Key Features:
- SymbolConfig: Per-symbol configuration with validation
- TradingConfigHierarchical: Hierarchical config with inheritance
- Support for any registered strategy type
- YAML format support (base.yaml)

Example YAML Configuration:
```yaml
trading:
  defaults:
    leverage: 1
    max_risk_per_trade: 0.01
    margin_type: ISOLATED

  symbols:
    BTCUSDT:
      strategy: ict_strategy
      leverage: 2
      strategy_params:
        active_profile: strict

    ETHUSDT:
      strategy: mock_sma
      leverage: 3
```
"""

from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional

from src.core.exceptions import ConfigurationError


def _get_valid_strategies() -> set:
    """Get valid strategies from registry (lazy import to avoid circular deps).

    This uses a deferred import inside the function body to prevent circular
    import issues at module initialization time. The import chain:
      src/config -> src/strategies/module_config_builder -> src/entry -> src/config
    would deadlock if triggered at module level.
    """
    from src.strategies.module_config_builder import get_registered_strategies  # noqa: PLC0415
    return get_registered_strategies()


# Module-level constant for backward compatibility (e.g., from src.config import VALID_STRATEGIES).
# This is intentionally left as an empty set at import time; the actual set of registered
# strategies is resolved lazily via _get_valid_strategies() at validation time.
# Consumers that need the live set should call _get_valid_strategies() directly.
VALID_STRATEGIES: set = set()

# Valid margin types
VALID_MARGIN_TYPES = {"ISOLATED", "CROSSED"}

# Binance interval formats
VALID_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w",
}


@dataclass
class SymbolConfig:
    """
    Per-symbol configuration with validation.

    Holds all configuration needed to instantiate and run a strategy
    for a specific trading symbol.

    Attributes:
        symbol: Trading pair (e.g., 'BTCUSDT')
        strategy: Strategy class name (e.g., 'ict_strategy')
        enabled: Whether this symbol is active for trading
        leverage: Position leverage (1-125)
        max_risk_per_trade: Maximum risk per trade (0.001-0.1)
        margin_type: 'ISOLATED' or 'CROSSED'
        backfill_limit: Number of historical candles to load
        intervals: List of intervals for MTF strategies
        strategy_params: Strategy-specific configuration parameters
    """

    symbol: str
    strategy: str
    enabled: bool = True
    leverage: int = 1
    max_risk_per_trade: float = 0.01
    margin_type: str = "ISOLATED"
    backfill_limit: int = 200
    intervals: List[str] = field(default_factory=lambda: ["5m", "1h", "4h"])

    # Strategy-specific configuration parameters (generic, replaces ict_config/momentum_config)
    strategy_params: Dict[str, Any] = field(default_factory=dict)

    # Module-level assembly spec for dynamic strategy composition (Phase 2)
    # Structure: {"entry": {"type": "ict_entry", "params": {...}}, "stop_loss": {...}, ...}
    modules: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        """Validate configuration on creation."""
        self._validate()

    def _validate(self) -> None:
        """Comprehensive validation of all fields."""
        # Symbol validation
        if not self.symbol or not isinstance(self.symbol, str):
            raise ConfigurationError(f"Invalid symbol: {self.symbol}")
        if not self.symbol.endswith("USDT"):
            raise ConfigurationError(
                f"Symbol must end with 'USDT': {self.symbol}"
            )

        # Strategy validation (dynamic from registry)
        valid = _get_valid_strategies()
        if self.strategy not in valid:
            raise ConfigurationError(
                f"Invalid strategy: {self.strategy}. "
                f"Must be one of {sorted(valid)}"
            )

        # Leverage validation (Binance limits)
        if self.leverage < 1 or self.leverage > 125:
            raise ConfigurationError(
                f"Leverage must be 1-125, got {self.leverage}"
            )

        # Risk validation
        if self.max_risk_per_trade <= 0 or self.max_risk_per_trade > 0.1:
            raise ConfigurationError(
                f"Max risk per trade must be 0-10%, got {self.max_risk_per_trade}"
            )

        # Margin type validation
        if self.margin_type not in VALID_MARGIN_TYPES:
            raise ConfigurationError(
                f"Margin type must be 'ISOLATED' or 'CROSSED', got {self.margin_type}"
            )

        # Backfill limit validation
        if self.backfill_limit < 0 or self.backfill_limit > 1000:
            raise ConfigurationError(
                f"Backfill limit must be 0-1000, got {self.backfill_limit}"
            )

        # Intervals validation
        for interval in self.intervals:
            if interval not in VALID_INTERVALS:
                raise ConfigurationError(
                    f"Invalid interval: {interval}. "
                    f"Must be one of {sorted(VALID_INTERVALS)}"
                )

        # Strategy-specific config: apply ICT defaults if no params provided
        if self.strategy == "ict_strategy" and not self.strategy_params:
            self.strategy_params = {
                "active_profile": "strict",
                "ltf_interval": "5m",
                "mtf_interval": "1h",
                "htf_interval": "4h",
                "use_killzones": True,
            }

    def get_strategy_config(self) -> Dict[str, Any]:
        """
        Get the strategy-specific configuration dict.

        Returns:
            Dictionary with strategy-specific parameters
        """
        return self.strategy_params

    def to_trading_config_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary compatible with TradingConfig.

        Returns:
            Dictionary that can be used to construct TradingConfig
        """
        config_dict = {
            "symbols": [self.symbol],
            "intervals": self.intervals,
            "strategy": self.strategy,
            "leverage": self.leverage,
            "max_risk_per_trade": self.max_risk_per_trade,
            "margin_type": self.margin_type,
            "backfill_limit": self.backfill_limit,
        }

        # Add strategy-specific config (generic key)
        strategy_config = self.get_strategy_config()
        if strategy_config:
            config_dict["strategy_config"] = strategy_config

        if self.modules:
            config_dict["modules"] = self.modules

        return config_dict


@dataclass
class TradingConfigHierarchical:
    """
    Hierarchical trading configuration with per-symbol overrides.

    Supports loading from YAML with inheritance:
    - Global defaults apply to all symbols
    - Symbol-specific settings override defaults

    Attributes:
        defaults: Global default settings
        symbols: Dict of symbol -> SymbolConfig
    """

    defaults: Dict[str, Any] = field(default_factory=dict)
    symbols: Dict[str, SymbolConfig] = field(default_factory=dict)

    def get_symbol_config(self, symbol: str) -> SymbolConfig:
        """
        Get configuration for specific symbol with default fallback.

        Resolution Order:
        1. Symbol-specific config (if exists)
        2. Create from defaults with symbol name

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')

        Returns:
            SymbolConfig for the requested symbol

        Raises:
            ConfigurationError: If symbol not configured
        """
        if symbol in self.symbols:
            return self.symbols[symbol]

        # Create from defaults if symbol is in defaults
        if self.defaults:
            merged = self.defaults.copy()
            merged["symbol"] = symbol
            if "strategy" not in merged:
                merged["strategy"] = "ict_strategy"  # Default strategy
            return SymbolConfig(**merged)

        raise ConfigurationError(
            f"Symbol '{symbol}' not configured and no defaults available"
        )

    def get_enabled_symbols(self) -> List[str]:
        """
        Get list of enabled trading symbols.

        Returns:
            List of symbol names that are enabled
        """
        return [
            symbol for symbol, config in self.symbols.items()
            if config.enabled
        ]

    def get_symbols_by_strategy(self, strategy: str) -> List[str]:
        """
        Get symbols using a specific strategy.

        Args:
            strategy: Strategy name to filter by

        Returns:
            List of symbol names using the strategy
        """
        return [
            symbol for symbol, config in self.symbols.items()
            if config.strategy == strategy and config.enabled
        ]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradingConfigHierarchical":
        """
        Create from dictionary (YAML parsed data).

        Args:
            data: Dictionary with 'defaults' and 'symbols' keys

        Returns:
            TradingConfigHierarchical instance
        """
        defaults = data.get("defaults", {})
        symbols_data = data.get("symbols", {})

        # Filter defaults to only valid SymbolConfig fields
        valid_fields = {f.name for f in fields(SymbolConfig)}

        symbols = {}
        for symbol, symbol_config in symbols_data.items():
            # Merge with defaults, filtering out non-SymbolConfig keys
            merged_config = {k: v for k, v in defaults.items() if k in valid_fields}
            merged_config.update({k: v for k, v in symbol_config.items() if k in valid_fields})
            merged_config["symbol"] = symbol

            # Ensure strategy is set
            if "strategy" not in merged_config:
                merged_config["strategy"] = "ict_strategy"

            # Backward compatibility: convert old ict_config/momentum_config to strategy_params
            if "ict_config" in merged_config and "strategy_params" not in merged_config:
                merged_config["strategy_params"] = merged_config.pop("ict_config")
            elif "momentum_config" in merged_config and "strategy_params" not in merged_config:
                merged_config["strategy_params"] = merged_config.pop("momentum_config")
            merged_config.pop("ict_config", None)
            merged_config.pop("momentum_config", None)

            # Preserve modules block for dynamic assembly
            # modules is passed through as-is (Dict[str, Dict])

            symbols[symbol] = SymbolConfig(**merged_config)

        return cls(defaults=defaults, symbols=symbols)

    def to_legacy_trading_config_list(self) -> List[Dict[str, Any]]:
        """
        Convert to list of dictionaries compatible with legacy TradingConfig.

        Useful for backward compatibility during migration.

        Returns:
            List of config dicts, one per symbol
        """
        return [
            config.to_trading_config_dict()
            for config in self.symbols.values()
            if config.enabled
        ]
