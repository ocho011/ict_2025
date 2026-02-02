# Claude Code Instructions

## Task Master AI Instructions
**Import Task Master's development workflow commands and guidelines, treat as if import is in the main CLAUDE.md file.**
@./.taskmaster/CLAUDE.md

---

## Real-time Trading System Guidelines

> **목적**: 이벤트 기반 실시간 자동매매 시스템 개발 시 준수해야 할 트레이드오프 기준 및 구현 지침
> **핵심 원칙**: 실시간 성능이 최우선. 안정성/편의성 도입 시 지연시간(Latency) 영향을 최소화할 것.

### 1. 데이터 검증 및 객체화 (Data Validation & Serialization)

**기준**
- Hot Path(실시간 데이터 흐름): 런타임 검증 최소화
- Cold Path(초기화, 설정 로드): 엄격한 검증 허용

**DO**
```python
# Hot Path: 경량 dataclass 사용
@dataclass(slots=True)
class TickData:
    symbol: str
    price: float
    timestamp: int

# Cold Path: Pydantic으로 설정 검증
class TradingConfig(BaseModel):
    api_key: str
    symbols: list[str]
    max_position: Decimal
```

**DON'T**
```python
# Hot Path에서 Pydantic 사용 금지
class TickData(BaseModel):  # 매 틱마다 검증 오버헤드 발생
    symbol: str
    price: float
```

**체크리스트**
- [ ] 웹소켓 메시지 파싱에 Pydantic 대신 `dataclass` 또는 `NamedTuple` 사용
- [ ] `datetime` 파싱은 배치 처리 또는 지연 평가(lazy evaluation) 적용
- [ ] `Decimal` 변환은 주문 실행 직전 단계에서만 수행
- [ ] 타입 검증 필요 시 `__debug__` 플래그로 개발/운영 분리

### 2. 로깅 및 가시성 (Logging & Observability)

**기준**
- 동기(Sync) I/O 로깅 금지 - 이벤트 루프 블로킹 방지
- 로그 레벨별 출력 대상 분리

**DO**
```python
# 비동기 로깅 큐 사용
import logging
from logging.handlers import QueueHandler, QueueListener

log_queue = queue.Queue()
handler = QueueHandler(log_queue)
logger.addHandler(handler)

listener = QueueListener(log_queue, FileHandler('trading.log'))
listener.start()
```

**DON'T**
```python
# Hot Path에서 동기 파일 쓰기
logger.debug(f"Received tick: {tick}")  # 매 틱마다 디스크 I/O
```

**로그 레벨 정책**
| 레벨 | 용도 | 출력 대상 | Hot Path 허용 |
|------|------|-----------|---------------|
| ERROR | 시스템 장애 | 파일 + 알림 | Yes (드물게 발생) |
| WARNING | 이상 징후 | 파일 | Yes |
| INFO | 주문/체결 | 파일 | 주문 시에만 |
| DEBUG | 상세 추적 | 메모리 버퍼 | No - 운영 환경 비활성화 |

**체크리스트**
- [ ] `QueueHandler` 또는 비동기 로깅 라이브러리(`aiologger`) 적용
- [ ] 운영 환경에서 DEBUG 레벨 비활성화 확인
- [ ] 모니터링 데이터 전송은 별도 스레드/프로세스에서 처리

### 3. 상태 관리 및 동기화 (State Management & Synchronization)

**기준**
- Lock 경합 최소화 - Lock-free 자료구조 우선 고려
- 메모리 할당 패턴 최적화로 GC 부하 감소

**DO**
```python
# Lock-free 큐 사용
from collections import deque
tick_buffer = deque(maxlen=1000)  # 자동 크기 제한

# 또는 asyncio.Queue
tick_queue = asyncio.Queue(maxsize=1000)

# 사전 할당된 버퍼 재사용
class CandleBuffer:
    def __init__(self, size: int):
        self._data = [None] * size
        self._index = 0
```

**DON'T**
```python
# 빈번한 Lock 획득
with self._lock:  # 매 틱마다 Lock 경합
    self.candles.append(candle)

# 무제한 리스트 증가 (GC 부하)
self.history.append(tick)
```

**동기화 전략 우선순위**
1. Lock-free: `deque`, `asyncio.Queue` (최우선)
2. Read-Write Lock: 읽기 빈번, 쓰기 드문 경우
3. Fine-grained Lock: 심볼별 개별 Lock
4. Global Lock: 최후의 수단 (사용 자제)

**체크리스트**
- [ ] 웹소켓 → 전략 데이터 전달에 `asyncio.Queue` 사용
- [ ] 캔들 히스토리는 고정 크기 버퍼(`deque(maxlen=N)`) 적용
- [ ] 심볼별 상태는 개별 객체로 분리하여 Lock 범위 최소화

### 4. 에러 핸들링 및 복구 (Error Handling & Recovery)

