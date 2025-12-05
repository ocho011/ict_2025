# Project Structure - ICT 2025 Trading System

## Directory Layout
```
ict_2025/
├── src/                    # Main source code
│   ├── __init__.py
│   ├── main.py            # Entry point
│   ├── core/              # Core system components
│   │   ├── __init__.py
│   │   ├── data_collector.py    # WebSocket data collection
│   │   ├── event_handler.py     # Event-driven architecture
│   │   └── exceptions.py        # Custom exceptions
│   ├── strategies/        # Trading strategies
│   │   ├── __init__.py
│   │   ├── base.py             # Base strategy class
│   │   └── mock_strategy.py    # Example strategy
│   ├── indicators/        # ICT technical indicators
│   │   ├── __init__.py
│   │   └── base.py             # Base indicator class
│   ├── execution/         # Order execution
│   │   ├── __init__.py
│   │   └── order_manager.py    # Order management
│   ├── risk/              # Risk management
│   │   ├── __init__.py
│   │   └── manager.py          # Risk controls
│   ├── models/            # Data structures (CURRENT FOCUS)
│   │   ├── __init__.py
│   │   ├── candle.py           # OHLCV candle data
│   │   ├── signal.py           # Trade signals
│   │   ├── order.py            # Order data
│   │   └── position.py         # Position data
│   └── utils/             # Utilities
│       ├── __init__.py
│       ├── config.py           # Config management
│       └── logger.py           # Logging setup
├── configs/               # Configuration files
│   ├── api_keys.ini.example
│   └── trading_config.ini.example
├── tests/                 # Test suite
│   └── __init__.py
├── logs/                  # Log files (gitignored)
├── pyproject.toml         # Project metadata & tools
├── requirements.txt       # Production dependencies
├── requirements-dev.txt   # Development dependencies
└── README.md             # Project documentation
```

## Current Development Focus
- **Task #2**: Implementing data models in `src/models/`
- All model files use Python dataclasses with type hints
- Models must be compatible with Binance API specifications
- Export all models from `models/__init__.py`

## Key Files Already Implemented
- `src/utils/config.py`: ConfigManager with INI file support
- `pyproject.toml`: Complete build configuration
- `requirements.txt`: Production dependencies
- `.gitignore`: Excludes sensitive config and logs
