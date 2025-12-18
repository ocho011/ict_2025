# Task 9: Configuration Management Architecture Diagrams

## System Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                       ICT Trading System                              │
│                     Configuration Layer                               │
└──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                   Environment Variables (Highest Priority)           │
├─────────────────────────────────────────────────────────────────────┤
│  BINANCE_API_KEY          │  BINANCE_API_SECRET                     │
│  BINANCE_USE_TESTNET      │                                         │
└───────────────────────┬─────────────────────────────────────────────┘
                        │ Override Priority 1
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ConfigManager                                   │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  __init__(config_dir: str = "configs")                        │ │
│  │  ├─ _load_configs()                                           │ │
│  │  │  ├─ _load_api_config()      ──► APIConfig                 │ │
│  │  │  ├─ _load_trading_config()  ──► TradingConfig             │ │
│  │  │  └─ _load_logging_config()  ──► LoggingConfig             │ │
│  │  └─ validate() -> bool                                        │ │
│  │                                                                │ │
│  │  Properties:                                                  │ │
│  │  • api_config: APIConfig                                      │ │
│  │  • trading_config: TradingConfig                              │ │
│  │  • logging_config: LoggingConfig                              │ │
│  │  • is_testnet: bool                                           │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────┬───────────────────────┬───────────────┬──────────────┘
              │                       │               │
              ▼                       ▼               ▼
    ┌─────────────────┐   ┌──────────────────┐   ┌─────────────────┐
    │   APIConfig     │   │ TradingConfig    │   │ LoggingConfig   │
    ├─────────────────┤   ├──────────────────┤   ├─────────────────┤
    │ • api_key       │   │ • symbol         │   │ • log_level     │
    │ • api_secret    │   │ • intervals[]    │   │ • log_dir       │
    │ • is_testnet    │   │ • strategy       │   │                 │
    │                 │   │ • leverage       │   │ Defaults:       │
    │ Validation:     │   │ • max_risk       │   │ INFO, logs/     │
    │ ✓ Non-empty     │   │ • take_profit    │   │                 │
    │ ✓ No "your_*"   │   │ • stop_loss      │   └─────────────────┘
    │                 │   │                  │
    │                 │   │ Validation:      │
    │                 │   │ ✓ Leverage 1-125 │
    │                 │   │ ✓ Risk 0-10%     │
    │                 │   │ ✓ TP ratio > 0   │
    │                 │   │ ✓ SL 0-50%       │
    │                 │   │ ✓ Symbol ends    │
    │                 │   │   with USDT      │
    │                 │   │ ✓ Valid intervals│
    └─────────────────┘   └──────────────────┘
              ▲                       ▲
              │                       │
        ┌─────┴────────┐        ┌────┴────────┐
        │ api_keys.ini │        │ trading_    │
        │              │        │ config.ini  │
        └──────────────┘        └─────────────┘
