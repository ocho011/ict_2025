"""
Unit tests for RiskGuard - Subtask 7.1, 7.2, 7.3, 7.4
"""

import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.models.position import Position
from src.models.signal import Signal, SignalType
from src.risk.risk_guard import RiskGuard


class TestPositionSizeCalculation:
    """Test suite for subtask 7.1 - Position size calculation"""

    @pytest.fixture
    def mock_audit_logger(self):
        """Mock AuditLogger"""
        return MagicMock()

    @pytest.fixture
    def risk_manager(self, mock_audit_logger):
        """Setup RiskGuard with standard config"""
        config = {
            "max_risk_per_trade": 0.01,  # 1%
            "max_leverage": 20,
            "default_leverage": 10,
            "max_position_size_percent": 0.1,  # 10%
        }
        return RiskGuard(config, audit_logger=mock_audit_logger)

    def test_normal_case_2_percent_sl(self, risk_manager):
        """
        Normal case: 1% risk with 2% SL distance

        Account: $10,000
        Risk: 1% = $100
        SL: 2% = 1,000 USDT distance
        Position Value: $100 / 0.02 = $5,000
        Quantity: $5,000 / $50,000 = 0.1 BTC
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000, entry_price=50000, stop_loss_price=49000, leverage=10  # 2% SL
        )

        expected = 0.1  # 0.1 BTC
        assert quantity == pytest.approx(expected, rel=0.01)

    def test_tight_sl_0_1_percent(self, risk_manager):
        """
        Tight SL: 0.1% distance creates large position

        Account: $10,000
        Risk: 1% = $100
        SL: 0.1% = 50 USDT distance
        Position Value: $100 / 0.001 = $100,000
        Quantity: $100,000 / $50,000 = 2.0 BTC

        But capped to max: 0.2 BTC (10% × 10x leverage)
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49950,  # 0.1% SL (tight)
            leverage=10,
        )

        # Position size capped at 10% of account with 10x leverage
        max_quantity = 10000 * 0.1 * 10 / 50000  # 0.2 BTC
        assert quantity == pytest.approx(max_quantity, rel=0.01)

    def test_wide_sl_10_percent(self, risk_manager):
        """
        Wide SL: 10% distance creates small position

        Account: $10,000
        Risk: 1% = $100
        SL: 10% = 5,000 USDT distance
        Position Value: $100 / 0.10 = $1,000
        Quantity: $1,000 / $50,000 = 0.02 BTC
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=45000,  # 10% SL (wide)
            leverage=10,
        )

        expected = 0.02  # 0.02 BTC
        assert quantity == pytest.approx(expected, rel=0.01)

    def test_different_account_balance(self, risk_manager):
        """Test with $50,000 account balance"""
        quantity = risk_manager.calculate_position_size(
            account_balance=50000, entry_price=50000, stop_loss_price=49000, leverage=10  # 2% SL
        )

        # Risk: 1% of $50,000 = $500
        # Position Value: $500 / 0.02 = $25,000
        # Quantity: $25,000 / $50,000 = 0.5 BTC
        expected = 0.5
        assert quantity == pytest.approx(expected, rel=0.01)

    def test_different_risk_percentage(self):
        """Test with 2% risk per trade"""
        config = {
            "max_risk_per_trade": 0.02,  # 2% risk
            "max_leverage": 20,
            "default_leverage": 10,
            "max_position_size_percent": 0.1,
        }
        mock_audit_logger = MagicMock()
        risk_manager = RiskGuard(config, audit_logger=mock_audit_logger)

        quantity = risk_manager.calculate_position_size(
            account_balance=10000, entry_price=50000, stop_loss_price=49000, leverage=10  # 2% SL
        )

        # Risk: 2% of $10,000 = $200
        # Position Value: $200 / 0.02 = $10,000
        # Quantity: $10,000 / $50,000 = 0.2 BTC
        expected = 0.2
        assert quantity == pytest.approx(expected, rel=0.01)

    def test_zero_sl_distance_uses_minimum(self, risk_manager, caplog):
        """
        Edge case: SL = Entry → uses minimum 0.1% SL

        Should log warning and use 0.001 (0.1%) as minimum SL distance
        """
        with caplog.at_level(logging.WARNING):
            quantity = risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=50000,  # Same as entry!
                leverage=10,
            )

        # With 0.1% minimum SL:
        # Risk: 1% = $100
        # Position Value: $100 / 0.001 = $100,000
        # Quantity: $100,000 / $50,000 = 2.0 BTC
        # But capped at 0.2 BTC
        max_quantity = 10000 * 0.1 * 10 / 50000  # 0.2 BTC
        assert quantity == pytest.approx(max_quantity, rel=0.01)

        # Verify warning logged
        assert "Zero SL distance detected" in caplog.text

    def test_invalid_account_balance(self, risk_manager):
        """Negative account balance raises ValueError"""
        with pytest.raises(ValueError, match="Account balance must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=-1000, entry_price=50000, stop_loss_price=49000, leverage=10
            )

    def test_invalid_entry_price(self, risk_manager):
        """Zero entry price raises ValueError"""
        with pytest.raises(ValueError, match="Entry price must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=10000, entry_price=0, stop_loss_price=49000, leverage=10
            )

    def test_invalid_stop_loss_price(self, risk_manager):
        """Negative SL price raises ValueError"""
        with pytest.raises(ValueError, match="Stop loss price must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=10000, entry_price=50000, stop_loss_price=-1000, leverage=10
            )

    def test_leverage_too_low(self, risk_manager):
        """Leverage < 1 raises ValueError"""
        with pytest.raises(ValueError, match="Leverage must be between"):
            risk_manager.calculate_position_size(
                account_balance=10000, entry_price=50000, stop_loss_price=49000, leverage=0
            )

    def test_leverage_too_high(self, risk_manager):
        """Leverage > max_leverage raises ValueError"""
        with pytest.raises(ValueError, match="Leverage must be between"):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=49000,
                leverage=125,  # Exceeds max_leverage=20
            )

    def test_leverage_at_max(self, risk_manager):
        """Leverage = max_leverage is valid"""
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=20,  # At max_leverage
        )

        # Should succeed without error
        assert quantity > 0

    def test_short_position_sl_above_entry(self, risk_manager):
        """
        SHORT position: SL above entry

        Entry: 50,000, SL: 51,000 (2% above for SHORT)
        Should calculate same as LONG with 2% SL distance
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=51000,  # Above entry for SHORT
            leverage=10,
        )

        # SL distance: |51000 - 50000| / 50000 = 2%
        # Same calculation as test_normal_case_2_percent_sl
        expected = 0.1
        assert quantity == pytest.approx(expected, rel=0.01)

    def test_high_leverage_20x(self, risk_manager):
        """Test with 20x leverage (max allowed)"""
        quantity = risk_manager.calculate_position_size(
            account_balance=10000, entry_price=50000, stop_loss_price=49000, leverage=20  # 2% SL
        )

        # Position size calculation independent of leverage
        # Leverage only affects max position size
        expected = 0.1
        assert quantity == pytest.approx(expected, rel=0.01)

    def test_logging_output(self, risk_manager, caplog):
        """Verify position size calculation is logged"""
        with caplog.at_level(logging.INFO):
            risk_manager.calculate_position_size(
                account_balance=10000, entry_price=50000, stop_loss_price=49000, leverage=10
            )

        # Check for calculation details in logs
        assert "Final position size" in caplog.text
        assert "risk=" in caplog.text
        assert "SL distance=" in caplog.text


