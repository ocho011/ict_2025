# Plan: Fix Binance -4130 SL Collision in update_stop_loss (v4)

## Problem

`update_stop_loss()` at `src/execution/order_gateway.py:806` fails with -4130 because the type filter at lines 850/906 never matches the actual `type` field from Binance's Algo API, so existing SL orders are never cancelled.

## Root Cause

Type filter `o.get("type") in ["STOP", "STOP_MARKET", ...]` doesn't match actual API response. Both initial cancel and recovery silently fail. `cancel_all_algo_orders(symbol)` (used at line 1801) is proven to work.

## Fix: 3 Changes to `src/execution/order_gateway.py`

### Change 1: Replace lines 843-924 (entire cancel + placement logic)

Replace the "Robust SL Sync Logic" block AND the placement loop with a restructured flow that uses `break` instead of `return` on success, enabling TP restoration after the loop.

**Replace from line 843 (`# 2. Robust SL Sync Logic`) through line 924 (`return None`):**

```python
        # 2. Cancel existing algo orders (nuclear approach) with TP preservation
        tp_trigger_price = None
        try:
            # 2a. Fetch existing orders to check same-price and preserve TP info
            open_algo_orders = await self.client.get_open_algo_orders(symbol)
            if open_algo_orders:
                self.logger.info(
                    f"Open algo orders for {symbol} before SL update: "
                    f"{[{k: o.get(k) for k in ['algoId', 'type', 'side', 'triggerPrice', 'stopPrice', 'closePosition', 'algoType']} for o in open_algo_orders]}"
                )
                for o in open_algo_orders:
                    trigger = float(o.get("triggerPrice", 0) or o.get("stopPrice", 0))
                    if trigger <= 0:
                        continue
                    # Same-price optimization: skip if existing order matches target SL
                    if abs(trigger - new_stop_price) < 1e-8:
                        self.logger.info(f"Existing SL for {symbol} matches target {new_stop_price}. Skipping update.")
                        return self._parse_order_response(o, symbol, side, OrderType.STOP_MARKET)
                    # Identify TP by trigger direction vs mark price
                    # SELL (closing LONG): TP > mark, SL < mark
                    # BUY (closing SHORT): TP < mark, SL > mark
                    is_tp = (side == OrderSide.SELL and trigger > mark_price) or \
                            (side == OrderSide.BUY and trigger < mark_price)
                    if is_tp:
                        tp_trigger_price = trigger
                        self.logger.info(f"Preserving TP for {symbol}: triggerPrice={trigger}")

            # 2b. Nuclear cancel (proven at line 1801)
            await self.client.cancel_all_algo_orders(symbol)
            self.logger.info(f"Cancelled all algo orders for {symbol} before SL update")
            await asyncio.sleep(0.3)

        except Exception as e:
            self.logger.error(f"Failed to clear existing orders for {symbol}: {e}")
            return None

        # 3. Place new SL order with collision recovery
        stop_price_str = await self._format_price(new_stop_price, symbol)
        max_place_retries = 5
        order = None  # Initialize to handle case where all attempts fail

        for attempt in range(max_place_retries + 1):
            try:
                response = await self.client.new_algo_order(
                    symbol=symbol, side=side.value, type=OrderType.STOP_MARKET.value,
                    triggerPrice=stop_price_str, closePosition="true", workingType="MARK_PRICE"
                )
                order = self._parse_order_response(response, symbol, side, OrderType.STOP_MARKET)
                order.stop_price = new_stop_price
                self.logger.info(f"SL dynamically updated for {symbol}: new stopPrice={stop_price_str} (Attempt {attempt+1})")

                try:
                    self.audit_logger.log_order_placed(
                        symbol=symbol,
                        order_data={"order_type": "STOP_MARKET", "side": side.value, "stop_price": new_stop_price, "close_position": True, "update_reason": "trailing_stop_dynamic_update"},
                        response={"order_id": order.order_id, "status": order.status.value},
                    )
                except Exception: pass
                break  # SUCCESS: exit loop, fall through to TP restoration

            except Exception as e:
                if "-4130" in str(e) and attempt < max_place_retries:
                    self.logger.warning(
                        f"SL collision (-4130) for {symbol}. Recovery {attempt+1}/{max_place_retries}..."
                    )
                    try:
                        await self.client.cancel_all_algo_orders(symbol)
                        self.logger.info(f"Recovery: nuclear cancel completed for {symbol}")
                        await asyncio.sleep(0.5)
                        continue
                    except Exception as cancel_err:
                        self.logger.error(f"Recovery cancel failed for {symbol}: {cancel_err}")
                        break

                if "-4112" in str(e):
                    self.logger.critical(f"ReduceOnly rejected for {symbol} SL: {e}")
                    break

                self.logger.error(f"New SL placement failed for {symbol} (Attempt {attempt+1}): {e}")
                if attempt < max_place_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    break

        # 4. Restore TP if it was cancelled during SL update
        if tp_trigger_price is not None:
            await self._restore_tp_order(symbol, side, tp_trigger_price)

        return order
```

