# Suggested Commands - ICT 2025 Trading System

## Development Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install in editable mode
pip install -e .
```

## Code Quality (Run Before Committing)
```bash
# Format code
black src/ tests/

# Sort imports
isort src/ tests/

# Type checking
mypy src/

# Linting
flake8 src/ tests/

# All quality checks
black src/ tests/ && isort src/ tests/ && mypy src/ && flake8 src/ tests/
```

## Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_config.py -v

# Run specific test
pytest tests/test_config.py::test_config_loading -v
```

## Running the System
```bash
# Using module
python -m src.main

# Using installed script
ict-trading
```

## Git Workflow
```bash
# Standard development flow
git status
git add .
git commit -m "feat: descriptive message"
git push
```

## Configuration
```bash
# Copy example configs
cp configs/api_keys.ini.example configs/api_keys.ini
cp configs/trading_config.ini.example configs/trading_config.ini

# Edit with your API keys (use testnet first!)
# Testnet: https://testnet.binancefuture.com/
```

## Darwin-Specific Commands
```bash
# List files
ls -la

# Find files
find . -name "*.py" -type f

# Search content
grep -r "pattern" src/

# Directory navigation
cd src/models
pwd
```
