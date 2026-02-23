# Feature Plan: 모듈 조립형 아키텍처 확장을 위한 리팩토링

## 1. 개요 (Overview)

### 1.1 배경
본 프로젝트는 ICT(Inner Circle Trader) 이론 기반 선물 자동매매 시스템으로 시작되었으나, 현재 모듈 조립형 전략으로 확장 중입니다. 최초 설계는 ICT 특화 패턴에 최적화되어 있었으나, ComposableStrategy 패턴 도입 후 다양한 전략 타입을 지원할 수 있는 구조로 진화하고 있습니다.

### 1.2 목표
- ICT 특화 설계를 모듈 조립형 확장에 맞게 리팩토링
- 새로운 전략 타입 추가 시 최소한의 변경만 필요하도록 구조화
- 백테스팅/Paper Trading 지원을 위한 추상화 계층 도입
- 실행 레이어와 전략 레이어의 완전한 분리

### 1.3 범위
| 영역 | 현재 상태 | 목표 상태 |
|------|-----------|-----------|
| **설정 레이어** | ICT 전용 필드 하드코딩 | 범용 strategy_config + Registry |
| 전략 레이어 | ComposableStrategy 구현됨 | 완전한 모듈화, 새 전략 타입 용이 |
| 이벤트 파이프라인 | EventBus + EventDispatcher | 다중 전략 지원, 백테스팅 리플레이 |
| 실행 레이어 | OrderGateway 직접 호출 | ExecutionProtocol 추상화 |
| 데이터 레이어 | WebSocket 중심 | 데이터 소스 추상화 |

### 1.4 완료된 항목
| 항목 | 완료일 | 커밋 |
|------|--------|------|
| ModuleRequirements (데이터 요구사항 자기선언) | 2026-02-23 | c8d14f6 |
| ComposableStrategy 4-Determiner 패턴 | 이전 완료 | - |
| PriceContext.extras 범용화 | 이전 완료 | - |
| EntryDecision.price_extras 분리 | 이전 완료 | - |

---

## 2. 현재 아키텍처 분석

### 2.1 설정 레이어 (Config Layer) — 신규 분석

> **PDCA 분석(2026-02-23)에서 발견**: 기존 Plan에서 누락되었던 영역.
> Config 레이어의 ICT 하드코딩이 모듈 확장성의 가장 큰 병목.

#### 현황
설정 레이어에 ICT 전략 전용 필드와 분기 로직이 산재되어 있어,
**새 전략 추가 시 최소 5개 파일을 수정**해야 하는 구조.

#### 커플링 포인트 상세

| 파일 | 위치 | 문제점 | 심각도 |
|------|------|--------|--------|
| `config_manager.py:202` | `TradingConfig.ict_config` | ICT 전용 필드가 글로벌 설정에 존재. 새 전략마다 필드 추가 필요 | **Critical** |
| `symbol_config.py:41` | `VALID_STRATEGIES` | 하드코딩된 전략명 집합. `momentum_strategy` 등록됨에도 구현 없음 (런타임 ValueError) | **Critical** |
| `symbol_config.py:85-86` | `ict_config`/`momentum_config` 필드 | 전략별 별도 필드 → 전략 추가마다 SymbolConfig 클래스 수정 | **High** |
| `symbol_config.py:152-163` | `get_strategy_config()` | if/elif 체인으로 전략별 config 분기 | **High** |
| `symbol_config.py:185-189` | `to_trading_config_dict()` | if/elif 체인으로 전략별 dict 변환 분기 | **High** |
| `symbol_config.py:350-358` | `from_ini_sections()` | ICT config 키 하드코딩 파싱 | **Medium** |
| `trading_engine.py:186-191` | `initialize_components()` | `if trading_config.ict_config is not None:` 분기 | **High** |
| `module_config_builder.py:86-96` | `build_module_config()` | 3개 전략에 대한 if/elif 체인 | **High** |

#### 구체적 리팩토링 항목

