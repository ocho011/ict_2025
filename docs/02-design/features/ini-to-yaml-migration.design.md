# INI to YAML Migration - Design Document

> **Feature**: ini-to-yaml-migration
> **Status**: Draft
> **Author**: Claude Code (PDCA Design)
> **Created**: 2026-03-01
> **PDCA Phase**: Design
> **Plan Reference**: `docs/01-plan/features/ini-to-yaml-migration.plan.md`

---

## 1. Design Overview

### 1.1 목표

`trading_config.ini`의 6개 섹션을 `configs/base.yaml` 단일 파일로 통합하고,
ConfigManager의 INI 파싱 코드를 YAML 기반 통합 로더로 교체한다.

### 1.2 설계 원칙

1. **단일 소스**: 모든 trading 설정은 `base.yaml`에서만 로딩
2. **기존 dataclass 유지**: `BinanceConfig`, `TradingConfig`, `LoggingConfig`, `LiquidationConfig`, `ExitConfig` 구조 변경 없음
3. **즉시 제거**: INI fallback 코드 완전 제거, `configparser` 사용은 `_load_api_config()`만
4. **DynamicAssembler 단일 경로**: `has_hierarchical_config` 분기 제거

---

## 2. AS-IS → TO-BE 아키텍처

### 2.1 AS-IS: Config Loading Flow

```
configs/trading_config.ini ──────────────────────────────┐
  [binance]  ─→ ConfigParser ─→ _load_binance_config()   ─→ BinanceConfig
  [trading]  ─→ ConfigParser ─→ _load_trading_config()    ─→ TradingConfig
  [logging]  ─→ ConfigParser ─→ _load_logging_config()    ─→ LoggingConfig
  [liquidation] → ConfigParser → _load_liquidation_config() → LiquidationConfig
  [ict_strategy] → (merged into strategy_config dict)     ─→ TradingConfig.strategy_config
  [exit_config]  → ConfigParser → (merged into ExitConfig) → TradingConfig.exit_config
                                                          │
configs/trading_config.yaml ── (Optional) ────────────────┤
  trading.defaults/symbols → yaml.safe_load()             │
    → _load_hierarchical_config()                         │
    → TradingConfigHierarchical (or None)                 │
                                                          ▼
                                              ConfigManager._load_configs()
                                                          │
                                              has_hierarchical_config?
                                              ├─ True  → DynamicAssembler
                                              └─ False → build_module_config (legacy)
```

### 2.2 TO-BE: Config Loading Flow

```
configs/base.yaml ───────────────────────────────────────┐
  binance:       → yaml.safe_load() ─→ BinanceConfig     │
  logging:       → yaml.safe_load() ─→ LoggingConfig     │
  liquidation:   → yaml.safe_load() ─→ LiquidationConfig │
  trading:                                                │
    defaults:    → yaml.safe_load() ─→ TradingConfig      │
      strategy_params: → (merged)                         │
      exit_config:     → ExitConfig                       │
    symbols:     → yaml.safe_load() ─→ TradingConfigHierarchical
                                                          │
configs/api_keys.ini ─→ ConfigParser (변경 없음)          │
                                                          ▼
                                              ConfigManager._load_configs()
                                                          │
                                              DynamicAssembler (항상)
```

---

## 3. `configs/base.yaml` 스키마 상세

### 3.1 전체 구조

