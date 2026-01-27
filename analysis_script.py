import json
import pandas as pd
from datetime import datetime
import sys

def analyze_logs(file_path):
    data = []
    with open(file_path, 'r') as f:
        for line in f:
            try:
                data.append(json.loads(line))
            except:
                continue

    df = pd.DataFrame(data)
    
    # 1. Analyze Signals & RR
    print("=== Order Appropriateness (RR & TP/SL) ===")
    signals = df[df['event_type'] == 'signal_processing'].copy()
    signals = signals[signals['additional_data'].apply(lambda x: x.get('signal_generated', False))]
    
    for _, row in signals.iterrows():
        ad = row['additional_data']
        entry = float(ad['entry_price'])
        tp = float(ad['take_profit'])
        sl = float(ad['stop_loss'])
        signal_type = ad['signal_type']
        
        risk = abs(entry - sl)
        reward = abs(entry - tp)
        
        rr = reward / risk if risk > 0 else 0
        print(f"Timestamp: {row['timestamp']}, Symbol: {row['symbol']}, Type: {signal_type}")
        print(f"  Entry: {entry}, TP: {tp}, SL: {sl}")
        print(f"  Risk: {risk:.5f}, Reward: {reward:.5f}, RR Ratio: {rr:.4f}")
        
        # Check alignment
        if 'long' in signal_type:
            valid_tp = tp > entry
            valid_sl = sl < entry
        else:
            valid_tp = tp < entry
            valid_sl = sl > entry
            
        if not (valid_tp and valid_sl):
            print(f"  WARINING: Invalid TP/SL direction! Valid TP: {valid_tp}, Valid SL: {valid_sl}")
        print("-" * 30)

    # 2. Analyze PnL & Balance
    print("\n=== PnL & Balance Analysis ===")
    balances = df[df['event_type'] == 'balance_query'].copy()
    if not balances.empty:
        balances['bal'] = balances['response'].apply(lambda x: float(x.get('balance', 0)) if isinstance(x, dict) else 0)
        start_bal = balances.iloc[0]['bal']
        end_bal = balances.iloc[-1]['bal']
        print(f"Start Balance: {start_bal}")
        print(f"End Balance: {end_bal}")
        print(f"Net Change: {end_bal - start_bal:.4f}")
    
    # Position PnL from queries
    positions = df[df['event_type'] == 'position_query'].copy()
    if not positions.empty:
        positions['upnl'] = positions['response'].apply(lambda x: float(x.get('unrealized_pnl', 0)) if isinstance(x, dict) else 0)
        print("\nLast Known Unrealized PnL per Symbol:")
        latest_positions = positions.sort_values('timestamp').groupby('symbol').last()
        for symbol, row in latest_positions.iterrows():
            print(f"  {symbol}: {row['upnl']}")

    # 3. Orphan & Rejected Orders
    print("\n=== Orphan & Rejected Orders Analysis ===")
    rejections = df[df['event_type'] == 'order_rejected']
    print(f"Total Rejections: {len(rejections)}")
    if not rejections.empty:
        print(rejections[['timestamp', 'symbol', 'operation', 'error']].head(10))
        
    print("\n=== Order Cancellations ===")
    cancellations = df[df['event_type'] == 'order_cancelled']
    print(f"Total Cancellation Events: {len(cancellations)}")
    
    # 4. Monitoring Frequency
    print("\n=== Monitoring Frequency (Sample) ===")
    pos_queries = df[df['event_type'] == 'position_query']
    if not pos_queries.empty:
        pos_queries['ts'] = pd.to_datetime(pos_queries['timestamp'])
        pos_queries = pos_queries.sort_values('ts')
        pos_queries['diff'] = pos_queries.groupby('symbol')['ts'].diff().dt.total_seconds()
        print(pos_queries.groupby('symbol')['diff'].describe())

if __name__ == "__main__":
    analyze_logs('/Users/osangwon/github/ict_2025/logs/audit/audit_20260127.jsonl')