| ID | 항목 | 우선순위 | 영향도 | 작업량 |
|----|------|----------|--------|--------|
| C-1 | TradingConfig 범용화: `ict_config` → `strategy_config: Dict[str, Any]` | **Critical** | High | Low |
| C-2 | SymbolConfig 범용화: `ict_config`/`momentum_config` → `strategy_params: Dict[str, Any]` | **Critical** | High | Medium |
| C-3 | VALID_STRATEGIES 동적화: 하드코딩 set → Registry에서 자동 생성 | High | Medium | Low |
| C-4 | `momentum_strategy` 유령 등록 제거 또는 stub 구현 | **Immediate** | Low | Trivial |
| R-1 | Strategy Registry 패턴 도입: `module_config_builder.py` if/elif → dict registry | High | High | Medium |

#### 목표 구조

```python
# Before (현재): 전략별 필드 추가 필요
class TradingConfig:
    ict_config: Optional[Dict] = None      # ICT 전용
    momentum_config: Optional[Dict] = None  # Momentum 전용
    # 새 전략마다 필드 추가...

# After (목표): 범용 필드 1개
class TradingConfig:
    strategy_config: Dict[str, Any] = field(default_factory=dict)  # 전략별 config 통합

# Before (현재): if/elif 체인
def build_module_config(strategy_name, ...):
    if strategy_name == "ict_strategy":
        return _build_ict_config(...)
    elif strategy_name == "mock_sma":
        return _build_sma_config(...)

# After (목표): Registry 패턴
_REGISTRY: Dict[str, StrategyBuilder] = {}

def register_strategy(name: str, builder: StrategyBuilder):
    _REGISTRY[name] = builder

def build_module_config(strategy_name, ...):
    if strategy_name not in _REGISTRY:
        raise ValueError(f"Unknown strategy: {strategy_name}. Available: {list(_REGISTRY)}")
    return _REGISTRY[strategy_name](strategy_config, exit_config)

# 각 전략 패키지에서 자체 등록
# src/strategies/ict/__init__.py
register_strategy("ict_strategy", _build_ict_config)
```

### 2.2 전략 레이어 (Strategy Layer)

#### 강점
```
✅ ComposableStrategy: 4개 Determiner 조립 패턴 구현
✅ EntryDeterminer/ExitDeterminer/StopLossDeterminer/TakeProfitDeterminer 인터페이스 정의
✅ PriceContext.extras: Dict[str, Any] - ICT 특화 필드 제거 완료
✅ EntryDecision.price_extras - 메타데이터 분리 완료
✅ StrategyModuleConfig - 모듈 설정 번들
✅ ModuleRequirements - 데이터 요구사항 선언 (c8d14f6, 완료)
```

#### 개선 필요사항
```
⚠️ BaseStrategy (946 lines) - 책임 과다
   - 버퍼 관리, 지표 캐시, 초기화, 설정 검증 등 혼재
   - 제안: BufferManager, IndicatorCacheManager로 분리

⚠️ ICT 특화 로직이 여러 패키지에 분산 (총 11개 파일)
   - src/entry/ict_entry.py, src/exit/ict_exit.py
   - src/detectors/ict_*.py (6개)
   - src/pricing/stop_loss/zone_based.py, src/pricing/take_profit/displacement.py
   - src/config/ict_profiles.py, src/strategies/indicator_cache.py
   - 제안: ICT 모듈을 별도 패키지로 격리 + Registry 자동 등록

⚠️ BaseDetector ABC (src/detectors/base.py) 미활용
   - pd.DataFrame 인터페이스 정의되었으나, 실제 ICT detector들은 순수 함수로 구현
   - ICTEntryDeterminer가 직접 호출
   - 제안: S-2에서 ICT 패키지 격리 시 정리
```

#### 구체적 리팩토링 항목

| ID | 항목 | 우선순위 | 영향도 | 작업량 |
|----|------|----------|--------|--------|
| S-1 | BaseStrategy 책임 분리 (BufferManager 추출) | High | High | Medium |
| S-2 | ICT 모듈 패키지 격리 (src/strategies/ict/) + Registry 등록 | Medium | Medium | Medium |
| S-3 | Determiner 인터페이스 확장 (pre_analyze/post_analyze 훅) | Low | Medium | Low |
| S-4 | 전략 타입 추가 가이드라인 문서화 | Medium | Low | Low |