```yaml
# =============================================================
# ICT 2025 Trading System Configuration
# =============================================================
# 모든 trading 관련 설정을 관리하는 단일 YAML 파일
# API 키는 별도 api_keys.ini 또는 환경변수로 관리

binance:
  rest_testnet_url: "https://testnet.binancefuture.com"
  rest_mainnet_url: "https://fapi.binance.com"
  ws_testnet_url: "wss://stream.binancefuture.com"
  ws_mainnet_url: "wss://fstream.binance.com"
  user_ws_testnet_url: "wss://stream.binancefuture.com/ws"
  user_ws_mainnet_url: "wss://fstream.binance.com/ws"

logging:
  log_level: "INFO"
  log_dir: "logs"
  log_live_data: false

liquidation:
  emergency_liquidation: true
  close_positions: true
  cancel_orders: true
  timeout_seconds: 5.0
  max_retries: 3
  retry_delay_seconds: 0.5

trading:
  defaults:
    strategy: "ict_strategy"
    strategy_type: "composable"
    leverage: 1
    max_risk_per_trade: 0.01
    take_profit_ratio: 2.0
    stop_loss_percent: 0.02
    max_symbols: 10
    backfill_limit: 200
    margin_type: "ISOLATED"
    intervals:
      - "1m"
      - "5m"
      - "15m"

    strategy_params:
      ltf_interval: "1m"
      mtf_interval: "5m"
      htf_interval: "15m"
      active_profile: "RELAXED"
      buffer_size: 200
      rr_ratio: 2.0
      use_killzones: false

    exit_config:
      dynamic_exit_enabled: true
      exit_strategy: "trailing_stop"
      trailing_distance: 0.02
      trailing_activation: 0.01
      breakeven_enabled: true
      breakeven_offset: 0.001
      timeout_enabled: false
      timeout_minutes: 240
      volatility_enabled: false
      atr_period: 14
      atr_multiplier: 2.0

  symbols:
    BTCUSDT:
      leverage: 1
    ETHUSDT:
      leverage: 1
    ZECUSDT:
      leverage: 1
    XRPUSDT:
      leverage: 1
    TAOUSDT:
      leverage: 1
    DOTUSDT:
      leverage: 1
    DOGEUSDT:
      leverage: 1
```

### 3.2 YAML → Dataclass 매핑

| YAML 경로 | Dataclass | 필드 | 타입 변환 |
|-----------|-----------|------|-----------|
| `binance.rest_testnet_url` | `BinanceConfig` | `rest_testnet_url` | str (직접) |
| `binance.rest_mainnet_url` | `BinanceConfig` | `rest_mainnet_url` | str (직접) |
| `binance.ws_*` | `BinanceConfig` | `ws_*` | str (직접) |
| `logging.log_level` | `LoggingConfig` | `log_level` | str (직접) |
| `logging.log_dir` | `LoggingConfig` | `log_dir` | str (직접) |
| `logging.log_live_data` | `LoggingConfig` | `log_live_data` | bool (YAML 네이티브) |
| `liquidation.*` | `LiquidationConfig` | 동일 필드명 | 직접 매핑 |
| `trading.defaults.strategy` | `TradingConfig` | `strategy` | str |
| `trading.defaults.intervals` | `TradingConfig` | `intervals` | List[str] (YAML 리스트) |
| `trading.defaults.exit_config.*` | `ExitConfig` | 동일 필드명 | 직접 매핑 |
| `trading.defaults.strategy_params.*` | `TradingConfig` | `strategy_config` | Dict[str, Any] |
| `trading.symbols.*` | `SymbolConfig` | per-symbol | `TradingConfigHierarchical.from_dict()` |

**INI vs YAML 타입 변환 비교:**

| INI (ConfigParser) | YAML (yaml.safe_load) | 비고 |
|----|------|------|
| `getboolean("key", True)` | `data.get("key", True)` | YAML은 `true`/`false` 네이티브 |
| `getint("key", 1)` | `int(data.get("key", 1))` | YAML은 정수 네이티브 |
| `getfloat("key", 0.01)` | `float(data.get("key", 0.01))` | YAML은 실수 네이티브 |
| `"a, b, c".split(",")` | `["a", "b", "c"]` | YAML 리스트 네이티브 |

---

## 4. ConfigManager 변경 상세

### 4.1 제거 대상 메서드

