# ICT 2025 트레이딩 시스템 설계 분석

**작성일**: 2026-01-23  
**LLM 모델**: opencode  
**분석 범위**: 전체 프로젝트 아키텍처 및 코드베이스

---

## 1. 아키텍처 개요

### 1.1 시스템 구조

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TradingBot (main.py)                      │
│  - 라이프사이클 관리                                     │
│  - 컴포넌트 조율                                          │
└──────────────────────┬──────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    TradingEngine                                │
│  - 컴포넌트 초기화                                       │
│  - 이벤트 핸들러 등록                                     │
│  - 라이프사이클 상태 관리                                │
└──────────────────────┬──────────────────────────────────────────────┘
                     │
         ┌───────────┴───────────┬───────────┐
         ▼                       ▼           ▼
┌─────────────────┐  ┌─────────────────┐  ┌────────────┐
│ EventBus      │  │ DataCollector  │  │ Strategies  │
│ (Pub-Sub)    │  │ (WebSocket)    │  │ (ICT, etc) │
└─────────────────┘  └─────────────────┘  └────────────┘
         │                   │                   │
         └────────┬──────────┬───────────────┘
                  ▼          ▼
         ┌─────────────────────────┐
         │   OrderManager       │
         │   RiskManager       │
         │   LiquidationManager │
         └─────────────────────────┘
```

### 1.2 코드 라인 수 통계

| 카테고리 | 최대 파일 | 라인 수 |
|---------|-----------|---------|
| 실행 | order_manager.py | 1,645 |
| 핵심 | trading_engine.py | 1,452 |
| 전략 | indicator_cache.py | 821 |
| 테스트 | test_order_execution.py | 1,848 |
| **전체 소스** | - | **16,256 줄** |

---

## 2. ✅ 구현 완료 부분

### 2.1 이벤트 기반 아키텍처
- **EventBus**: Pub-Sub 패턴 구현
  - 3개 우선순위 큐 (DATA, SIGNAL, ORDER)
  - 비동기 핸들러 지원 (sync/async 모두)
  - 오버플로우 핸들링 (timeout 전략: DATA=1s, SIGNAL=5s, ORDER=None)

### 2.2 핵심 컴포넌트
- **TradingEngine**: 
  - 상태 기계 (CREATED → INITIALIZED → RUNNING → STOPPING → STOPPED)
  - 이벤트 핸들러 등록 및 라우팅
  - Graceful shutdown 구현

- **DataCollector**:
  - Binance WebSocket 스트리밍
  - REST API 백필 지원
  - Symbol 정규화 및 유효성 검증

- **OrderManager**:
  - Market Order 실행
  - TP/SL 자동 주문
  - 레버리지 및 마진 타입 설정

- **RiskManager**:
  - 포지션 사이징 알고리즘
  - RR(Risk-Reward) 기반 계산
  - 포지션 크기 제한 적용

- **LiquidationManager**:
  - 비상 청산 시퀀스 (주문 취소 → 포지션 청산)
  - 상태 기계 (IDLE → IN_PROGRESS → {COMPLETED, PARTIAL, FAILED, SKIPPED})
  - Timeout 및 재시도 로직

- **AuditLogger**:
  - JSON Lines 포맷 (1줄 = 1 JSON 객체)
  - QueueHandler + QueueListener 패턴 (비동기 I/O)
  - 30일 로테이션

### 2.3 전략 프레임워크 (Issue #47 완료)
- **BaseStrategy** (단일 통합 클래스):
  - `Dict[str, deque]` 기반 버퍼 관리
  - Template Method 패턴 (update_buffer → analyze)
  - IndicatorStateCache 지원
  - 다중 타임프레임 지원 (single-TF는 interval이 1개인 MTF로 취급)

- **ICTStrategy**:
  - 10단계 ICT 분석 프로세스
  - Kill Zone 필터
  - FVG/OB/Liquidity 감지
  - Profile 기반 파라미터 관리

### 2.4 ICT Detector 패키지
- **6개 핵심 디텍터**:
  - FVG (Fair Value Gap): `ict_fvg.py` (347줄)
  - Order Block: `ict_order_block.py` (313줄)
  - Market Structure: `ict_market_structure.py` (350줄)
  - Kill Zones: `ict_killzones.py` (165줄)
  - Liquidity Sweep: `ict_liquidity.py` (422줄)
  - Smart Money Concepts: `ict_smc.py` (274줄)

### 2.5 테스트 커버리지
- **909개 테스트 케이스**:
  - 단위 테스트: 데이터 컬렉터, 전략, 리스크, 오더
  - 통합 테스트: 다중 코인, MTF, 백필
  - 셧다운 테스트, 설정 검증 테스트

---

## 3. ⚠️ 미완성 또는 개선 필요 부분

### 3.1 Position 모델 및 추적

**문제**: 
- `Position` 모델은 단순 dataclass
- 실시간 PnL 업데이트 로직 부재
- 포지션 상태 (OPEN, CLOSED, PARTIAL) 관리 미구현

**현재 구현** (`src/models/position.py`):
```python
@dataclass
class Position:
    symbol: str
    side: str  # 'LONG' or 'SHORT'
    entry_price: float
    quantity: float
    leverage: int
    unrealized_pnl: float = 0.0  # ❌ 실시간 업데이트 기능 없음
    liquidation_price: Optional[float] = None
    entry_time: Optional[datetime] = None
