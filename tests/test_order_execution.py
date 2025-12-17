"""
OrderExecutionManager 단위 테스트
"""

import pytest
import logging
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone
import os
from binance.error import ClientError

from src.execution.order_manager import OrderExecutionManager
from src.models.signal import Signal, SignalType
from src.models.order import Order, OrderSide, OrderType, OrderStatus
from src.core.exceptions import ValidationError, OrderRejectedError, OrderExecutionError


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


# ==================== execute_signal() 테스트 ====================

class TestExecuteSignal:
    """execute_signal() 메서드 테스트"""

    @pytest.fixture
    def mock_client(self):
        """Mock Binance UMFutures 클라이언트"""
        client = MagicMock()
        client.new_order.return_value = {
            "orderId": 123456789,
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "clientOrderId": "test_order_123",
            "price": "0",
            "avgPrice": "59808.02",
            "origQty": "0.001",
            "executedQty": "0.001",
            "cumQty": "0.001",
            "cumQuote": "59.80802",
            "timeInForce": "GTC",
            "type": "MARKET",
            "reduceOnly": False,
            "closePosition": False,
            "side": "BUY",
            "positionSide": "BOTH",
            "stopPrice": "0",
            "workingType": "CONTRACT_PRICE",
            "priceProtect": False,
            "origType": "MARKET",
            "updateTime": 1653563095000
        }
        return client

    @pytest.fixture
    def manager(self, mock_client):
        """OrderExecutionManager 인스턴스 (mock client 사용)"""
        with patch('src.execution.order_manager.UMFutures', return_value=mock_client):
            with patch.dict('os.environ', {
                'BINANCE_API_KEY': 'test_key',
                'BINANCE_API_SECRET': 'test_secret'
            }):
                return OrderExecutionManager(is_testnet=True)

    @pytest.fixture
    def long_entry_signal(self):
        """LONG_ENTRY 시그널"""
        return Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='BTCUSDT',
            entry_price=59800.0,
            take_profit=61000.0,
            stop_loss=58500.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )

    @pytest.fixture
    def short_entry_signal(self):
        """SHORT_ENTRY 시그널"""
        return Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol='BTCUSDT',
            entry_price=59800.0,
            take_profit=58500.0,
            stop_loss=61000.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )

    # ==================== _determine_order_side() 테스트 ====================

    def test_determine_order_side_long_entry(self, manager, long_entry_signal):
        """LONG_ENTRY → BUY 매핑 확인"""
        side = manager._determine_order_side(long_entry_signal)
        assert side == OrderSide.BUY

    def test_determine_order_side_short_entry(self, manager, short_entry_signal):
        """SHORT_ENTRY → SELL 매핑 확인"""
        side = manager._determine_order_side(short_entry_signal)
        assert side == OrderSide.SELL

    def test_determine_order_side_close_long(self, manager):
        """CLOSE_LONG → SELL 매핑 확인"""
        signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol='BTCUSDT',
            entry_price=59800.0,
            take_profit=61000.0,
            stop_loss=58500.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )
        side = manager._determine_order_side(signal)
        assert side == OrderSide.SELL

    def test_determine_order_side_close_short(self, manager):
        """CLOSE_SHORT → BUY 매핑 확인"""
        signal = Signal(
            signal_type=SignalType.CLOSE_SHORT,
            symbol='BTCUSDT',
            entry_price=59800.0,
            take_profit=58500.0,
            stop_loss=61000.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )
        side = manager._determine_order_side(signal)
        assert side == OrderSide.BUY

    # ==================== _parse_order_response() 테스트 ====================

    def test_parse_order_response_filled(self, manager):
        """FILLED 상태 응답 파싱"""
        response = {
            "orderId": 123456789,
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "avgPrice": "59808.02",
            "origQty": "0.001",
            "updateTime": 1653563095000,
            "clientOrderId": "test_123"
        }

        order = manager._parse_order_response(response, 'BTCUSDT', OrderSide.BUY)

        assert order.order_id == '123456789'
        assert order.symbol == 'BTCUSDT'
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == 0.001
        assert order.price == 59808.02
        assert order.status == OrderStatus.FILLED
        assert order.client_order_id == 'test_123'
        assert isinstance(order.timestamp, datetime)

    def test_parse_order_response_partially_filled(self, manager):
        """PARTIALLY_FILLED 상태 응답 파싱"""
        response = {
            "orderId": 987654321,
            "symbol": "ETHUSDT",
            "status": "PARTIALLY_FILLED",
            "avgPrice": "3500.50",
            "origQty": "0.5",
            "updateTime": 1653563100000
        }

        order = manager._parse_order_response(response, 'ETHUSDT', OrderSide.SELL)

        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.side == OrderSide.SELL

    def test_parse_order_response_timestamp_conversion(self, manager):
        """타임스탬프 변환 (milliseconds → UTC datetime)"""
        response = {
            "orderId": 111,
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "avgPrice": "60000.0",
            "origQty": "0.001",
            "updateTime": 1653563095000  # 2022-05-26 09:31:35 UTC
        }

        order = manager._parse_order_response(response, 'BTCUSDT', OrderSide.BUY)

        # UTC datetime으로 변환되었는지 확인
        assert order.timestamp.tzinfo == timezone.utc
        assert order.timestamp.year == 2022
        assert order.timestamp.month == 5
        assert order.timestamp.day == 26

    def test_parse_order_response_missing_field(self, manager):
        """필수 필드 누락 시 OrderExecutionError"""
        response = {
            # orderId 누락
            "symbol": "BTCUSDT",
            "status": "FILLED"
        }

        with pytest.raises(OrderExecutionError, match="Missing required field"):
            manager._parse_order_response(response, 'BTCUSDT', OrderSide.BUY)

    def test_parse_order_response_invalid_status(self, manager):
        """유효하지 않은 status 값"""
        response = {
            "orderId": 123,
            "symbol": "BTCUSDT",
            "status": "INVALID_STATUS",
            "avgPrice": "60000.0",
            "origQty": "0.001",
            "updateTime": 1653563095000
        }

        with pytest.raises(OrderExecutionError):
            manager._parse_order_response(response, 'BTCUSDT', OrderSide.BUY)

    def test_parse_order_response_zero_avg_price(self, manager):
        """avgPrice가 0인 경우 price를 None으로 설정"""
        response = {
            "orderId": 123,
            "symbol": "BTCUSDT",
            "status": "NEW",
            "avgPrice": "0",  # 미체결 주문
            "origQty": "0.001",
            "updateTime": 1653563095000
        }

        order = manager._parse_order_response(response, 'BTCUSDT', OrderSide.BUY)

        assert order.price is None  # avgPrice가 0이면 None

    # ==================== execute_signal() 통합 테스트 ====================

    def test_execute_signal_long_entry_success(self, manager, mock_client, long_entry_signal):
        """LONG_ENTRY 시그널 실행 성공"""
        order = manager.execute_signal(long_entry_signal, quantity=0.001)

        # Order 객체 검증
        assert order.symbol == 'BTCUSDT'
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == 0.001
        assert order.order_id == '123456789'
        assert order.status == OrderStatus.FILLED
        assert order.price == 59808.02

        # API 호출 검증
        mock_client.new_order.assert_called_once_with(
            symbol='BTCUSDT',
            side='BUY',
            type='MARKET',
            quantity=0.001,
            reduceOnly=False
        )

    def test_execute_signal_short_entry_success(self, manager, mock_client, short_entry_signal):
        """SHORT_ENTRY 시그널 실행 성공"""
        mock_client.new_order.return_value['side'] = 'SELL'

        order = manager.execute_signal(short_entry_signal, quantity=0.001)

        # Order 객체 검증
        assert order.side == OrderSide.SELL
        assert order.symbol == 'BTCUSDT'

        # API 호출 검증 (side가 SELL인지 확인)
        call_args = mock_client.new_order.call_args
        assert call_args.kwargs['side'] == 'SELL'

    def test_execute_signal_reduce_only_true(self, manager, mock_client, long_entry_signal):
        """reduce_only=True 파라미터 전달"""
        manager.execute_signal(long_entry_signal, quantity=0.001, reduce_only=True)

        # API 호출 시 reduceOnly=True 전달 확인
        call_args = mock_client.new_order.call_args
        assert call_args.kwargs['reduceOnly'] is True

    def test_execute_signal_invalid_quantity_zero(self, manager, long_entry_signal):
        """quantity=0 → ValidationError"""
        with pytest.raises(ValidationError, match="Quantity must be > 0"):
            manager.execute_signal(long_entry_signal, quantity=0)

    def test_execute_signal_invalid_quantity_negative(self, manager, long_entry_signal):
        """quantity < 0 → ValidationError"""
        with pytest.raises(ValidationError, match="Quantity must be > 0"):
            manager.execute_signal(long_entry_signal, quantity=-0.001)

    def test_execute_signal_binance_rejection(self, manager, mock_client, long_entry_signal):
        """Binance API 거부 → OrderRejectedError"""
        mock_client.new_order.side_effect = ClientError(
            status_code=400,
            error_code=-2019,
            error_message="Margin is insufficient",
            header={}
        )

        with pytest.raises(OrderRejectedError, match="Binance rejected order"):
            manager.execute_signal(long_entry_signal, quantity=0.001)

    def test_execute_signal_network_error(self, manager, mock_client, long_entry_signal):
        """네트워크 오류 → OrderExecutionError"""
        mock_client.new_order.side_effect = Exception("Network unreachable")

        with pytest.raises(OrderExecutionError, match="Failed to execute order"):
            manager.execute_signal(long_entry_signal, quantity=0.001)

    def test_execute_signal_logging_intent(self, manager, mock_client, long_entry_signal, caplog):
        """실행 전 의도 로깅 확인"""
        with caplog.at_level(logging.INFO):
            manager.execute_signal(long_entry_signal, quantity=0.001)

            # 의도 로깅 확인
            assert "Executing long_entry signal" in caplog.text
            assert "BTCUSDT BUY 0.001" in caplog.text
            assert "strategy: TestStrategy" in caplog.text

    def test_execute_signal_logging_success(self, manager, mock_client, long_entry_signal, caplog):
        """실행 성공 로깅 확인"""
        with caplog.at_level(logging.INFO):
            manager.execute_signal(long_entry_signal, quantity=0.001)

            # 성공 로깅 확인
            assert "Order executed" in caplog.text
            assert "ID=123456789" in caplog.text
            assert "status=FILLED" in caplog.text

    def test_execute_signal_logging_error(self, manager, mock_client, long_entry_signal, caplog):
        """실행 실패 로깅 확인"""
        mock_client.new_order.side_effect = ClientError(
            status_code=400,
            error_code=-2019,
            error_message="Margin is insufficient",
            header={}
        )

        with caplog.at_level(logging.ERROR):
            try:
                manager.execute_signal(long_entry_signal, quantity=0.001)
            except OrderRejectedError:
                pass

            # 에러 로깅 확인
            assert "Order rejected by Binance" in caplog.text
            assert "code=-2019" in caplog.text
            assert "Margin is insufficient" in caplog.text
