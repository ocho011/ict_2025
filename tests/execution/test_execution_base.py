"""Tests for execution layer ABC hierarchy."""

import pytest

from src.execution.base import ExecutionGateway, ExchangeProvider, PositionProvider
from src.execution.order_gateway import OrderGateway
from src.core.position_cache_manager import PositionCacheManager
from src.execution.mock_exchange import MockExchange


class TestABCHierarchy:
    """Verify ABC inheritance relationships."""

    def test_order_gateway_is_execution_gateway(self):
        """OrderGateway should be a subclass of ExecutionGateway."""
        assert issubclass(OrderGateway, ExecutionGateway)

    def test_order_gateway_is_exchange_provider(self):
        """OrderGateway should be a subclass of ExchangeProvider."""
        assert issubclass(OrderGateway, ExchangeProvider)

    def test_position_cache_manager_is_position_provider(self):
        """PositionCacheManager should be a subclass of PositionProvider."""
        assert issubclass(PositionCacheManager, PositionProvider)

    def test_mock_exchange_is_execution_gateway(self):
        """MockExchange should be a subclass of ExecutionGateway."""
        assert issubclass(MockExchange, ExecutionGateway)

    def test_mock_exchange_is_exchange_provider(self):
        """MockExchange should be a subclass of ExchangeProvider."""
        assert issubclass(MockExchange, ExchangeProvider)

    def test_mock_exchange_is_position_provider(self):
        """MockExchange should be a subclass of PositionProvider."""
        assert issubclass(MockExchange, PositionProvider)

    def test_mock_exchange_instance_checks(self):
        """MockExchange instances should pass isinstance checks for all ABCs."""
        mock = MockExchange()
        assert isinstance(mock, ExecutionGateway)
        assert isinstance(mock, ExchangeProvider)
        assert isinstance(mock, PositionProvider)
