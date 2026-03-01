# INI to YAML Migration Plan

> **Feature**: ini-to-yaml-migration
> **Status**: Draft
> **Author**: Claude Code (PDCA Plan)
> **Created**: 2026-03-01
> **PDCA Phase**: Plan

---

## 1. Overview

### 1.1 목적

`trading_config.ini`를 완전히 제거하고 `configs/base.yaml` 단일 YAML 파일로 대체한다.
`api_keys.ini`는 현행 유지하며, `configparser` 의존성은 API 키 로딩에만 남긴다.

### 1.2 배경

- 이전 PDCA (`dynamic-strategy-config-interface`)에서 YAML 기반 DynamicAssembler 인프라 완성
- 현재 `ConfigManager`는 dual-path (INI fallback + YAML) 구조
- INI의 한계: 중첩 구조 불가, 리스트 표현 어려움, per-symbol 설정 비직관적
- YAML로 통일하여 코드 복잡도 감소 및 유지보수성 향상

### 1.3 범위

| 항목 | 포함 | 제외 |
|------|------|------|
| `trading_config.ini` 전체 섹션 | O | - |
| `api_keys.ini` | - | O (현행 유지) |
| ConfigManager INI 로딩 코드 | O (즉시 제거) | - |
| 마이그레이션 도구 | - | O (즉시 제거 정책) |
| INI fallback 코드 | O (제거) | - |

---

## 2. 사용자 결정사항

| # | 질문 | 결정 |
|---|------|------|
| 1 | 제거 범위 | `trading_config.ini`만 제거, `api_keys.ini` 유지 |
| 2 | YAML 파일 구조 | 계층적 분리: `base.yaml` 내 defaults + symbols 섹션 |
| 3 | API Keys 관리 | 현행 유지 (`api_keys.ini` + 환경변수) |
| 4 | 하위 호환 정책 | 즉시 제거 (INI fallback 코드 완전 제거) |
| 5 | 이전 섹션 범위 | 전체 (binance, trading, logging, liquidation, exit_config, ict_strategy) |
| 6 | 심볼 구조 | `base.yaml` 내 `trading.symbols` 섹션으로 관리 |

---

## 3. AS-IS / TO-BE

### 3.1 AS-IS (현재)

```
configs/
├── trading_config.ini          ← 350줄, 6개 섹션
├── api_keys.ini                ← 유지
└── examples/
    └── dynamic_exit_examples.yaml

ConfigManager._load_configs():
  1. _load_api_config()           → api_keys.ini (ConfigParser)
  2. _load_binance_config()       → trading_config.ini [binance] (ConfigParser)
  3. _load_hierarchical_config()  → trading_config.yaml (YAML, Optional)
  4. _load_trading_config()       → trading_config.ini [trading] (ConfigParser)
  5. _load_logging_config()       → trading_config.ini [logging] (ConfigParser)
  6. _load_liquidation_config()   → trading_config.ini [liquidation] (ConfigParser)

TradingEngine Step 4/4.5:
  if has_hierarchical_config → DynamicAssembler (YAML)
  else → build_module_config (INI)
```

### 3.2 TO-BE (목표)

```
configs/
├── base.yaml                   ← 신규: 전체 설정 통합
├── api_keys.ini                ← 유지 (변경 없음)
└── examples/
    └── dynamic_exit_examples.yaml

ConfigManager._load_configs():
  1. _load_api_config()           → api_keys.ini (ConfigParser, 변경 없음)
  2. _load_yaml_config()          → base.yaml (YAML, 신규 통합 로더)
     → binance, trading, logging, liquidation, exit_config 전부 파싱
     → TradingConfigHierarchical 생성 (항상)
  3. has_hierarchical_config = True (항상)

TradingEngine Step 4/4.5:
  DynamicAssembler (YAML) 경로만 존재 (legacy 분기 제거)
```

---

## 4. YAML 스키마 설계

### 4.1 `configs/base.yaml` 구조

