# PDCA Design: ConfigManager Class Reorganization

## 1. 클래스 구조 재정의 (Class Structure Redefinition)

최종적인 `ConfigManager` 클래스의 구조는 다음과 같은 섹션 순서를 따릅니다:

### Section 1: Initialization
- `__init__(self, config_dir: str = "configs")`
- `_load_configs(self)`

### Section 2: Public Properties
- `is_testnet(self) -> bool`
- `api_config(self) -> APIConfig`
- `trading_config(self) -> TradingConfig`
- `hierarchical_config(self) -> Optional["TradingConfigHierarchical"]`
- `has_hierarchical_config(self) -> bool`
- `logging_config(self) -> LoggingConfig`
- `liquidation_config(self) -> LiquidationConfig`
- `binance_config(self) -> BinanceConfig`

### Section 3: Public Methods
- `validate(self) -> bool`

### Section 4: Private Loaders (Helpers)
- `_load_api_config(self) -> APIConfig`
- `_load_trading_config(self) -> TradingConfig`
- `_load_hierarchical_config(self) -> Optional["TradingConfigHierarchical"]`
- `_load_logging_config(self) -> LoggingConfig`
- `_load_liquidation_config(self) -> LiquidationConfig`
- `_load_binance_config(self) -> BinanceConfig`

## 2. 주요 변경 사항 (Key Changes)

### 2.1 중복 제거
- 파일 하단부(Line 1040 근처)에 존재하는 중복된 `@property api_config`, `trading_config`, `logging_config` 정의를 제거합니다.

### 2.2 메서드 이동
- `validate` 메서드를 공개 메서드 섹션으로 이동합니다.
- `_load_*`로 시작하는 모든 내부 메서드를 클래스 최하단으로 이동합니다.

### 2.3 타입 힌팅 유지
- `hierarchical_config` 관련 프로퍼티와 로더에서 사용되는 `TYPE_CHECKING` 및 내부 임포트 구조를 깨뜨리지 않도록 주의합니다.

## 3. 예외 처리 및 검증 (Exceptions & Validation)
- 변경 후에도 기존의 `ConfigurationError` 발생 로직이 동일하게 작동해야 합니다.
- 테스트 코드를 통해 각 설정값이 올바르게 로드되는지 확인합니다.