class TestSignalValidation:
    """Test suite for subtask 7.2 - Signal validation"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskGuard"""
        config = {
            "max_risk_per_trade": 0.01,
            "max_leverage": 20,
            "default_leverage": 10,
            "max_position_size_percent": 0.1,
        }
        mock_audit_logger = MagicMock()
        return RiskGuard(config, audit_logger=mock_audit_logger)

    def test_valid_long_signal(self, risk_manager):
        """Valid LONG signal passes validation"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,  # Above entry ✅
            stop_loss=49000,  # Below entry ✅
            strategy_name="test",
            timestamp=datetime.now(),
        )
        assert risk_manager.validate_risk(signal, None) is True

    def test_valid_short_signal(self, risk_manager):
        """Valid SHORT signal passes validation"""
        signal = Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=49000,  # Below entry ✅
            stop_loss=51000,  # Above entry ✅
            strategy_name="test",
            timestamp=datetime.now(),
        )
        assert risk_manager.validate_risk(signal, None) is True

    def test_long_invalid_tp_below_entry(self, risk_manager, caplog):
        """LONG signal with TP ≤ entry is rejected"""
        # Bypass Signal.__post_init__ validation to test RiskGuard validation
        with patch.object(Signal, "__post_init__", lambda self: None):
            signal = Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000,
                take_profit=49000,  # Below entry ❌
                stop_loss=49500,  # Below entry (valid for SL)
                strategy_name="test",
                timestamp=datetime.now(),
            )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, None)

        assert result is False
        assert "LONG TP" in caplog.text
        assert "must be > entry" in caplog.text

    def test_long_invalid_sl_above_entry(self, risk_manager, caplog):
        """LONG signal with SL ≥ entry is rejected"""
        # Bypass Signal.__post_init__ validation to test RiskGuard validation
        with patch.object(Signal, "__post_init__", lambda self: None):
            signal = Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000,
                take_profit=51000,  # Above entry (valid for TP)
                stop_loss=50000,  # Equal to entry ❌
                strategy_name="test",
                timestamp=datetime.now(),
            )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, None)

        assert result is False
        assert "LONG SL" in caplog.text
        assert "must be < entry" in caplog.text

    def test_short_invalid_tp_above_entry(self, risk_manager, caplog):
        """SHORT signal with TP ≥ entry is rejected"""
        # Bypass Signal.__post_init__ validation to test RiskGuard validation
        with patch.object(Signal, "__post_init__", lambda self: None):
            signal = Signal(
                signal_type=SignalType.SHORT_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000,
                take_profit=51000,  # Above entry ❌
                stop_loss=51500,  # Above entry (valid for SL)
                strategy_name="test",
                timestamp=datetime.now(),
            )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, None)

        assert result is False
        assert "SHORT TP" in caplog.text
        assert "must be < entry" in caplog.text

    def test_short_invalid_sl_below_entry(self, risk_manager, caplog):
        """SHORT signal with SL ≤ entry is rejected"""
        # Bypass Signal.__post_init__ validation to test RiskGuard validation
        with patch.object(Signal, "__post_init__", lambda self: None):
            signal = Signal(
                signal_type=SignalType.SHORT_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000,
                take_profit=49000,  # Below entry (valid for TP)
                stop_loss=50000,  # Equal to entry ❌
                strategy_name="test",
                timestamp=datetime.now(),
            )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, None)

        assert result is False
        assert "SHORT SL" in caplog.text
        assert "must be > entry" in caplog.text

    def test_existing_position_rejection(self, risk_manager, caplog):
        """Signal rejected when position exists"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,
            stop_loss=49000,
            strategy_name="test",
            timestamp=datetime.now(),
        )
        position = Position(
            symbol="BTCUSDT", side="LONG", entry_price=50000, quantity=0.1, leverage=10
        )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, position)

        assert result is False
        assert "Signal rejected: existing position" in caplog.text
        assert "BTCUSDT" in caplog.text


