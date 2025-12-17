
import asyncio
from datetime import datetime, timezone
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategies.mock_strategy import MockSMACrossoverStrategy
from src.models.candle import Candle

def verify_tpsl():
    print("Verifying TP/SL Logic in MockSMACrossoverStrategy...")
    
    # 1. Config: Risk/Reward 2.0, Stop Loss 1%
    config = {
        'risk_reward_ratio': 2.0,
        'stop_loss_percent': 0.01,
        'buffer_size': 100
    }
    
    strategy = MockSMACrossoverStrategy('BTCUSDT', config)
    entry_price = 50000.0
    
    print(f"\nConfiguration:")
    print(f"  Entry Price: {entry_price}")
    print(f"  Stop Loss %: {config['stop_loss_percent']*100}%")
    print(f"  Risk/Reward: {config['risk_reward_ratio']}")
    
    # 2. Test LONG
    print(f"\n[LONG Position]")
    sl_long = strategy.calculate_stop_loss(entry_price, 'LONG')
    tp_long = strategy.calculate_take_profit(entry_price, 'LONG')
    
    expected_sl_long = 50000 * (1 - 0.01) # 49500
    expected_tp_long = 50000 + (500 * 2.0) # 51000
    
    print(f"  Calculated SL: {sl_long} (Expected: {expected_sl_long})")
    print(f"  Calculated TP: {tp_long} (Expected: {expected_tp_long})")
    
    if sl_long == expected_sl_long and tp_long == expected_tp_long:
        print("  ✅ LONG Logic Verified")
    else:
        print("  ❌ LONG Logic Failed")

    # 3. Test SHORT
    print(f"\n[SHORT Position]")
    sl_short = strategy.calculate_stop_loss(entry_price, 'SHORT')
    tp_short = strategy.calculate_take_profit(entry_price, 'SHORT')
    
    expected_sl_short = 50000 * (1 + 0.01) # 50500
    expected_tp_short = 50000 - (500 * 2.0) # 49000
    
    print(f"  Calculated SL: {sl_short} (Expected: {expected_sl_short})")
    print(f"  Calculated TP: {tp_short} (Expected: {expected_tp_short})")
    
    if sl_short == expected_sl_short and tp_short == expected_tp_short:
        print("  ✅ SHORT Logic Verified")
    else:
        print("  ❌ SHORT Logic Failed")

if __name__ == "__main__":
    verify_tpsl()
