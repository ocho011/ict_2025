"""
Base indicator interface
"""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class BaseIndicator(ABC):
    """
    Abstract base class for technical indicators
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def calculate(self, data: pd.DataFrame) -> Any:
        """
        Calculate indicator value from market data

        Args:
            data: OHLCV dataframe

        Returns:
            Calculated indicator value(s)
        """
