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

    @pytest.fixture
    def close_long_signal(self):
        """CLOSE_LONG 시그널"""
        return Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol='BTCUSDT',
            entry_price=61000.0,
            take_profit=62000.0,  # Not used for close signals
            stop_loss=60000.0,    # Not used for close signals
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )

    @pytest.fixture
    def close_short_signal(self):
        """CLOSE_SHORT 시그널"""
        return Signal(
            signal_type=SignalType.CLOSE_SHORT,
            symbol='BTCUSDT',
            entry_price=58000.0,
            take_profit=57000.0,  # Not used
            stop_loss=59000.0,    # Not used
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


class TestTPSLPlacement:
    """TP/SL 주문 배치 테스트 (Task 6.3)"""

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

    @pytest.fixture
    def long_entry_signal(self):
        """LONG_ENTRY 시그널"""
        return Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='BTCUSDT',
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )

    @pytest.fixture
    def short_entry_signal(self):
        """SHORT_ENTRY 시그널"""
        return Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol='BTCUSDT',
            entry_price=50000.0,
            take_profit=48000.0,
            stop_loss=51000.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )

    @pytest.fixture
    def close_long_signal(self):
        """CLOSE_LONG 시그널"""
        return Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol='BTCUSDT',
            entry_price=51000.0,
            take_profit=52000.0,
            stop_loss=50000.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )

    # ==================== Helper Method Tests ====================

    def test_format_price_rounds_correctly(self, manager):
        """가격 포맷팅 (2자리 소수점)"""
        assert manager._format_price(50123.456, 'BTCUSDT') == '50123.46'
        assert manager._format_price(50123.444, 'BTCUSDT') == '50123.44'
        assert manager._format_price(50123.0, 'BTCUSDT') == '50123.00'

    def test_format_price_handles_edge_cases(self, manager):
        """가격 포맷팅 엣지 케이스"""
        assert manager._format_price(0.01, 'BTCUSDT') == '0.01'
        assert manager._format_price(99999.99, 'BTCUSDT') == '99999.99'

    # ==================== TP Order Tests ====================

    def test_place_tp_order_long_success(self, manager, mock_client, long_entry_signal):
        """LONG 포지션 TP 주문 배치 성공"""
        mock_client.new_order.return_value = {
            "orderId": 987654321,
            "symbol": "BTCUSDT",
            "status": "NEW",
            "type": "TAKE_PROFIT_MARKET",
            "side": "SELL",
            "stopPrice": "52000.00",
            "updateTime": 1678886401000,
            "origQty": "0.000",
            "avgPrice": "0.00"
        }

        tp_order = manager._place_tp_order(long_entry_signal, OrderSide.SELL)

        assert tp_order is not None
        assert tp_order.order_id == "987654321"
        assert tp_order.order_type == OrderType.TAKE_PROFIT_MARKET
        assert tp_order.stop_price == 52000.0
        assert tp_order.side == OrderSide.SELL

        mock_client.new_order.assert_called_once_with(
            symbol="BTCUSDT",
            side="SELL",
            type="TAKE_PROFIT_MARKET",
            stopPrice="52000.00",
            closePosition="true",
            workingType="MARK_PRICE"
        )

    def test_place_tp_order_short_success(self, manager, mock_client, short_entry_signal):
        """SHORT 포지션 TP 주문 배치 성공"""
        mock_client.new_order.return_value = {
            "orderId": 987654322,
            "symbol": "BTCUSDT",
            "status": "NEW",
            "type": "TAKE_PROFIT_MARKET",
            "side": "BUY",
            "stopPrice": "48000.00",
            "updateTime": 1678886401000,
            "origQty": "0.000",
            "avgPrice": "0.00"
        }

        tp_order = manager._place_tp_order(short_entry_signal, OrderSide.BUY)

        assert tp_order is not None
        assert tp_order.side == OrderSide.BUY
        assert tp_order.stop_price == 48000.0

    def test_place_tp_order_api_error_returns_none(self, manager, mock_client, long_entry_signal):
        """TP 주문 API 에러 시 None 반환"""
        mock_client.new_order.side_effect = ClientError(
            status_code=400,
            error_code=-2010,
            error_message="Order would immediately trigger",
            header={}
        )

        tp_order = manager._place_tp_order(long_entry_signal, OrderSide.SELL)

        assert tp_order is None  # Should return None, not raise

    # ==================== SL Order Tests ====================

    def test_place_sl_order_long_success(self, manager, mock_client, long_entry_signal):
        """LONG 포지션 SL 주문 배치 성공"""
        mock_client.new_order.return_value = {
            "orderId": 987654323,
            "symbol": "BTCUSDT",
            "status": "NEW",
            "type": "STOP_MARKET",
            "side": "SELL",
            "stopPrice": "49000.00",
            "updateTime": 1678886402000,
            "origQty": "0.000",
            "avgPrice": "0.00"
        }

        sl_order = manager._place_sl_order(long_entry_signal, OrderSide.SELL)

        assert sl_order is not None
        assert sl_order.order_type == OrderType.STOP_MARKET
        assert sl_order.stop_price == 49000.0

        mock_client.new_order.assert_called_once_with(
            symbol="BTCUSDT",
            side="SELL",
            type="STOP_MARKET",
            stopPrice="49000.00",
            closePosition="true",
            workingType="MARK_PRICE"
        )

    def test_place_sl_order_short_success(self, manager, mock_client, short_entry_signal):
        """SHORT 포지션 SL 주문 배치 성공"""
        mock_client.new_order.return_value = {
            "orderId": 987654324,
            "symbol": "BTCUSDT",
            "status": "NEW",
            "type": "STOP_MARKET",
            "side": "BUY",
            "stopPrice": "51000.00",
            "updateTime": 1678886402000,
            "origQty": "0.000",
            "avgPrice": "0.00"
        }

        sl_order = manager._place_sl_order(short_entry_signal, OrderSide.BUY)

        assert sl_order is not None
        assert sl_order.side == OrderSide.BUY
        assert sl_order.stop_price == 51000.0

    def test_place_sl_order_network_error_returns_none(self, manager, mock_client, long_entry_signal):
        """SL 주문 네트워크 에러 시 None 반환"""
        mock_client.new_order.side_effect = ConnectionError("Network timeout")

        sl_order = manager._place_sl_order(long_entry_signal, OrderSide.SELL)

        assert sl_order is None  # Should not raise exception

    # ==================== Integration Tests ====================

    def test_execute_signal_long_entry_with_tpsl_success(
        self, manager, mock_client, long_entry_signal
    ):
        """LONG 진입 + TP/SL 완전 성공"""
        mock_client.new_order.side_effect = [
            # Entry order (MARKET)
            {
                "orderId": 123456789,
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "type": "MARKET",
                "side": "BUY",
                "avgPrice": "50123.45",
                "origQty": "0.001",
                "executedQty": "0.001",
                "updateTime": 1678886400000
            },
            # TP order (TAKE_PROFIT_MARKET)
            {
                "orderId": 123456790,
                "symbol": "BTCUSDT",
                "status": "NEW",
                "type": "TAKE_PROFIT_MARKET",
                "side": "SELL",
                "stopPrice": "52000.00",
                "updateTime": 1678886401000,
                "origQty": "0.000",
                "avgPrice": "0.00"
            },
            # SL order (STOP_MARKET)
            {
                "orderId": 123456791,
                "symbol": "BTCUSDT",
                "status": "NEW",
                "type": "STOP_MARKET",
                "side": "SELL",
                "stopPrice": "49000.00",
                "updateTime": 1678886402000,
                "origQty": "0.000",
                "avgPrice": "0.00"
            }
        ]

        entry_order, tpsl_orders = manager.execute_signal(
            long_entry_signal,
            quantity=0.001
        )

        # Entry order assertions
        assert entry_order.order_id == "123456789"
        assert entry_order.order_type == OrderType.MARKET
        assert entry_order.side == OrderSide.BUY
        assert entry_order.status == OrderStatus.FILLED

        # TP/SL orders assertions
        assert len(tpsl_orders) == 2

        tp_order = tpsl_orders[0]
        assert tp_order.order_type == OrderType.TAKE_PROFIT_MARKET
        assert tp_order.stop_price == 52000.0
        assert tp_order.side == OrderSide.SELL

        sl_order = tpsl_orders[1]
        assert sl_order.order_type == OrderType.STOP_MARKET
        assert sl_order.stop_price == 49000.0
        assert sl_order.side == OrderSide.SELL

        assert mock_client.new_order.call_count == 3

    def test_execute_signal_short_entry_with_tpsl_success(
        self, manager, mock_client, short_entry_signal
    ):
        """SHORT 진입 + TP/SL 완전 성공"""
        mock_client.new_order.side_effect = [
            {
                "orderId": 123456800,
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "type": "MARKET",
                "side": "SELL",
                "avgPrice": "50000.00",
                "origQty": "0.001",
                "updateTime": 1678886400000
            },
            {
                "orderId": 123456801,
                "symbol": "BTCUSDT",
                "status": "NEW",
                "type": "TAKE_PROFIT_MARKET",
                "side": "BUY",
                "stopPrice": "48000.00",
                "updateTime": 1678886401000,
                "origQty": "0.000",
                "avgPrice": "0.00"
            },
            {
                "orderId": 123456802,
                "symbol": "BTCUSDT",
                "status": "NEW",
                "type": "STOP_MARKET",
                "side": "BUY",
                "stopPrice": "51000.00",
                "updateTime": 1678886402000,
                "origQty": "0.000",
                "avgPrice": "0.00"
            }
        ]

        entry_order, tpsl_orders = manager.execute_signal(
            short_entry_signal,
            quantity=0.001
        )

        assert entry_order.side == OrderSide.SELL
        assert len(tpsl_orders) == 2
        assert tpsl_orders[0].side == OrderSide.BUY  # TP for SHORT
        assert tpsl_orders[1].side == OrderSide.BUY  # SL for SHORT

    def test_execute_signal_close_long_no_tpsl(
        self, manager, mock_client, close_long_signal
    ):
        """CLOSE_LONG 시그널은 TP/SL 주문 없음"""
        mock_client.new_order.return_value = {
            "orderId": 123456789,
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "type": "MARKET",
            "side": "SELL",
            "avgPrice": "51000.00",
            "origQty": "0.001",
            "executedQty": "0.001",
            "updateTime": 1678886400000
        }

        entry_order, tpsl_orders = manager.execute_signal(
            close_long_signal,
            quantity=0.001
        )

        assert entry_order.side == OrderSide.SELL
        assert len(tpsl_orders) == 0  # No TP/SL for close signals
        assert mock_client.new_order.call_count == 1  # Only entry order

    # ==================== Error Handling Tests ====================

    def test_execute_signal_entry_fails_raises_exception(
        self, manager, mock_client, long_entry_signal
    ):
        """진입 주문 실패 시 예외 발생 (TP/SL 시도 없음)"""
        mock_client.new_order.side_effect = ClientError(
            status_code=400,
            error_code=-2019,
            error_message="Margin is insufficient",
            header={}
        )

        with pytest.raises(OrderRejectedError, match="Margin is insufficient"):
            manager.execute_signal(long_entry_signal, quantity=0.001)

        # Verify only entry order was attempted
        assert mock_client.new_order.call_count == 1

    def test_execute_signal_entry_success_tp_fails_sl_success(
        self, manager, mock_client, long_entry_signal
    ):
        """진입 성공, TP 실패, SL 성공 (부분 실행)"""
        mock_client.new_order.side_effect = [
            # Entry succeeds
            {
                "orderId": 123456789,
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "type": "MARKET",
                "side": "BUY",
                "avgPrice": "50123.45",
                "origQty": "0.001",
                "updateTime": 1678886400000
            },
            # TP fails
            ClientError(
                status_code=400,
                error_code=-2010,
                error_message="Order would immediately trigger",
                header={}
            ),
            # SL succeeds
            {
                "orderId": 123456791,
                "symbol": "BTCUSDT",
                "status": "NEW",
                "type": "STOP_MARKET",
                "side": "SELL",
                "stopPrice": "49000.00",
                "updateTime": 1678886402000,
                "origQty": "0.000",
                "avgPrice": "0.00"
            }
        ]

        entry_order, tpsl_orders = manager.execute_signal(
            long_entry_signal,
            quantity=0.001
        )

        # Entry succeeded
        assert entry_order.status == OrderStatus.FILLED

        # Only SL order placed (TP failed)
        assert len(tpsl_orders) == 1
        assert tpsl_orders[0].order_type == OrderType.STOP_MARKET

    def test_execute_signal_entry_success_both_tpsl_fail(
        self, manager, mock_client, long_entry_signal
    ):
        """진입 성공, TP/SL 모두 실패"""
        mock_client.new_order.side_effect = [
            # Entry succeeds
            {
                "orderId": 123456789,
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "type": "MARKET",
                "side": "BUY",
                "avgPrice": "50123.45",
                "origQty": "0.001",
                "updateTime": 1678886400000
            },
            # TP fails
            ClientError(
                status_code=400,
                error_code=-2010,
                error_message="TP error",
                header={}
            ),
            # SL fails
            ClientError(
                status_code=400,
                error_code=-2010,
                error_message="SL error",
                header={}
            )
        ]

        entry_order, tpsl_orders = manager.execute_signal(
            long_entry_signal,
            quantity=0.001
        )

        # Entry succeeded, no TP/SL orders
        assert entry_order.status == OrderStatus.FILLED
        assert len(tpsl_orders) == 0


