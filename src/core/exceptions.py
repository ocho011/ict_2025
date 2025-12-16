"""
Custom exceptions for the trading system
"""


class TradingSystemError(Exception):
    """Base exception for trading system errors"""
    pass


class ConfigurationError(TradingSystemError):
    """Configuration related errors"""
    pass


class DataCollectionError(TradingSystemError):
    """Data collection errors"""
    pass


class OrderExecutionError(TradingSystemError):
    """Order execution errors"""
    pass


class ValidationError(OrderExecutionError):
    """주문 파라미터 검증 실패"""
    pass


class RateLimitError(OrderExecutionError):
    """Rate limit 초과"""
    pass


class OrderRejectedError(OrderExecutionError):
    """Binance가 주문 거부"""
    pass


class RiskManagementError(TradingSystemError):
    """Risk management errors"""
    pass


class StrategyError(TradingSystemError):
    """Strategy execution errors"""
    pass