```

**개선 필요**:
```python
# 필요한 속성 추가:
- status: PositionStatus (OPEN, CLOSED, PARTIAL, LIQUIDATED)
- exit_price: float
- exit_time: datetime
- exit_reason: str
- realized_pnl: float
- fees_paid: float
```

---

### 3.2 TradingEngine의 포지션 관리

**문제**:
- 포지션 저장소 (`_positions` dict) 미구현
- 포지션 열림/닫힘 이벤트 처리 미완료
- 다중 포지션 허용 여부 검증 없음

**현재 상황** (`src/core/trading_engine.py`):
```python
class TradingEngine:
    # ❌ _positions 속성이 없음
    # ❌ open_positions 속성이 없음
    # ❌ 포지션 관리 로직 미구현
```

**필요한 구현**:
1. 포지션 저장소 추가:
   ```python
   self._positions: Dict[str, Position] = {}  # symbol -> position
   ```

2. 이벤트 핸들러 추가:
   ```python
   async def _on_position_opened(self, event: Event):
       """포지션 오픈 이벤트 처리"""
   
   async def _on_position_closed(self, event: Event):
       """포지션 클로즈 이벤트 처리"""
   ```

---

### 3.3 OrderManager의 TP/SL 체결 추적

**문제**:
- TP/SL 주문이 실제로 체결되었는지 추적 미구현
- TP/SL 주문의 취소 로직 미구현
- Position 업데이트와 연동 미구현

**현재 구현** (`src/execution/order_manager.py`):
```python
async def execute_entry_order(self, signal: Signal, position_size: float) -> Order:
    # TP/SL 주문 생성
    tp_order = self._create_tp_order(...)
    sl_order = self._create_sl_order(...)
    # ❌ 체결 여부 추적 없음
    # ❌ 취소 로직 없음
    # ❌ Position 업데이트 없음
```

**필요한 기능**:
1. TP/SL 주문 체결 추적:
   ```python
   # WebSocket 또는 주문 상태 폴링 필요
   # 또는 Binance API로 주문 상태 조회
   ```

2. 엔트리 시 TP/SL 취소:
   ```python
   async def cancel_oco_orders(self, symbol: str):
       """해당 심볼의 모든 TP/SL 주문 취소"""
   ```

---

### 3.4 Monitoring 시스템 연동

**문제**:
- `MonitoringAggregator` 존재하지만 TradingEngine에 연결 안됨
- 실시간 메트릭 수집 파이프라인 구현 미완료

**현재 상황**:
```
src/monitoring/aggregator.py (7,378줄)  ❌ 사용되지 않음
src/monitoring/metrics_collector.py (9,660줄) ❌ 사용되지 않음
```

**필요한 구현**:
1. TradingEngine에서 메트릭 전송:
   ```python
   # EventBus를 통해 메트릭 이벤트 발송
   await self.event_bus.publish(Event(
       event_type=EventType.METRIC_UPDATE,
       data={"position_pnl": ..., "order_count": ...}
   ))
   ```

2. MonitoringAggregator 구동:
   ```python
   # main.py에서 Aggregator 초기화 후 TradingEngine에 주입
   ```

---

### 3.5 BinanceServiceClient Rate Limiting

**문제**:
- 기본적인 요청량 추적만 구현
- Rate Limit 근접 시 요청 지연/대기 로직 미구현
- 여러 컴포넌트에서 동일 클라이언트 사용 시 동기화 부족

**현재 구현** (`src/core/binance_service.py`):
```python
class RequestWeightTracker:
    def check_limit(self) -> bool:
        # 90% 이하면 계속 진행
        return self.current_weight < self.weight_limit * 0.9
        # ❌ 대기/지연 로직 없음
