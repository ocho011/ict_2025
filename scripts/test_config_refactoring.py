import yaml
import os
import asyncio
from src.config.symbol_config import TradingConfigHierarchical
from src.strategies.dynamic_assembler import DynamicAssembler

async def test_config_load():
    base_yaml_path = "configs/base.yaml"
    with open(base_yaml_path, 'r') as f:
        data = yaml.safe_load(f)
    
    trading_data = data.get("trading", {})
    config = TradingConfigHierarchical.from_dict(trading_data)
    
    print(f"Loaded {len(config.symbols)} symbols")
    
    # Check defaults
    btc_config = config.get_symbol_config("BTCUSDT")
    print(f"BTC Strategy: {btc_config.strategy}")
    
    assert btc_config.strategy == "composable_strategy"
    
    # Test Dynamic Assembly
    print("\nTesting Dynamic Assembly...")
    assembler = DynamicAssembler()
    module_config, intervals, min_rr = assembler.assemble_for_symbol(btc_config)
    
    print(f"Entry: {module_config.entry_determiner.name}")
    print(f"SL: {module_config.stop_loss_determiner.name}")
    print(f"TP: {module_config.take_profit_determiner.name}")
    print(f"Exit: {module_config.exit_determiner.name}")
    
    assert module_config.entry_determiner.name == "ICTOptimalEntryDeterminer"
    assert module_config.stop_loss_determiner.name == "PercentageStopLossDeterminer"
    
    print("\nConfig validation and Dynamic Assembly passed!")

if __name__ == "__main__":
    asyncio.run(test_config_load())