```

## Configuration Loading Sequence Diagram

```
User/System         ConfigManager       ConfigParser       Dataclasses       Exceptions
    │                     │                   │                  │                │
    │  new ConfigManager()│                   │                  │                │
    ├────────────────────►│                   │                  │                │
    │                     │                   │                  │                │
    │                     │ _load_configs()   │                  │                │
    │                     ├──────────────────►│                  │                │
    │                     │                   │                  │                │
    │                     │ _load_api_config()│                  │                │
    │                     ├──────────────────►│                  │                │
    │                     │                   │                  │                │
    │                     │  Check ENV vars   │                  │                │
    │                     │◄──────────────────┤                  │                │
    │                     │                   │                  │                │
    │                     │  ENV complete?    │                  │                │
    │                     │─────┐             │                  │                │
    │                     │     │ Yes: Use ENV vars             │                │
    │                     │◄────┘             │                  │                │
    │                     │                   │                  │                │
    │                     │  No: Read INI file│                  │                │
    │                     ├──────────────────►│                  │                │
    │                     │                   │ read(api_keys.ini)│               │
    │                     │                   ├──────────────────►│               │
    │                     │                   │                  │                │
    │                     │  Parse sections   │                  │                │
    │                     │◄──────────────────┤                  │                │
    │                     │                   │                  │                │
    │                     │  Validate env     │                  │                │
    │                     │  selection        │                  │                │
    │                     │─────┐             │                  │                │
    │                     │     │ testnet/mainnet              │                │
    │                     │◄────┘             │                  │                │
    │                     │                   │                  │                │
    │                     │  Check placeholder│                  │                │
    │                     │  values           │                  │                │
    │                     │─────┐             │                  │                │
    │                     │     │ "your_*"?   │                  │                │
    │                     │◄────┘             │                  │                │
    │                     │                   │                  │ Invalid?       │
    │                     │                   │                  │◄───────────────┤
    │                     │                   │                  │ raise          │
    │                     │                   │                  │ ConfigError    │
    │                     │                   │                  │                │
    │                     │  Create APIConfig │                  │                │
    │                     ├──────────────────────────────────────►│                │
    │                     │                   │                  │                │
    │                     │                   │                  │ __post_init__()│
    │                     │                   │                  ├────────┐       │
    │                     │                   │                  │        │Validate│
    │                     │                   │                  │◄───────┘       │
    │                     │                   │                  │                │
    │                     │  APIConfig object │                  │                │
    │                     │◄──────────────────────────────────────┤                │
    │                     │                   │                  │                │
    │                     │ _load_trading_config()               │                │
    │                     ├──────────────────►│                  │                │
    │                     │                   │ read(trading_config.ini)          │
    │                     │                   ├──────────────────►│               │
    │                     │                   │                  │                │
    │                     │  Parse [trading]  │                  │                │
    │                     │  Parse [logging]  │                  │                │
    │                     │◄──────────────────┤                  │                │
    │                     │                   │                  │                │
    │                     │  Create TradingConfig                │                │
    │                     ├──────────────────────────────────────►│                │
    │                     │                   │                  │                │
    │                     │                   │                  │ __post_init__()│
    │                     │                   │                  ├────────┐       │
    │                     │                   │                  │        │Validate│
    │                     │                   │                  │        │leverage│
    │                     │                   │                  │        │risk    │
    │                     │                   │                  │        │TP/SL   │
    │                     │                   │                  │◄───────┘       │
    │                     │                   │                  │                │
    │                     │  TradingConfig    │                  │                │
    │                     │◄──────────────────────────────────────┤                │
    │                     │                   │                  │                │
    │  ConfigManager obj  │                   │                  │                │
    │◄────────────────────┤                   │                  │                │
    │                     │                   │                  │                │
```

## Environment Variable Override Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                   Configuration Priority System                      │
└─────────────────────────────────────────────────────────────────────┘

Priority 1: Direct Environment Override
┌────────────────────────────────────────┐
│  BINANCE_API_KEY = "env_key"           │
│  BINANCE_API_SECRET = "env_secret"     │
│  BINANCE_USE_TESTNET = "true"          │
└────────────────┬───────────────────────┘
                 │
                 ▼
          ┌─────────────┐
          │ Both set?   │
          └──────┬──────┘
                 │ YES
                 ▼
    ┌────────────────────────┐
    │ Use ENV credentials    │
    │ Skip INI file parsing  │
    │ Return APIConfig       │
    └────────────────────────┘


Priority 2: Environment Selection + INI File
┌────────────────────────────────────────┐
│  ENV vars incomplete or not set        │
└────────────────┬───────────────────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │ Read api_keys.ini      │
    └────────────┬───────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │ Check [binance]        │
    │ use_testnet = ?        │
    └────────────┬───────────┘
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ use_testnet  │  │ use_testnet  │
│ = true       │  │ = false      │
└──────┬───────┘  └──────┬───────┘
       │                 │
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│[binance.     │  │[binance.     │
│ testnet]     │  │ mainnet]     │
│ api_key      │  │ api_key      │
│ api_secret   │  │ api_secret   │
└──────┬───────┘  └──────┬───────┘
       │                 │
       └────────┬────────┘
                │
                ▼
       ┌────────────────┐
       │ Validate       │
       │ credentials    │
       │ not "your_*"   │
       └────────┬───────┘
                │
                ▼
       ┌────────────────┐
       │ Create         │
       │ APIConfig      │
       └────────────────┘


ENV Override: BINANCE_USE_TESTNET can override use_testnet
┌────────────────────────────────────────┐
│  BINANCE_USE_TESTNET = "false"         │
└────────────────┬───────────────────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │ Override file setting  │
    │ is_testnet = False     │
    └────────────────────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │ Select [binance.mainnet]│
    └────────────────────────┘
```