| 메서드 | 현재 역할 | 제거 후 |
|--------|-----------|---------|
| `_load_trading_config()` | INI → TradingConfig | `_parse_trading_config()` 로 교체 |
| `_load_logging_config()` | INI → LoggingConfig | `_parse_logging_config()` 로 교체 |
| `_load_liquidation_config()` | INI → LiquidationConfig | `_parse_liquidation_config()` 로 교체 |
| `_load_binance_config()` | INI → BinanceConfig | `_parse_binance_config()` 로 교체 |
| `_load_hierarchical_config()` | YAML → Optional[TCH] | 통합 로더에 흡수 |

### 4.2 신규 메서드

#### `_load_yaml_config()` — 통합 YAML 로더

```python
def _load_yaml_config(self) -> Dict[str, Any]:
    """
    Load and parse base.yaml configuration file.

    Returns:
        Parsed YAML data dictionary

    Raises:
        ConfigurationError: If base.yaml not found or invalid
    """
    yaml_file = self.config_dir / "base.yaml"

    if not yaml_file.exists():
        raise ConfigurationError(
            f"Configuration file not found: {yaml_file}\n"
            f"Please create {yaml_file} from base.yaml.example"
        )

    with open(yaml_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ConfigurationError(f"Empty configuration file: {yaml_file}")

    return data
```

#### `_parse_binance_config(data)` — YAML → BinanceConfig

```python
def _parse_binance_config(self, data: Dict[str, Any]) -> BinanceConfig:
    """Parse binance section from YAML data."""
    binance = data.get("binance", {})
    return BinanceConfig(**{
        k: binance.get(k, getattr(BinanceConfig, k, None) or BinanceConfig().__dict__[k])
        for k in BinanceConfig.__dataclass_fields__
        if k in binance
    }) if binance else BinanceConfig()
```

**간소화 구현** (실제 적용):

```python
def _parse_binance_config(self, data: Dict[str, Any]) -> BinanceConfig:
    """Parse binance section from YAML data."""
    binance = data.get("binance", {})
    if not binance:
        return BinanceConfig()
    return BinanceConfig(
        rest_testnet_url=binance.get("rest_testnet_url", "https://testnet.binancefuture.com"),
        rest_mainnet_url=binance.get("rest_mainnet_url", "https://fapi.binance.com"),
        ws_testnet_url=binance.get("ws_testnet_url", "wss://stream.binancefuture.com"),
        ws_mainnet_url=binance.get("ws_mainnet_url", "wss://fstream.binance.com"),
        user_ws_testnet_url=binance.get("user_ws_testnet_url", "wss://stream.binancefuture.com/ws"),
        user_ws_mainnet_url=binance.get("user_ws_mainnet_url", "wss://fstream.binance.com/ws"),
    )
```

#### `_parse_logging_config(data)` — YAML → LoggingConfig

```python
def _parse_logging_config(self, data: Dict[str, Any]) -> LoggingConfig:
    """Parse logging section from YAML data."""
    log = data.get("logging", {})
    if not log:
        return LoggingConfig()
    return LoggingConfig(
        log_level=log.get("log_level", "INFO"),
        log_dir=log.get("log_dir", "logs"),
        log_live_data=log.get("log_live_data", True),
    )
```

#### `_parse_liquidation_config(data)` — YAML → LiquidationConfig

```python
def _parse_liquidation_config(self, data: Dict[str, Any]) -> LiquidationConfig:
    """Parse liquidation section from YAML data."""
    liq = data.get("liquidation", {})
    if not liq:
        return LiquidationConfig()
    return LiquidationConfig(
        emergency_liquidation=liq.get("emergency_liquidation", True),
        close_positions=liq.get("close_positions", True),
        cancel_orders=liq.get("cancel_orders", True),
        timeout_seconds=float(liq.get("timeout_seconds", 5.0)),
        max_retries=int(liq.get("max_retries", 3)),
        retry_delay_seconds=float(liq.get("retry_delay_seconds", 0.5)),
    )
```

#### `_parse_trading_config(data)` — YAML → TradingConfig + TradingConfigHierarchical