```

**필요한 개선**:
1. Rate Limit 근접 시 대기:
   ```python
   async def wait_if_needed(self):
       while not self.check_limit():
           wait_time = self.calculate_wait_time()
           await asyncio.sleep(wait_time)
   ```

2. 전역 Weight Tracker 공유:
   ```python
   # 모든 컴포넌트가 동일 RequestWeightTracker 인스턴스 사용
   ```

---

### 3.6 Signal 모델의 exit_reason 처리

**문제**:
- `Signal.exit_reason`이 생성됨
- TradingEngine에서 이를 처리하는 로직 미구현
- 청산, 리스크 거부 등 이유에 따른 로깅 차이 부족

**현재 구현**:
```python
@dataclass(frozen=True)
class Signal:
    # ...
    exit_reason: Optional[str] = None  # ❌ 활용되지 않음
```

**필요한 구현**:
1. TradingEngine에서 exit_reason 처리:
   ```python
   async def _on_signal(self, event: Event):
       signal = event.data
       if signal.is_exit_signal:
           if signal.exit_reason == "trailing_stop":
               self.logger.info("Trailing stop exit")
           elif signal.exit_reason == "time_exit":
               self.logger.info("Time-based exit")
   ```

---

### 3.7 상태 기계와 에러 핸들링

**문제**:
- TradingEngine과 LiquidationManager 상태 기계가 분리됨
- 에러 전파 방지를 위한 에러 핸들링 레이어 불확실
- 셧다운 시점의 이벤트 처리 완료를 보장하는 로직 미구현

**현재 상황**:
```
TradingEngine 상태: CREATED → INITIALIZED → RUNNING → STOPPING → STOPPED
LiquidationManager 상태: IDLE → IN_PROGRESS → {COMPLETED, PARTIAL, FAILED, SKIPPED}
```

**개선 필요**:
1. 상태 동기화:
   ```python
   # TradingEngine이 LiquidationManager의 상태를 인지
   # 셧다운 중 청산 진행 중이면 완료 대기
   ```

2. 에러 핸들링 표준화:
   ```python
   # 모든 try-except에서 일관된 에러 처리
   except StrategyError as e:
       await self.event_bus.publish(Event(
           event_type=EventType.STRATEGY_ERROR,
           data={"error": str(e)}
       ))
   ```

---

### 3.8 Config 유효성 검증 및 YAML 지원

**문제**:
- `TradingConfigHierarchical`가 사용되지 않음
- YAML 파싱 로직 구현되었으나 호출되지 않음
- INI 파일만 실제로 사용됨

**현재 상황** (`src/utils/config.py`):
```python
class ConfigManager:
    def __init__(self):
        # INI 파일만 로드
        self.api_config = self._load_api_config()
        self.trading_config = self._load_trading_config()
        # ❌ YAML 로딩 미사용
        # ❌ TradingConfigHierarchical 미사용
```

**필요한 구현**:
1. YAML 지원 활성화:
   ```python
   if Path("trading_config.yaml").exists():
       self.trading_config = self._load_yaml_config()
   ```

2. 계층적 구성 지원:
   ```python
   # TradingConfigHierarchical 사용
   # defaults + symbols override 구조
   ```

---

### 3.9 Backfill 로직

**문제**:
- DataCollector의 `get_candle_buffer()` 메서드 존재
- 초기화 단계에서 호출되는지 확인 필요
- 역사 데이터 로드 파이프라인 검증 필요

**필요한 검증**:
1. 백필 호출 확인:
   ```python
   # main.py 또는 TradingEngine 초기화 시
   # data_collector.get_candle_buffer() 호출 여부 확인
   ```

2. 간격 데이터 검증:
   ```python
   # 백필된 캔들이 전략에 전달되는지 확인
   strategy.initialize_with_historical_data(candles, interval)
   ```

---

### 3.10 WebSocket 연결 복구 메커니즘

**문제**:
- 연결 끊김 시 자동 재연결 로직 불확실
- 연결 상태 모니터링 및 복구 전략 명확하지 않음

**현재 구현** (`src/core/data_collector.py`):
```python
async def start_streaming(self):
    self._running = True
    # ❌ 재연결 로직 없음
    # ❌ ping/pong 감지 없음