**기준**
- Critical Path 보호: 파싱/계산 실패가 전체 시스템을 중단시키지 않을 것
- 복구 로직 비용 인지: Retry, Graceful Shutdown의 지연 허용 범위 설정

**DO**
```python
# 계층별 에러 처리
async def process_message(raw: bytes):
    try:
        data = fast_parse(raw)
    except ParseError:
        logger.warning("Parse failed, skipping")
        return  # 해당 메시지만 스킵
    await strategy.on_tick(data)

# Exponential backoff
async def connection_manager():
    backoff = ExponentialBackoff(base=1, max=60)
    while True:
        try:
            await connect_and_run()
        except ConnectionError:
            await asyncio.sleep(backoff.next())
```

**DON'T**
```python
# 과도한 중첩 try-except
try:
    try:
        try:
            price = float(data['price'])
        except:
            price = Decimal(data['price'])
    except:
        price = 0
except:
    pass
```

**에러 복구 정책**
| 에러 유형 | 처리 방식 | 최대 지연 허용 |
|-----------|-----------|----------------|
| 메시지 파싱 실패 | 해당 메시지 스킵 | 0ms |
| 웹소켓 연결 끊김 | Exponential Backoff 재연결 | 60초 |
| API Rate Limit | 대기 후 재시도 | API 명시 시간 |
| 전략 계산 에러 | 해당 심볼 스킵, 알림 | 0ms |
| 시스템 리소스 부족 | Graceful Shutdown | 5초 |

**체크리스트**
- [ ] 메시지 레벨 에러가 연결 레벨로 전파되지 않음
- [ ] 재연결 로직에 Exponential Backoff 적용
- [ ] `finally` 블록에서 리소스 정리 보장
- [ ] 치명적 에러 발생 시 포지션 정리 로직 구현

### 구현 우선순위

| 우선순위 | 영역 | 조치 | 성능 영향 | 구현 복잡도 |
|----------|------|------|-----------|-------------|
| 1 | Validation | dataclass 전환 | High | Low |
| 2 | State Sync | Lock-free 전환 | Medium | High |
| 3 | Logging | 비동기화 | High | Low |
| 4 | Error Handling | 계층 분리 | Low | Low |

### 성능 검증 기준

| 메트릭 | 목표값 | 측정 방법 |
|--------|--------|-----------|
| 틱 처리 지연 | < 1ms (p99) | `time.perf_counter_ns()` |
| 메모리 증가율 | < 10MB/hour | `tracemalloc` |
| GC Pause | < 10ms | `gc.callbacks` 모니터링 |
| Lock 대기 시간 | < 100μs | Lock 래퍼로 측정 |

## Logging Architecture

### Overview

The system uses two separate logging systems with distinct purposes:

| Logger | Purpose | Output | Format |
|--------|---------|--------|--------|
| TradingLogger | Application logging (debug/operations) | `logs/trading.log` + console | Human-readable, colored |
| AuditLogger | Compliance/analysis audit trail | `logs/audit/audit_YYYYMMDD.jsonl` | JSON Lines (machine-readable) |

### Usage Guidelines

**1. Component Logger (`self.logger`)**
- Use for development/debugging information
- Created via `logging.getLogger(__name__)`
- Outputs to TradingLogger's handlers (console + file)

```python
self.logger.debug("Processing candle for %s", symbol)
self.logger.info("Order placed: %s", order_id)
self.logger.warning("Rate limit approaching")
self.logger.error("Connection failed: %s", error)
```

**2. Audit Logger (`self.audit_logger`)**
- Use for compliance-critical events that need structured tracking
- Singleton pattern: `AuditLogger.get_instance()`
- Events: orders, trades, risk decisions, position changes

```python
self.audit_logger.log_event(
    AuditEventType.ORDER_PLACED,
    operation="place_order",
    symbol=symbol,
    order_data={"side": side, "quantity": qty}
)
```

### When to Use Each Logger

| Event Type | Logger | Rationale |
|------------|--------|-----------|
| Debug traces | `self.logger` | Development only |
| Order lifecycle | `audit_logger` | Compliance requirement |
| Risk decisions | `audit_logger` | Audit trail needed |
| Position changes | `audit_logger` | Compliance requirement |
| WebSocket events | `self.logger` | Debugging only |
| API errors | Both | Debug + audit trail |
| Performance metrics | `self.logger` | Operational monitoring |

### Hot Path Considerations

In performance-critical code paths:
- Prefer `audit_logger` only (single I/O operation)
- Avoid duplicate logging to both systems
- Use DEBUG level sparingly (disabled in production)

### Singleton Pattern (AuditLogger)

AuditLogger uses singleton pattern for resource efficiency:

```python
# Production: Use singleton
audit_logger = AuditLogger.get_instance()

# Testing: Reset singleton between tests
AuditLogger.reset_instance()
audit_logger = AuditLogger.get_instance(log_dir="test_logs")
```

Benefits:
- Single QueueListener thread (vs multiple threads per instance)
- Consistent log file handling
- Simplified dependency injection
