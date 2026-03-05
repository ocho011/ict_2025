import sys
import asyncio
import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch

# Add src to path
sys.path.insert(0, "src")

from src.execution.order_gateway import OrderGateway
from src.core.async_binance_client import AsyncBinanceClient
from src.models.order import OrderSide, OrderType, OrderStatus
from src.models.signal import Signal

@pytest.mark.asyncio
async def test_tc01_ghost_cancel_resilience():
    """TC-01: Resilience against -2011 (Unknown Order) during cancellation."""
    mock_client = AsyncMock(spec=AsyncBinanceClient)
    mock_audit = Mock()
    
    # Setup: One existing order that will return -2011 on cancel
    mock_client.get_open_algo_orders.return_value = [
        {"algoId": "ghost_123", "type": "STOP_MARKET", "stopPrice": "60000.0"}
    ]
    mock_client.cancel_algo_order.side_effect = Exception("Binance API error: {'code': -2011, 'msg': 'Unknown order'}")
    mock_client.get_mark_price.return_value = 50000.0
    mock_client.new_algo_order.return_value = {"algoId": "new_456", "status": "NEW", "updateTime": 123456789, "time": 123456789, "stopPrice": "55000.0"}

    gateway = OrderGateway(audit_logger=mock_audit, binance_service=AsyncMock())
    gateway.client = mock_client
    gateway._format_price = AsyncMock(side_effect=lambda p, s: str(p))

    # Action: Update SL to 55000
    order = await gateway.update_stop_loss("BTCUSDT", 55000.0, OrderSide.BUY)

    # Verification: Should proceed to place new order despite -2011
    assert order is not None
    mock_client.new_algo_order.assert_called_once()
    print("✓ TC-01 Passed: System ignored -2011 and placed new SL.")

@pytest.mark.asyncio
async def test_tc02_collision_recovery_4130():
    """TC-02: Recovery from -4130 (Duplicate Order) via force re-sync."""
    mock_client = AsyncMock(spec=AsyncBinanceClient)
    mock_audit = Mock()
    
    # Setup: 
    # 1st place attempt fails with -4130
    # 2nd place attempt succeeds after force cleanup
    mock_client.get_open_algo_orders.side_effect = [
        [], # Initial fetch finds nothing
        [{"algoId": "hidden_sl", "type": "STOP_MARKET"}] # Force re-sync finds the culprit
    ]
    mock_client.new_algo_order.side_effect = [
        Exception("Binance API error: {'code': -4130, 'msg': 'Duplicate'}"),
        {"algoId": "final_sl", "status": "NEW", "updateTime": 123456789, "time": 123456789, "stopPrice": "55000.0"}
    ]
    mock_client.get_mark_price.return_value = 50000.0

    gateway = OrderGateway(audit_logger=mock_audit, binance_service=AsyncMock())
    gateway.client = mock_client
    gateway._format_price = AsyncMock(side_effect=lambda p, s: str(p))

    # Action
    order = await gateway.update_stop_loss("BTCUSDT", 55000.0, OrderSide.BUY)

    # Verification: Should have retried and succeeded
    assert order is not None
    assert mock_client.new_algo_order.call_count == 2
    mock_client.cancel_algo_order.assert_called_with("BTCUSDT", "hidden_sl")
    print("✓ TC-02 Passed: Recovered from -4130 via force re-sync.")

@pytest.mark.asyncio
async def test_tc04_position_mismatch_4112():
    """TC-04: Immediate stop on -4112 (ReduceOnly reject)."""
    mock_client = AsyncMock(spec=AsyncBinanceClient)
    
    mock_client.get_open_algo_orders.return_value = []
    mock_client.new_algo_order.side_effect = Exception("Binance API error: {'code': -4112, 'msg': 'ReduceOnly reject'}")
    mock_client.get_mark_price.return_value = 50000.0

    gateway = OrderGateway(audit_logger=Mock(), binance_service=AsyncMock())
    gateway.client = mock_client
    gateway._format_price = AsyncMock(side_effect=lambda p, s: str(p))

    # Action
    order = await gateway.update_stop_loss("BTCUSDT", 55000.0, OrderSide.BUY)

    # Verification: Should NOT retry on -4112
    assert order is None
    assert mock_client.new_algo_order.call_count == 1
    print("✓ TC-04 Passed: Stopped immediately on -4112.")

@pytest.mark.asyncio
async def test_tc05_price_match_optimization():
    """TC-05: Skip API calls if SL price is already correct."""
    mock_client = AsyncMock(spec=AsyncBinanceClient)
    
    # Setup: Existing order already at 55000.0
    mock_client.get_open_algo_orders.return_value = [
        {
            "algoId": "same_price_sl", 
            "type": "STOP_MARKET", 
            "stopPrice": "55000.0", 
            "symbol": "BTCUSDT",
            "updateTime": 123456789,
            "time": 123456789
        }
    ]
    mock_client.get_mark_price.return_value = 50000.0

    gateway = OrderGateway(audit_logger=Mock(), binance_service=AsyncMock())
    gateway.client = mock_client
    gateway._format_price = AsyncMock(side_effect=lambda p, s: str(p))

    # Action: Try to update to same price 55000.0
    order = await gateway.update_stop_loss("BTCUSDT", 55000.0, OrderSide.BUY)

    # Verification: No cancel or new order should be called
    assert order is not None
    mock_client.cancel_algo_order.assert_not_called()
    mock_client.new_algo_order.assert_not_called()
    print("✓ TC-05 Passed: Optimized by skipping redundant update.")

if __name__ == "__main__":
    # Manual run if pytest not available
    async def run_tests():
        await test_tc01_ghost_cancel_resilience()
        await test_tc02_collision_recovery_4130()
        await test_tc04_position_mismatch_4112()
        await test_tc05_price_match_optimization()
        print("\nAll Resilience Tests Passed!")
    
    asyncio.run(run_tests())