### Change 2: Add `_restore_tp_order` helper method

**Insert after `update_stop_loss` method** (after line 927):

```python
    async def _restore_tp_order(
        self, symbol: str, side: OrderSide, tp_trigger_price: float
    ) -> None:
        """Re-place TP order after nuclear cancel during SL update, with mark price validation."""
        try:
            mark_price = await self.client.get_mark_price(symbol)
            min_buffer = mark_price * 0.002  # 0.2% buffer (same as _place_tp_order line 965)

            # Validate TP trigger price relative to mark (same logic as _place_tp_order lines 972-999)
            if side == OrderSide.SELL:
                # Closing LONG: TP must be ABOVE mark
                if tp_trigger_price <= mark_price:
                    tp_trigger_price = mark_price + min_buffer
                    self.logger.warning(f"TP restore adjusted for {symbol}: trigger <= mark, new={tp_trigger_price:.4f}")
                elif tp_trigger_price - mark_price < min_buffer:
                    tp_trigger_price = mark_price + min_buffer
                    self.logger.warning(f"TP restore adjusted for {symbol}: too close to mark, new={tp_trigger_price:.4f}")
            else:  # BUY - closing SHORT
                if tp_trigger_price >= mark_price:
                    tp_trigger_price = mark_price - min_buffer
                    self.logger.warning(f"TP restore adjusted for {symbol}: trigger >= mark, new={tp_trigger_price:.4f}")
                elif mark_price - tp_trigger_price < min_buffer:
                    tp_trigger_price = mark_price - min_buffer
                    self.logger.warning(f"TP restore adjusted for {symbol}: too close to mark, new={tp_trigger_price:.4f}")

            tp_price_str = await self._format_price(tp_trigger_price, symbol)
            await self.client.new_algo_order(
                symbol=symbol,
                side=side.value,
                type=OrderType.TAKE_PROFIT_MARKET.value,
                triggerPrice=tp_price_str,
                closePosition="true",
                workingType="MARK_PRICE",
            )
            self.logger.info(f"TP restored for {symbol}: triggerPrice={tp_price_str}")
        except Exception as e:
            self.logger.error(
                f"CRITICAL: Failed to restore TP for {symbol}: {e}. "
                f"Position has SL but NO TP protection. Manual intervention may be needed."
            )
```

### Change 3: No other files changed

All changes are in `src/execution/order_gateway.py` only.

## Control Flow Summary

```
update_stop_loss(symbol, new_stop_price, side)
  │
  ├─ 1. Validate mark price / buffer (unchanged, lines 821-841)
  │
  ├─ 2. Fetch orders → save TP price → nuclear cancel
  │     ├─ Same-price match? → return early (no cancel needed)
  │     └─ TP detected? → save tp_trigger_price
  │
  ├─ 3. Place new SL (loop with retries)
  │     ├─ Success → break (fall through to step 4)
  │     └─ -4130 → nuclear cancel → retry
  │
  ├─ 4. Restore TP if saved (always runs after loop)
  │     ├─ Validates trigger vs mark price
  │     └─ Failure → ERROR log "NO TP protection"
  │
  └─ return order (or None if all attempts failed)
```

## Acceptance Criteria

1. `-4130` resolved via nuclear cancel (grep: `"Cancelled all algo orders"`)
2. TP restored after SL update on BOTH success and failure paths (grep: `"TP restored for"`)
3. TP failure escalated to ERROR (grep: `"NO TP protection"`)
4. Diagnostic log reveals API field structure (grep: `"Open algo orders for"`)
5. Same-price optimization works (grep: `"Skipping update"`)

## Verification

```bash
grep "\-4130" logs/trading.log           # Should not appear or show recovery
grep "TP restored for" logs/trading.log  # Confirms TP preservation
grep "NO TP protection" logs/trading.log # Should NOT appear
grep "Open algo orders for" logs/trading.log # Shows actual API fields
```
