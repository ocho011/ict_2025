# StrategyFactory Pattern Design Document

**Task**: Subtask 5.4 - Implement StrategyFactory Pattern
**Date**: 2025-12-16
**Status**: Design Phase

---

## 1. Overview

### 1.1 Purpose
Implement a Factory Method pattern for strategy instantiation that provides:
- **Centralized** strategy registration and management
- **Type-safe** strategy creation with proper type hints
- **Extensible** architecture for future ICT strategies
- **Clean API** for strategy consumers

### 1.2 Design Pattern
**Factory Method Pattern** - Creational design pattern that provides an interface for creating objects while allowing subclasses or registry to determine the actual class to instantiate.

### 1.3 Key Benefits
- **Decoupling**: Clients don't need to know concrete strategy classes
- **Extensibility**: New strategies can be added without modifying client code
- **Type Safety**: Returns BaseStrategy interface ensuring contract compliance
- **Maintainability**: Single location for strategy registration

---

## 2. Architecture Design

### 2.1 Class Structure

```
┌─────────────────────────────────────────────────────────────┐
│                      StrategyFactory                        │
├─────────────────────────────────────────────────────────────┤
│ - _strategies: Dict[str, Type[BaseStrategy]]                │
│   └─ {'mock_sma': MockSMACrossoverStrategy}                 │
├─────────────────────────────────────────────────────────────┤
│ + create(name: str, symbol: str, config: dict)              │
│   → BaseStrategy                                            │
│ + register(name: str, strategy_class: Type[BaseStrategy])   │
│   → None                                                    │
│ + list_strategies() → List[str]                             │
│ + is_registered(name: str) → bool                           │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ creates
                          ▼
          ┌───────────────────────────────┐
          │       BaseStrategy            │
          │  (Abstract Interface)         │
          └───────────────────────────────┘
                    △         △
                    │         │
        ┌───────────┘         └──────────────┐
        │                                    │
┌───────────────────┐            ┌──────────────────────┐
│ MockSMACrossover  │            │  ICTFVGStrategy     │
│    Strategy       │            │   (Future)          │
└───────────────────┘            └──────────────────────┘
```

### 2.2 Component Responsibilities

**StrategyFactory**
- Maintain registry of available strategies (`_strategies` dict)
- Validate strategy names before instantiation
- Create strategy instances with proper configuration
- Provide introspection methods (list, check registration)

**BaseStrategy**
- Define abstract interface for all strategies
- Enforce contract for `analyze()`, `calculate_take_profit()`, `calculate_stop_loss()`

**Concrete Strategies**
- Implement specific trading logic
- Register themselves in the factory

---

## 3. Detailed Implementation Design

### 3.1 Core Methods

#### 3.1.1 `create()` - Factory Method

**Signature:**
```python
@classmethod
def create(cls, name: str, symbol: str, config: dict) -> BaseStrategy:
    """
    Create a strategy instance by name.

    Args:
        name: Strategy identifier (e.g., 'mock_sma', 'ict_fvg')
        symbol: Trading symbol (e.g., 'BTCUSDT')
        config: Strategy configuration dictionary

    Returns:
        Instantiated strategy object

    Raises:
        ValueError: If strategy name is not registered
        TypeError: If config is not a dict
    """
```

**Implementation Logic:**
1. Validate `name` parameter (non-empty string)
2. Check if `name` exists in `_strategies` registry
3. If not found → Raise `ValueError` with helpful message listing available strategies
4. Validate `config` is a dict (type check)
5. Retrieve strategy class from registry
6. Instantiate with `symbol` and `config`
7. Return typed as `BaseStrategy`

**Error Messages:**
```python
# Unknown strategy
raise ValueError(
    f"Unknown strategy: '{name}'. "
    f"Available strategies: {', '.join(cls._strategies.keys())}"
)

# Invalid config type
raise TypeError(
    f"config must be a dict, got {type(config).__name__}"
)
```