class TestPositionSizeLimiting:
    """Test suite for subtask 7.3 - Position size limiting"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskGuard with 10% max position size"""
        config = {
            "max_risk_per_trade": 0.01,
            "max_leverage": 20,
            "default_leverage": 10,
            "max_position_size_percent": 0.1,  # 10% max
        }
        mock_audit_logger = MagicMock()
        return RiskGuard(config, audit_logger=mock_audit_logger)

    def test_within_limit_no_capping(self, risk_manager):
        """
        Position within limit is not capped

        Account: $10,000
        Max position: 10% × 10x = $10,000 / $50,000 = 0.2 BTC
        Calculated: 0.1 BTC < 0.2 BTC → not capped
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000, entry_price=50000, stop_loss_price=49000, leverage=10  # 2% SL
        )

        expected = 0.1  # Not capped
        assert quantity == pytest.approx(expected, rel=0.01)

    def test_tight_sl_exceeds_limit_capped(self, risk_manager, caplog):
        """
        Edge case: Tight SL creates large position that exceeds limit

        Risk-based: 2.0 BTC (from 0.1% tight SL)
        Max (10% × 10x): 0.2 BTC
        Result: 0.2 BTC (capped)
        """
        with caplog.at_level(logging.WARNING):
            quantity = risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=49950,  # 0.1% tight SL
                leverage=10,
            )

        max_quantity = 10000 * 0.1 * 10 / 50000  # 0.2 BTC
        assert quantity == pytest.approx(max_quantity, rel=0.01)
        assert "exceeds maximum" in caplog.text

    def test_leverage_scaling(self, risk_manager):
        """
        Max position scales with leverage

        10x leverage: max = 0.2 BTC
        20x leverage: max = 0.4 BTC (doubles)
        """
        # 10x leverage
        qty_10x = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49950,  # Tight SL to trigger limit
            leverage=10,
        )

        # 20x leverage
        qty_20x = risk_manager.calculate_position_size(
            account_balance=10000, entry_price=50000, stop_loss_price=49950, leverage=20
        )

        # 20x should allow 2x the position size
        assert qty_20x == pytest.approx(qty_10x * 2, rel=0.01)

    def test_custom_max_percentage(self):
        """Test with 20% max position size"""
        config = {
            "max_risk_per_trade": 0.01,
            "max_leverage": 20,
            "default_leverage": 10,
            "max_position_size_percent": 0.2,  # 20% max
        }
        mock_audit_logger = MagicMock()
        risk_manager = RiskGuard(config, audit_logger=mock_audit_logger)

        quantity = risk_manager.calculate_position_size(
            account_balance=10000, entry_price=50000, stop_loss_price=49950, leverage=10  # Tight SL
        )

        # Max: 20% × 10x = $20,000 / $50,000 = 0.4 BTC
        max_quantity = 10000 * 0.2 * 10 / 50000
        assert quantity == pytest.approx(max_quantity, rel=0.01)

    def test_warning_logged_when_capped(self, risk_manager, caplog):
        """Warning is logged when position exceeds limit"""
        with caplog.at_level(logging.WARNING):
            risk_manager.calculate_position_size(
                account_balance=10000, entry_price=50000, stop_loss_price=49950, leverage=10
            )

        assert "Position size" in caplog.text
        assert "exceeds maximum" in caplog.text
        assert "capping to" in caplog.text

    def test_max_allowed_in_log(self, risk_manager, caplog):
        """max_allowed value is included in final log"""
        with caplog.at_level(logging.INFO):
            risk_manager.calculate_position_size(
                account_balance=10000, entry_price=50000, stop_loss_price=49000, leverage=10
            )

        assert "max_allowed=" in caplog.text

    def test_integration_full_flow(self, risk_manager):
        """
        Integration test: Calculate → Limit → Verify

        Scenario: Tight SL triggers limiting
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49990,  # 0.02% tight SL
            leverage=10,
        )

        # Max position: 10% × 10x = 0.2 BTC
        max_quantity = 10000 * 0.1 * 10 / 50000
        assert quantity <= max_quantity
        assert quantity == pytest.approx(max_quantity, rel=0.01)


