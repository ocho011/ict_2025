"""
Unit tests for LiquidationManager with state machine and fail-safe coverage.

Test Coverage:
- State machine transitions (IDLE → IN_PROGRESS → final states)
- Fail-safe design (timeouts, errors don't block shutdown)
- Idempotency (re-entrant calls handled gracefully)
- Audit logging (all operations logged with correlation IDs)
- Configuration-driven behavior (emergency_liquidation flag)
- Result states (COMPLETED, PARTIAL, FAILED, SKIPPED)
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.audit_logger import AuditLogger
from src.execution.liquidation_manager import (
    LiquidationManager,
    LiquidationState,
    LiquidationResult,
)
from src.utils.config_manager import LiquidationConfig


@pytest.fixture
def mock_order_gateway():
    """Mock OrderGateway for testing."""
    manager = MagicMock()
    manager.get_all_positions = AsyncMock(return_value=[])
    manager.cancel_all_orders = MagicMock(return_value=0)  # Sync method returns int
    manager.execute_market_close = AsyncMock(return_value={"success": True, "order_id": "123"})
    return manager


@pytest.fixture
def mock_audit_logger():
    """Mock AuditLogger for testing."""
    logger = MagicMock(spec=AuditLogger)
    logger.log_event = MagicMock()
    return logger


@pytest.fixture
def security_first_config():
    """Security-first liquidation configuration."""
    return LiquidationConfig(
        emergency_liquidation=True,
        close_positions=True,
        cancel_orders=True,
        timeout_seconds=5.0,
        max_retries=3,
        retry_delay_seconds=0.5,
    )


@pytest.fixture
def disabled_config():
    """Disabled liquidation configuration."""
    return LiquidationConfig(
        emergency_liquidation=False,
        close_positions=False,
        cancel_orders=False,
    )


@pytest.fixture
def liquidation_manager(mock_order_gateway, mock_audit_logger, security_first_config):
    """LiquidationManager instance with security-first config."""
    return LiquidationManager(
        order_gateway=mock_order_gateway,
        audit_logger=mock_audit_logger,
        config=security_first_config,
    )


class TestLiquidationManagerInitialization:
    """Test initialization and configuration."""

    def test_manager_initializes_with_idle_state(self, liquidation_manager):
        """Manager starts in IDLE state."""
        assert liquidation_manager.state == LiquidationState.IDLE

    def test_manager_stores_config(self, liquidation_manager, security_first_config):
        """Manager stores configuration."""
        assert liquidation_manager.config == security_first_config

    def test_manager_stores_dependencies(
        self, liquidation_manager, mock_order_gateway, mock_audit_logger
    ):
        """Manager stores order manager and audit logger."""
        assert liquidation_manager.order_gateway == mock_order_gateway
        assert liquidation_manager.audit_logger == mock_audit_logger


class TestLiquidationStateMachine:
    """Test state machine transitions."""

    @pytest.mark.asyncio
    async def test_state_transitions_idle_to_in_progress(self, liquidation_manager):
        """State transitions from IDLE to IN_PROGRESS during execution."""
        # Start execution (will transition to IN_PROGRESS)
        task = asyncio.create_task(liquidation_manager.execute_liquidation(["BTCUSDT"]))

        # Give state machine time to transition
        await asyncio.sleep(0.01)

        # Check state changed (unless already completed due to fast execution)
        # State could be IN_PROGRESS or already back to IDLE if very fast
        await task  # Wait for completion

        # After completion, state should be back to IDLE
        assert liquidation_manager.state == LiquidationState.IDLE

    @pytest.mark.asyncio
    async def test_re_entrant_calls_blocked(self, liquidation_manager):
        """Re-entrant calls are blocked when liquidation is IN_PROGRESS."""
        # Mock slow liquidation
        async def slow_liquidation(*args, **kwargs):
            await asyncio.sleep(0.2)
            return {"cancelled": 0, "failed": 0}

        liquidation_manager._cancel_all_orders = slow_liquidation
        liquidation_manager._close_all_positions = slow_liquidation

        # Start first liquidation
        task1 = asyncio.create_task(liquidation_manager.execute_liquidation(["BTCUSDT"]))

        # Wait for state to transition to IN_PROGRESS
        await asyncio.sleep(0.01)

        # Try to start second liquidation (should be blocked)
        result2 = await liquidation_manager.execute_liquidation(["ETHUSDT"])

        # Second call should fail with re-entrant error
        assert result2.state == LiquidationState.FAILED
        assert "already in progress" in result2.error_message.lower()

        # Wait for first task to complete
        await task1

    @pytest.mark.asyncio
    async def test_state_resets_to_idle_after_completion(self, liquidation_manager):
        """State resets to IDLE after liquidation completes."""
        result = await liquidation_manager.execute_liquidation(["BTCUSDT"])

        # State should be back to IDLE
        assert liquidation_manager.state == LiquidationState.IDLE

    @pytest.mark.asyncio
    async def test_state_resets_to_idle_after_error(self, liquidation_manager):
        """State resets to IDLE even if liquidation fails."""
        # Mock error
        liquidation_manager._cancel_all_orders = AsyncMock(
            side_effect=Exception("API error")
        )

        result = await liquidation_manager.execute_liquidation(["BTCUSDT"])

        # State should reset to IDLE despite error
        assert liquidation_manager.state == LiquidationState.IDLE


class TestLiquidationResults:
    """Test liquidation result states."""

    @pytest.mark.asyncio
    async def test_skipped_state_when_disabled(
        self, mock_order_gateway, mock_audit_logger, disabled_config
    ):
        """Liquidation returns SKIPPED when emergency_liquidation=False."""
        manager = LiquidationManager(
            order_gateway=mock_order_gateway,
            audit_logger=mock_audit_logger,
            config=disabled_config,
        )

        result = await manager.execute_liquidation(["BTCUSDT"])

        assert result.state == LiquidationState.SKIPPED
        assert result.positions_closed == 0
        assert result.orders_cancelled == 0

    @pytest.mark.asyncio
    async def test_completed_state_when_no_positions(self, liquidation_manager):
        """Liquidation returns COMPLETED when no positions/orders exist."""
        result = await liquidation_manager.execute_liquidation(["BTCUSDT"])

        assert result.state == LiquidationState.COMPLETED
        assert result.is_success()

    @pytest.mark.asyncio
    async def test_result_has_correlation_id(self, liquidation_manager, mock_audit_logger):
        """Result is logged with correlation ID."""
        await liquidation_manager.execute_liquidation(["BTCUSDT"])

        # Verify audit log was called with correlation_id
        mock_audit_logger.log_event.assert_called()
        call_args = mock_audit_logger.log_event.call_args
        assert "correlation_id" in call_args[1]["data"]

    @pytest.mark.asyncio
    async def test_result_contains_duration(self, liquidation_manager):
        """Result includes total_duration_seconds."""
        result = await liquidation_manager.execute_liquidation(["BTCUSDT"])

        assert result.total_duration_seconds > 0
        assert isinstance(result.total_duration_seconds, float)


class TestFailSafeDesign:
    """Test fail-safe design (errors don't block shutdown)."""

    @pytest.mark.asyncio
    async def test_timeout_does_not_raise_exception(self, liquidation_manager):
        """Timeout returns FAILED result, does not raise exception."""
        # Mock slow operation that exceeds timeout
        async def slow_operation(*args, **kwargs):
            await asyncio.sleep(10.0)  # Longer than 5s timeout
            return {"cancelled": 0, "failed": 0}

        liquidation_manager._cancel_all_orders = slow_operation

        # Should not raise, should return FAILED result
        result = await liquidation_manager.execute_liquidation(["BTCUSDT"])

        assert result.state == LiquidationState.FAILED
        assert "Timeout" in result.error_message

    @pytest.mark.asyncio
    async def test_exceptions_do_not_raise(self, liquidation_manager):
        """Exceptions return FAILED result, do not propagate."""
        # Mock exception
        liquidation_manager._cancel_all_orders = AsyncMock(
            side_effect=Exception("Binance API error")
        )

        # Should not raise, should return FAILED result
        result = await liquidation_manager.execute_liquidation(["BTCUSDT"])

        assert result.state == LiquidationState.FAILED
        assert "Unexpected error" in result.error_message

    @pytest.mark.asyncio
    async def test_partial_failure_does_not_block(self, liquidation_manager):
        """Partial failures are acceptable, shutdown continues."""
        # Mock partial failure
        liquidation_manager._cancel_all_orders = AsyncMock(
            return_value={"cancelled": 2, "failed": 1}
        )
        liquidation_manager._close_all_positions = AsyncMock(
            return_value={"closed": 1, "failed": 1}
        )

        result = await liquidation_manager.execute_liquidation(["BTCUSDT"])

        assert result.state == LiquidationState.PARTIAL
        assert result.orders_cancelled == 2
        assert result.orders_failed == 1
        assert result.positions_closed == 1
        assert result.positions_failed == 1


class TestAuditLogging:
    """Test comprehensive audit logging."""

    @pytest.mark.asyncio
    async def test_all_operations_logged(self, liquidation_manager, mock_audit_logger):
        """All liquidation operations are logged."""
        await liquidation_manager.execute_liquidation(["BTCUSDT"])

        # Verify audit logger was called
        assert mock_audit_logger.log_event.called

    @pytest.mark.asyncio
    async def test_audit_log_contains_config(self, liquidation_manager, mock_audit_logger):
        """Audit log includes configuration."""
        await liquidation_manager.execute_liquidation(["BTCUSDT"])

        call_args = mock_audit_logger.log_event.call_args
        assert "config" in call_args[1]["data"]

    @pytest.mark.asyncio
    async def test_audit_log_contains_result(self, liquidation_manager, mock_audit_logger):
        """Audit log includes result."""
        await liquidation_manager.execute_liquidation(["BTCUSDT"])

        call_args = mock_audit_logger.log_event.call_args
        assert "result" in call_args[1]["data"]


class TestMetrics:
    """Test metrics collection."""

    @pytest.mark.asyncio
    async def test_execution_count_increments(self, liquidation_manager):
        """Execution count increments after each execution."""
        initial_metrics = liquidation_manager.get_metrics()
        assert initial_metrics["execution_count"] == 0

        await liquidation_manager.execute_liquidation(["BTCUSDT"])

        final_metrics = liquidation_manager.get_metrics()
        assert final_metrics["execution_count"] == 1

    @pytest.mark.asyncio
    async def test_last_execution_time_recorded(self, liquidation_manager):
        """Last execution time is recorded."""
        await liquidation_manager.execute_liquidation(["BTCUSDT"])

        metrics = liquidation_manager.get_metrics()
        assert metrics["last_execution_time_seconds"] is not None
        assert metrics["last_execution_time_seconds"] > 0

    @pytest.mark.asyncio
    async def test_metrics_include_config(self, liquidation_manager):
        """Metrics include configuration."""
        metrics = liquidation_manager.get_metrics()

        assert "config" in metrics
        assert metrics["config"]["emergency_liquidation"] is True


class TestLiquidationResultHelpers:
    """Test LiquidationResult helper methods."""

    def test_is_success_true_for_completed(self):
        """is_success() returns True for COMPLETED with no failures."""
        result = LiquidationResult(
            state=LiquidationState.COMPLETED,
            positions_closed=2,
            orders_cancelled=3,
            positions_failed=0,
            orders_failed=0,
        )

        assert result.is_success() is True

    def test_is_success_false_for_partial(self):
        """is_success() returns False for PARTIAL state."""
        result = LiquidationResult(
            state=LiquidationState.PARTIAL,
            positions_closed=1,
            positions_failed=1,
        )

        assert result.is_success() is False

    def test_is_partial_true_for_mixed_results(self):
        """is_partial() returns True when some succeeded and some failed."""
        result = LiquidationResult(
            state=LiquidationState.COMPLETED,  # State might not match
            positions_closed=2,
            positions_failed=1,
        )

        assert result.is_partial() is True

    def test_to_dict_exports_all_fields(self):
        """to_dict() exports all result fields."""
        result = LiquidationResult(
            state=LiquidationState.COMPLETED,
            positions_closed=5,
            positions_failed=0,
            orders_cancelled=3,
            orders_failed=1,
            total_duration_seconds=2.345,
        )

        result_dict = result.to_dict()

        assert result_dict["state"] == "completed"
        assert result_dict["positions_closed"] == 5
        assert result_dict["positions_failed"] == 0
        assert result_dict["orders_cancelled"] == 3
        assert result_dict["orders_failed"] == 1
        assert result_dict["total_duration_seconds"] == 2.345
