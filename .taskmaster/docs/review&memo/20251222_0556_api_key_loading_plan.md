# Implementation Plan - API Key Loading Design Improvement (Moved)

This plan addresses the design issue where API keys and secrets are loaded independently of the `is_testnet` flag. We will modify the configuration loading logic to ensure that keys are always coupled with the intended network.

## User Review Required

> [!IMPORTANT]
> This change will remove support for the generic `BINANCE_API_KEY` and `BINANCE_API_SECRET` environment variables. 
> Instead, network-specific environment variables must be used:
> - `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET`
> - `BINANCE_MAINNET_API_KEY` / `BINANCE_MAINNET_API_SECRET`

## Proposed Changes

### Configuration Management

#### [MODIFY] [config.py](file:///Users/osangwon/github/ict_2025/src/utils/config.py)
- Update `_load_api_config` to:
    1. Determine `is_testnet` first (from `BINANCE_USE_TESTNET` env or `api_keys.ini`).
    2. Based on the selected network, fetch the corresponding keys.
    3. Use network-specific environment variables:
        - Testnet: `BINANCE_TESTNET_API_KEY`, `BINANCE_TESTNET_API_SECRET`
        - Mainnet: `BINANCE_MAINNET_API_KEY`, `BINANCE_MAINNET_API_SECRET`
    4. Fall back to `api_keys.ini` sections `[binance.testnet]` or `[binance.mainnet]`.
    5. Raise an error if keys for the selected network are not found.
    6. Remove support for `BINANCE_API_KEY` and `BINANCE_API_SECRET` to ensure strict coupling.

### Bot Initialization

#### [MODIFY] [main.py](file:///Users/osangwon/github/ict_2025/src/main.py)
- Review `TradingBot.initialize` to ensure it correctly handles the updated `APIConfig`. (No major changes expected here as the `APIConfig` interface remains similar).

---

## Verification Plan

### Automated Tests
- Update `tests/test_config_environments.py` to reflect the new environment variable names.
- Run tests:
  ```bash
  pytest tests/test_config_environments.py
  ```
- Add a new test case to verify that generic `BINANCE_API_KEY` is ignored (or causes an error if no other keys are found).

### Manual Verification
- Set `BINANCE_USE_TESTNET=true` and `BINANCE_TESTNET_API_KEY=mock_test_key`.
- Run the bot and verify (via logs) that it uses the testnet key.
- Set `BINANCE_USE_TESTNET=false` and `BINANCE_MAINNET_API_KEY=mock_main_key`.
- Run the bot and verify (via logs) that it uses the mainnet key.