class TestSignalRiskRewardRatio:
    """Test suite for verifying Signal.risk_reward_ratio property (Task 7.3 discovery)"""

    def test_long_signal_rr_ratio(self):
        """LONG signal: TP=52000, Entry=50000, SL=49000 → R:R = 2:1"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=49000,  # 1,000 risk (below for LONG)
            take_profit=52000,  # 2,000 reward (above for LONG)
            strategy_name="test",
            timestamp=datetime.now(),
        )

        # Risk: 50000 - 49000 = 1,000
        # Reward: 52000 - 50000 = 2,000
        # R:R = 2,000 / 1,000 = 2.0
        assert signal.risk_reward_ratio == pytest.approx(2.0, rel=0.01)

    def test_short_signal_rr_ratio(self):
        """SHORT signal: Entry=50000, TP=48000, SL=51000 → R:R = 2:1"""
        signal = Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=51000,  # 1,000 risk (above for SHORT)
            take_profit=48000,  # 2,000 reward (below for SHORT)
            strategy_name="test",
            timestamp=datetime.now(),
        )

        assert signal.risk_reward_ratio == pytest.approx(2.0, rel=0.01)

    def test_1_to_1_rr_ratio(self):
        """1:1 risk-reward ratio"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=49000,  # 1,000 risk
            take_profit=51000,  # 1,000 reward
            strategy_name="test",
            timestamp=datetime.now(),
        )

        assert signal.risk_reward_ratio == pytest.approx(1.0, rel=0.01)

    def test_3_to_1_rr_ratio(self):
        """3:1 risk-reward ratio (aggressive TP)"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=49000,  # 1,000 risk
            take_profit=53000,  # 3,000 reward
            strategy_name="test",
            timestamp=datetime.now(),
        )

        assert signal.risk_reward_ratio == pytest.approx(3.0, rel=0.01)


class TestQuantityRounding:
    """Test suite for subtask 7.4 - Quantity rounding to Binance specifications"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskGuard with standard config"""
        config = {
            "max_risk_per_trade": 0.01,
            "max_leverage": 20,
            "default_leverage": 10,
            "max_position_size_percent": 0.1,
        }
        mock_audit_logger = MagicMock()
        return RiskGuard(config, audit_logger=mock_audit_logger)

    def test_standard_rounding_btcusdt(self, risk_manager):
        """Standard case: 1.2345 BTC with BTCUSDT specs → 1.234"""
        symbol_info = {"lot_size": 0.001, "quantity_precision": 3}
        result = risk_manager._round_to_lot_size(1.2345, symbol_info)
        assert result == pytest.approx(1.234, abs=1e-9)

    def test_lot_size_flooring(self, risk_manager):
        """Lot size flooring: 0.0567 with stepSize=0.01 → 0.05"""
        symbol_info = {"lot_size": 0.01, "quantity_precision": 2}
        result = risk_manager._round_to_lot_size(0.0567, symbol_info)
        assert result == pytest.approx(0.05, abs=1e-9)

    def test_precision_dominates(self, risk_manager):
        """Precision rounding: 0.0567 with fine lot_size → 0.056"""
        symbol_info = {"lot_size": 0.001, "quantity_precision": 3}
        result = risk_manager._round_to_lot_size(0.0567, symbol_info)
        assert result == pytest.approx(0.056, abs=1e-9)

    def test_no_upward_rounding(self, risk_manager):
        """1.9999 should NOT round up to 2.0, floors to 1.999"""
        symbol_info = {"lot_size": 0.001, "quantity_precision": 3}
        result = risk_manager._round_to_lot_size(1.9999, symbol_info)
        assert result == pytest.approx(1.999, abs=1e-9)

    def test_minimum_lot_size(self, risk_manager):
        """0.001 BTC (minimum) should remain 0.001"""
        symbol_info = {"lot_size": 0.001, "quantity_precision": 3}
        result = risk_manager._round_to_lot_size(0.001, symbol_info)
        assert result == pytest.approx(0.001, abs=1e-9)

    def test_missing_symbol_info_uses_defaults(self, risk_manager):
        """Missing symbol_info uses BTCUSDT defaults (0.001, 3)"""
        result = risk_manager._round_to_lot_size(1.2345, None)
        assert result == pytest.approx(1.234, abs=1e-9)

    def test_partial_symbol_info(self, risk_manager):
        """Partial symbol_info fills missing values with defaults"""
        # Only lot_size provided, precision defaults to 3
        symbol_info = {"lot_size": 0.01}
        result = risk_manager._round_to_lot_size(1.2345, symbol_info)
        assert result == pytest.approx(1.230, abs=1e-9)  # lot_size=0.01 dominates

    def test_integration_with_calculate_position_size(self, risk_manager):
        """Full integration: calculate → limit → round"""
        symbol_info = {"lot_size": 0.001, "quantity_precision": 3}

        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,  # 2% SL
            leverage=10,
            symbol_info=symbol_info,
        )

        # Verify quantity is Binance-compliant
        # 1. Check precision (exactly 3 decimals or less)
        decimal_part = str(quantity).split(".")[1] if "." in str(quantity) else ""
        assert len(decimal_part) <= 3

        # 2. Check lot_size compliance (multiple of 0.001)
        assert (quantity % 0.001) < 1e-9

    def test_ethusdt_specs(self, risk_manager):
        """Real-world: ETHUSDT (lot_size=0.001, precision=3)"""
        symbol_info = {"lot_size": 0.001, "quantity_precision": 3}
        result = risk_manager._round_to_lot_size(12.3456, symbol_info)
        assert result == pytest.approx(12.345, abs=1e-9)

    def test_bnbusdt_specs(self, risk_manager):
        """Real-world: BNBUSDT (lot_size=0.01, precision=2)"""
        symbol_info = {"lot_size": 0.01, "quantity_precision": 2}
        result = risk_manager._round_to_lot_size(49.876, symbol_info)
        assert result == pytest.approx(49.87, abs=1e-9)

    def test_no_symbol_info_legacy_rounding(self, risk_manager):
        """Legacy behavior: No symbol_info → round(qty, 3)"""
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10,
            symbol_info=None,  # No symbol info
        )

        # Should use default round(qty, 3)
        decimal_part = str(quantity).split(".")[1] if "." in str(quantity) else ""
        assert len(decimal_part) <= 3

    def test_debug_logging(self, risk_manager, caplog):
        """Verify rounding is logged at DEBUG level"""
        symbol_info = {"lot_size": 0.001, "quantity_precision": 3}

        with caplog.at_level(logging.DEBUG):
            risk_manager._round_to_lot_size(1.2345, symbol_info)

        assert "Quantity rounding" in caplog.text
        assert "lot_size=" in caplog.text
        assert "precision=" in caplog.text