```yaml
# ============================================================
# Trading System Configuration
# ============================================================

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

### 4.2 섹션 매핑 (INI → YAML)

| INI 섹션 | YAML 경로 | 비고 |
|----------|-----------|------|
| `[binance]` | `binance.*` | 최상위 섹션 |
| `[trading]` | `trading.defaults.*` | 글로벌 기본값 |
| `[trading] symbols` | `trading.symbols.*` | 심볼 목록 → 개별 키 |
| `[trading] intervals` | `trading.defaults.intervals[]` | CSV → YAML 리스트 |
| `[ict_strategy]` | `trading.defaults.strategy_params.*` | 전략별 파라미터 |
| `[exit_config]` | `trading.defaults.exit_config.*` | 중첩 객체 |
| `[logging]` | `logging.*` | 최상위 섹션 |
| `[liquidation]` | `liquidation.*` | 최상위 섹션 |

---

## 5. 구현 작업 목록

### Task 1: `configs/base.yaml` 생성

- `trading_config.ini`의 모든 현재 값을 `base.yaml`로 변환
- 위 4.1 스키마에 따라 YAML 파일 작성
- 주석 포함 (INI의 설명을 YAML 주석으로 이전)

### Task 2: ConfigManager YAML 통합 로더 구현

- `_load_yaml_config()` 신규 메서드: `base.yaml` 파싱
- 기존 `_load_hierarchical_config()` 확장하여 전체 섹션 로딩
- `_load_binance_config()` → YAML에서 `binance` 섹션 읽기
- `_load_logging_config()` → YAML에서 `logging` 섹션 읽기
- `_load_liquidation_config()` → YAML에서 `liquidation` 섹션 읽기
- `_load_trading_config()` → YAML `trading.defaults`에서 `TradingConfig` 생성
- `_load_configs()` 진입점 수정

**핵심 변경**: `has_hierarchical_config`가 항상 `True`가 되므로, 프로퍼티 자체를 제거하거나 상수화

### Task 3: TradingEngine legacy 분기 제거

- `if config_manager.has_hierarchical_config:` 분기 제거
- DynamicAssembler 경로만 유지
- `else` 블록의 `build_module_config()` 호출 제거
- `has_hierarchical_config` 체크하는 모든 위치 정리

### Task 4: INI 관련 코드 제거

- `_load_trading_config()` INI 파싱 코드 제거 (ConfigParser 사용 부분)
- `_load_logging_config()` INI 파싱 제거
- `_load_liquidation_config()` INI 파싱 제거
- `_load_binance_config()` INI 파싱 제거
- `from_ini_sections()` 메서드 제거 (`TradingConfigHierarchical`)
- `configparser` import를 `_load_api_config()`에만 유지
- `trading_config.ini` 파일 삭제 (또는 `.example`로 보관)

### Task 5: 테스트 마이그레이션

- **영향받는 테스트 파일** (6개):
  - `tests/test_symbol_config.py` — INI fallback 테스트 수정
  - `tests/test_config_validation.py` — YAML 기반으로 전환
  - `tests/test_config_environments.py` — YAML 기반으로 전환
  - `tests/test_fixes.py` — INI 참조 수정
  - `tests/core/test_trading_engine.py` — `has_hierarchical_config=False` 분기 제거
  - `tests/strategies/test_module_config_builder.py` — legacy 경로 테스트 정리
- 기존 테스트의 INI fixture를 YAML fixture로 변환
- `from_ini_sections()` 테스트 제거
- 신규: `base.yaml` 로딩 통합 테스트 추가

### Task 6: `build_module_config` legacy 경로 정리

- `build_module_config()` 함수 자체는 유지 (DynamicAssembler의 `_legacy_fallback`에서 사용)
- TradingEngine에서의 직접 호출만 제거
- `_STRATEGY_REGISTRY` 기반 빌더 패턴은 DynamicAssembler fallback으로 보존

---

## 6. 영향 분석

### 6.1 수정 대상 파일

| 파일 | 변경 유형 | 영향도 |
|------|-----------|--------|
| `configs/base.yaml` | 신규 생성 | - |
| `configs/trading_config.ini` | 삭제 | High |
| `src/utils/config_manager.py` | 대폭 수정 (INI→YAML) | High |
| `src/core/trading_engine.py` | 분기 제거 | Medium |
| `src/config/symbol_config.py` | `from_ini_sections()` 제거 | Low |
| `tests/test_symbol_config.py` | INI 테스트 수정 | Medium |
| `tests/test_config_validation.py` | YAML 기반 전환 | Medium |
| `tests/test_config_environments.py` | YAML 기반 전환 | Medium |
| `tests/test_fixes.py` | INI 참조 수정 | Low |
| `tests/core/test_trading_engine.py` | 분기 제거 | Low |

### 6.2 제거되는 코드

| 항목 | 예상 제거량 |
|------|------------|
| ConfigManager INI 로딩 (4개 메서드) | ~200줄 |
| TradingEngine legacy 분기 | ~40줄 |
| `from_ini_sections()` | ~50줄 |
| INI 관련 테스트 | ~100줄 |
| **총 제거** | **~390줄** |

### 6.3 추가되는 코드

| 항목 | 예상 추가량 |
|------|------------|
| `_load_yaml_config()` 통합 로더 | ~80줄 |
| `configs/base.yaml` | ~100줄 |
| YAML 기반 테스트 | ~60줄 |
| **총 추가** | **~240줄** |

### 6.4 순 효과: **~150줄 감소**

---

## 7. 리스크 및 완화

| 리스크 | 확률 | 영향 | 완화 방안 |
|--------|------|------|-----------|
| INI 값 → YAML 변환 시 타입 불일치 | Medium | High | `__post_init__` 검증으로 즉시 감지 |
| 테스트 fixture 누락 | Low | Medium | 전체 회귀 테스트로 검증 |
| YAML 파싱 에러 (들여쓰기 등) | Low | High | Pydantic 스키마 검증 추가 |
| `build_module_config` 참조 누락 | Low | Low | Grep으로 전수 검사 |

---

## 8. 검증 기준

| 기준 | 목표 |
|------|------|
| 전체 테스트 통과 | 1189+ tests, 0 failures |
| `trading_config.ini` 참조 | 0건 (코드 내) |
| `ConfigParser` 사용처 | `_load_api_config()`만 |
| `has_hierarchical_config` 참조 | 0건 (제거) |
| `base.yaml` 로딩 성공 | ConfigManager 정상 초기화 |
| legacy 분기 코드 | 0건 |

---

## 9. 구현 순서

```
Task 1: base.yaml 생성
  ↓
