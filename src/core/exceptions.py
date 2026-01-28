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
    """Order parameter validation failed"""


class RateLimitError(OrderExecutionError):
    """Rate limit exceeded"""


class OrderRejectedError(OrderExecutionError):
    """Order rejected by Binance"""


class RiskManagementError(TradingSystemError):
    """Risk management errors"""


class StrategyError(TradingSystemError):
    """Strategy execution errors"""
