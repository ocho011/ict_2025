"""
Mock strategy for testing purposes
"""

from typing import Optional
from src.strategies.base import BaseStrategy
from src.models.signal import Signal
from src.models.candle import Candle


class MockStrategy(BaseStrategy):
    """
    Simple mock strategy for system testing
    """

    def __init__(self):
        super().__init__("MockStrategy")

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Mock analysis - always returns None
        """
        return None

    def validate_signal(self, signal: Signal) -> bool:
        """
        Mock validation - always returns True
        """
        return True