### 2.3 이벤트 파이프라인 (Event Pipeline)

#### 강점
```
✅ EventBus: 4개 Queue (CANDLE_UPDATE, CANDLE_CLOSED, SIGNAL, ORDER)
✅ 우선순위 기반 처리 (ORDER queue는 timeout 없음 - critical)
✅ EventDispatcher: 캔들 → 전략 라우팅 (전략 무관, 범용적)
✅ TradeCoordinator: Signal → Order 변환 (전략 무관, 범용적)
✅ WebSocket → EventBus → Strategy → Execution 흐름 확립
```

#### 개선 필요사항
```
⚠️ 다중 전략 동시 실행 미지원
   - 현재: symbol당 단일 전략 (Dict[str, BaseStrategy])
   - SMC/ICT 변형 전략 동시 운용 시 필수
   - 제안: strategy_id 기반 이벤트 라우팅

⚠️ 백테스팅을 위한 이벤트 리플레이 미지원
   - 현재: 실시간 WebSocket만 지원
   - 제안: HistoricalEventPlayer 구현

⚠️ Signal 생성자 추적 불완전
   - Signal.strategy_name은 문자열만 보유
   - 다중 전략 환경에서 Signal 출처 추적 불가
   - 제안: strategy_id, determiner_chain 메타데이터 추가
```

#### 구체적 리팩토링 항목

| ID | 항목 | 우선순위 | 영향도 | 작업량 |
|----|------|----------|--------|--------|
| E-1 | 다중 전략 지원 (strategy_id 라우팅) | Medium | High | High |
| E-2 | HistoricalEventPlayer 구현 (백테스팅용) | High | High | High |
| E-3 | Signal 메타데이터 확장 (strategy_id, determiner_chain) | Low | Medium | Low |
| E-4 | 이벤트 필터링/변환 파이프라인 | Low | Medium | Medium |

### 2.4 실행 레이어 (Execution Layer)

#### 강점
```
✅ OrderGateway: Binance API 캡슐화
✅ RiskGuard: 리스크 검증 및 포지션 사이징
✅ PositionCacheManager: TTL 기반 캐시 + WebSocket 동기화
✅ LiquidationManager: 긴급 청산 상태 머신
✅ CircuitBreaker: 장애 격리
```

#### 개선 필요사항
```
⚠️ 실행 레이어와 전략 레이어 강결합
   - TradeCoordinator가 OrderGateway, RiskGuard, PositionCacheManager 직접 참조
   - EventDispatcher가 order_gateway 직접 참조 (동적 SL 업데이트용)
   - 제안: ExecutionProtocol, PositionProvider 인터페이스 도입

⚠️ 백테스팅/Paper Trading 미구현
   - README에 "Backtesting Ready" 명시되었으나 실제 구현 없음
   - 제안: MockExchange, PaperOrderGateway 구현

⚠️ TP/SL 주문 추적 불완전
   - 체결 확인, 취소 로직 없음
   - 제안: OrderTracker 컴포넌트 추가

⚠️ Position 모델 미완성
   - 실시간 PnL, 상태 추적 없음
   - 제안: PositionStatus enum, realized_pnl 필드 추가
```

#### 구체적 리팩토링 항목

| ID | 항목 | 우선순위 | 영향도 | 작업량 |
|----|------|----------|--------|--------|
| X-1 | ExecutionProtocol 추상화 | High | High | Medium |
| X-2 | PositionProvider 인터페이스 도입 | High | Medium | Medium |
| X-3 | MockExchange 구현 (백테스팅용) | High | High | High |
| X-4 | OrderTracker 컴포넌트 추가 | Medium | Medium | Medium |
| X-5 | Position 모델 확장 (PnL, 상태) | Medium | Medium | Low |

### 2.5 데이터 레이어 (Data Layer)

#### 강점
```
✅ PublicMarketStreamer: WebSocket 시장 데이터
✅ PrivateUserStreamer: WebSocket 사용자 데이터
✅ DataCollector: Facade 패턴으로 스트리머 조립
✅ EnrichedBuffer: 캔들 버퍼 관리
```

