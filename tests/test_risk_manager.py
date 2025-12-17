"""
Unit tests for RiskManager - Subtask 7.1 & 7.2
"""

import pytest
import logging
from datetime import datetime
from src.risk.manager import RiskManager
from src.models.signal import Signal, SignalType
from src.models.position import Position


class TestPositionSizeCalculation:
    """Test suite for subtask 7.1 - Position size calculation"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskManager with standard config"""
        config = {
            'max_risk_per_trade': 0.01,  # 1%
            'max_leverage': 20,
            'default_leverage': 10,
            'max_position_size_percent': 0.1  # 10%
        }
        return RiskManager(config)

    def test_normal_case_2_percent_sl(self, risk_manager):
        """
        Normal case: 1% risk with 2% SL distance

        Expected:
        - Risk: 10000 * 0.01 = 100 USDT
        - SL Distance: (50000-49000)/50000 = 2%
        - Position Value: 100 / 0.02 = 5000 USDT
        - Quantity: 5000 / 50000 = 0.1 BTC
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10
        )

        assert quantity == pytest.approx(0.1, rel=0.01)

    def test_tight_sl_0_1_percent(self, risk_manager):
        """
        Edge case: Very tight SL (0.1%)

        Expected:
        - Risk: 100 USDT
        - SL Distance: 0.1% (tight)
        - Position Value: 100 / 0.001 = 100,000 USDT
        - Quantity: 100,000 / 50000 = 2.0 BTC (large!)
        - But capped to max: 0.2 BTC (10% × 10x leverage)
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49950,  # 0.1% SL
            leverage=10
        )

        # Tight SL would give 2.0 BTC, but capped to max 0.2 BTC
        assert quantity == pytest.approx(0.2, rel=0.01)

    def test_wide_sl_10_percent(self, risk_manager):
        """
        Edge case: Wide SL (10%)

        Expected:
        - Risk: 100 USDT
        - SL Distance: 10%
        - Position Value: 100 / 0.10 = 1000 USDT
        - Quantity: 1000 / 50000 = 0.02 BTC (small)
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=45000,  # 10% SL
            leverage=10
        )

        # Wide SL = smaller position
        assert quantity == pytest.approx(0.02, rel=0.01)

    def test_zero_sl_distance_uses_minimum(self, risk_manager, caplog):
        """
        Edge case: Zero SL distance (entry == stop_loss)

        Expected:
        - Warning logged for zero SL
        - Use 0.001 (0.1%) minimum SL distance
        - Quantity calculated based on 0.1% SL would be 2.0 BTC
        - But capped to max: 0.2 BTC (10% × 10x leverage)
        """
        with caplog.at_level(logging.WARNING):
            quantity = risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=50000,  # Same as entry!
                leverage=10
            )

        # Should use 0.1% minimum SL, giving 2.0 BTC
        # But capped to max 0.2 BTC
        assert quantity == pytest.approx(0.2, rel=0.01)

        # Check warnings were logged (both zero SL and position limiting)
        assert "Zero SL distance" in caplog.text
        assert "0.1%" in caplog.text

    def test_logging_outputs_correct_values(self, risk_manager, caplog):
        """Verify logging includes risk amount and SL distance"""
        with caplog.at_level(logging.INFO):
            quantity = risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=49000,
                leverage=10
            )

        # Check log message contains expected values
        assert "Position size calculated" in caplog.text
        assert "risk=100.00 USDT" in caplog.text
        # Check for SL distance (format may vary: 2.00% or 0.02)
        assert any(x in caplog.text for x in ["2.00%", "2%", "0.02"])

    def test_invalid_account_balance_zero(self, risk_manager):
        """Should raise ValueError for zero balance"""
        with pytest.raises(ValueError, match="Account balance must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=0,  # Invalid
                entry_price=50000,
                stop_loss_price=49000,
                leverage=10
            )

    def test_invalid_account_balance_negative(self, risk_manager):
        """Should raise ValueError for negative balance"""
        with pytest.raises(ValueError, match="Account balance must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=-1000,  # Invalid
                entry_price=50000,
                stop_loss_price=49000,
                leverage=10
            )

    def test_invalid_entry_price_zero(self, risk_manager):
        """Should raise ValueError for zero entry price"""
        with pytest.raises(ValueError, match="Entry price must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=0,  # Invalid
                stop_loss_price=49000,
                leverage=10
            )

    def test_invalid_entry_price_negative(self, risk_manager):
        """Should raise ValueError for negative entry price"""
        with pytest.raises(ValueError, match="Entry price must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=-50000,  # Invalid
                stop_loss_price=49000,
                leverage=10
            )

    def test_invalid_stop_loss_price(self, risk_manager):
        """Should raise ValueError for invalid stop loss price"""
        with pytest.raises(ValueError, match="Stop loss price must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=-49000,  # Invalid
                leverage=10
            )

    def test_invalid_leverage_too_low(self, risk_manager):
        """Should raise ValueError for leverage < 1"""
        with pytest.raises(ValueError, match="Leverage must be between"):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=49000,
                leverage=0  # Too low
            )

    def test_invalid_leverage_too_high(self, risk_manager):
        """Should raise ValueError for leverage > max_leverage"""
        with pytest.raises(ValueError, match="Leverage must be between"):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=49000,
                leverage=200  # Exceeds max_leverage=20
            )

    def test_different_account_balances(self, risk_manager):
        """Test with various account balances"""
        # 5000 USDT balance
        quantity_5k = risk_manager.calculate_position_size(
            account_balance=5000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10
        )
        # Risk: 5000 * 0.01 = 50 USDT
        # Position Value: 50 / 0.02 = 2500 USDT
        # Quantity: 2500 / 50000 = 0.05 BTC
        assert quantity_5k == pytest.approx(0.05, rel=0.01)

        # 20000 USDT balance
        quantity_20k = risk_manager.calculate_position_size(
            account_balance=20000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10
        )
        # Risk: 20000 * 0.01 = 200 USDT
        # Position Value: 200 / 0.02 = 10000 USDT
        # Quantity: 10000 / 50000 = 0.2 BTC
        assert quantity_20k == pytest.approx(0.2, rel=0.01)

    def test_different_risk_percentages(self):
        """Test with various risk percentages"""
        # 2% risk
        manager_2pct = RiskManager({'max_risk_per_trade': 0.02})
        quantity_2pct = manager_2pct.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10
        )
        # Risk: 10000 * 0.02 = 200 USDT
        # Position Value: 200 / 0.02 = 10000 USDT
        # Quantity: 10000 / 50000 = 0.2 BTC
        assert quantity_2pct == pytest.approx(0.2, rel=0.01)

        # 0.5% risk (very conservative)
        manager_0_5pct = RiskManager({'max_risk_per_trade': 0.005})
        quantity_0_5pct = manager_0_5pct.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10
        )
        # Risk: 10000 * 0.005 = 50 USDT
        # Position Value: 50 / 0.02 = 2500 USDT
        # Quantity: 2500 / 50000 = 0.05 BTC
        assert quantity_0_5pct == pytest.approx(0.05, rel=0.01)

    def test_short_position_sl_above_entry(self, risk_manager):
        """
        Test SHORT position (SL above entry)

        For SHORT: entry=50000, SL=51000 (2% above)
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=51000,  # SL above entry (SHORT)
            leverage=10
        )

        # SL Distance: |50000 - 51000| / 50000 = 2%
        # Risk: 100 USDT
        # Position Value: 100 / 0.02 = 5000 USDT
        # Quantity: 5000 / 50000 = 0.1 BTC
        assert quantity == pytest.approx(0.1, rel=0.01)

    def test_config_defaults(self):
        """Test that config defaults are applied correctly"""
        # Empty config should use defaults
        manager = RiskManager({})

        assert manager.max_risk_per_trade == 0.01  # 1% default
        assert manager.max_leverage == 20  # Default
        assert manager.default_leverage == 10  # Default
        assert manager.max_position_size_percent == 0.1  # 10% default

    def test_symbol_info_parameter_accepted(self, risk_manager):
        """Test that symbol_info parameter is accepted (even if not used yet)"""
        # Should not raise error even with symbol_info provided
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10,
            symbol_info={'lot_size': 0.001, 'precision': 3}  # Not used yet
        )

        assert quantity == pytest.approx(0.1, rel=0.01)


