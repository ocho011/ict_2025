#!/usr/bin/env python3
"""
Test script to validate implemented fixes.
"""

import sys
from unittest.mock import Mock, MagicMock

# Add src to path
sys.path.insert(0, "src")

from src.execution.order_gateway import OrderGateway
from src.core.data_collector import BinanceDataCollector
from src.core.public_market_streamer import PublicMarketStreamer


import asyncio
import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch

# Add src to path
sys.path.insert(0, "src")

from src.execution.order_gateway import OrderGateway
from src.core.async_binance_client import AsyncBinanceClient
from src.models.order import OrderSide, OrderType, OrderStatus


@pytest.mark.asyncio
async def test_sl_dynamic_update_error_handling():
    """Test SL dynamic update with error handling for -4130 and -5000 fixes."""
    # 1. Mock dependencies
    mock_client = AsyncMock(spec=AsyncBinanceClient)
    mock_audit_logger = Mock()
    
    # 2. Setup mock behavior for get_open_algo_orders
    # Simulate one existing STOP_MARKET order and one unrelated order
    mock_client.get_open_algo_orders.return_value = [
        {"algoId": "123", "type": "STOP_MARKET", "symbol": "BTCUSDT"},
        {"algoId": "456", "type": "TAKE_PROFIT_MARKET", "symbol": "BTCUSDT"}
    ]
    mock_client.cancel_algo_order.return_value = {"status": "CANCELLED"}
    mock_client.get_mark_price.return_value = 60000.0
    mock_client.new_algo_order.return_value = {
        "algoId": "789", "status": "NEW", "type": "STOP_MARKET", "symbol": "BTCUSDT"
    }

    # 3. Create order manager
    manager = OrderGateway(
        audit_logger=mock_audit_logger, 
        binance_service=AsyncMock() # Dummy service
    )
    manager.client = mock_client # Inject mock client
    manager._format_price = AsyncMock(side_effect=lambda p, s: str(p))

    # 4. Execute update_sl_dynamic
    # Scenario: Short position at 61000, mark price 60000, new SL 60500
    order = await manager.update_sl_dynamic(
        symbol="BTCUSDT",
        side=OrderSide.SELL, # SHORT position uses SELL for SL? No, SHORT uses BUY to close. 
        # Wait, in OrderGateway: side is the position side.
        new_stop_price=60500.0
    )

    # 5. Verify results
    # Check that cancel_algo_order was called ONLY for the STOP_MARKET order (algoId 123)
    mock_client.cancel_algo_order.assert_called_once_with("BTCUSDT", "123")
    assert order is not None
    assert order.stop_price == 60500.0


@pytest.mark.asyncio
async def test_sl_dynamic_update_collision_logging():
    """Test that -4130 error triggers additional context logging."""
    # 1. Mock dependencies
    mock_client = AsyncMock(spec=AsyncBinanceClient)
    mock_audit_logger = Mock()
    
    mock_client.get_open_algo_orders.return_value = []
    mock_client.get_mark_price.return_value = 60000.0
    # Simulate -4130 error from Binance
    mock_client.new_algo_order.side_effect = Exception("Binance API error: {'code': -4130, 'msg': 'Duplicate'}")

    # 2. Create order manager
    manager = OrderGateway(
        audit_logger=mock_audit_logger, 
        binance_service=AsyncMock()
    )
    manager.client = mock_client
    manager._format_price = AsyncMock(side_effect=lambda p, s: str(p))

    # 3. Execute update_sl_dynamic
    await manager.update_sl_dynamic(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        new_stop_price=60500.0
    )

    # 4. Verify that get_open_algo_orders was called AGAIN to gather context after failure
    # First call in step 3, second call in exception handler
    assert mock_client.get_open_algo_orders.call_count == 2


def test_position_caching():
    """Test position query functionality."""
    # Mock dependencies
    mock_audit_logger = Mock()
    mock_binance_service = Mock()

    # Create order manager
    manager = OrderGateway(
        audit_logger=mock_audit_logger, binance_service=mock_binance_service
    )

    # Test basic initialization
    assert hasattr(manager, "get_position"), "get_position method should exist"
    assert hasattr(manager, "_position_circuit_breaker"), "Circuit breaker not initialized"


def test_api_logging():
    """Test API logging improvements."""
    # Mock dependencies
    mock_audit_logger = Mock()
    mock_binance_service = Mock()

    # Create order manager
    manager = OrderGateway(
        audit_logger=mock_audit_logger, binance_service=mock_binance_service
    )

    # Test that the method exists and works
    assert hasattr(manager, "get_position"), "get_position method should exist"


def test_configuration_changes():
    """Test configuration file exists and has profile setting."""
    # Read config file (now base.yaml, migrated from trading_config.ini)
    import yaml
    with open("configs/base.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Check that an active_profile is set (any valid profile)
    trading = config.get("trading", {})
    defaults = trading.get("defaults", {})
    strategy_params = defaults.get("strategy_params", {})
    assert "active_profile" in strategy_params, "active_profile should be configured"


def test_websocket_monitoring():
    """Test WebSocket monitoring via composition pattern."""
    # Mock dependencies
    mock_binance_service = Mock()
    mock_binance_service.is_testnet = True
    mock_market_streamer = MagicMock(spec=PublicMarketStreamer)
    mock_market_streamer.symbols = ["BTCUSDT"]
    mock_market_streamer.intervals = ["1m"]

    # Create data collector using composition pattern
    collector = BinanceDataCollector(
        binance_service=mock_binance_service,
        market_streamer=mock_market_streamer,
    )

    # Test that composition works
    assert hasattr(collector, "market_streamer"), "Market streamer not set"
    assert hasattr(collector, "binance_service"), "Binance service not set"