```python
def _parse_trading_config(self, data: Dict[str, Any]) -> TradingConfig:
    """
    Parse trading section from YAML data.

    Creates TradingConfig from trading.defaults and
    TradingConfigHierarchical from trading.symbols.
    """
    trading = data.get("trading", {})
    if not trading:
        raise ConfigurationError("'trading' section required in base.yaml")

    defaults = trading.get("defaults", {})

    # Parse exit_config from nested object
    exit_config = None
    exit_data = defaults.get("exit_config", {})
    if exit_data:
        exit_config = ExitConfig(
            dynamic_exit_enabled=exit_data.get("dynamic_exit_enabled", True),
            exit_strategy=exit_data.get("exit_strategy", "trailing_stop"),
            trailing_distance=float(exit_data.get("trailing_distance", 0.02)),
            trailing_activation=float(exit_data.get("trailing_activation", 0.01)),
            breakeven_enabled=exit_data.get("breakeven_enabled", True),
            breakeven_offset=float(exit_data.get("breakeven_offset", 0.001)),
            timeout_enabled=exit_data.get("timeout_enabled", False),
            timeout_minutes=int(exit_data.get("timeout_minutes", 240)),
            volatility_enabled=exit_data.get("volatility_enabled", False),
            atr_period=int(exit_data.get("atr_period", 14)),
            atr_multiplier=float(exit_data.get("atr_multiplier", 2.0)),
        )

    # Parse symbols list from trading.symbols keys
    symbols_data = trading.get("symbols", {})
    symbols = list(symbols_data.keys()) if symbols_data else ["BTCUSDT"]

    # Validate max_symbols
    max_symbols = int(defaults.get("max_symbols", 10))
    if not (1 <= max_symbols <= 20):
        raise ConfigurationError(f"max_symbols must be 1-20, got {max_symbols}")

    # strategy_params = strategy-specific config (replaces [ict_strategy] section)
    strategy_config = defaults.get("strategy_params", {})

    return TradingConfig(
        symbols=symbols,
        intervals=defaults.get("intervals", ["1m", "5m", "15m"]),
        strategy=defaults.get("strategy", "ict_strategy"),
        leverage=int(defaults.get("leverage", 1)),
        max_risk_per_trade=float(defaults.get("max_risk_per_trade", 0.01)),
        take_profit_ratio=float(defaults.get("take_profit_ratio", 2.0)),
        stop_loss_percent=float(defaults.get("stop_loss_percent", 0.02)),
        backfill_limit=int(defaults.get("backfill_limit", 100)),
        margin_type=defaults.get("margin_type", "ISOLATED"),
        strategy_config=strategy_config,
        exit_config=exit_config,
        max_symbols=max_symbols,
        strategy_type=defaults.get("strategy_type", "composable"),
    )
```

### 4.3 `_load_configs()` 변경

```python
# AS-IS
def _load_configs(self):
    self._api_config = self._load_api_config()
    self._binance_config = self._load_binance_config()        # INI
    self._hierarchical_config = self._load_hierarchical_config()  # YAML (Optional)
    self._trading_config = self._load_trading_config()          # INI
    self._logging_config = self._load_logging_config()          # INI
    self._liquidation_config = self._load_liquidation_config()  # INI

# TO-BE
def _load_configs(self):
    self._api_config = self._load_api_config()        # api_keys.ini (변경 없음)

    yaml_data = self._load_yaml_config()               # base.yaml 로드 (신규)
    self._binance_config = self._parse_binance_config(yaml_data)
    self._trading_config = self._parse_trading_config(yaml_data)
    self._logging_config = self._parse_logging_config(yaml_data)
    self._liquidation_config = self._parse_liquidation_config(yaml_data)
    self._hierarchical_config = self._parse_hierarchical_config(yaml_data)
```

### 4.4 `_parse_hierarchical_config()` — 항상 생성