## Validation Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Validation Strategy                             │
└─────────────────────────────────────────────────────────────────────┘

Layer 1: Dataclass __post_init__ Validation (Fail-Fast)
┌─────────────────────────────────────────────────────────────────────┐
│  APIConfig.__post_init__()                                           │
│  ├─ Check: api_key not empty                                        │
│  ├─ Check: api_secret not empty                                     │
│  └─ Raise ConfigurationError if invalid                             │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  TradingConfig.__post_init__()                                       │
│  ├─ Check: 1 ≤ leverage ≤ 125                                       │
│  ├─ Check: 0 < max_risk_per_trade ≤ 0.1                            │
│  ├─ Check: take_profit_ratio > 0              [TODO]                │
│  ├─ Check: 0 < stop_loss_percent ≤ 0.5        [TODO]                │
│  ├─ Check: symbol ends with 'USDT'            [TODO]                │
│  ├─ Check: intervals in valid set             [TODO]                │
│  └─ Raise ConfigurationError if invalid                             │
└─────────────────────────────────────────────────────────────────────┘


Layer 2: ConfigManager.validate() (Error Accumulation)  [ENHANCEMENT NEEDED]
┌─────────────────────────────────────────────────────────────────────┐
│  validate() -> bool                                                  │
│  ├─ errors = []                                                      │
│  ├─ Cross-config validation                                         │
│  │  └─ Check: High leverage in testnet (warning)                    │
│  ├─ Log environment mode (TESTNET vs PRODUCTION)                    │
│  ├─ For each error: logger.error(error)                             │
│  └─ Return len(errors) == 0                                         │
└─────────────────────────────────────────────────────────────────────┘


Validation Flow:
┌──────────────┐
│ Create       │
│ dataclass    │
└──────┬───────┘
       │
       ▼
┌──────────────┐         ┌──────────────────┐
│ __post_init__├────────►│ Validation Rules │
└──────┬───────┘         └──────────────────┘
       │
       │ Invalid?
       ├─────────────► raise ConfigurationError("detailed message")
       │
       │ Valid
       ▼
┌──────────────┐
│ Dataclass    │
│ instance     │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ ConfigManager│
│ .validate()  │
└──────┬───────┘
       │
       ├─── Collect all issues
       ├─── Log warnings/errors
       └─── Return bool status
