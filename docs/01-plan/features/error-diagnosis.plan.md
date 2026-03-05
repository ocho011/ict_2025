# PDCA Plan: Binance API Error Diagnosis & Logic Review

**Date:** 2026-03-05
**Feature:** Error Diagnosis
**Status:** Planning

## 1. Problem Identification

Based on recent logs (`trading.log`), two recurring Binance API errors are severely impacting the stability of the automated trading system:

1.  **Error -4130**: `An open stop or take profit order with GTE and closePosition in the direction is existing.`
    *   **Context**: Occurs during dynamic Stop-Loss (SL) updates at `src.execution.order_gateway:910`.
    *   **Symptom**: New SL order placement fails because an existing `closePosition=true` order for the same direction already exists.
    *   **Risk**: Positions may remain unprotected if SL updates fail consistently.

2.  **Error -5000**: `Path /fapi/v1/allOpenAlgoOrders, Method DELETE is invalid`
    *   **Context**: Occurs at `AsyncBinanceClient:219` during attempts to cancel algo orders by type.
    *   **Symptom**: The client tries to call a non-existent or misconfigured endpoint for cancelling all open algo orders.
    *   **Risk**: Failed cancellations lead to orphaned orders, causing Error -4130 subsequently.

## 2. Root Cause Analysis Strategy (Research Phase)

### 2.1. Code Review (Order Management Logic)
*   **Target**: `src.execution.order_gateway.py` (Lines 861, 910)
*   **Objective**: Investigate the `_cancel_existing_sl_orders` logic. Why does it report "Cancelled 0 existing SL algo orders" while Binance claims one still exists (Error -4130)?
*   **Question**: Is the order filtering logic (by symbol, type, side) matching exactly what Binance holds?

### 2.2. Client-Side API Specification Check
*   **Target**: `AsyncBinanceClient` implementation.
*   **Objective**: Verify the endpoint used for `allOpenAlgoOrders`.
*   **Question**: Is `/fapi/v1/allOpenAlgoOrders` a valid DELETE endpoint in the current Binance Futures API? If not, what is the correct replacement (e.g., individual cancellation vs. batch)?

### 2.3. Logic Bug Review (Race Conditions)
*   **Objective**: Determine if SL updates are being triggered too frequently (every candle) without waiting for previous cancellation confirmations.
*   **Question**: Should there be a "cancel-then-check-then-place" guard or a lock mechanism?

## 3. Implementation Strategy (Do Phase)

1.  **Fix API Endpoint**: Correct the invalid endpoint in `AsyncBinanceClient`.
2.  **Robust Order Synchronization**: Enhance `OrderGateway` to query current open orders explicitly before placing new ones, rather than relying on internal state or potentially failed batch cancellations.
3.  **Graceful Error Handling**: Implement specific handling for -4130 to fetch and adopt existing order IDs if appropriate, instead of throwing an exception.

## 4. Verification & Regression Testing (Check Phase)

1.  **Unit Tests**: Mock Binance API responses for -4130 and -5000 to ensure the system handles them without crashing.
2.  **Integration Tests**: Run `tests/execution/test_order_execution.py` (if exists) or create a new one to simulate the SL update flow.
3.  **Log Verification**: Confirm that "SL dynamic update failed" messages disappear from the logs.

## 5. Success Criteria
*   Zero occurrences of Error -4130 and -5000 in `trading.log` over a 1-hour window.
*   Stop-Loss orders are correctly updated/ratcheted as price moves.