class TestSignalValidation:
    """Test suite for subtask 7.2 - Signal validation"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskManager with standard config"""
        config = {
            'max_risk_per_trade': 0.01,
            'max_leverage': 20,
            'default_leverage': 10,
            'max_position_size_percent': 0.1
        }
        return RiskManager(config)

    def test_valid_long_signal_passes(self, risk_manager):
        """
        Valid LONG signal with correct TP/SL passes validation

        LONG requirements:
        - TP > entry_price
        - SL < entry_price
        """
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,  # Above entry ✅
            stop_loss=49000,    # Below entry ✅
            strategy_name="test_strategy",
            timestamp=datetime.now()
        )

        result = risk_manager.validate_risk(signal, position=None)
        assert result is True

    def test_valid_short_signal_passes(self, risk_manager):
        """
        Valid SHORT signal with correct TP/SL passes validation

        SHORT requirements:
        - TP < entry_price
        - SL > entry_price
        """
        signal = Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=49000,  # Below entry ✅
            stop_loss=51000,    # Above entry ✅
            strategy_name="test_strategy",
            timestamp=datetime.now()
        )

        result = risk_manager.validate_risk(signal, position=None)
        assert result is True

    def test_long_signal_invalid_tp_rejected(self, risk_manager, caplog):
        """
        LONG signal with TP <= entry is rejected

        Note: Signal.__post_init__ validates this, so we can't create
        an invalid Signal directly. This tests the RiskManager layer.
        """
        # Create a valid signal first
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,
            stop_loss=49000,
            strategy_name="test_strategy",
            timestamp=datetime.now()
        )

        # Manually override TP to invalid value (for testing purposes)
        # In real scenario, Signal validation would catch this first
        object.__setattr__(signal, 'take_profit', 49000)  # Invalid: TP <= entry

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, position=None)

        assert result is False
        assert "LONG TP" in caplog.text
        assert "must be > entry" in caplog.text

    def test_long_signal_invalid_sl_rejected(self, risk_manager, caplog):
        """
        LONG signal with SL >= entry is rejected
        """
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,
            stop_loss=49000,
            strategy_name="test_strategy",
            timestamp=datetime.now()
        )

        # Manually override SL to invalid value
        object.__setattr__(signal, 'stop_loss', 51000)  # Invalid: SL >= entry

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, position=None)

        assert result is False
        assert "LONG SL" in caplog.text
        assert "must be < entry" in caplog.text

    def test_short_signal_invalid_tp_rejected(self, risk_manager, caplog):
        """
        SHORT signal with TP >= entry is rejected
        """
        signal = Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=49000,
            stop_loss=51000,
            strategy_name="test_strategy",
            timestamp=datetime.now()
        )

        # Manually override TP to invalid value
        object.__setattr__(signal, 'take_profit', 51000)  # Invalid: TP >= entry

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, position=None)

        assert result is False
        assert "SHORT TP" in caplog.text
        assert "must be < entry" in caplog.text

    def test_short_signal_invalid_sl_rejected(self, risk_manager, caplog):
        """
        SHORT signal with SL <= entry is rejected
        """
        signal = Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=49000,
            stop_loss=51000,
            strategy_name="test_strategy",
            timestamp=datetime.now()
        )

        # Manually override SL to invalid value
        object.__setattr__(signal, 'stop_loss', 49000)  # Invalid: SL <= entry

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, position=None)

        assert result is False
        assert "SHORT SL" in caplog.text
        assert "must be > entry" in caplog.text

    def test_signal_rejected_when_position_exists(self, risk_manager, caplog):
        """
        Signal rejected when position already exists (no concurrent positions)
        """
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,
            stop_loss=49000,
            strategy_name="test_strategy",
            timestamp=datetime.now()
        )

        # Create existing position
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000,
            quantity=0.1,
            leverage=10
        )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, position)

        assert result is False
        assert "Signal rejected: existing position" in caplog.text
        assert "BTCUSDT" in caplog.text
        assert "LONG" in caplog.text

    def test_warning_logs_contain_specific_values(self, risk_manager, caplog):
        """
        Verify warning logs contain specific rejection reasons and values
        """
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,
            stop_loss=49000,
            strategy_name="test_strategy",
            timestamp=datetime.now()
        )

        # Test with invalid TP
        object.__setattr__(signal, 'take_profit', 49000)

        with caplog.at_level(logging.WARNING):
            risk_manager.validate_risk(signal, position=None)

        # Check log contains actual values
        assert "49000" in caplog.text  # Invalid TP value
        assert "50000" in caplog.text  # Entry price value