```

**필요한 구현**:
1. 자동 재연결:
   ```python
   async def _reconnect_handler(self):
       while self._running:
           try:
               await self._connect_websocket()
           except ConnectionError:
               backoff = self._calculate_backoff()
               await asyncio.sleep(backoff)
   ```

2. 연결 상태 모니터링:
   ```python
   # 주기적으로 연결 상태 확인
   # health check 로직
   ```

---

## 4. 🔄 구현되지 않았으나 고려할 필요 사항

### 4.1 포트폴리오 백테스팅 시스템

**현황**: 실시간 트레이딩 시스템 완료
**고려 사항**:
- 역사 데이터 기반 백테스팅 모듈 필요
- Walk-forward 분석 기능
- 성과 지표 계산 (Sharpe Ratio, Max Drawdown, etc.)

### 4.2 데이터베이스 계층

**현황**: 로그 파일에만 저장
**고려 사항**:
- 포지션, 주문, 거래 기록 DB 저장
- SQLite/PostgreSQL 사용
- 분석 및 리포팅을 위한 데이터 구조화

### 4.3 웹 기반 대시보드

**현황**: CLI 기반 시스템
**고려 사항**:
- 실시간 포지션/PnL 표시
- 이벤트 로그 뷰어
- 시스템 상태 모니터링
- 알림 시스템 (Telegram, Slack, etc.)

### 4.4 A/B 테스팅 프레임워크

**현황**: 단일 전략만 실행 가능
**고려 사항**:
- 여러 전략 파라미터 조합 동시 테스트
- 통계적 유의성 평가
- 최적의 파라미터 자동 추천

### 4.5 머신러닝 기반 전략

**현황**: 규칙 기반 ICT 전략
**고려 사항**:
- LSTM/Transformer 기반 가격 예측
- Reinforcement Learning 에이전트
- 실시간 모델 학습

### 4.6 다중 거래소 지원

**현황**: Binance만 지원
**고려 사항**:
- Bybit, OKX, 등 다른 거래소 연동
- 거래소 간 차익거래 (Arbitrage)
- 유동성 집계 기능

---

## 5. 📋 요약

| 카테고리 | 항목 | 상태 |
|---------|------|------|
| **아키텍처** | 이벤트 기반 시스템 | ✅ 완료 |
| **데이터 수집** | WebSocket + REST | ✅ 완료 |
| **전략** | ICT 전략 + Base 통합 | ✅ 완료 (Issue #47) |
| **주문 실행** | Market Order + TP/SL | ✅ 완료 |
| **리스크 관리** | 포지션 사이징 | ✅ 완료 |
| **비상 청산** | 자동 청산 | ✅ 완료 |
| **감사 로깅** | JSON Lines | ✅ 완료 |
| **포지션 추적** | 실시간 상태/업데이트 | ❌ 미완성 |
| **TP/SL 체결 추적** | 주문 상태 모니터링 | ❌ 미완성 |
| **모니터링** | 실시간 메트릭 | ❌ 연동 미완성 |
| **Rate Limiting** | 요청량 제어 | ⚠️ 기본 구현만 |
| **상태 관리** | 포지션 상태 | ❌ 미구현 |
| **Config 관리** | YAML 지원 | ⚠️ 미사용 |
| **재연결** | WebSocket 복구 | ❌ 미구현 |

---

## 6. 🎯 우선순위 추천

### P0 (즉시 필요)
1. 포지션 추적 및 상태 관리
2. TP/SL 체결 추적 로직

### P1 (높은 우선순위)
3. Monitoring 시스템 연동
4. WebSocket 재연결 메커니즘

### P2 (중간 우선순위)
5. Rate Limiting 개선
6. Config YAML 지원 활성화

### P3 (낮은 우선순위)
7. 백테스팅 시스템
8. 데이터베이스 계층
9. 웹 대시보드

---

## 7. 📝 참고 사항

### 7.1 완료된 이슈
- **Issue #47**: 전략 클래스 계층 구조 통합 (BaseStrategy + MultiTimeframeStrategy)
  - PR #51로 머지 완료
  - 2026-01-23 완료

- **Issue #49**: 도메인 본질에 따른 용어 재정의 (Indicator → Detector, Feature → Indicator)
  - PR #50으로 머지 완료
  - 2026-01-23 완료

### 7.2 코드 품질 지표
- **총 라인 수**: 16,256줄 (소스)
- **테스트 수**: 909개
- **커버리지**: 약 22% (전체 프로젝트 기준)
- **최대 파일**: order_manager.py (1,645줄)

### 7.3 기술 스택
- **언어**: Python 3.9+
- **비동기**: asyncio
- **거래소**: Binance Futures (USDT-M)
- **데이터**: WebSocket (실시간) + REST (역사)
- **로깅**: JSON Lines, QueueHandler/QueueListener
- **테스트**: pytest, pytest-asyncio, pytest-mock

---

*이 문서는 opencode에 의해 2026-01-23에 작성되었습니다.*