#### 개선 필요사항
```
⚠️ EnrichedBuffer에 5개 TODOs 존재
   - ICT detector 통합 대기 중 (Phase 3)
   - 제안: DetectorIntegrationManager 구현

⚠️ 데이터 소스 추상화 미흡
   - 현재: 실시간 WebSocket만 지원
   - 제안: DataSource 인터페이스 (Live, Historical, Simulated)

⚠️ 멀티 타임프레임 데이터 동기화
   - 현재: 각 interval 독립 버퍼
   - 제안: TimeSynchronizer 컴포넌트
```

#### 구체적 리팩토링 항목

| ID | 항목 | 우선순위 | 영향도 | 작업량 |
|----|------|----------|--------|--------|
| D-1 | EnrichedBuffer TODOs 해결 (ICT detector 통합) | Medium | Medium | Medium |
| D-2 | DataSource 인터페이스 추상화 | High | High | Medium |
| D-3 | HistoricalDataSource 구현 | High | High | High |
| D-4 | TimeSynchronizer 컴포넌트 | Low | Medium | Medium |

---

## 3. 리팩토링 로드맵

### Phase 0: Config 레이어 범용화 + Strategy Registry (1주) — 신규

> **근거**: Config 레이어가 정리되지 않으면, 새 전략 추가 시 최소 5개 파일 수정이
> Phase 1~4 완료 후에도 지속됨. 모든 후속 Phase의 전제 조건.

**목표**: 새 전략 추가 시 변경 파일을 **1개** (전략 자체 패키지)로 줄이기

```
[C-4] momentum_strategy 유령 등록 제거 (즉시)
  - VALID_STRATEGIES에서 momentum_strategy 제거
  - 또는 mock_strategy → mock_sma로 정정 (실제 builder명과 일치)

[C-1] TradingConfig.strategy_config 범용화
  - ict_config: Optional[Dict] → strategy_config: Dict[str, Any]
  - ConfigManager._load_trading_config()에서 전략별 분기 제거
  - TradingEngine.initialize_components()의 ict_config 분기 제거

[C-2] SymbolConfig.strategy_params 범용화
  - ict_config/momentum_config 개별 필드 → strategy_params: Dict[str, Any]
  - get_strategy_config() if/elif → return self.strategy_params
  - to_trading_config_dict() if/elif → 단일 경로
  - from_ini_sections() ICT 하드코딩 → 전략 이름 기반 동적 파싱

[R-1] Strategy Registry 패턴 도입
  - _STRATEGY_REGISTRY: Dict[str, Callable] 도입
  - register_strategy() 함수 제공
  - build_module_config()의 if/elif → Registry 조회
  - 기존 3개 전략(ict, sma, always_signal) Registry에 등록

[C-3] VALID_STRATEGIES 동적화
  - 하드코딩 set → Registry 키에서 자동 생성
  - SymbolConfig 검증이 Registry 기반으로 동작
```

### Phase 1: 실행 레이어 추상화 (2주)
**목표**: 백테스팅/Paper Trading 지원 기반 구축

```
[X-1] ExecutionProtocol 추상화
  - execute_order(), cancel_order(), get_position(), get_open_orders()
  - OrderGateway가 Protocol 구현
  - TradeCoordinator는 Protocol에만 의존

[X-2] PositionProvider 인터페이스
  - get_position(), get_all_positions(), on_position_update()
  - PositionCacheManager가 Protocol 구현

[X-3] MockExchange 구현
  - 메모리 기반 주문장
  - 시뮬레이션된 체결
  - 수수료/슬리피지 모델
```

### Phase 2: 데이터 레이어 추상화 (1주)
**목표**: 히스토리컬 데이터 재생 지원

```
[D-2] DataSource 인터페이스
  - subscribe_candles(), unsubscribe(), get_historical()
  - PublicMarketStreamer가 Protocol 구현

[D-3] HistoricalDataSource 구현
  - CSV/Parquet 파일 읽기
  - 이벤트 리플레이
  - 속도 조절 (realtime, fast, instant)
```

### Phase 3: 전략 레이어 정리 (1주)
**목표**: 새 전략 타입 추가 용이성 확보