```python
def _parse_hierarchical_config(self, data: Dict[str, Any]) -> "TradingConfigHierarchical":
    """
    Parse hierarchical per-symbol config from YAML data.

    Unlike the old _load_hierarchical_config() which returned Optional,
    this always returns a TradingConfigHierarchical instance.
    """
    from src.config.symbol_config import TradingConfigHierarchical

    trading_data = data.get("trading", {})
    return TradingConfigHierarchical.from_dict(trading_data)
```

### 4.5 프로퍼티 변경

```python
# 제거
@property
def has_hierarchical_config(self) -> bool:
    return self._hierarchical_config is not None

# hierarchical_config 프로퍼티는 유지하되, 항상 non-None 반환
@property
def hierarchical_config(self) -> "TradingConfigHierarchical":
    """Get hierarchical per-symbol configuration (always available)."""
    return self._hierarchical_config
```

---

## 5. TradingEngine 변경 상세

### 5.1 Step 4/4.5: Legacy 분기 제거

```python
# AS-IS (lines 180-266)
if config_manager.has_hierarchical_config:
    # DynamicAssembler path (~35 lines)
    ...
    self._deferred_assembler = assembler
    self._deferred_hierarchical = hierarchical
else:
    # Legacy path (~50 lines) ← 제거
    ...

# TO-BE
# Step 4/4.5: Create strategy instances via DynamicAssembler
from src.strategies import StrategyFactory
from src.strategies.dynamic_assembler import DynamicAssembler

hierarchical = config_manager.hierarchical_config
assembler = DynamicAssembler()

self.logger.info("Creating strategies via DynamicAssembler...")
self.strategies = {}
for symbol in trading_config.symbols:
    symbol_config = hierarchical.get_symbol_config(symbol)
    module_config, intervals, min_rr_ratio = assembler.assemble_for_symbol(symbol_config)

    strat_config = {
        "buffer_size": 100,
        "risk_reward_ratio": trading_config.take_profit_ratio,
        "stop_loss_percent": trading_config.stop_loss_percent,
    }
    if symbol_config.strategy_params:
        strat_config.update(symbol_config.strategy_params)

    self.strategies[symbol] = StrategyFactory.create_composed(
        symbol=symbol,
        config=strat_config,
        module_config=module_config,
        intervals=intervals,
        min_rr_ratio=min_rr_ratio,
    )
    self.logger.info(f"  Strategy created for {symbol}")

self._deferred_assembler = assembler
self._deferred_hierarchical = hierarchical
```

### 5.2 Step 6.4: StrategyHotReloader (분기 제거)

```python
# AS-IS (lines 332-341)
if config_manager.has_hierarchical_config:
    from src.core.strategy_hot_reloader import StrategyHotReloader
    self.strategy_hot_reloader = StrategyHotReloader(...)

# TO-BE
from src.core.strategy_hot_reloader import StrategyHotReloader
self.strategy_hot_reloader = StrategyHotReloader(
    strategies=self.strategies,
    assembler=self._deferred_assembler,
    hierarchical_config=self._deferred_hierarchical,
    position_closer=self.position_cache_manager,
    audit_logger=self.audit_logger,
)
```

---

## 6. symbol_config.py 변경

### 6.1 `from_ini_sections()` 제거

```python
# 제거 대상: TradingConfigHierarchical.from_ini_sections() (lines 322-391)
# 이유: INI 소스가 없으므로 더 이상 필요 없음
# from_dict()만 유지
```

### 6.2 모듈 docstring 업데이트

```python
# AS-IS
"""
...
- YAML and INI format support
...
"""

# TO-BE
"""
...
- YAML format support (base.yaml)
...
"""
```

---

## 7. 테스트 변경 상세

### 7.1 영향받는 테스트 파일과 변경 방향