class TestPositionSizeLimiting:
    """Test suite for subtask 7.3 - Position size limiting"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskManager with standard config"""
        config = {
            'max_risk_per_trade': 0.01,
            'max_leverage': 20,
            'default_leverage': 10,
            'max_position_size_percent': 0.1  # 10%
        }
        return RiskManager(config)

    def test_position_within_limit_not_capped(self, risk_manager):
        """
        Normal case: Position size within limit is not capped

        Risk-based: 0.1 BTC
        Max (10% × 10x): 0.2 BTC
        Result: 0.1 BTC (not limited)
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,  # 2% SL
            leverage=10
        )

        # Should not be limited
        assert quantity == pytest.approx(0.1, rel=0.01)

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
                leverage=10
            )

        # Should be capped to max
        max_quantity = 10000 * 0.1 * 10 / 50000  # 0.2 BTC
        assert quantity == pytest.approx(max_quantity, rel=0.01)

        # Check warning logged
        assert "exceeds maximum" in caplog.text
        assert "capping to" in caplog.text

    def test_high_leverage_increases_max_limit(self, risk_manager):
        """
        Max position size scales with leverage

        Leverage 10x: Max = 0.2 BTC
        Leverage 20x: Max = 0.4 BTC
        """
        # Calculate max with different leverages
        max_10x = 10000 * 0.1 * 10 / 50000  # 0.2 BTC
        max_20x = 10000 * 0.1 * 20 / 50000  # 0.4 BTC

        # Verify scaling
        assert max_20x == pytest.approx(2 * max_10x, rel=0.01)

        # Test with tight SL to trigger both limits
        quantity_10x = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49950,  # Tight SL
            leverage=10
        )

        quantity_20x = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49950,  # Same tight SL
            leverage=20
        )

        # 20x should allow 2x larger position
        assert quantity_20x == pytest.approx(2 * quantity_10x, rel=0.01)

    def test_custom_max_position_percent(self):
        """
        Custom max_position_size_percent is respected

        5% max instead of 10%
        """
        manager = RiskManager({
            'max_risk_per_trade': 0.01,
            'max_position_size_percent': 0.05  # 5%
        })

        quantity = manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49500,  # 1% SL to potentially trigger limit
            leverage=10
        )

        # Max with 5%: 10000 * 0.05 * 10 / 50000 = 0.1 BTC
        max_quantity = 0.1
        assert quantity <= max_quantity

    def test_warning_contains_specific_values(self, risk_manager, caplog):
        """
        Warning log contains actual calculated and max values
        """
        with caplog.at_level(logging.WARNING):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=49950,  # 0.1% tight SL
                leverage=10
            )

        # Check log contains specific values
        assert "0.2" in caplog.text  # Max quantity
        assert "10.0%" in caplog.text or "10%" in caplog.text  # Percentage
        assert "10x" in caplog.text  # Leverage

    def test_integration_full_calculation_with_limiting(self, risk_manager):
        """
        Integration test: Full position calculation with limiting

        Verifies entire flow from input to limited output
        """
        # Scenario: Very tight SL (0.05%) should trigger limit
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49975,  # 0.05% SL
            leverage=10
        )

        # Max allowed: 0.2 BTC
        max_quantity = 0.2

        # Should be capped
        assert quantity == pytest.approx(max_quantity, rel=0.01)

        # Should be less than uncapped calculation
        # Risk-based would give: 100 / 0.0005 / 50000 = 4.0 BTC
        assert quantity < 4.0

    def test_max_position_respects_leverage_parameter(self, risk_manager):
        """
        Max position calculation uses the provided leverage parameter
        """
        # Test with leverage 5x
        quantity_5x = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49950,  # Tight SL to trigger limit
            leverage=5
        )

        # Test with leverage 15x
        quantity_15x = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49950,  # Same tight SL
            leverage=15
        )

        # 15x leverage should allow 3x larger position than 5x
        assert quantity_15x == pytest.approx(3 * quantity_5x, rel=0.01)


class TestSignalRiskRewardRatio:
    """Test suite for Signal.risk_reward_ratio property (verification)"""

    def test_risk_reward_ratio_1_to_2(self):
        """
        R:R ratio 1:2 correctly calculated

        Entry: 50,000
        SL: 49,000 (1,000 risk)
        TP: 52,000 (2,000 reward)
        R:R: 2,000 / 1,000 = 2.0
        """
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=49000,  # 1,000 risk
            take_profit=52000,  # 2,000 reward
            strategy_name="test",
            timestamp=datetime.now()
        )

        assert signal.risk_reward_ratio == pytest.approx(2.0, rel=0.01)

    def test_risk_reward_ratio_1_to_1(self):
        """
        R:R ratio 1:1 correctly calculated

        Entry: 50,000
        SL: 49,000 (1,000 risk)
        TP: 51,000 (1,000 reward)
        R:R: 1,000 / 1,000 = 1.0
        """
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=49000,  # 1,000 risk
            take_profit=51000,  # 1,000 reward
            strategy_name="test",
            timestamp=datetime.now()
        )

        assert signal.risk_reward_ratio == pytest.approx(1.0, rel=0.01)

    def test_risk_reward_ratio_1_to_3(self):
        """
        R:R ratio 1:3 correctly calculated (attractive ratio)

        Entry: 50,000
        SL: 49,000 (1,000 risk)
        TP: 53,000 (3,000 reward)
        R:R: 3,000 / 1,000 = 3.0
        """
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=49000,  # 1,000 risk
            take_profit=53000,  # 3,000 reward
            strategy_name="test",
            timestamp=datetime.now()
        )

        assert signal.risk_reward_ratio == pytest.approx(3.0, rel=0.01)

    def test_risk_reward_ratio_for_short_signal(self):
        """
        R:R ratio works for SHORT signals

        Entry: 50,000
        SL: 51,000 (1,000 risk - above entry for SHORT)
        TP: 48,000 (2,000 reward - below entry for SHORT)
        R:R: 2,000 / 1,000 = 2.0
        """
        signal = Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=51000,  # 1,000 risk (above for SHORT)
            take_profit=48000,  # 2,000 reward (below for SHORT)
            strategy_name="test",
            timestamp=datetime.now()
        )

        assert signal.risk_reward_ratio == pytest.approx(2.0, rel=0.01)
