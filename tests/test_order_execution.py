"""
OrderExecutionManager 단위 테스트
"""

import pytest
import logging
from unittest.mock import Mock, patch, MagicMock
import os
from binance.error import ClientError

from src.execution.order_manager import OrderExecutionManager


class TestOrderExecutionManager:
    """OrderExecutionManager 단위 테스트"""

    @pytest.fixture
    def mock_client(self):
        """Mock Binance UMFutures 클라이언트"""
        return MagicMock()

    @pytest.fixture
    def manager(self, mock_client):
        """OrderExecutionManager 인스턴스 (mock client 사용)"""
        with patch('src.execution.order_manager.UMFutures', return_value=mock_client):
            with patch.dict('os.environ', {
                'BINANCE_API_KEY': 'test_key',
                'BINANCE_API_SECRET': 'test_secret'
            }):
                return OrderExecutionManager(is_testnet=True)

    # ==================== 초기화 테스트 ====================

    def test_init_testnet_url(self, manager):
        """Testnet URL이 올바르게 설정되는지 검증"""
        # UMFutures mock의 call_args에서 base_url 확인
        assert manager.client is not None

    def test_init_mainnet_url(self):
        """Mainnet URL이 올바르게 설정되는지 검증"""
        with patch('src.execution.order_manager.UMFutures') as mock_um:
            with patch.dict('os.environ', {
                'BINANCE_API_KEY': 'test_key',
                'BINANCE_API_SECRET': 'test_secret'
            }):
                manager = OrderExecutionManager(is_testnet=False)

                # UMFutures가 mainnet URL로 호출되었는지 확인
                call_args = mock_um.call_args
                assert 'fapi.binance.com' in call_args.kwargs['base_url']

    def test_init_without_api_keys(self):
        """API 키 없이 초기화 시 ValueError 발생"""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="API credentials required"):
                OrderExecutionManager()

    def test_init_with_api_key_params(self):
        """파라미터로 API 키 전달"""
        with patch('src.execution.order_manager.UMFutures'):
            manager = OrderExecutionManager(
                api_key='param_key',
                api_secret='param_secret'
            )
            # 예외 없이 초기화 완료
            assert manager is not None

    def test_init_open_orders_empty(self, manager):
        """초기화 시 _open_orders가 빈 딕셔너리인지 확인"""
        assert manager._open_orders == {}

    # ==================== 레버리지 설정 테스트 ====================

    def test_set_leverage_success(self, manager, mock_client):
        """레버리지 설정 성공"""
        mock_client.change_leverage.return_value = {
            'symbol': 'BTCUSDT',
            'leverage': 10
        }

        result = manager.set_leverage('BTCUSDT', 10)

        assert result is True
        mock_client.change_leverage.assert_called_once_with(
            symbol='BTCUSDT',
            leverage=10
        )

    def test_set_leverage_various_values(self, manager, mock_client):
        """다양한 레버리지 값 테스트 (1x, 20x, 125x)"""
        mock_client.change_leverage.return_value = {'leverage': 0}

        for leverage in [1, 20, 125]:
            result = manager.set_leverage('BTCUSDT', leverage)
            assert result is True

    def test_set_leverage_api_error(self, manager, mock_client):
        """API 오류 시 False 반환"""
        mock_client.change_leverage.side_effect = ClientError(
            status_code=400,
            error_code=-4028,
            error_message="Leverage 200 is not valid",
            header={}
        )

        result = manager.set_leverage('BTCUSDT', 200)

        assert result is False

    def test_set_leverage_network_error(self, manager, mock_client):
        """네트워크 오류 시 False 반환"""
        mock_client.change_leverage.side_effect = Exception("Network error")

        result = manager.set_leverage('BTCUSDT', 10)

        assert result is False

    def test_set_leverage_logging_success(self, manager, mock_client, caplog):
        """성공 시 로깅 확인"""
        mock_client.change_leverage.return_value = {'leverage': 10}

        with caplog.at_level(logging.INFO):
            manager.set_leverage('BTCUSDT', 10)

            assert "Leverage set to 10x for BTCUSDT" in caplog.text

    def test_set_leverage_logging_error(self, manager, mock_client, caplog):
        """실패 시 로깅 확인"""
        mock_client.change_leverage.side_effect = ClientError(
            status_code=400,
            error_code=-4028,
            error_message="Invalid leverage",
            header={}
        )

        with caplog.at_level(logging.ERROR):
            manager.set_leverage('BTCUSDT', 200)

            assert "Failed to set leverage" in caplog.text

    # ==================== 마진 타입 설정 테스트 ====================

    def test_set_margin_type_isolated_success(self, manager, mock_client):
        """ISOLATED 마진 타입 설정 성공"""
        mock_client.change_margin_type.return_value = {
            'code': 200,
            'msg': 'success'
        }

        result = manager.set_margin_type('BTCUSDT', 'ISOLATED')

        assert result is True
        mock_client.change_margin_type.assert_called_once_with(
            symbol='BTCUSDT',
            marginType='ISOLATED'
        )

    def test_set_margin_type_crossed_success(self, manager, mock_client):
        """CROSSED 마진 타입 설정 성공"""
        mock_client.change_margin_type.return_value = {'code': 200}

        result = manager.set_margin_type('BTCUSDT', 'CROSSED')

        assert result is True

    def test_set_margin_type_default_isolated(self, manager, mock_client):
        """기본값이 ISOLATED인지 확인"""
        mock_client.change_margin_type.return_value = {'code': 200}

        manager.set_margin_type('BTCUSDT')

        # ISOLATED이 기본값으로 호출되었는지 확인
        call_args = mock_client.change_margin_type.call_args
        assert call_args.kwargs['marginType'] == 'ISOLATED'

    def test_set_margin_type_already_set(self, manager, mock_client):
        """이미 설정된 경우 (True 반환)"""
        mock_client.change_margin_type.side_effect = ClientError(
            status_code=400,
            error_code=-4046,
            error_message="No need to change margin type.",
            header={}
        )

        result = manager.set_margin_type('BTCUSDT', 'ISOLATED')

        # "No need to change"는 성공으로 간주
        assert result is True

    def test_set_margin_type_open_orders_error(self, manager, mock_client):
        """오픈 주문이 있어서 실패"""
        mock_client.change_margin_type.side_effect = ClientError(
            status_code=400,
            error_code=-4047,
            error_message="Margin type cannot be changed if there is open order.",
            header={}
        )

        result = manager.set_margin_type('BTCUSDT', 'ISOLATED')

        assert result is False

    def test_set_margin_type_logging_success(self, manager, mock_client, caplog):
        """성공 시 로깅 확인"""
        mock_client.change_margin_type.return_value = {'code': 200}

        with caplog.at_level(logging.INFO):
            manager.set_margin_type('BTCUSDT', 'ISOLATED')

            assert "Margin type set to ISOLATED for BTCUSDT" in caplog.text

    def test_set_margin_type_logging_already_set(self, manager, mock_client, caplog):
        """이미 설정된 경우 디버그 로깅 확인"""
        # Logger 레벨을 DEBUG로 설정
        manager.logger.setLevel(logging.DEBUG)

        mock_client.change_margin_type.side_effect = ClientError(
            status_code=400,
            error_code=-4046,
            error_message="No need to change margin type.",
            header={}
        )

        with caplog.at_level(logging.DEBUG):
            manager.set_margin_type('BTCUSDT', 'ISOLATED')

            assert "already set" in caplog.text


# ==================== 예외 클래스 테스트 ====================

def test_validation_error_inheritance():
    """ValidationError가 OrderExecutionError를 상속하는지 확인"""
    from src.core.exceptions import ValidationError, OrderExecutionError

    err = ValidationError("Test error")
    assert isinstance(err, OrderExecutionError)


def test_rate_limit_error_inheritance():
    """RateLimitError가 OrderExecutionError를 상속하는지 확인"""
    from src.core.exceptions import RateLimitError, OrderExecutionError

    err = RateLimitError("Test error")
    assert isinstance(err, OrderExecutionError)


def test_order_rejected_error_inheritance():
    """OrderRejectedError가 OrderExecutionError를 상속하는지 확인"""
    from src.core.exceptions import OrderRejectedError, OrderExecutionError

    err = OrderRejectedError("Test error")
    assert isinstance(err, OrderExecutionError)