| 파일 | 현재 | 변경 |
|------|------|------|
| `tests/test_symbol_config.py` | `from_ini_sections()` 테스트, `has_hierarchical_config` 테스트 | INI 관련 테스트 제거, YAML-only 테스트로 전환 |
| `tests/test_config_validation.py` | INI fixture로 검증 | YAML fixture로 전환, 동일 검증 로직 유지 |
| `tests/test_config_environments.py` | INI 파일 기반 환경 테스트 | YAML 파일 기반으로 전환 |
| `tests/test_fixes.py` | INI 파일 경로 참조 | `base.yaml` 경로로 변경 |
| `tests/core/test_trading_engine.py` | `has_hierarchical_config = False` 설정 | 해당 mock 제거, DynamicAssembler 경로 테스트만 유지 |

### 7.2 테스트 fixture 전환 패턴

```python
# AS-IS: INI fixture
@pytest.fixture
def config_ini(tmp_path):
    ini_content = """
    [trading]
    symbols = BTCUSDT
    leverage = 1
    """
    config_file = tmp_path / "trading_config.ini"
    config_file.write_text(ini_content)
    return tmp_path

# TO-BE: YAML fixture
@pytest.fixture
def config_yaml(tmp_path):
    yaml_content = {
        "trading": {
            "defaults": {
                "strategy": "ict_strategy",
                "leverage": 1,
                "intervals": ["1m", "5m", "15m"],
            },
            "symbols": {
                "BTCUSDT": {"leverage": 1}
            }
        }
    }
    config_file = tmp_path / "base.yaml"
    with open(config_file, "w") as f:
        yaml.dump(yaml_content, f)
    return tmp_path
```

### 7.3 신규 테스트

```python
# tests/test_yaml_config_loading.py (신규)

class TestYamlConfigLoading:
    """base.yaml 통합 로딩 테스트"""

    def test_load_complete_config(self):
        """전체 base.yaml 로딩 성공"""

    def test_missing_base_yaml_raises_error(self):
        """base.yaml 없으면 ConfigurationError"""

    def test_empty_base_yaml_raises_error(self):
        """빈 base.yaml이면 ConfigurationError"""

    def test_missing_trading_section_raises_error(self):
        """trading 섹션 없으면 ConfigurationError"""

    def test_binance_defaults_when_section_missing(self):
        """binance 섹션 없으면 기본값 사용"""

    def test_logging_defaults_when_section_missing(self):
        """logging 섹션 없으면 기본값 사용"""

    def test_liquidation_defaults_when_section_missing(self):
        """liquidation 섹션 없으면 기본값 사용"""

    def test_symbols_from_yaml_keys(self):
        """trading.symbols 키 목록이 TradingConfig.symbols가 됨"""

    def test_exit_config_nested_parsing(self):
        """trading.defaults.exit_config 중첩 파싱"""

    def test_strategy_params_as_strategy_config(self):
        """trading.defaults.strategy_params → TradingConfig.strategy_config"""

    def test_hierarchical_config_always_created(self):
        """hierarchical_config가 항상 non-None"""

    def test_intervals_as_yaml_list(self):
        """intervals가 YAML 리스트로 직접 파싱 (CSV split 불필요)"""
```

---

## 8. 삭제 대상 정리

### 8.1 파일 삭제

| 파일 | 이유 |
|------|------|
| `configs/trading_config.ini` | YAML로 완전 대체 |

### 8.2 코드 삭제

| 위치 | 대상 | 줄 수 |
|------|------|-------|
| `config_manager.py` | `_load_trading_config()` | ~100줄 |
| `config_manager.py` | `_load_logging_config()` | ~20줄 |
| `config_manager.py` | `_load_liquidation_config()` | ~35줄 |
| `config_manager.py` | `_load_binance_config()` | ~45줄 |
| `config_manager.py` | `_load_hierarchical_config()` | ~40줄 |
| `config_manager.py` | `has_hierarchical_config` 프로퍼티 | ~3줄 |
| `symbol_config.py` | `from_ini_sections()` 클래스메서드 | ~70줄 |
| `trading_engine.py` | `else:` legacy 분기 블록 | ~50줄 |
| `trading_engine.py` | `if has_hierarchical_config:` (Step 6.4) | ~2줄 (조건만) |
| **합계** | | **~365줄** |

### 8.3 import 정리

