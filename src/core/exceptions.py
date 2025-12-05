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


class RiskManagementError(TradingSystemError):
    """Risk management errors"""
    pass


class StrategyError(TradingSystemError):
    """Strategy execution errors"""
    pass