#### 3.1.2 `register()` - Dynamic Registration (Optional Enhancement)

**Signature:**
```python
@classmethod
def register(cls, name: str, strategy_class: Type[BaseStrategy]) -> None:
    """
    Register a new strategy class.

    Args:
        name: Strategy identifier
        strategy_class: Strategy class inheriting from BaseStrategy

    Raises:
        TypeError: If strategy_class doesn't inherit from BaseStrategy
        ValueError: If name is already registered
    """
```

**Use Case:** Allow plugins or external strategies to register themselves dynamically.

#### 3.1.3 `list_strategies()` - Introspection

**Signature:**
```python
@classmethod
def list_strategies(cls) -> List[str]:
    """Return list of all registered strategy names."""
    return list(cls._strategies.keys())
```

#### 3.1.4 `is_registered()` - Validation Helper

**Signature:**
```python
@classmethod
def is_registered(cls, name: str) -> bool:
    """Check if a strategy name is registered."""
    return name in cls._strategies
```

### 3.2 Strategy Registry

**Initial Registry:**
```python
_strategies: Dict[str, Type[BaseStrategy]] = {
    'mock_sma': MockSMACrossoverStrategy,
    # Future strategies:
    # 'ict_fvg': ICTFVGStrategy,
    # 'ict_ob': ICTOrderBlockStrategy,
    # 'ict_bos': ICTBreakOfStructureStrategy,
}
```

**Registry Design Decisions:**
- **Dict-based**: Fast O(1) lookup by strategy name
- **Class-level**: Shared across all instances (singleton-like registry)
- **Type hints**: `Dict[str, Type[BaseStrategy]]` ensures type safety
- **Lowercase keys**: Convention for strategy names (e.g., 'mock_sma', not 'MockSMA')

### 3.3 Type Hints & Type Safety

**Complete Type Annotations:**
```python
from typing import Dict, Type, List
from src.strategies.base import BaseStrategy
from src.strategies.mock_strategy import MockSMACrossoverStrategy

class StrategyFactory:
    _strategies: Dict[str, Type[BaseStrategy]] = {...}

    @classmethod
    def create(
        cls,
        name: str,
        symbol: str,
        config: dict
    ) -> BaseStrategy:
        ...
```

**Type Checking Benefits:**
- IDE autocomplete for strategy methods
- Static analysis catches type errors
- Documentation through types
- Refactoring safety

---

## 4. Integration Design

### 4.1 File Location
**Chosen Location:** `src/strategies/__init__.py`

**Rationale:**
- ✅ Central location for strategy exports
- ✅ Clean import: `from src.strategies import StrategyFactory`
- ✅ Co-located with strategy registrations
- ✅ Follows Python package conventions

**Alternative:** `src/strategies/factory.py`
- Would require additional import statement
- Adds complexity for simple factory
- Better for complex factory logic (future enhancement)

### 4.2 Package Structure After Implementation

```
src/strategies/
├── __init__.py           # ← StrategyFactory implementation here
│   ├── BaseStrategy (imported)
│   ├── MockSMACrossoverStrategy (imported)
│   └── StrategyFactory (defined)
├── base.py
└── mock_strategy.py
```

### 4.3 Import Strategy

**Before (current):**
```python
from src.strategies.base import BaseStrategy
from src.strategies.mock_strategy import MockSMACrossoverStrategy

__all__ = ['BaseStrategy', 'MockSMACrossoverStrategy']
```

**After (with factory):**
```python
from typing import Dict, Type, List
from src.strategies.base import BaseStrategy
from src.strategies.mock_strategy import MockSMACrossoverStrategy


class StrategyFactory:
    # Implementation here
    pass


__all__ = [
    'BaseStrategy',
    'MockSMACrossoverStrategy',
    'StrategyFactory'
]
```

### 4.4 Usage Examples