```
[S-1] BaseStrategy 책임 분리
  - BufferManager 추출
  - IndicatorCacheManager 추출
  - BaseStrategy는 인터페이스 정의만 유지

[S-2] ICT 모듈 패키지 격리
  - src/strategies/ict/ 패키지 생성
  - ICTEntryDeterminer, ICTExitDeterminer 이동
  - ZoneBasedStopLoss, DisplacementTakeProfit 이동
  - ict_profiles.py, indicator_cache.py 이동
  - detectors/ 하위 ICT 파일 이동
  - Registry에 자동 등록 (Phase 0의 R-1 활용)
```

### Phase 4: 이벤트 파이프라인 확장 (1주)
**목표**: 다중 전략 및 백테스팅 지원

```
[E-2] HistoricalEventPlayer 구현
  - HistoricalDataSource와 연동
  - EventBus로 이벤트 발행
  - 진행률 추적

[E-1] 다중 전략 지원 (선택적)
  - strategy_id 기반 라우팅
  - 전략별 독립 버퍼
```

---

## 4. 수용 기준 (Acceptance Criteria)

### Phase 0 완료 기준
- [ ] `TradingConfig`에서 `ict_config` 필드 제거, `strategy_config: Dict[str, Any]` 도입
- [ ] `SymbolConfig`에서 `ict_config`/`momentum_config` 필드 제거, `strategy_params` 도입
- [ ] `VALID_STRATEGIES`가 Registry에서 자동 생성됨
- [ ] `module_config_builder.py`에 if/elif 체인 없음 (Registry 조회만)
- [ ] `TradingEngine.initialize_components()`에 전략 이름 분기 없음
- [ ] 기존 3개 전략(ict, sma, always_signal) 모든 테스트 통과
- [ ] **새 전략 추가 시 변경 파일: 전략 자체 + Registry 등록 = 1~2개**

### Phase 1 완료 기준
- [ ] ExecutionProtocol 인터페이스 정의
- [ ] OrderGateway가 ExecutionProtocol 구현
- [ ] TradeCoordinator가 Protocol만 의존하도록 변경
- [ ] MockExchange 구현 및 단위 테스트 통과
- [ ] Paper Trading 모드로 실제 주문 없이 전략 실행 가능

### Phase 2 완료 기준
- [ ] DataSource 인터페이스 정의
- [ ] PublicMarketStreamer가 DataSource 구현
- [ ] HistoricalDataSource 구현 및 테스트
- [ ] 히스토리컬 데이터로 전략 백테스트 실행 가능

### Phase 3 완료 기준
- [ ] BufferManager 별도 클래스로 분리
- [ ] BaseStrategy 라인 수 500 이하
- [ ] ICT 모듈이 src/strategies/ict/ 패키지로 격리
- [ ] ICT 전략이 Registry에 자동 등록됨
- [ ] 새 전략 타입 추가 시 변경 파일 2개 이하

### Phase 4 완료 기준
- [ ] HistoricalEventPlayer 구현
- [ ] 백테스팅 실행 시간: 1년 데이터 < 5분
- [ ] 다중 전략 동시 실행 지원 (선택적)

---

## 5. 리스크 및 완화 전략

### 기술적 리스크

| 리스크 | 영향도 | 확률 | 완화 전략 |
|--------|--------|------|-----------|
| Config 범용화 시 기존 INI/YAML 호환성 파괴 | High | Medium | 마이그레이션 함수 작성, deprecated 필드 경고 후 제거 |
| Registry 패턴 도입 시 import 순서 의존성 | Medium | Medium | 전략 패키지의 `__init__.py`에서 등록, lazy import 활용 |
| Protocol 도입 후 성능 저하 | High | Low | 벤치마크 테스트, hot path는 직접 호출 유지 |
| 백테스팅 결과와 실거래 결과 불일치 | High | Medium | Paper Trading으로 중간 검증, 슬리피지 모델링 |
| 기존 전략 호환성 깨짐 | Medium | Low | 어댑터 패턴, deprecation 경고 |

### 일정 리스크

