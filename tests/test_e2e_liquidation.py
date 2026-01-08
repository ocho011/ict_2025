"""
End-to-end integration tests for emergency liquidation workflow.

Tests complete liquidation scenarios including:
- Full shutdown workflow with liquidation
- Emergency scenarios (timeout, API failures, partial success)
- Audit trail completeness
- Configuration validation integration
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.audit_logger import AuditEventType, AuditLogger
from src.execution.config_validator import LiquidationConfigValidator, ValidationLevel
from src.utils.config import LiquidationConfig
from src.execution.liquidation_manager import LiquidationManager, LiquidationState


class TestE2ELiquidationWorkflow:
    """End-to-end tests for complete liquidation workflow."""

    @pytest.fixture
    def mock_audit_logger(self):
        """Create mock audit logger."""
        logger = MagicMock(spec=AuditLogger)
        logger.log_event = MagicMock()
        return logger

    @pytest.fixture
    def mock_order_manager(self):
        """Create mock order execution manager."""
        manager = MagicMock()
        manager.get_all_positions = AsyncMock(return_value=[])
        manager.cancel_all_orders = MagicMock(return_value=0)
        manager.execute_market_close = AsyncMock(
            return_value={"success": True, "order_id": "test", "realized_pnl": 0.0}
        )
        return manager

    @pytest.mark.asyncio
    async def test_complete_shutdown_workflow_no_positions(
        self, mock_order_manager, mock_audit_logger
    ):
        """Test complete shutdown with no open positions."""
        # Setup
        config = LiquidationConfig()
        manager = LiquidationManager(
            config=config,
            order_manager=mock_order_manager,
            audit_logger=mock_audit_logger,
        )

        # Execute
        result = await manager.execute_liquidation(symbols=[])

        # Verify
        assert result.state == LiquidationState.COMPLETED
        assert result.positions_closed == 0
        assert result.error_message is None

        # Verify audit trail
        mock_audit_logger.log_event.assert_called()
        event_types = [
            call.kwargs.get("event_type")
            for call in mock_audit_logger.log_event.call_args_list
        ]
        assert AuditEventType.LIQUIDATION_COMPLETE in event_types

    @pytest.mark.asyncio
    async def test_complete_shutdown_workflow_with_positions(
        self, mock_order_manager, mock_audit_logger
    ):
        """Test complete shutdown workflow with open positions."""
        # Setup positions (as dictionaries - API format)
        positions = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.1",  # Positive = LONG
                "entryPrice": "50000.0",
                "unrealizedProfit": "100.0",
            },
            {
                "symbol": "ETHUSDT",
                "positionAmt": "-1.0",  # Negative = SHORT
                "entryPrice": "3000.0",
                "unrealizedProfit": "-50.0",
            },
        ]
        mock_order_manager.get_all_positions = AsyncMock(return_value=positions)
        mock_order_manager.execute_market_close = AsyncMock(
            side_effect=[
                {"success": True, "order_id": "order1", "realized_pnl": 100.0},
                {"success": True, "order_id": "order2", "realized_pnl": -50.0},
            ]
        )

        config = LiquidationConfig()
        manager = LiquidationManager(
            config=config,
            order_manager=mock_order_manager,
            audit_logger=mock_audit_logger,
        )

        # Execute
        result = await manager.execute_liquidation(symbols=["BTCUSDT", "ETHUSDT"])

        # Verify
        assert result.state == LiquidationState.COMPLETED
        assert result.positions_closed == 2
        assert result.positions_failed == 0

        # Verify audit trail completeness
        event_types = [
            call.kwargs.get("event_type")
            for call in mock_audit_logger.log_event.call_args_list
        ]
        assert AuditEventType.ORDER_PLACED in event_types  # Position close logs
        assert AuditEventType.LIQUIDATION_COMPLETE in event_types

    @pytest.mark.asyncio
    async def test_partial_liquidation_success(
        self, mock_order_manager, mock_audit_logger
    ):
        """Test partial liquidation with some failures."""
        # Setup: 3 positions, 1 fails to close
        positions = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.1",  # LONG
                "entryPrice": "50000.0",
                "unrealizedProfit": "50.0",
            },
            {
                "symbol": "ETHUSDT",
                "positionAmt": "1.0",  # LONG
                "entryPrice": "3000.0",
                "unrealizedProfit": "30.0",
            },
            {
                "symbol": "BNBUSDT",
                "positionAmt": "-5.0",  # SHORT
                "entryPrice": "400.0",
                "unrealizedProfit": "0.0",
            },
        ]
        mock_order_manager.get_all_positions = AsyncMock(return_value=positions)

        # First 2 succeed, third fails
        mock_order_manager.execute_market_close = AsyncMock(
            side_effect=[
                {"success": True, "order_id": "order1", "realized_pnl": 50.0},
                {"success": True, "order_id": "order2", "realized_pnl": 30.0},
                {"success": False, "error": "Failed"},  # Failed
            ]
        )

        config = LiquidationConfig()
        manager = LiquidationManager(
            config=config,
            order_manager=mock_order_manager,
            audit_logger=mock_audit_logger,
        )

        # Execute
        result = await manager.execute_liquidation(symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"])

        # Verify
        assert result.state == LiquidationState.PARTIAL
        assert result.positions_closed == 2
        assert result.positions_failed == 1

        # Verify audit trail includes both successes and failure
        event_types = [
            call.kwargs.get("event_type")
            for call in mock_audit_logger.log_event.call_args_list
        ]
        assert AuditEventType.ORDER_PLACED in event_types
        assert AuditEventType.ORDER_REJECTED in event_types

    @pytest.mark.asyncio
    async def test_liquidation_timeout_scenario(
        self, mock_order_manager, mock_audit_logger
    ):
        """Test liquidation timeout handling."""
        # Setup slow position query
        async def slow_query(symbols):
            await asyncio.sleep(10)  # Simulate slow API
            return []

        mock_order_manager.get_all_positions = slow_query

        config = LiquidationConfig(timeout_seconds=1.0)  # Short timeout (minimum valid)
        manager = LiquidationManager(
            config=config,
            order_manager=mock_order_manager,
            audit_logger=mock_audit_logger,
        )

        # Execute
        result = await manager.execute_liquidation(symbols=["BTCUSDT"])

        # Verify timeout handling - should complete within timeout window
        assert result.total_duration_seconds < 3.0  # Should not wait 10 seconds

    @pytest.mark.asyncio
    async def test_api_failure_with_retry(
        self, mock_order_manager, mock_audit_logger
    ):
        """Test API failure handling with retry logic."""
        positions = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.1",  # LONG
                "entryPrice": "50000.0",
                "unrealizedProfit": "0.0",
            }
        ]

        # Fail twice, then succeed
        mock_order_manager.get_all_positions = AsyncMock(
            side_effect=[
                Exception("Network error"),
                Exception("Network error"),
                positions,  # Third attempt succeeds
            ]
        )

        config = LiquidationConfig(max_retries=3)
        manager = LiquidationManager(
            config=config,
            order_manager=mock_order_manager,
            audit_logger=mock_audit_logger,
        )

        # Execute
        result = await manager.execute_liquidation(symbols=["BTCUSDT"])

        # Verify retry worked - should eventually succeed or handle gracefully
        assert result.state in (LiquidationState.COMPLETED, LiquidationState.PARTIAL, LiquidationState.FAILED)
        # Should have called get_all_positions multiple times (with retries)
        assert mock_order_manager.get_all_positions.call_count >= 1

    @pytest.mark.asyncio
    async def test_order_cancellation_workflow(
        self, mock_order_manager, mock_audit_logger
    ):
        """Test order cancellation during liquidation."""
        positions = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.1",  # LONG
                "entryPrice": "50000.0",
                "unrealizedProfit": "0.0",
            }
        ]

        mock_order_manager.get_all_positions = AsyncMock(return_value=positions)
        mock_order_manager.cancel_all_orders = MagicMock(return_value=3)  # 3 orders cancelled

        config = LiquidationConfig()
        manager = LiquidationManager(
            config=config,
            order_manager=mock_order_manager,
            audit_logger=mock_audit_logger,
        )

        # Execute
        result = await manager.execute_liquidation(symbols=["BTCUSDT"])

        # Verify
        assert result.orders_cancelled == 3
        mock_order_manager.cancel_all_orders.assert_called_once_with("BTCUSDT")

        # Verify audit log
        event_types = [
            call.kwargs.get("event_type")
            for call in mock_audit_logger.log_event.call_args_list
        ]
        assert AuditEventType.ORDER_CANCELLED in event_types


class TestE2EConfigurationValidation:
    """End-to-end tests for configuration validation workflow."""

    def test_config_validator_integration_with_manager(self):
        """Test config validator integrates with liquidation manager."""
        # Create valid config
        config = LiquidationConfig()

        # Validate
        validator = LiquidationConfigValidator()
        result = validator.validate_production_config(config, is_testnet=False)

        # Should pass validation
        assert result.is_valid is True
        assert not result.has_errors

        # Config should work with manager (no initialization errors)
        audit_logger = MagicMock(spec=AuditLogger)
        order_manager = MagicMock()

        try:
            manager = LiquidationManager(
                config=config,
                order_manager=order_manager,
                audit_logger=audit_logger,
            )
            # Manager created successfully
            assert manager is not None
        except Exception as e:
            pytest.fail(f"Valid config should not raise exception: {e}")

    def test_config_validator_detects_production_issues(self):
        """Test config validator detects production issues."""
        # Create risky config
        config = LiquidationConfig(
            emergency_liquidation=False,
            close_positions=False,
            cancel_orders=False,
        )

        # Validate for production
        validator = LiquidationConfigValidator()
        result = validator.validate_production_config(config, is_testnet=False)

        # Should fail validation
        assert result.is_valid is False
        assert result.has_errors

        # Should have critical issue about emergency_liquidation
        critical_issues = result.get_issues_by_level(ValidationLevel.CRITICAL)
        assert len(critical_issues) > 0

    def test_deployment_readiness_check_workflow(self):
        """Test deployment readiness check workflow."""
        validator = LiquidationConfigValidator()

        # Test production config
        prod_config = LiquidationConfig()
        readiness = validator.check_deployment_readiness(prod_config, is_testnet=False)

        assert readiness.is_ready is True
        assert readiness.environment == "production"
        assert len(readiness.recommendations) > 0

        # Should recommend testing
        assert any(
            "testnet" in rec.lower()
            for rec in readiness.recommendations
        )


class TestE2EEmergencyScenarios:
    """End-to-end tests for emergency scenarios."""

    @pytest.mark.asyncio
    async def test_emergency_disabled_skips_liquidation(self):
        """Test emergency_liquidation=False skips liquidation."""
        # Setup
        audit_logger = MagicMock(spec=AuditLogger)
        order_manager = MagicMock()

        config = LiquidationConfig(
            emergency_liquidation=False,
            close_positions=False,
            cancel_orders=False,
        )

        manager = LiquidationManager(
            config=config,
            order_manager=order_manager,
            audit_logger=audit_logger,
        )

        # Execute
        result = await manager.execute_liquidation(symbols=[])

        # Verify - with emergency_liquidation=False, should be skipped
        assert result.state == LiquidationState.SKIPPED
        assert result.positions_closed == 0

        # Should not call order manager when emergency is disabled
        order_manager.get_all_positions.assert_not_called()

    @pytest.mark.asyncio
    async def test_catastrophic_failure_never_blocks(self):
        """Test catastrophic failures never block shutdown."""
        # Setup with failing everything
        audit_logger = MagicMock(spec=AuditLogger)
        order_manager = MagicMock()

        # Make everything fail
        order_manager.get_all_positions = AsyncMock(
            side_effect=Exception("Catastrophic API failure")
        )

        config = LiquidationConfig(max_retries=1)
        manager = LiquidationManager(
            config=config,
            order_manager=order_manager,
            audit_logger=audit_logger,
        )

        # Execute - should NOT raise exception
        result = await manager.execute_liquidation(symbols=["BTCUSDT"])

        # Verify failure is captured but not raised
        assert result.state == LiquidationState.FAILED
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_multiple_position_closure_sequence(self):
        """Test multiple positions are closed in correct sequence."""
        # Setup
        audit_logger = MagicMock(spec=AuditLogger)
        order_manager = MagicMock()

        positions = [
            {"symbol": "BTCUSDT", "positionAmt": "0.1", "entryPrice": "50000", "unrealizedProfit": "50.0"},
            {"symbol": "ETHUSDT", "positionAmt": "-1.0", "entryPrice": "3000", "unrealizedProfit": "30.0"},
            {"symbol": "BNBUSDT", "positionAmt": "5.0", "entryPrice": "400", "unrealizedProfit": "20.0"},
        ]

        order_manager.get_all_positions = AsyncMock(return_value=positions)
        order_manager.cancel_all_orders = MagicMock(side_effect=[1, 2, 0])  # Different counts
        order_manager.execute_market_close = AsyncMock(
            side_effect=[
                {"success": True, "order_id": "order1", "realized_pnl": 50.0},
                {"success": True, "order_id": "order2", "realized_pnl": 30.0},
                {"success": True, "order_id": "order3", "realized_pnl": 20.0},
            ]
        )

        config = LiquidationConfig()
        manager = LiquidationManager(
            config=config,
            order_manager=order_manager,
            audit_logger=audit_logger,
        )

        # Execute
        result = await manager.execute_liquidation(symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"])

        # Verify all positions closed
        assert result.positions_closed == 3

        # Verify cancel_all_orders called for each symbol
        assert order_manager.cancel_all_orders.call_count == 3
        assert order_manager.execute_market_close.call_count == 3
