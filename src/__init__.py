"""
ICT 2025 Binance USDT-M Futures Trading System
Main package initialization
"""

__version__ = "0.1.0"
__author__ = "Your Name"

from src.utils.logger import setup_logger
from src.utils.config import ConfigManager

__all__ = ["setup_logger", "ConfigManager"]
