"""
Custom exceptions for the trading system
"""


class TradingSystemError(Exception):
    """Base exception for trading system errors"""


class ConfigurationError(TradingSystemError):
    """Configuration related errors"""


class DataCollectionError(TradingSystemError):
    """Data collection errors"""


class OrderExecutionError(TradingSystemError):
    """Order execution errors"""


class ValidationError(OrderExecutionError):
    """주문 파라미터 검증 실패"""


class RateLimitError(OrderExecutionError):
    """Rate limit 초과"""


class OrderRejectedError(OrderExecutionError):
    """Binance가 주문 거부"""


class RiskManagementError(TradingSystemError):
    """Risk management errors"""


class StrategyError(TradingSystemError):
    """Strategy execution errors"""