#### Example 1: Basic Strategy Creation
```python
from src.strategies import StrategyFactory

# Create mock SMA strategy
strategy = StrategyFactory.create(
    name='mock_sma',
    symbol='BTCUSDT',
    config={
        'fast_period': 10,
        'slow_period': 20,
        'risk_reward_ratio': 2.0,
        'stop_loss_percent': 0.01
    }
)

# Use strategy
signal = await strategy.analyze(candle)
```

#### Example 2: Error Handling
```python
try:
    strategy = StrategyFactory.create('unknown_strategy', 'BTCUSDT', {})
except ValueError as e:
    print(e)  # "Unknown strategy: 'unknown_strategy'. Available: mock_sma"
```

#### Example 3: Strategy Introspection
```python
# List available strategies
available = StrategyFactory.list_strategies()
print(f"Available strategies: {', '.join(available)}")

# Check before creating
if StrategyFactory.is_registered('mock_sma'):
    strategy = StrategyFactory.create('mock_sma', 'BTCUSDT', {})
```

#### Example 4: TradingEngine Integration
```python
class TradingEngine:
    def __init__(self, config: dict):
        self.config = config

        # Use factory to create strategy
        strategy_name = config.get('strategy', 'mock_sma')
        strategy_config = config.get('strategy_config', {})

        self.strategy = StrategyFactory.create(
            name=strategy_name,
            symbol=config['symbol'],
            config=strategy_config
        )
```

---

## 5. Test Strategy Design

### 5.1 Test Structure

**Test File:** `tests/strategies/test_factory.py`

**Test Classes:**
```python
class TestStrategyFactoryCreation:
    """Test successful strategy creation scenarios"""

class TestStrategyFactoryValidation:
    """Test error handling and validation"""

class TestStrategyFactoryIntrospection:
    """Test registry query methods"""

class TestStrategyFactoryExtensibility:
    """Test dynamic registration (if implemented)"""
```

### 5.2 Test Cases

#### TC1: Successful Strategy Creation
```python
def test_create_mock_sma_strategy():
    """Test factory creates MockSMACrossoverStrategy correctly"""
    strategy = StrategyFactory.create(
        name='mock_sma',
        symbol='BTCUSDT',
        config={'fast_period': 5, 'slow_period': 10}
    )

    assert isinstance(strategy, MockSMACrossoverStrategy)
    assert isinstance(strategy, BaseStrategy)
    assert strategy.symbol == 'BTCUSDT'
    assert strategy.fast_period == 5
    assert strategy.slow_period == 10
```

#### TC2: Unknown Strategy Error
```python
def test_create_unknown_strategy_raises_error():
    """Test ValueError raised for unregistered strategy"""
    with pytest.raises(ValueError) as exc_info:
        StrategyFactory.create('nonexistent', 'BTCUSDT', {})

    error_msg = str(exc_info.value)
    assert 'Unknown strategy' in error_msg
    assert 'nonexistent' in error_msg
    assert 'mock_sma' in error_msg  # Lists available strategies
```

#### TC3: Type Validation
```python
def test_create_with_invalid_config_type():
    """Test TypeError raised for non-dict config"""
    with pytest.raises(TypeError) as exc_info:
        StrategyFactory.create('mock_sma', 'BTCUSDT', "invalid")

    assert 'config must be a dict' in str(exc_info.value)
```

#### TC4: Configuration Passthrough
```python
def test_config_parameters_passed_correctly():
    """Test all config params reach strategy constructor"""
    custom_config = {
        'fast_period': 7,
        'slow_period': 21,
        'risk_reward_ratio': 3.0,
        'stop_loss_percent': 0.015
    }

    strategy = StrategyFactory.create('mock_sma', 'ETHUSDT', custom_config)

    assert strategy.fast_period == 7
    assert strategy.slow_period == 21
    assert strategy.risk_reward_ratio == 3.0
    assert strategy.stop_loss_percent == 0.015
    assert strategy.symbol == 'ETHUSDT'
```