```

## Data Model Class Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         @dataclass                                   │
│                         APIConfig                                    │
├─────────────────────────────────────────────────────────────────────┤
│ Attributes:                                                          │
│  + api_key: str                                                      │
│  + api_secret: str                                                   │
│  + is_testnet: bool = True                                          │
├─────────────────────────────────────────────────────────────────────┤
│ Methods:                                                             │
│  + __post_init__(self) -> None                                      │
│  + __repr__(self) -> str          [TODO: Mask credentials]          │
├─────────────────────────────────────────────────────────────────────┤
│ Validation Rules:                                                    │
│  • api_key must be non-empty                                        │
│  • api_secret must be non-empty                                     │
│  • Raise ConfigurationError if invalid                              │
└─────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                         @dataclass                                   │
│                       TradingConfig                                  │
├─────────────────────────────────────────────────────────────────────┤
│ Attributes:                                                          │
│  + symbol: str                                                       │
│  + intervals: List[str]                                              │
│  + strategy: str                                                     │
│  + leverage: int                                                     │
│  + max_risk_per_trade: float                                        │
│  + take_profit_ratio: float                                         │
│  + stop_loss_percent: float                                         │
├─────────────────────────────────────────────────────────────────────┤
│ Methods:                                                             │
│  + __post_init__(self) -> None                                      │
├─────────────────────────────────────────────────────────────────────┤
│ Validation Rules:                                                    │
│  • 1 ≤ leverage ≤ 125                     ✓ IMPLEMENTED            │
│  • 0 < max_risk_per_trade ≤ 0.1          ✓ IMPLEMENTED            │
│  • take_profit_ratio > 0                  ⚠ TODO                    │
│  • 0 < stop_loss_percent ≤ 0.5           ⚠ TODO                    │
│  • symbol ends with 'USDT'                ⚠ TODO                    │
│  • intervals in valid set                 ⚠ TODO                    │
│  • Raise ConfigurationError if invalid                              │
└─────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                         @dataclass                                   │
│                       LoggingConfig                                  │
├─────────────────────────────────────────────────────────────────────┤
│ Attributes:                                                          │
│  + log_level: str = "INFO"                                          │
│  + log_dir: str = "logs"                                            │
├─────────────────────────────────────────────────────────────────────┤
│ Methods:                                                             │
│  + __post_init__(self) -> None                                      │
├─────────────────────────────────────────────────────────────────────┤
│ Validation Rules:                                                    │
│  • log_level in {DEBUG, INFO, WARNING, ERROR, CRITICAL}            │
│  • Raise ConfigurationError if invalid                              │
└─────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                        ConfigManager                                 │
├─────────────────────────────────────────────────────────────────────┤
│ Attributes:                                                          │
│  + config_dir: Path                                                  │
│  - _api_config: Optional[APIConfig]                                 │
│  - _trading_config: Optional[TradingConfig]                         │
│  - _logging_config: Optional[LoggingConfig]                         │
├─────────────────────────────────────────────────────────────────────┤
│ Methods:                                                             │
│  + __init__(config_dir: str = "configs")                            │
│  - _load_configs() -> None                                          │
│  - _load_api_config() -> APIConfig                                  │
│  - _load_trading_config() -> TradingConfig                          │
│  - _load_logging_config() -> LoggingConfig                          │
│  + validate() -> bool                  [NEEDS ENHANCEMENT]          │
├─────────────────────────────────────────────────────────────────────┤
│ Properties:                                                          │
│  + api_config -> APIConfig                                          │
│  + trading_config -> TradingConfig                                  │
│  + logging_config -> LoggingConfig                                  │
│  + is_testnet -> bool                                               │
└─────────────────────────────────────────────────────────────────────┘
       │
       │ manages
       ▼
   ┌────────┬────────┬────────┐
   │        │        │        │
   ▼        ▼        ▼
APIConfig TradingConfig LoggingConfig
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                  Configuration Error Scenarios                       │
└─────────────────────────────────────────────────────────────────────┘


Scenario 1: Missing Config File
─────────────────────────────────
┌──────────────┐
│ ConfigManager│
│ __init__()   │
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│ _load_api_config()│
└──────┬───────────┘
       │
       ▼
┌──────────────────┐      ┌─────────────────────────────┐
│ api_keys.ini     │─────►│ File not found?             │
│ exists?          │      └─────────┬───────────────────┘
└──────────────────┘                │ YES
                                    ▼
                    ┌───────────────────────────────────┐
                    │ raise ConfigurationError(         │
                    │   "API configuration not found.   │
                    │   Either:                         │
                    │   1. Set BINANCE_API_KEY env, or │
                    │   2. Create api_keys.ini"        │
                    │ )                                 │
                    └───────────────────────────────────┘


Scenario 2: Invalid Credentials (Placeholder)
──────────────────────────────────────────────
┌──────────────────┐
│ Read api_keys.ini│
└──────┬───────────┘
       │
       ▼
┌──────────────────┐      ┌─────────────────────────────┐
│ api_key =        │─────►│ Starts with "your_"?        │
│ "your_testnet_   │      └─────────┬───────────────────┘
│  key_here"       │                │ YES
└──────────────────┘                ▼
                    ┌───────────────────────────────────┐
                    │ raise ConfigurationError(         │
                    │   "Invalid API key in             │
                    │   [binance.testnet].              │
                    │   Please set your actual          │
                    │   credentials."                   │
                    │ )                                 │
                    └───────────────────────────────────┘


Scenario 3: Invalid Validation (Leverage)
──────────────────────────────────────────
┌──────────────────┐
│ Create           │
│ TradingConfig    │
│ leverage=200     │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ __post_init__()  │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐      ┌─────────────────────────────┐
│ Check: 1 ≤       │─────►│ 200 > 125?                  │
│ leverage ≤ 125   │      └─────────┬───────────────────┘
└──────────────────┘                │ YES
                                    ▼
                    ┌───────────────────────────────────┐
                    │ raise ConfigurationError(         │
                    │   "Leverage must be between       │
                    │   1-125, got 200"                │
                    │ )                                 │
                    └───────────────────────────────────┘
```