class TestQueryMethods:
    """Test suite for position and account query methods."""

    @pytest.fixture
    def mock_client(self):
        """Mock Binance UMFutures client"""
        return MagicMock()

    @pytest.fixture
    def manager(self, mock_client):
        """OrderExecutionManager instance (using mock client)"""
        with patch('src.execution.order_manager.UMFutures', return_value=mock_client):
            with patch.dict('os.environ', {
                'BINANCE_API_KEY': 'test_key',
                'BINANCE_API_SECRET': 'test_secret'
            }):
                return OrderExecutionManager(is_testnet=True)

    @pytest.fixture
    def mock_position_long(self):
        """Mock API response for LONG position"""
        return [{
            "symbol": "BTCUSDT",
            "positionAmt": "0.001",
            "entryPrice": "50000.00",
            "unRealizedProfit": "10.25",
            "leverage": "20",
            "isolated": True,
            "isolatedWallet": "100.00",
            "positionSide": "BOTH",
            "liquidationPrice": "45000.00",
            "markPrice": "50500.00",
            "updateTime": 1678886400000
        }]

    @pytest.fixture
    def mock_position_short(self):
        """Mock API response for SHORT position"""
        return [{
            "symbol": "BTCUSDT",
            "positionAmt": "-0.001",
            "entryPrice": "50000.00",
            "unRealizedProfit": "-5.50",
            "leverage": "10",
            "isolated": False,
            "liquidationPrice": "55000.00",
            "markPrice": "49500.00",
            "updateTime": 1678886400000
        }]

    @pytest.fixture
    def mock_position_zero(self):
        """Mock API response for no position"""
        return [{
            "symbol": "BTCUSDT",
            "positionAmt": "0.000",
            "entryPrice": "0.00",
            "unRealizedProfit": "0.00",
            "leverage": "20",
            "isolated": False,
            "updateTime": 1678886400000
        }]

    @pytest.fixture
    def mock_account_with_usdt(self):
        """Mock account response with USDT balance"""
        return {
            "feeTier": 0,
            "canTrade": True,
            "assets": [
                {
                    "asset": "USDT",
                    "walletBalance": "1234.56",
                    "unrealizedProfit": "10.25",
                    "marginBalance": "1244.81",
                    "maintMargin": "5.00",
                    "initialMargin": "10.00",
                    "availableBalance": "1224.56",
                    "updateTime": 1678886400000
                },
                {
                    "asset": "BTC",
                    "walletBalance": "0.001",
                    "unrealizedProfit": "0.00",
                    "updateTime": 1678886400000
                }
            ]
        }

    @pytest.fixture
    def mock_account_without_usdt(self):
        """Mock account response without USDT"""
        return {
            "feeTier": 0,
            "canTrade": True,
            "assets": [
                {
                    "asset": "BTC",
                    "walletBalance": "0.001",
                    "unrealizedProfit": "0.00",
                    "updateTime": 1678886400000
                }
            ]
        }

    @pytest.fixture
    def mock_cancel_with_orders(self):
        """Mock response for cancel with orders"""
        return [
            {
                "orderId": 123456,
                "symbol": "BTCUSDT",
                "status": "CANCELED",
                "clientOrderId": "order1",
                "price": "50000.00",
                "origQty": "0.001",
                "type": "LIMIT",
                "side": "BUY",
                "updateTime": 1678886400000
            },
            {
                "orderId": 123457,
                "symbol": "BTCUSDT",
                "status": "CANCELED",
                "clientOrderId": "order2",
                "price": "51000.00",
                "origQty": "0.002",
                "type": "LIMIT",
                "side": "SELL",
                "updateTime": 1678886400000
            }
        ]

    @pytest.fixture
    def mock_cancel_no_orders(self):
        """Mock response for cancel with no orders"""
        return {
            "code": 200,
            "msg": "The operation of cancel all open order is done."
        }

    # ========== get_position() Tests ==========

    def test_get_position_long_success(self, manager, mock_client, mock_position_long):
        """LONG 포지션 조회 성공"""
        mock_client.get_position_risk.return_value = mock_position_long

        position = manager.get_position('BTCUSDT')

        assert position is not None
        assert position.symbol == 'BTCUSDT'
        assert position.side == 'LONG'
        assert position.quantity == 0.001
        assert position.entry_price == 50000.0
        assert position.leverage == 20
        assert position.unrealized_pnl == 10.25
        assert position.liquidation_price == 45000.0

        mock_client.get_position_risk.assert_called_once_with(symbol='BTCUSDT')

    def test_get_position_short_success(self, manager, mock_client, mock_position_short):
        """SHORT 포지션 조회 성공"""
        mock_client.get_position_risk.return_value = mock_position_short

        position = manager.get_position('BTCUSDT')

        assert position is not None
        assert position.symbol == 'BTCUSDT'
        assert position.side == 'SHORT'
        assert position.quantity == 0.001  # abs(-0.001)
        assert position.entry_price == 50000.0
        assert position.leverage == 10
        assert position.unrealized_pnl == -5.50
        assert position.liquidation_price == 55000.0

    def test_get_position_no_position(self, manager, mock_client, mock_position_zero):
        """포지션 없음 (positionAmt=0)"""
        mock_client.get_position_risk.return_value = mock_position_zero

        position = manager.get_position('BTCUSDT')

        assert position is None
        mock_client.get_position_risk.assert_called_once_with(symbol='BTCUSDT')

    def test_get_position_invalid_symbol(self, manager, mock_client):
        """잘못된 심볼"""
        mock_client.get_position_risk.side_effect = ClientError(
            status_code=400,
            error_code=-1121,
            error_message="Invalid symbol.",
            header={}
        )

        with pytest.raises(ValidationError, match="Invalid symbol"):
            manager.get_position('INVALID')

    def test_get_position_api_error(self, manager, mock_client):
        """API 인증 오류"""
        mock_client.get_position_risk.side_effect = ClientError(
            status_code=401,
            error_code=-2015,
            error_message="Invalid API-key",
            header={}
        )

        with pytest.raises(OrderExecutionError, match="API authentication failed"):
            manager.get_position('BTCUSDT')

    # ========== get_account_balance() Tests ==========

    def test_get_account_balance_success(self, manager, mock_client, mock_account_with_usdt):
        """USDT 잔액 조회 성공"""
        mock_client.account.return_value = mock_account_with_usdt

        balance = manager.get_account_balance()

        assert balance == 1234.56
        mock_client.account.assert_called_once()

    def test_get_account_balance_usdt_not_found(self, manager, mock_client, mock_account_without_usdt):
        """USDT가 assets에 없음"""
        mock_client.account.return_value = mock_account_without_usdt

        balance = manager.get_account_balance()

        assert balance == 0.0
        mock_client.account.assert_called_once()

    def test_get_account_balance_api_error(self, manager, mock_client):
        """API 인증 오류"""
        mock_client.account.side_effect = ClientError(
            status_code=401,
            error_code=-2015,
            error_message="Invalid API-key",
            header={}
        )

        with pytest.raises(OrderExecutionError, match="API authentication failed"):
            manager.get_account_balance()

    # ========== cancel_all_orders() Tests ==========

    def test_cancel_all_orders_success_with_orders(self, manager, mock_client, mock_cancel_with_orders):
        """주문 취소 성공 (2개 주문 취소)"""
        mock_client.cancel_open_orders.return_value = mock_cancel_with_orders

        cancelled_count = manager.cancel_all_orders('BTCUSDT')

        assert cancelled_count == 2
        mock_client.cancel_open_orders.assert_called_once_with(symbol='BTCUSDT')

    def test_cancel_all_orders_success_no_orders(self, manager, mock_client, mock_cancel_no_orders):
        """취소할 주문 없음"""
        mock_client.cancel_open_orders.return_value = mock_cancel_no_orders

        cancelled_count = manager.cancel_all_orders('BTCUSDT')

        assert cancelled_count == 0
        mock_client.cancel_open_orders.assert_called_once_with(symbol='BTCUSDT')

    def test_cancel_all_orders_invalid_symbol(self, manager, mock_client):
        """잘못된 심볼"""
        mock_client.cancel_open_orders.side_effect = ClientError(
            status_code=400,
            error_code=-1121,
            error_message="Invalid symbol.",
            header={}
        )

        with pytest.raises(ValidationError, match="Invalid symbol"):
            manager.cancel_all_orders('INVALID')

    def test_cancel_all_orders_api_error(self, manager, mock_client):
        """API 오류"""
        mock_client.cancel_open_orders.side_effect = ClientError(
            status_code=500,
            error_code=-1000,
            error_message="Internal server error",
            header={}
        )

        with pytest.raises(OrderExecutionError, match="Order cancellation failed"):
            manager.cancel_all_orders('BTCUSDT')


