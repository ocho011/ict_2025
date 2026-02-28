# Tech Stack: ICT 2025 Trading System

## Core Technologies
- **Programming Language**: Python 3.11+
- **Exchange Interface**: `binance-futures-connector` for Binance USDT-M Futures API.
- **Asynchronous Engine**: `asyncio` and `aiohttp` for non-blocking event-driven architecture.
- **Data Analysis & Processing**: `pandas` and `numpy` for high-performance indicator calculations and historical data processing.

## Configuration & Environments
- **Environment Management**: `.env` files managed via `python-dotenv`.
- **System Configuration**: YAML and INI formats (using `pyyaml` and `configparser`) for flexible trading and API settings.
- **Timezone Management**: `pytz` for accurate handling of exchange timestamps.

## Quality Assurance & Testing
- **Test Framework**: `pytest` with `pytest-asyncio` for comprehensive unit and integration testing.
- **Code Coverage**: `pytest-cov` for maintaining high test coverage (>80%).
- **Mocking**: `pytest-mock` for simulating exchange API responses and market data streams.

## Development & Formatting
- **Linter**: `flake8` for style checking and `mypy` for static type verification.
- **Formatter**: `black` and `isort` for consistent code formatting and import sorting.
- **Type Safety**: Strong focus on type hints to ensure system reliability and ease of maintenance.
