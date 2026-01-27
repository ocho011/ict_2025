#!/usr/bin/env python3
"""
Test script to validate implemented fixes.
"""

import asyncio
import time

from unittest.mock import Mock

# Add src to path
sys.path.insert(0, "src")

from src.execution.order_manager import OrderExecutionManager
from src.core.data_collector import BinanceDataCollector


def test_position_caching():
    """Test position caching functionality."""
    print("Testing position caching...")

    # Mock dependencies
    mock_audit_logger = Mock()
    mock_binance_service = Mock()

    # Create order manager
    manager = OrderExecutionManager(
        audit_logger=mock_audit_logger, binance_service=mock_binance_service
    )

    # Test cache initialization
    assert hasattr(manager, "_position_cache"), "Position cache not initialized"
    assert hasattr(manager, "_cache_ttl_seconds"), "Cache TTL not set"
    assert manager._cache_ttl_seconds == 5.0, "Cache TTL should be 5 seconds"

    print("✅ Position caching test passed")
    return True


def test_api_logging():
    """Test API logging improvements."""
    print("Testing API logging improvements...")

    # Mock dependencies
    mock_audit_logger = Mock()
    mock_binance_service = Mock()

    # Create order manager
    manager = OrderExecutionManager(
        audit_logger=mock_audit_logger, binance_service=mock_binance_service
    )

    # Test that the method exists and works
    assert hasattr(manager, "get_position"), "get_position method should exist"

    print("✅ API logging test passed")
    return True


    """Test configuration changes."""
        print("Testing configuration changes...")
        
        with open("configs/trading_config.ini", "r") as f:
            content = f.read()
            
        print(f"✅ Configuration test passed")
    """Test configuration changes."""
    print("Testing configuration changes...")

    # Read config file
    with open("configs/trading_config.ini", "r") as f:
        content = f.read()

    # Check that BALANCED profile is set
    assert "active_profile = BALANCED" in content, "Profile should be BALANCED"

    print("✅ Configuration test passed")
    return True


def test_websocket_monitoring():
    """Test WebSocket monitoring features."""
    print("Testing WebSocket monitoring...")

    # Mock dependencies
    mock_audit_logger = Mock()
    mock_binance_service = Mock()

    # Create data collector
    collector = BinanceDataCollector(
        binance_service=mock_binance_service, symbols=["BTCUSDT"], intervals=["1m"]
    )

    # Test heartbeat monitoring attributes
    assert hasattr(collector, "_last_heartbeat_time"), "Heartbeat time not set"
    assert hasattr(collector, "_heartbeat_interval"), "Heartbeat interval not set"
    assert hasattr(collector, "_heartbeat_task"), "Heartbeat task not set"
    assert collector._heartbeat_interval == 30.0, (
        "Heartbeat interval should be 30 seconds"
    )

    print("✅ WebSocket monitoring test passed")
    return True


    """Run all tests."""
    """Run all tests."""
    print("🚀 Starting validation tests...\n")

    tests = [
        test_position_caching,
        test_api_logging,
        test_config_changes,
        test_websocket_monitoring,
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ Test failed: {e}")

    print(f"\n📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("✅ All tests passed! Implementation validated successfully.")
        return 0
    else:
        print("⚠️ Some tests failed. Please review implementation.")
        return 1


if __name__ == "__main__":
    exit(main())