#### TC5: Registry Introspection
```python
def test_list_strategies():
    """Test listing all registered strategies"""
    strategies = StrategyFactory.list_strategies()

    assert isinstance(strategies, list)
    assert 'mock_sma' in strategies
    assert len(strategies) >= 1

def test_is_registered():
    """Test checking strategy registration"""
    assert StrategyFactory.is_registered('mock_sma') is True
    assert StrategyFactory.is_registered('unknown') is False
```

#### TC6: Extensibility (Optional)
```python
def test_dynamic_registration():
    """Test registering a new strategy class"""
    class DummyStrategy(BaseStrategy):
        async def analyze(self, candle): pass
        def calculate_take_profit(self, price, side): return price
        def calculate_stop_loss(self, price, side): return price

    StrategyFactory.register('dummy', DummyStrategy)

    assert StrategyFactory.is_registered('dummy')
    strategy = StrategyFactory.create('dummy', 'BTCUSDT', {})
    assert isinstance(strategy, DummyStrategy)
```

### 5.3 Test Coverage Targets

**Coverage Goal:** 100% for StrategyFactory class

**Critical Paths:**
- ✓ Happy path: successful creation
- ✓ Error path: unknown strategy
- ✓ Error path: invalid config type
- ✓ Edge case: empty config dict
- ✓ Edge case: extra config parameters
- ✓ Introspection methods

**Fixtures:**
```python
@pytest.fixture
def default_config():
    return {
        'fast_period': 10,
        'slow_period': 20,
        'risk_reward_ratio': 2.0,
        'stop_loss_percent': 0.01
    }

@pytest.fixture
def mock_strategy():
    return StrategyFactory.create('mock_sma', 'BTCUSDT', {})
```

---

## 6. Implementation Plan

### 6.1 Implementation Steps

**Step 1: Update `__init__.py` with imports** (2 min)
```python
from typing import Dict, Type, List
```

**Step 2: Implement StrategyFactory class skeleton** (5 min)
```python
class StrategyFactory:
    _strategies: Dict[str, Type[BaseStrategy]] = {
        'mock_sma': MockSMACrossoverStrategy,
    }
```

**Step 3: Implement `create()` method** (10 min)
- Input validation
- Registry lookup
- Error handling with descriptive messages
- Strategy instantiation

**Step 4: Implement helper methods** (5 min)
- `list_strategies()`
- `is_registered()`
- Optional: `register()`

**Step 5: Update `__all__` exports** (1 min)
```python
__all__ = ['BaseStrategy', 'MockSMACrossoverStrategy', 'StrategyFactory']
```

**Step 6: Add docstrings** (5 min)
- Class-level docstring
- Method docstrings with Args/Returns/Raises

### 6.2 Testing Steps

**Step 1: Create test file** (2 min)
- `tests/strategies/test_factory.py`

**Step 2: Implement test fixtures** (3 min)
- Config fixtures
- Strategy fixtures

**Step 3: Implement test cases** (15 min)
- 5-6 core test methods
- Follow AAA pattern (Arrange, Act, Assert)

**Step 4: Run tests and verify coverage** (3 min)
```bash
pytest tests/strategies/test_factory.py -v --cov=src.strategies
```

**Step 5: Fix any issues** (5 min)

### 6.3 Total Estimated Time
- **Implementation:** 28 minutes
- **Testing:** 28 minutes
- **Documentation & commit:** 5 minutes
- **Total:** ~60 minutes

---

## 7. Quality Assurance

### 7.1 Code Quality Checklist

**Type Safety:**
- ✓ All methods have type hints
- ✓ Return types properly annotated
- ✓ `mypy` passes without errors

**Documentation:**
- ✓ Class docstring explains purpose
- ✓ Method docstrings with Args/Returns/Raises
- ✓ Inline comments for complex logic
- ✓ Usage examples in docstrings

