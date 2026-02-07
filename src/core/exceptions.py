"""
Custom exceptions and shared enums for the trading system
"""

from enum import Enum


class EngineState(Enum):
    """
    State machine for TradingEngine lifecycle.

    State Transitions:
        CREATED → INITIALIZED → RUNNING → STOPPING → STOPPED

    States:
        CREATED: Initial state after __init__()
        INITIALIZED: After initialize_components() called
        RUNNING: Event loop active, run() executing
        STOPPING: Shutdown initiated
        STOPPED: Shutdown complete
    """

    CREATED = "created"
    INITIALIZED = "initialized"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


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