Task 2: ConfigManager YAML 통합 로더
  ↓
Task 3: TradingEngine legacy 분기 제거
  ↓
Task 4: INI 관련 코드 제거
  ↓
Task 5: 테스트 마이그레이션
  ↓
Task 6: build_module_config 정리
  ↓
Gap Analysis (PDCA Check)
```

---

## 10. Future Consideration (UI 심볼별 전략 설정 연동)

이번 마이그레이션은 UI 통한 심볼별 전략 설정 기능에 구조적 장애를 만들지 않으나,
향후 UI 구현 시 아래 3가지를 별도 Task로 다루어야 한다.

### 10.1 YAML Write-back 시 주석 소실

`UIConfigHook.apply_config_update()` → `yaml_writer()` 호출 시, 표준 `yaml.dump()`는 모든 주석을 삭제한다. `base.yaml`에 운영 가이드 주석이 많을수록 문제가 커진다.

- **권장 해법**: `ruamel.yaml` 라이브러리 도입 (주석 보존 지원)
- **대안**: 주석은 별도 문서로 분리하고 YAML은 값만 관리

### 10.2 단일 파일 동시 쓰기 충돌

UI에서 여러 심볼의 설정을 동시에 변경하면 `base.yaml` 단일 파일에 대한 concurrent write가 발생할 수 있다. 현재 `UIConfigHook`은 in-memory 업데이트 후 전체 파일을 덮어쓰는 구조이다.

- **권장 해법**: `yaml_writer`에 파일 레벨 `asyncio.Lock` 추가
- **참고**: StrategyHotReloader는 이미 per-symbol Lock 사용 중이므로 패턴 일관성 유지

### 10.3 심볼 동적 추가/제거 API 부재

현재 `UIConfigHook`에는 기존 심볼의 모듈 설정 변경 API만 존재한다 (`apply_config_update`). UI에서 새 심볼 추가 또는 기존 심볼 제거 시, `trading.symbols` 키를 동적으로 관리하는 API가 필요하다.

- **권장 해법**: `UIConfigHook`에 `add_symbol()` / `remove_symbol()` 메서드 추가
- **참고**: 이번 마이그레이션의 범위 밖이며, 현재 Plan이 이를 막지 않음

---

## 11. 관련 문서

| 문서 | 경로 |
|------|------|
| Dynamic Strategy Config Interface (선행 PDCA) | `docs/01-plan/features/dynamic-strategy-config-interface.plan.md` |
| ConfigManager Reorganization | `docs/01-plan/features/config-manager-reorganization.plan.md` |
| TradingConfigHierarchical Architecture | `docs/01-plan/features/TradingConfigHierarchical-Architecture.plan.md` |