## File System Layout

```
ict_2025/
├── configs/                          # Configuration directory
│   ├── api_keys.ini                  # Active API credentials (gitignored)
│   ├── api_keys.ini.example          # Template for API setup
│   ├── trading_config.ini            # Active trading config
│   └── trading_config.ini.example    # Template for trading setup
│
├── src/
│   └── utils/
│       └── config.py                 # Configuration management
│           ├── APIConfig             # Dataclass: API credentials
│           ├── TradingConfig         # Dataclass: Trading parameters
│           ├── LoggingConfig         # Dataclass: Logging settings
│           └── ConfigManager         # Main configuration manager
│
├── tests/
│   ├── test_config_environments.py   # Environment override tests
│   └── test_config_validation.py     # Validation rule tests [TODO]
│
└── claudedocs/
    ├── task-9-configuration-design.md       # Complete design document
    └── task-9-architecture-diagram.md       # This file
```

## Integration Points

```
┌─────────────────────────────────────────────────────────────────────┐
│              Configuration System Integration                        │
└─────────────────────────────────────────────────────────────────────┘

ConfigManager
     │
     ├──► Binance Client (Task 3)
     │    └─ Uses: api_config.api_key, api_config.api_secret
     │    └─ Uses: api_config.is_testnet (endpoint selection)
     │
     ├──► Strategy Framework (Task 4)
     │    └─ Uses: trading_config.strategy (strategy selection)
     │    └─ Uses: trading_config.intervals (timeframe setup)
     │
     ├──► Risk Manager (Task 7)
     │    └─ Uses: trading_config.max_risk_per_trade
     │    └─ Uses: trading_config.leverage
     │    └─ Uses: trading_config.take_profit_ratio
     │    └─ Uses: trading_config.stop_loss_percent
     │
     ├──► Logging System (Task 8)
     │    └─ Uses: logging_config.log_level
     │    └─ Uses: logging_config.log_dir
     │
     └──► Main Application (src/main.py)
          └─ Initializes ConfigManager at startup
          └─ Validates configuration before trading
          └─ Provides config to all components
```

## Security Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Security Layers                                   │
└─────────────────────────────────────────────────────────────────────┘

Layer 1: File System Security
┌──────────────────────────────────────┐
│ .gitignore                            │
│ ├─ configs/api_keys.ini              │
│ └─ Prevent credential commits        │
└───────────────┬──────────────────────┘
                │
                ▼