```python
# config_manager.py
# AS-IS
from configparser import ConfigParser  # 전체 사용

# TO-BE
from configparser import ConfigParser  # _load_api_config()에서만 사용
# 나머지 메서드에서 ConfigParser 참조 제거
```

---

## 9. 시퀀스 다이어그램

### 9.1 TO-BE: ConfigManager 초기화

```
User                ConfigManager              base.yaml         api_keys.ini
  |                      |                        |                    |
  |-- __init__() ------->|                        |                    |
  |                      |-- _load_configs() ---->|                    |
  |                      |                        |                    |
  |                      |-- _load_api_config() --|------ read ------->|
  |                      |<-- APIConfig ----------|                    |
  |                      |                        |                    |
  |                      |-- _load_yaml_config() -|--- yaml.safe_load |
  |                      |<-- Dict[str, Any] -----|                    |
  |                      |                        |                    |
  |                      |-- _parse_binance_config(data)               |
  |                      |<-- BinanceConfig                            |
  |                      |                                             |
  |                      |-- _parse_trading_config(data)               |
  |                      |   |-- parse defaults → TradingConfig        |
  |                      |   |-- parse exit_config → ExitConfig        |
  |                      |<--|                                         |
  |                      |                                             |
  |                      |-- _parse_logging_config(data)               |
  |                      |<-- LoggingConfig                            |
  |                      |                                             |
  |                      |-- _parse_liquidation_config(data)           |
  |                      |<-- LiquidationConfig                        |
  |                      |                                             |
  |                      |-- _parse_hierarchical_config(data)          |
  |                      |<-- TradingConfigHierarchical (항상 non-None)|
  |<-- ready ------------|                                             |
```

### 9.2 TO-BE: TradingEngine 전략 생성

```
TradingEngine           ConfigManager        DynamicAssembler      StrategyFactory
     |                       |                      |                     |
     |-- hierarchical_config |                      |                     |
     |<-- TCH (always) ------|                      |                     |
     |                       |                      |                     |
     |-- DynamicAssembler() ----------------------->|                     |
     |                       |                      |                     |
     |-- for symbol in symbols:                     |                     |
     |   |-- assemble_for_symbol(symbol_config) --->|                     |
     |   |<-- (module_config, intervals, min_rr) ---|                     |
     |   |                                          |                     |
     |   |-- create_composed(symbol, ...) -------------------------------->|
     |   |<-- ComposableStrategy ------------------------------------------|
     |                       |                      |                     |
     |-- StrategyHotReloader(strategies, assembler, ...) ← 무조건 생성    |
```

---

## 10. 검증 체크리스트

| # | 검증 항목 | 방법 | 기대 결과 |
|---|-----------|------|-----------|
| 1 | `base.yaml` 로딩 성공 | `ConfigManager("configs")` | 에러 없이 초기화 |
| 2 | `trading_config.ini` 참조 0건 | `grep -r "trading_config.ini" src/` | 결과 없음 |
| 3 | `ConfigParser` 사용처 | `grep -r "ConfigParser" src/` | `_load_api_config`만 |
| 4 | `has_hierarchical_config` 참조 0건 | `grep -r "has_hierarchical_config"` | 결과 없음 |
| 5 | `from_ini_sections` 참조 0건 | `grep -r "from_ini_sections"` | 결과 없음 |
| 6 | 전체 테스트 통과 | `pytest` | 0 failures |
| 7 | DynamicAssembler 단일 경로 | `trading_engine.py` 코드 리뷰 | `if/else` 분기 없음 |
| 8 | StrategyHotReloader 항상 생성 | `trading_engine.py` 코드 리뷰 | 조건문 없음 |

---

## 11. 관련 문서

| 문서 | 경로 |
|------|------|
| Plan | `docs/01-plan/features/ini-to-yaml-migration.plan.md` |
| Dynamic Strategy Config Interface (선행) | `docs/02-design/features/dynamic-strategy-config-interface.design.md` |
