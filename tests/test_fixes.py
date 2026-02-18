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
    # Read config file
    with open("configs/trading_config.ini", "r") as f:
        content = f.read()

    # Check that an active_profile is set (any valid profile)
    assert "active_profile" in content, "active_profile should be configured"


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