┌──────────────────────────────────────┐
│ File Permissions (Recommended)        │
│ chmod 600 configs/api_keys.ini       │
│ ├─ Owner: read/write                 │
│ └─ Group/Others: no access           │
└──────────────────────────────────────┘


Layer 2: Environment Variable Override
┌──────────────────────────────────────┐
│ CI/CD Secrets Management              │
│ ├─ BINANCE_API_KEY (encrypted)      │
│ └─ BINANCE_API_SECRET (encrypted)   │
└───────────────┬──────────────────────┘
                │ Highest Priority
                ▼
┌──────────────────────────────────────┐
│ Runtime Environment                   │
│ ├─ No credentials in code            │
│ └─ No credentials in version control │
└──────────────────────────────────────┘


Layer 3: Placeholder Detection
┌──────────────────────────────────────┐
│ ConfigManager._load_api_config()     │
│ ├─ Check: api_key.startswith("your_")│
│ ├─ Check: api_secret.startswith(...) │
│ └─ Prevent example credential use    │
└──────────────────────────────────────┘


Layer 4: Credential Masking (TODO)
┌──────────────────────────────────────┐
│ APIConfig.__repr__()                 │
│ ├─ api_key: "ABC1...XYZ9"           │
│ ├─ api_secret: "***"                │
│ └─ Never log full credentials        │
└──────────────────────────────────────┘


Layer 5: Environment Separation
┌──────────────────────────────────────┐
│ Testnet vs Mainnet                    │
│ ├─ [binance.testnet] section        │
│ ├─ [binance.mainnet] section        │
│ ├─ use_testnet flag                 │
│ └─ Clear warnings at startup         │
└──────────────────────────────────────┘
```

## Testing Strategy Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Test Coverage Strategy                          │
└─────────────────────────────────────────────────────────────────────┘

Unit Tests: Dataclass Validation
┌────────────────────────────────┐
│ TestAPIConfigValidation        │
│ ├─ test_valid_config           │
│ ├─ test_empty_api_key_raises   │
│ └─ test_empty_secret_raises    │
└────────────────────────────────┘

┌────────────────────────────────┐
│ TestTradingConfigValidation    │
│ ├─ test_valid_config           │
│ ├─ test_leverage_bounds        │
│ ├─ test_risk_bounds            │
│ ├─ test_tp_ratio_validation    │
│ ├─ test_sl_validation          │
│ ├─ test_symbol_format          │
│ └─ test_interval_validation    │
└────────────────────────────────┘


Integration Tests: File Loading
┌────────────────────────────────┐
│ TestConfigManagerLoading       │
│ ├─ test_load_from_file         │
│ ├─ test_env_var_override       │
│ ├─ test_missing_file_error     │
│ ├─ test_placeholder_detection  │
│ └─ test_environment_selection  │
└────────────────────────────────┘


Edge Case Tests
┌────────────────────────────────┐
│ TestEdgeCases                  │
│ ├─ test_malformed_ini          │
│ ├─ test_mixed_env_file_config  │
│ ├─ test_permission_errors      │
│ └─ test_unicode_handling       │
└────────────────────────────────┘


Test Execution:
pytest tests/test_config*.py -v --cov=src.utils.config --cov-report=term-missing

Target Coverage: 100%
```

---

## Legend

**Symbols Used**:
- `→` : Data flow direction
- `├─` : Tree structure / composition
- `▼` : Process flow / sequence
- `✓` : Completed / Implemented
- `⚠` : Needs implementation
- `[TODO]` : Enhancement required

**Priority Indicators**:
- Priority 1: Highest precedence (environment variables)
- Priority 2: Fallback (INI file configuration)
- Priority 3: Default values

**Status Markers**:
- ✅ COMPLETE: Fully implemented and tested
- ⚠️ PARTIAL: Implemented but needs enhancement
- ❌ TODO: Not yet implemented

---

**Document Version**: 1.0
**Last Updated**: 2025-12-18
**Related**: task-9-configuration-design.md
