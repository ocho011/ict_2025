"""
Base strategy interface
"""

from abc import ABC, abstractmethod
from typing import Optional
from src.models.signal import Signal
from src.models.candle import Candle


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Analyze market data and generate trading signal

        Args:
            candle: Latest candle data

        Returns:
            Signal if conditions met, None otherwise
        """
        pass

    @abstractmethod
    def validate_signal(self, signal: Signal) -> bool:
        """
        Validate generated signal before execution

        Args:
            signal: Signal to validate

        Returns:
            True if signal is valid
        """
        pass
