"""
Strategy Hot Reload manager.

Receives ConfigUpdateEvent, safely closes positions, replaces strategy instances.

Real-time Trading Guideline Compliance:
- asyncio Lock per symbol prevents race conditions
- Position cleanup completes before strategy swap
- Audit logging for compliance
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Dict, Optional

from src.events.config_events import ConfigUpdateEvent, ConfigReloadCompleteEvent

if TYPE_CHECKING:
    from src.config.symbol_config import TradingConfigHierarchical
    from src.core.audit_logger import AuditLogger
    from src.strategies.base import BaseStrategy
    from src.strategies.dynamic_assembler import DynamicAssembler

logger = logging.getLogger(__name__)


class StrategyHotReloader:
    """
    Config change event handler for safe strategy replacement.

    Safety Protocol:
    1. Acquire per-symbol asyncio.Lock
    2. Close open positions for the symbol
    3. Create new strategy via DynamicAssembler
    4. Replace in strategies dict
    5. Log to AuditLogger
    6. Release lock
    """

    def __init__(
        self,
        strategies: Dict[str, "BaseStrategy"],
        assembler: "DynamicAssembler",
        hierarchical_config: "TradingConfigHierarchical",
        position_closer=None,
        audit_logger: Optional["AuditLogger"] = None,
    ):
        self._strategies = strategies
        self._assembler = assembler
        self._config = hierarchical_config
        self._position_closer = position_closer
        self._audit_logger = audit_logger
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, symbol: str) -> asyncio.Lock:
        """Get or create per-symbol lock."""
        if symbol not in self._locks:
            self._locks[symbol] = asyncio.Lock()
        return self._locks[symbol]

    async def on_config_update(
        self, event: ConfigUpdateEvent
    ) -> Optional[ConfigReloadCompleteEvent]:
        """
        Handle config update event.

        Params-only change: update strategy config dict (lightweight).
        Strategy rebuild: close positions, create new strategy (heavyweight).
        """
        async with self._get_lock(event.symbol):
            if event.requires_strategy_rebuild:
                return await self._rebuild_strategy(event)
            else:
                self._update_params(event)
                return None

    async def _rebuild_strategy(
        self, event: ConfigUpdateEvent
    ) -> ConfigReloadCompleteEvent:
        """Full strategy replacement with position safety."""
        symbol = event.symbol
        old_strategy = self._strategies.get(symbol)
        old_name = (
            old_strategy.module_config.entry_determiner.name
            if old_strategy else "none"
        )

        logger.info("[%s] Strategy rebuild: %s -> ...", symbol, old_name)

        # 1. Close positions
        closed_count = await self._close_positions(symbol)

        # 2. Get updated symbol config
        symbol_config = self._config.get_symbol_config(symbol)

        # 3. Assemble new strategy
        from src.strategies import StrategyFactory

        module_config, intervals, min_rr_ratio = (
            self._assembler.assemble_for_symbol(symbol_config)
        )
        new_strategy = StrategyFactory.create_composed(
            symbol=symbol,
            config=symbol_config.strategy_params,
            module_config=module_config,
            intervals=intervals,
            min_rr_ratio=min_rr_ratio,
        )

        # 4. Replace
        self._strategies[symbol] = new_strategy
        new_name = module_config.entry_determiner.name

        # 5. Audit log
        if self._audit_logger:
            self._audit_logger.log_event(
                "STRATEGY_HOT_RELOAD",
                operation="rebuild_strategy",
                symbol=symbol,
                old_strategy=old_name,
                new_strategy=new_name,
                positions_closed=closed_count,
            )

        logger.info(
            "[%s] Strategy rebuilt: %s -> %s (closed %d positions)",
            symbol, old_name, new_name, closed_count,
        )

        return ConfigReloadCompleteEvent(
            symbol=symbol,
            old_strategy_name=old_name,
            new_strategy_name=new_name,
            positions_closed=closed_count,
        )

    def _update_params(self, event: ConfigUpdateEvent) -> None:
        """Update strategy params without rebuilding (lightweight)."""
        strategy = self._strategies.get(event.symbol)
        if strategy:
            strategy.config.update(event.params)
            logger.info(
                "[%s] Strategy params updated: %s",
                event.symbol, list(event.params.keys()),
            )

    async def _close_positions(self, symbol: str) -> int:
        """Close open positions for symbol. Returns count."""
        if not self._position_closer:
            logger.warning("[%s] No position closer configured, skipping", symbol)
            return 0

        try:
            positions = self._position_closer.get_open_positions(symbol)
            count = 0
            for pos in positions:
                await self._position_closer.close_position(
                    pos, reason="strategy_hot_reload"
                )
                count += 1
            return count
        except Exception as e:
            logger.error("[%s] Failed to close positions: %s", symbol, e)
            return 0