**Error Handling:**
- ✓ ValueError for unknown strategies
- ✓ TypeError for invalid config
- ✓ Descriptive error messages
- ✓ Lists available strategies in error

**Testing:**
- ✓ 100% code coverage
- ✓ All edge cases covered
- ✓ Integration with MockSMACrossoverStrategy verified
- ✓ Fast execution (<1s for all tests)

### 7.2 Code Review Checklist

**Design:**
- ✓ Follows Factory Method pattern correctly
- ✓ Proper separation of concerns
- ✓ Extensible for future strategies
- ✓ Type-safe interface

**Implementation:**
- ✓ Clean, readable code
- ✓ No code duplication
- ✓ Proper use of class methods
- ✓ Consistent naming conventions

**Testing:**
- ✓ Comprehensive test coverage
- ✓ Tests are independent
- ✓ Clear test names
- ✓ Proper use of pytest features

---

## 8. Future Enhancements

### 8.1 Dynamic Registration System
**Feature:** Allow strategies to self-register via decorator

```python
@StrategyFactory.register_strategy('ict_fvg')
class ICTFVGStrategy(BaseStrategy):
    ...
```

**Benefits:**
- Automatic registration
- Cleaner code organization
- Plugin-friendly architecture

### 8.2 Strategy Metadata
**Feature:** Add metadata to strategy registry

```python
_strategies = {
    'mock_sma': {
        'class': MockSMACrossoverStrategy,
        'description': 'Simple Moving Average crossover',
        'version': '1.0.0',
        'category': 'trend_following'
    }
}
```

**Use Cases:**
- Strategy discovery UI
- Capability introspection
- Version compatibility checks

### 8.3 Configuration Validation
**Feature:** Validate config against strategy's expected schema

```python
class BaseStrategy(ABC):
    @classmethod
    def get_config_schema(cls) -> dict:
        """Return JSON schema for config validation"""
        pass
```

**Benefits:**
- Catch config errors early
- Better error messages
- Self-documenting configuration

### 8.4 Strategy Versioning
**Feature:** Support multiple versions of same strategy

```python
_strategies = {
    'mock_sma:v1': MockSMACrossoverStrategyV1,
    'mock_sma:v2': MockSMACrossoverStrategyV2,
    'mock_sma': MockSMACrossoverStrategyV2  # default to latest
}
```

---

## 9. References

### 9.1 Design Patterns
- **Factory Method Pattern** - Gang of Four (GoF) Design Patterns
- **Registry Pattern** - Martin Fowler, Patterns of Enterprise Application Architecture

### 9.2 Python Best Practices
- **PEP 484** - Type Hints
- **PEP 526** - Syntax for Variable Annotations
- **PEP 20** - The Zen of Python (simplicity, readability)

### 9.3 Project Context
- Task #5: Mock Strategy & Signal Generation Pipeline
- Subtask 5.1: BaseStrategy abstract class
- Subtask 5.2: MockSMACrossoverStrategy implementation
- Subtask 5.3: TP/SL calculation logic

---

## 10. Approval & Sign-off

**Design Status:** ✅ Ready for Implementation

**Design Reviewed By:** Claude Sonnet 4.5
**Review Date:** 2025-12-16

**Key Design Decisions:**
1. ✅ Factory location: `src/strategies/__init__.py`
2. ✅ Registry pattern with dict-based lookup
3. ✅ Class methods for stateless operation
4. ✅ Comprehensive error handling with helpful messages
5. ✅ Type-safe interface with full type hints

**Next Steps:**
1. Implement StrategyFactory in `__init__.py`
2. Create comprehensive unit tests
3. Verify integration with existing strategies
4. Commit and mark Subtask 5.4 as complete

---

**Document Version:** 1.0
**Last Updated:** 2025-12-16 23:15 KST