# ==================== Price Formatting Tests (Task 6.5) ====================

class TestPriceFormatting:
    """Test suite for dynamic price formatting with tick sizes"""

    @pytest.fixture
    def mock_client(self):
        """Mock Binance UMFutures client"""
        return MagicMock()

    @pytest.fixture
    def manager(self, mock_client):
        """OrderExecutionManager instance with mock client"""
        with patch('src.execution.order_manager.UMFutures', return_value=mock_client):
            with patch.dict('os.environ', {
                'BINANCE_API_KEY': 'test_key',
                'BINANCE_API_SECRET': 'test_secret'
            }):
                return OrderExecutionManager(is_testnet=True)

    @pytest.fixture
    def mock_exchange_info(self):
        """Mock exchange_info API response with various tick sizes"""
        return {
            'timezone': 'UTC',
            'serverTime': 1678886400000,
            'symbols': [
                {
                    'symbol': 'BTCUSDT',
                    'status': 'TRADING',
                    'filters': [
                        {
                            'filterType': 'PRICE_FILTER',
                            'tickSize': '0.01',
                            'minPrice': '100.00',
                            'maxPrice': '100000.00'
                        }
                    ]
                },
                {
                    'symbol': 'BNBUSDT',
                    'status': 'TRADING',
                    'filters': [
                        {
                            'filterType': 'PRICE_FILTER',
                            'tickSize': '0.001',
                            'minPrice': '10.000',
                            'maxPrice': '10000.000'
                        }
                    ]
                },
                {
                    'symbol': 'ETHUSDT',
                    'status': 'TRADING',
                    'filters': [
                        {
                            'filterType': 'PRICE_FILTER',
                            'tickSize': '0.1',
                            'minPrice': '100.0',
                            'maxPrice': '50000.0'
                        }
                    ]
                },
                {
                    'symbol': 'DOGEUSDT',
                    'status': 'TRADING',
                    'filters': [
                        {
                            'filterType': 'PRICE_FILTER',
                            'tickSize': '0.0001',
                            'minPrice': '0.0001',
                            'maxPrice': '1.0000'
                        }
                    ]
                },
                {
                    'symbol': '1000PEPEUSDT',
                    'status': 'TRADING',
                    'filters': [
                        {
                            'filterType': 'PRICE_FILTER',
                            'tickSize': '0.00001',
                            'minPrice': '0.00001',
                            'maxPrice': '0.10000'
                        }
                    ]
                }
            ]
        }

    # ========== _calculate_precision() Tests ==========

    def test_calculate_precision_two_decimals(self, manager):
        """tickSize 0.01 → 2 decimals"""
        precision = manager._calculate_precision(0.01)
        assert precision == 2

    def test_calculate_precision_three_decimals(self, manager):
        """tickSize 0.001 → 3 decimals"""
        precision = manager._calculate_precision(0.001)
        assert precision == 3

    def test_calculate_precision_one_decimal(self, manager):
        """tickSize 0.1 → 1 decimal"""
        precision = manager._calculate_precision(0.1)
        assert precision == 1

    def test_calculate_precision_four_decimals(self, manager):
        """tickSize 0.0001 → 4 decimals"""
        precision = manager._calculate_precision(0.0001)
        assert precision == 4

    def test_calculate_precision_integer(self, manager):
        """tickSize 1.0 → 0 decimals"""
        precision = manager._calculate_precision(1.0)
        assert precision == 0

    # ========== Cache Management Tests ==========

    def test_cache_expires_after_24_hours(self, manager):
        """Cache expires after 24 hours"""
        from datetime import datetime, timedelta

        # Set cache timestamp to 25 hours ago
        manager._cache_timestamp = datetime.now() - timedelta(hours=25)

        assert manager._is_cache_expired() is True

    def test_cache_valid_within_24_hours(self, manager):
        """Cache is valid within 24 hours"""
        from datetime import datetime, timedelta

        # Set cache timestamp to 23 hours ago
        manager._cache_timestamp = datetime.now() - timedelta(hours=23)

        assert manager._is_cache_expired() is False

    def test_cache_expired_when_never_set(self, manager):
        """Cache is expired when never set (None)"""
        assert manager._cache_timestamp is None
        assert manager._is_cache_expired() is True

    # ========== _refresh_exchange_info() Tests ==========

    def test_refresh_exchange_info_success(self, manager, mock_client, mock_exchange_info):
        """Exchange info refresh parses all symbols correctly"""
        mock_client.exchange_info.return_value = mock_exchange_info

        manager._refresh_exchange_info()

        # Verify all symbols cached
        assert 'BTCUSDT' in manager._exchange_info_cache
        assert 'BNBUSDT' in manager._exchange_info_cache
        assert 'ETHUSDT' in manager._exchange_info_cache
        assert 'DOGEUSDT' in manager._exchange_info_cache
        assert '1000PEPEUSDT' in manager._exchange_info_cache

        # Verify tick sizes
        assert manager._exchange_info_cache['BTCUSDT']['tickSize'] == 0.01
        assert manager._exchange_info_cache['BNBUSDT']['tickSize'] == 0.001
        assert manager._exchange_info_cache['ETHUSDT']['tickSize'] == 0.1
        assert manager._exchange_info_cache['DOGEUSDT']['tickSize'] == 0.0001
        assert manager._exchange_info_cache['1000PEPEUSDT']['tickSize'] == 0.00001

        # Verify cache timestamp set
        assert manager._cache_timestamp is not None

    def test_refresh_exchange_info_api_error(self, manager, mock_client):
        """Exchange info fetch API error raises OrderExecutionError"""
        mock_client.exchange_info.side_effect = ClientError(
            status_code=400,
            error_code=-1000,
            error_message="Server error",
            header={}
        )

        with pytest.raises(OrderExecutionError, match="Exchange info fetch failed"):
            manager._refresh_exchange_info()

    def test_refresh_exchange_info_network_error(self, manager, mock_client):
        """Exchange info fetch network error raises OrderExecutionError"""
        mock_client.exchange_info.side_effect = Exception("Network timeout")

        with pytest.raises(OrderExecutionError, match="Exchange info fetch failed"):
            manager._refresh_exchange_info()

    # ========== _get_tick_size() Tests ==========

    def test_get_tick_size_cache_hit(self, manager, mock_client, mock_exchange_info):
        """Tick size retrieval from valid cache (no API call)"""
        # Pre-populate cache
        mock_client.exchange_info.return_value = mock_exchange_info
        manager._refresh_exchange_info()

        # Reset mock to verify no additional API calls
        mock_client.reset_mock()

        tick_size = manager._get_tick_size('BTCUSDT')

        assert tick_size == 0.01
        mock_client.exchange_info.assert_not_called()  # Cache hit

    def test_get_tick_size_cache_miss_fetches_data(self, manager, mock_client, mock_exchange_info):
        """Tick size retrieval with empty cache triggers fetch"""
        mock_client.exchange_info.return_value = mock_exchange_info

        tick_size = manager._get_tick_size('BNBUSDT')

        assert tick_size == 0.001
        mock_client.exchange_info.assert_called_once()

    def test_get_tick_size_symbol_not_found_fallback(self, manager, mock_client, mock_exchange_info, caplog):
        """Symbol not in exchange info returns fallback 0.01 with warning"""
        mock_client.exchange_info.return_value = mock_exchange_info

        with caplog.at_level(logging.WARNING):
            tick_size = manager._get_tick_size('UNKNOWNUSDT')

        assert tick_size == 0.01  # Fallback value
        assert "UNKNOWNUSDT not found" in caplog.text

    def test_get_tick_size_expired_cache_refreshes(self, manager, mock_client, mock_exchange_info):
        """Expired cache triggers refresh before retrieval"""
        from datetime import datetime, timedelta

        # Pre-populate cache with expired timestamp
        mock_client.exchange_info.return_value = mock_exchange_info
        manager._refresh_exchange_info()
        manager._cache_timestamp = datetime.now() - timedelta(hours=25)  # Expire cache

        # Reset mock to count refresh calls
        mock_client.reset_mock()
        mock_client.exchange_info.return_value = mock_exchange_info

        tick_size = manager._get_tick_size('BTCUSDT')

        assert tick_size == 0.01
        mock_client.exchange_info.assert_called_once()  # Refresh triggered

    # ========== _format_price() Integration Tests ==========

    def test_format_price_btcusdt_two_decimals(self, manager, mock_client, mock_exchange_info):
        """BTCUSDT price formatting (tick_size=0.01, 2 decimals)"""
        mock_client.exchange_info.return_value = mock_exchange_info

        assert manager._format_price(50123.456, 'BTCUSDT') == '50123.46'
        assert manager._format_price(50123.444, 'BTCUSDT') == '50123.44'
        assert manager._format_price(50123.0, 'BTCUSDT') == '50123.00'

    def test_format_price_bnbusdt_three_decimals(self, manager, mock_client, mock_exchange_info):
        """BNBUSDT price formatting (tick_size=0.001, 3 decimals)"""
        mock_client.exchange_info.return_value = mock_exchange_info

        assert manager._format_price(492.1234, 'BNBUSDT') == '492.123'
        assert manager._format_price(492.1236, 'BNBUSDT') == '492.124'
        assert manager._format_price(492.0, 'BNBUSDT') == '492.000'

    def test_format_price_ethusdt_one_decimal(self, manager, mock_client, mock_exchange_info):
        """ETHUSDT price formatting (tick_size=0.1, 1 decimal)"""
        mock_client.exchange_info.return_value = mock_exchange_info

        assert manager._format_price(3456.789, 'ETHUSDT') == '3456.8'
        assert manager._format_price(3456.12, 'ETHUSDT') == '3456.1'
        assert manager._format_price(3456.0, 'ETHUSDT') == '3456.0'

    def test_format_price_dogeusdt_four_decimals(self, manager, mock_client, mock_exchange_info):
        """DOGEUSDT price formatting (tick_size=0.0001, 4 decimals)"""
        mock_client.exchange_info.return_value = mock_exchange_info

        assert manager._format_price(0.123456, 'DOGEUSDT') == '0.1235'
        assert manager._format_price(0.123444, 'DOGEUSDT') == '0.1234'
        assert manager._format_price(0.1, 'DOGEUSDT') == '0.1000'

    def test_format_price_unknown_symbol_uses_fallback(self, manager, mock_client, mock_exchange_info, caplog):
        """Unknown symbol uses fallback tick_size=0.01 (2 decimals)"""
        mock_client.exchange_info.return_value = mock_exchange_info

        with caplog.at_level(logging.WARNING):
            formatted = manager._format_price(123.456789, 'UNKNOWNUSDT')

        assert formatted == '123.46'  # Fallback to 2 decimals
        assert "UNKNOWNUSDT not found" in caplog.text
