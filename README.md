# ICT 2025 Trading System

Binance USDT-M Futures Trading System with ICT (Inner Circle Trader) Strategies

## 🚀 Features

- **Real-time Data Collection**: WebSocket-based market data from Binance
- **Event-Driven Architecture**: Scalable async event handling
- **ICT Strategy Support**: Implementing proven ICT trading concepts
- **Risk Management**: Position sizing and risk controls
- **Backtesting Ready**: Historical data analysis support
- **Testnet Support**: Safe testing environment before live trading

## 📋 Requirements

- Python 3.11+
- Binance Futures account (testnet or production)
- API keys with futures trading permissions

## 🔧 Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd ict_2025
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
# For development:
pip install -r requirements-dev.txt
```

4. **Configure API keys**
```bash
# Copy example configs
cp configs/api_keys.ini.example configs/api_keys.ini
cp configs/trading_config.ini.example configs/trading_config.ini

# Edit configs/api_keys.ini with your Binance API credentials
# Get testnet keys from: https://testnet.binancefuture.com/
```

5. **Set environment variables (recommended)**
```bash
export BINANCE_API_KEY="your_api_key"
export BINANCE_API_SECRET="your_api_secret"
export BINANCE_TESTNET="true"
```

## 🏃 Usage

```bash
# Run the trading system
python -m src.main

# Or using the installed script
ict-trading
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test
pytest tests/test_config.py -v
```

## 📁 Project Structure

```
ict_2025/
├── src/
│   ├── core/           # Core system components
│   ├── strategies/     # Trading strategies
│   ├── indicators/     # Technical indicators
│   ├── execution/      # Order execution
│   ├── risk/          # Risk management
│   ├── models/        # Data models
│   └── utils/         # Utilities (config, logger)
├── configs/           # Configuration files
├── tests/             # Test suite
├── logs/              # System logs
└── README.md          # This file
```

## 📊 Logging

All execution logs are automatically saved to the `logs/` directory for review and debugging.

### Log Files

1. **`logs/trading.log`** - Main application log
   - Contains ALL logs (DEBUG level and above)
   - Rotates at 10MB (keeps 5 backup files)
   - Includes:
     - Session start/end markers with system info
     - Component initialization
     - Data collection events
     - Strategy execution
     - Order management
     - Error traces

2. **`logs/trades.log`** - Trade-specific log
   - JSON-formatted trade events only
   - Daily rotation (keeps 30 days)
   - Includes:
     - Signal generation
     - Order placement
     - Order fills
     - Position updates

3. **`logs/audit/`** - Audit trail directory
   - Detailed audit logs for compliance

### Log Format

**Console output**: Simple, readable format
```
2025-12-25 15:30:45 | INFO     | src.main           | 🚀 TRADING BOT SESSION START
```

**File logs**: Detailed format with line numbers
```
2025-12-25 15:30:45 | INFO     | src.main:398 | 🚀 TRADING BOT SESSION START
2025-12-25 15:30:45 | INFO     | src.main:400 | Session Start Time: 2025-12-25 15:30:45
2025-12-25 15:30:45 | INFO     | src.main:401 | Python Version: 3.11.5
2025-12-25 15:30:45 | INFO     | src.main:402 | Platform: Darwin 24.6.0
```

### Configuration

Logging settings in `configs/trading_config.ini`:
```ini
[logging]
log_level = INFO      # DEBUG, INFO, WARNING, ERROR, CRITICAL
log_dir = logs       # Directory for log files
```

### Reviewing Logs

```bash
# View real-time logs
tail -f logs/trading.log

# View recent session
tail -100 logs/trading.log

# Search for errors
grep "ERROR" logs/trading.log

# View trade events (JSON format)
tail -f logs/trades.log | jq '.'
```

## ⚙️ Configuration

### API Configuration (`configs/api_keys.ini`)
- Binance API credentials
- Testnet/Production mode toggle

### Trading Configuration (`configs/trading_config.ini`)
- Trading symbol and timeframes
- Strategy selection
- Leverage settings
- Risk management parameters

## 🛡️ Security

- **Never commit `api_keys.ini`** - It's in `.gitignore`
- Use environment variables in production
- Start with testnet before live trading
- API keys are masked in logs
- Use read-only API keys for market data collection

## ⚠️ Risk Disclaimer

**This software is for educational purposes only. Trading cryptocurrencies involves substantial risk of loss. Never trade with money you cannot afford to lose. The authors are not responsible for any financial losses incurred through the use of this software.**

## 📝 Development

```bash
# Format code
black src/ tests/

# Sort imports
isort src/ tests/

# Type checking
mypy src/

# Linting
flake8 src/ tests/
```

## 📜 License

MIT License - See LICENSE file for details

## 🤝 Contributing

Contributions are welcome! Please read CONTRIBUTING.md for details.

## 📞 Support

For issues and questions, please open a GitHub issue.
