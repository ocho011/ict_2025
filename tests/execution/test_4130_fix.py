import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.execution.order_gateway import OrderGateway
from src.models.order import OrderSide, OrderStatus, OrderType

@pytest.mark.asyncio
async def test_update_stop_loss_clears_tp_conflict():
    """
    Test that update_stop_loss correctly identifies and cancels 
    TAKE_PROFIT_MARKET orders to avoid Binance Error -4130.
    """
    # 1. Setup mocks
    mock_client = AsyncMock()
    mock_audit = MagicMock()
    gateway = OrderGateway(binance_service=mock_client, audit_logger=mock_audit)
    
    symbol = "BTCUSDT"
    new_sl_price = 45000.0
    side = OrderSide.SELL # Closing a LONG position
    
    # Mock mark price
    mock_client.get_mark_price.return_value = 50000.0
    
    # Mock price formatting to bypass exchange_info dependency
    gateway._format_price = AsyncMock(return_value=str(new_sl_price))
    
    # Mock existing orders: One SL (different price) and One TP (conflict source)
    mock_client.get_open_algo_orders.return_value = [
        {
            "algoId": "sl_123",
            "symbol": symbol,
            "type": "STOP_MARKET",
            "stopPrice": "44000.0",
            "side": "SELL"
        },
        {
            "algoId": "tp_456",
            "symbol": symbol,
            "type": "TAKE_PROFIT_MARKET",
            "triggerPrice": "55000.0",
            "side": "SELL"
        }
    ]
    
    # Mock successful placement
    mock_client.new_algo_order.return_value = {
        "algoId": "new_sl_789",
        "symbol": symbol,
        "type": "STOP_MARKET",
        "side": "SELL",
        "triggerPrice": str(new_sl_price),
        "status": "NEW",
        "time": 123456789,
        "updateTime": 123456789
    }
    
    # 2. Execute
    order = await gateway.update_stop_loss(symbol, new_sl_price, side)
    
    # 3. Verify
    assert order is not None
    assert order.order_id == "new_sl_789"
    
    # Verify both SL and TP were cancelled
    # Note: cancel_algo_order should be called for both sl_123 and tp_456
    cancel_calls = [call.args for call in mock_client.cancel_algo_order.call_args_list]
    assert (symbol, "sl_123") in cancel_calls
    assert (symbol, "tp_456") in cancel_calls
    
    # Verify new order was placed
    mock_client.new_algo_order.assert_called_once()
    args, kwargs = mock_client.new_algo_order.call_args
    assert kwargs["closePosition"] == "true"
    assert kwargs["type"] == "STOP_MARKET"

@pytest.mark.asyncio
async def test_update_stop_loss_retry_on_4130():
    """
    Test that if -4130 still occurs, the retry logic also clears TP orders.
    """
    mock_client = AsyncMock()
    gateway = OrderGateway(binance_service=mock_client, audit_logger=MagicMock())
    
    symbol = "BTCUSDT"
    mock_client.get_mark_price.return_value = 50000.0
    gateway._format_price = AsyncMock(return_value="45000.0")
    
    # First call to get_open_algo_orders returns nothing (simulating out of sync)
    mock_client.get_open_algo_orders.side_effect = [
        [], # Initial sync finds nothing
        [{"algoId": "stubborn_tp", "type": "TAKE_PROFIT_MARKET"}] # Second sync (inside retry) finds TP
    ]
    
    # First placement fails with -4130, second fails with -4130, third succeeds
    mock_client.new_algo_order.side_effect = [
        Exception("Binance API error: {'code': -4130, 'msg': 'Duplicate'}"),
        Exception("Binance API error: {'code': -4130, 'msg': 'Duplicate'}"),
        {"algoId": "success_sl", "status": "NEW", "updateTime": 123456789}
    ]
    
    # Execute
    await gateway.update_stop_loss(symbol, 45000.0, OrderSide.SELL)
    
    # Verify the retry logic cancelled the "stubborn_tp"
    mock_client.cancel_algo_order.assert_called_with(symbol, "stubborn_tp")
    # Total calls: 1 initial fail + 1 retry success = 2
    assert mock_client.new_algo_order.call_count == 2
