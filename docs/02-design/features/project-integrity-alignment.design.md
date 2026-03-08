# Design: Project Integrity Alignment

## 1. 시스템 설계 반영 명세

### 1.1 의존성 (Dependencies)
- `pydantic>=2.6.0`: 전략 모듈의 `ParamSchema` 검증을 위해 필수.
- `pyyaml>=6.0`, `pytz>=2024.1`: 설정 로딩 및 시간 처리를 위해 명시적 선언 필요.
- `pyproject.toml`과 `requirements.txt` 간의 버전 및 목록 동기화.

### 1.2 설정 템플릿 (Config Examples)
- `trading_config.yaml.example`: 
    - `defaults`와 `symbols` 계층 구조 포함.
    - `entry_config`, `stop_loss_config`, `take_profit_config`, `exit_config` 블록을 통한 모듈 조립 예시 제공.
    - `ict_strategy`를 기본값으로 사용.
- 구형 `.ini` 파일 및 파편화된 동적 청산 설정 파일 제거.

### 1.3 유지보수 스크립트 (Operational Scripts)
- **`analyze_ict_conditions.py`**: `ICTOptimalEntryDeterminer`의 `LONG Signal`, `Conditions Fail` 로그 패턴 지원.
- **`test_binance_integration.py`**: `AsyncBinanceClient` 및 `PublicMarketStreamer`를 `BinanceDataCollector`에 주입하여 초기화.
- **`validate_liquidation_config.py`**: `ConfigManager`를 통해 실제 `base.yaml`의 `liquidation` 섹션을 검증.

## 2. 데이터 구조 및 흐름
- `ConfigManager` -> `base.yaml` 로드 -> `TradingConfigHierarchical` 생성 -> `DynamicAssembler`를 통한 모듈 인스턴스화.
- 모든 스크립트는 `src`를 파이썬 경로에 추가하여 모듈을 임포트함.

## 3. 예외 처리
- 누락된 패키지 설치 시 `ConfigurationError` 발생 확인.
- 잘못된 YAML 구조에 대한 스키마 검증 (Pydantic).