| 리스크 | 영향도 | 확률 | 완화 전략 |
|--------|--------|------|-----------|
| Phase 0이 후속 Phase 지연 유발 | Medium | Low | Phase 0은 단순 리네이밍/재구조화로 1주 내 완료 가능 |
| Phase 1~2 병렬 진행 시 충돌 | Medium | Medium | 인터페이스 먼저 확정, 구현은 순차 |
| MockExchange 구현 복잡도 증가 | Medium | Medium | 최소 기능부터 시작, 점진적 확장 |

---

## 6. 의존성 관계

```
Phase 0 (설정 레이어) ── 모든 후속 Phase의 전제 조건
    │
    ├── C-4: 유령 등록 제거 (즉시, 독립)
    │
    ├── C-1: TradingConfig 범용화 ──┐
    │                               │
    ├── C-2: SymbolConfig 범용화 ───┤
    │                               │
    ├── R-1: Strategy Registry ─────┤
    │                               │
    └── C-3: VALID_STRATEGIES 동적화 ┘ (R-1 완료 후)
                    │
                    ▼
Phase 1 (실행 레이어) ── Phase 0 완료 후
    │
    ├── X-1: ExecutionProtocol ──────────────────┐
    │                                            │
    ├── X-2: PositionProvider ───────────────────┤
    │                                            │
    └── X-3: MockExchange (X-1, X-2 완료 후) ───┤
                                                 │
Phase 2 (데이터 레이어) ── Phase 0 완료 후       │
    │                      (Phase 1과 병렬 가능)  │
    ├── D-2: DataSource ─────────────────────────┤
    │                                            │
    └── D-3: HistoricalDataSource ───────────────┤
                                                 │
Phase 3 (전략 레이어) ── Phase 0 완료 후         │
    │                    (Phase 1, 2와 병렬 가능) │
    ├── S-1: BaseStrategy 분리 ──────────────────┤
    │                                            │
    └── S-2: ICT 패키지 격리 + Registry 등록 ────┤
                                                 │
Phase 4 (이벤트 파이프라인) ─────────────────────┘
    │
    ├── E-2: HistoricalEventPlayer
    │         (Phase 1 X-3, Phase 2 D-3 완료 필수)
    │
    └── E-1: 다중 전략 지원 (선택적, Phase 3 S-2 권장)
```

**병렬 실행 가능 조합** (Phase 0 완료 후):
- Phase 1 + Phase 3: 실행 추상화와 전략 정리는 독립적
- Phase 1 + Phase 2: 인터페이스 먼저 확정 시 병렬 가능
- Phase 4는 Phase 1, 2 모두 완료 필수

---

## 7. 새 전략 추가 시 변경 파일 비교

### 현재 (Phase 0 이전)
새 전략 `my_strategy` 추가 시:
1. `symbol_config.py` — VALID_STRATEGIES에 추가, 전용 config 필드 추가, get_strategy_config() 분기 추가
2. `config_manager.py` — TradingConfig에 전용 필드 추가, INI 파싱 분기 추가
3. `module_config_builder.py` — if/elif에 분기 추가, import 추가
4. `trading_engine.py` — initialize_components()에 config 분기 추가
5. 전략 구현 파일들 (entry, exit, pricing determiners)

**총 변경: 4개 인프라 파일 + N개 전략 파일**

### Phase 0 완료 후
1. 전략 패키지 생성 (entry, exit, pricing determiners)
2. 전략 패키지 `__init__.py`에서 `register_strategy()` 호출

**총 변경: 전략 패키지만 (인프라 파일 0개)**

---

## 8. 참고 문서

- [Strategy Abstraction Redesign Report](../PDCA-Strategy-Abstraction-Redesign.report.md)
- [Event-Driven Pipeline Migration Design](./event-driven-pipeline-migration.design.md)
- [System Architecture Flow](../architecture/ict_2025_system_flow.md)
- [Real-time Trading Guidelines](../../CLAUDE.md)
- [Module Data Requirements Completion Report](../../04-report/module-data-requirements-completion.md)

---

**작성일**: 2026-02-23
**최종 수정**: 2026-02-23 (PDCA 분석 반영 — Phase 0 추가, Config 레이어 분석 신규)
**상태**: Plan (개정 v2)
**예상 소요**: 6주 (Phase 0: 1주 + Phase 1~4: 5주)
