# PDCA Design: Binance API Error Fix & SL/TP Synchronization

**Date:** 2026-03-05
**Feature:** Error Diagnosis
**Related Plan:** `docs/01-plan/features/error-diagnosis.plan.md`

## 1. Problem Definition (Refined)

1.  **Error -5000**: `DELETE /fapi/v1/allOpenAlgoOrders` is an invalid endpoint. The system cannot batch-cancel SL/TP orders placed via the `algoOrder` endpoint.
2.  **Error -4130**: Because previous SL orders are not cancelled (due to Error -5000), new SL orders with `closePosition=true` collide with existing ones.

## 2. Technical Solution

### 2.1. Update `AsyncBinanceClient` (src/core/async_binance_client.py)
*   **Rename/Fix Batch Cancel**: Change `cancel_all_algo_orders` to use the correct endpoint (if exists) or implement a fallback. 
*   **Add Fetching**: Implement `get_open_algo_orders(symbol: str)` to query current conditional orders.
    *   Endpoint: `GET /fapi/v1/openAlgoOrders` (Signed)
*   **Add Individual Cancel**: Implement `cancel_algo_order(symbol: str, algoId: str)` to cancel a specific conditional order.
    *   Endpoint: `DELETE /fapi/v1/algoOrder` (Signed)

### 2.2. Update `OrderGateway` (src/execution/order_gateway.py)
*   **Refactor `_cancel_existing_sl_orders` (Wait, method is named in plan, but let's check actual code)**:
    *   Instead of calling a single (broken) batch cancel, it should:
        1. Fetch all open algo orders for the symbol.
        2. Filter by `algoType="CONDITIONAL"` and `type="STOP_MARKET"`.
        3. Cancel each matching order individually.
    *   This ensures that even if batch cancellation is unavailable, SL updates are deterministic and clean.

### 2.3. Correct API Endpoints Reference
*   According to recent Binance Futures API updates:
    *   `/fapi/v1/algoOrder` is for Strategy Orders (VP, TWAP).
    *   **Wait**: Let's re-verify if `STOP_MARKET` with `closePosition=true` should actually be placed via `/fapi/v1/order` instead of `/fapi/v1/algoOrder`. 
    *   **Strategic Decision**: If the project currently uses `/fapi/v1/algoOrder` for STOP_MARKET, we will fix the cancellation flow for it. If we find that regular STOP_MARKET is better, we will migrate it to `/fapi/v1/order`. 

## 3. Implementation Steps

1.  **Modify `AsyncBinanceClient`**:
    *   Add `get_open_algo_orders`.
    *   Add `cancel_algo_order`.
    *   Fix/Remove `cancel_all_algo_orders`.
2.  **Modify `OrderGateway`**:
    *   Update `update_sl_dynamic` to use the new fetching/cancellation logic.
    *   Add a check for Error -4130 in the `try...except` block to log more context (e.g., current open orders) for further debugging.

## 4. Test Strategy

1.  **Mock Test**: Create a test case in `tests/test_fixes.py` that mocks a lingering SL order and verifies the new cancellation logic triggers before the new placement.
2.  **Log Check**: Monitor `trading.log` for `-4130` and `-5000` errors.
3.  **Manual Verification**: If possible, trigger a small manual trade and move the price to force an SL dynamic update.
