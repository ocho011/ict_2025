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
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49950,  # 0.1% SL
            leverage=10
        )

        # Tight SL = larger position for same risk
        assert quantity == pytest.approx(2.0, rel=0.01)

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
        - Warning logged
        - Use 0.001 (0.1%) minimum SL distance
        - Quantity calculated based on 0.1% SL
        """
        with caplog.at_level(logging.WARNING):
            quantity = risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=50000,  # Same as entry!
                leverage=10
            )

        # Should use 0.1% minimum SL
        # Position Value: 100 / 0.001 = 100,000 USDT
        # Quantity: 100,000 / 50000 = 2.0 BTC
        assert quantity == pytest.approx(2.0, rel=0.01)

        # Check warning was logged
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
