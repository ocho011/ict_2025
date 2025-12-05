# ICT 2025 Trading System - Project Overview

## Purpose
Binance USDT-M Futures automated trading system implementing ICT (Inner Circle Trader) strategies.
Target users: Hobbyist developers with Python knowledge who want to automate their ICT trading ideas.

## Core Objectives
- **Event-driven architecture**: Real-time WebSocket data processing
- **ICT Strategy Engine**: Automated FVG, Order Block, Market Structure analysis
- **Risk Management**: Automated position sizing and stop-loss/take-profit
- **Testnet Support**: Safe simulation environment before live trading

## Tech Stack
- **Language**: Python 3.11+
- **API**: binance-futures-connector (WebSocket + REST)
- **Data Processing**: pandas, numpy
- **Async**: aiohttp for concurrent operations
- **Config**: python-dotenv, configparser (INI files)

## Architecture Pattern
Event-driven system with clear separation of concerns:
- `core/`: Event handlers, data collectors, exceptions
- `strategies/`: Trading strategy implementations
- `indicators/`: ICT technical indicators
- `execution/`: Order management and execution
- `risk/`: Position sizing and risk controls
- `models/`: Data structures (Candle, Signal, Order, Position)
- `utils/`: Configuration and logging utilities
