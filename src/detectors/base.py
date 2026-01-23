"""
Base detector interface
"""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class BaseDetector(ABC):
    """
    Abstract base class for ICT concept detectors
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def calculate(self, data: pd.DataFrame) -> Any:
        """
        Detect ICT concepts from market data

        Args:
            data: OHLCV dataframe

        Returns:
            Detected concept indicators
        """
