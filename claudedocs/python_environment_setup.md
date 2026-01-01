# Python Environment Setup Guide

**Project**: ICT 2025 Trading System
**Python Version**: 3.12.12
**Updated**: 2026-01-02

---

## Overview

This project uses **pyenv** for Python version management and **venv** for virtual environments. Python 3.12+ is required for the `@dataclass(slots=True)` optimization.

---

## Initial Setup (One-Time)

### 1. Install pyenv

```bash
# macOS (Homebrew)
brew install pyenv

# Linux (bash)
curl https://pyenv.run | bash
```

### 2. Configure Shell (IMPORTANT)

Add these lines to your shell configuration file:

**For zsh** (`~/.zshrc`):
```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv init -)"
```

**For bash** (`~/.bashrc` or `~/.bash_profile`):
```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv init -)"
```

**Apply changes**:
```bash
# For zsh
source ~/.zshrc

# For bash
source ~/.bashrc
```

### 3. Install Python 3.12.12

```bash
# Install Python 3.12.12
pyenv install 3.12.12

# Verify installation
pyenv versions
```

---

## Project Setup

### 1. Clone Repository (if not already done)

```bash
git clone https://github.com/ocho011/ict_2025.git
cd ict_2025
```

### 2. Set Local Python Version

The `.python-version` file is already in the repository, so pyenv will automatically use Python 3.12.12:

```bash
# Verify Python version
python --version
# Output: Python 3.12.12
```

### 3. Create Virtual Environment

```bash
# Create venv
python -m venv venv

# Activate venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows
```

### 4. Install Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install project dependencies
pip install -r requirements.txt
```

### 5. Verify Installation

```bash
# Test imports
python -c "import pandas; import numpy; import aiohttp; print('All imports successful!')"

# Test __slots__ optimization
python scripts/measure_slots_memory.py
```

---

## Daily Development Workflow

### Start Development Session

```bash
# Navigate to project
cd /path/to/ict_2025

# Activate virtual environment
source venv/bin/activate

# Verify Python version
python --version  # Should show 3.12.12
```

### Run the Trading System

```bash
# With virtual environment activated
python src/main.py
```

### Deactivate Virtual Environment

```bash
deactivate
```

---

## Troubleshooting

### Problem: `python --version` shows wrong version

**Solution**: Ensure pyenv is initialized in your shell config
```bash
# Check if pyenv is in PATH
which pyenv

# If not found, re-run shell configuration
source ~/.zshrc  # or ~/.bashrc
```

### Problem: `No module named 'binance'`

**Solution**: Virtual environment not activated
```bash
# Activate venv first
source venv/bin/activate

# Then install dependencies
pip install -r requirements.txt
```

### Problem: `TypeError: dataclass() got an unexpected keyword argument 'slots'`

**Solution**: Using Python < 3.10
```bash
# Check Python version
python --version

# If < 3.10, ensure pyenv is properly configured
pyenv local 3.12.12
python --version  # Should now show 3.12.12
```

### Problem: `pyenv: command not found`

**Solution**: pyenv not installed or not in PATH
```bash
# macOS: Install with Homebrew
brew install pyenv

# Add to shell config (see "Configure Shell" above)
```

---

## File Structure

```
ict_2025/
├── .python-version          # pyenv local version (3.12.12)
├── venv/                    # Virtual environment (in .gitignore)
├── requirements.txt         # Python dependencies
├── src/                     # Source code
│   ├── main.py
│   ├── models/
│   │   ├── candle.py       # Uses @dataclass(slots=True)
│   │   └── event.py        # Uses @dataclass(slots=True)
│   └── ...
└── scripts/
    └── measure_slots_memory.py  # Memory measurement tool
```

---

## Dependencies

### Production Requirements

```
binance-futures-connector>=4.1.0   # Binance API
pandas>=2.2.0                       # Data processing
numpy>=1.26.0                       # Numerical operations
aiohttp>=3.9.0                      # Async HTTP
python-dotenv>=1.0.0                # Environment configuration
pytz>=2024.1                        # Timezone handling
```

### Why Python 3.12+?

1. **`@dataclass(slots=True)` support**: Achieves 75-84% memory reduction
2. **Performance improvements**: Faster attribute access, reduced GC pressure
3. **Latest Python features**: Better typing, improved asyncio

---

## Environment Variables

Create a `.env` file in the project root:

```bash
# Binance API Configuration
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_secret_here
BINANCE_TESTNET=true

# Trading Configuration
SYMBOL=BTCUSDT
LEVERAGE=10
POSITION_SIZE_USDT=100

# Risk Management
MAX_POSITION_SIZE_USDT=1000
STOP_LOSS_PERCENT=2.0
TAKE_PROFIT_PERCENT=5.0
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12.12'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run tests
        run: |
          python -m pytest tests/
```

---

## Additional Resources

- **pyenv documentation**: https://github.com/pyenv/pyenv
- **venv documentation**: https://docs.python.org/3/library/venv.html
- **Python 3.12 release notes**: https://docs.python.org/3/whatsnew/3.12.html
- **PEP 681 (dataclass slots)**: https://peps.python.org/pep-0681/

---

## Notes

- The `.python-version` file is tracked in git to ensure all developers use Python 3.12.12
- The `venv/` directory is in `.gitignore` (not tracked)
- Always activate `venv` before running the trading system
- Run `pip install -r requirements.txt` after pulling updates

---

**Maintainer**: Claude Code (Sonnet 4.5)
**Last Updated**: 2026-01-02
