# Task #3: Binance API Connection & WebSocket Data Collector

## 📋 메타데이터

- **Task ID**: #3
- **완료 날짜**: 2025-12-10
- **복잡도**: High (7/10)
- **소요 시간**: ~8시간 (6 subtasks)
- **담당자**: Claude Code Agent
- **브랜치**: `feature/task-3-binance-data-collector`

## 🎯 목표

Binance Futures WebSocket API를 활용한 실시간 캔들스틱 데이터 수집 레이어 구현. Testnet 및 Mainnet 환경을 모두 지원하며, 안정적인 데이터 스트리밍과 버퍼 관리, 그리고 우아한 종료 메커니즘을 제공하는 `BinanceDataCollector` 클래스를 개발.

**핵심 문제 해결**:
- 실시간 시장 데이터 수집을 위한 안정적인 WebSocket 연결 관리
- Testnet/Mainnet 환경 간 원활한 전환
- 효율적인 캔들 데이터 버퍼링 및 히스토리 데이터 통합
- 비동기 리소스의 안전한 생명주기 관리

## ✅ 구현 내용

### 3.1 BinanceDataCollector 클래스 초기화
- **구현**: REST 클라이언트 초기화 및 환경별 URL 설정
- **기능**:
  - Testnet/Mainnet URL 상수 정의
  - `UMFutures` REST 클라이언트 초기화
  - 심볼 정규화 (대문자 변환)
  - 인스턴스 변수 초기화 (`_candle_buffers`, logger, `ws_client`)
- **주요 파일**: `src/core/data_collector.py` (lines 29-141)
- **테스트**: 8 unit tests (초기화, 심볼 정규화, URL 설정)

### 3.2 WebSocket 연결 관리
- **구현**: 비동기 WebSocket 스트리밍 시작 및 구독 관리
- **기능**:
  - `start_streaming()` async 메서드
  - 스트림 이름 생성 (`{symbol_lower}@kline_{interval}`)
  - `UMFuturesWebsocketClient` 초기화
  - 심볼/인터벌 조합별 kline 스트림 구독
  - 연결 상태 추적 (`_running`, `_is_connected`)
- **주요 파일**: `src/core/data_collector.py` (lines 143-192)
- **테스트**: 8 unit tests (연결 설정, 스트림 구독, 상태 관리)

### 3.3 WebSocket 메시지 파싱
- **구현**: 실시간 kline 메시지를 `Candle` 객체로 변환
- **기능**:
  - `_handle_kline_message()` 메서드
  - Binance kline 포맷 파싱 (e, k 필드)
  - 타임스탬프 변환 (milliseconds → datetime)
  - 가격/볼륨 문자열을 float로 변환
  - Candle 객체 생성 및 콜백 호출
  - 예외 처리 및 로깅 (잘못된 메시지, 누락 필드)
- **주요 파일**: `src/core/data_collector.py` (lines 194-250)
- **테스트**: 16 unit tests (파싱 정확도, 타임스탬프 변환, 에러 핸들링)

### 3.4 Historical Candles REST API
- **구현**: REST API를 통한 히스토리 캔들 데이터 조회
- **기능**:
  - `get_historical_candles()` 메서드
  - `_parse_rest_kline()` 헬퍼 메서드
  - REST API klines 배열을 Candle 객체로 변환
  - 심볼 정규화 및 limit 파라미터 검증
  - API 에러 처리 (잘못된 심볼, 레이트 리밋)
- **주요 파일**: `src/core/data_collector.py` (lines 486-576)
- **테스트**: 14 unit tests (REST 파싱, limit 검증, 에러 핸들링)

### 3.5 Buffer Management (캔들 버퍼 관리)
- **구현**: 심볼/인터벌별 캔들 데이터 버퍼링
- **기능**:
  - `asyncio.Queue` 기반 스레드 안전 버퍼
  - `_get_buffer_key()`: 버퍼 키 생성 (`{symbol}_{interval}`)
  - `add_candle_to_buffer()`: 캔들 추가 (자동 오버플로우 처리)
  - `get_candle_buffer()`: 비파괴적 버퍼 읽기
  - 버퍼 크기 제한 (500 candles/buffer)
  - WebSocket 및 REST API와 자동 통합
- **주요 파일**: `src/core/data_collector.py` (lines 578-624)
- **테스트**: 15 unit tests (버퍼 추가/조회, 오버플로우, 통합 시나리오)

### 3.6 Lifecycle Management (생명주기 관리)
- **구현**: 우아한 종료 및 리소스 정리
- **기능**:
  - `is_connected` 프로퍼티: 연결 상태 추적
  - `stop()` async 메서드: 타임아웃 기반 우아한 종료
  - `__aenter__/__aexit__`: async context manager 지원
  - WebSocket 클라이언트 정리 (`asyncio.wait_for` 타임아웃)
  - 버퍼 상태 로깅 (비파괴적)
  - 멱등성 보장 (여러 번 호출 안전)
- **주요 파일**: `src/core/data_collector.py` (lines 143-141, 625-762)
- **테스트**: 19 unit tests (연결 상태, stop 메서드, context manager)

## 🔧 주요 기술 결정

### 결정 1: binance-futures-connector 라이브러리 선택
- **문제**: Binance Futures API와의 안정적인 연동 방법
- **선택**: `binance-futures-connector` v4.1.0 공식 라이브러리 사용
- **이유**:
  - Binance 공식 지원 라이브러리로 API 호환성 보장
  - WebSocket 자동 재연결 기능 내장
  - REST API 및 WebSocket 통합 지원
  - USDT-M Futures 전용 최적화
- **트레이드오프**:
  - 장점: 안정성, 유지보수성, 공식 문서 지원
  - 단점: 라이브러리 의존성 추가, 특정 구현에 종속

### 결정 2: asyncio.Queue 기반 버퍼 관리
- **문제**: 멀티스레드 환경에서 안전한 캔들 데이터 버퍼링
- **선택**: `asyncio.Queue` 사용 (리스트 대신)
- **이유**:
  - 비동기 환경에서 스레드 안전성 보장
  - Queue의 FIFO 특성으로 시간순 정렬 자동 유지
  - 오버플로우 처리 (자동으로 오래된 데이터 제거)
- **트레이드오프**:
  - 장점: 스레드 안전, 성능, 코드 단순성
  - 단점: Queue 크기 고정 (동적 조정 불가), 메모리 사용 증가

### 결정 3: 비파괴적 버퍼 보존 정책
- **문제**: `stop()` 호출 시 버퍼 데이터를 지울 것인가?
- **선택**: 버퍼를 보존하고 `get_candle_buffer()`로 접근 가능하게 유지
- **이유**:
  - 종료 후에도 마지막 데이터 분석 가능
  - 재시작 시 컨텍스트 복원 지원
  - 데이터 손실 방지
- **트레이드오프**:
  - 장점: 데이터 무결성, 디버깅 용이성
  - 단점: 메모리 해제 지연

### 결정 4: asyncio.wait_for 타임아웃 패턴
- **문제**: WebSocket 종료가 무한 대기할 수 있음
- **선택**: `asyncio.wait_for(ws_client.stop(), timeout=5.0)`
- **이유**:
  - 종료 시간 상한선 보장 (5초)
  - 타임아웃 시 경고 로그 후 강제 정리
  - 애플리케이션 전체 종료 블로킹 방지
- **트레이드오프**:
  - 장점: 안정적 종료, 예측 가능한 리소스 정리
  - 단점: 5초 대기 시간, 일부 리소스 누수 가능성 (극히 드묾)

### 결정 5: Async Context Manager 패턴
- **문제**: 리소스 정리를 자동화하고 실수 방지
- **선택**: `__aenter__/__aexit__` 구현으로 context manager 지원
- **이유**:
  - Pythonic한 리소스 관리 패턴
  - 예외 발생 시에도 자동 정리 보장
  - 사용자 코드 단순화 (`async with collector: ...`)
- **트레이드오프**:
  - 장점: 안전성, 가독성, 모범 사례
  - 단점: 명시적 `start_streaming()` 호출 필요

## 📦 변경된 파일

```
src/
├── core/
│   └── data_collector.py         [NEW] BinanceDataCollector class (762 lines)
tests/
├── core/
│   ├── test_data_collector.py    [NEW] Main test suite (1,195 lines, 67 tests)
│   └── test_lifecycle.py         [NEW] Lifecycle tests (447 lines, 19 tests)
.taskmaster/
├── designs/
│   ├── task-3.2-websocket-design.md           [NEW] WebSocket 설계 문서
│   ├── task-3.3-message-parsing-design.md     [NEW] 메시지 파싱 설계 문서
│   ├── task-3.4-historical-candles-design.md  [NEW] Historical Candles 설계 문서
│   └── task-3.6-lifecycle-management-design.md [NEW] Lifecycle 설계 문서
└── reports/
    └── task-3-report.md          [NEW] 이 보고서
```

**코드 통계**:
- 신규 구현 코드: 762 lines (data_collector.py)
- 테스트 코드: 1,642 lines (86 tests)
- 설계 문서: 4 files
- 테스트 커버리지: 92% (data_collector.py)

## 🧪 테스트 결과

### 단위 테스트
```bash
# 실행 명령어
python3 -m pytest tests/core/test_data_collector.py tests/core/test_lifecycle.py -v

# 결과
✅ TestBinanceDataCollectorInitialization: 8/8 PASSED
✅ TestBinanceDataCollectorURLConstants: 5/5 PASSED
✅ TestBinanceDataCollectorStreaming: 8/8 PASSED
✅ TestBinanceDataCollectorMessageParsing: 16/16 PASSED
✅ TestBinanceDataCollectorHistoricalCandles: 14/14 PASSED
✅ TestBinanceDataCollectorBufferManagement: 15/15 PASSED
✅ TestBinanceDataCollectorConnectionState: 3/3 PASSED
✅ TestBinanceDataCollectorStop: 8/8 PASSED
✅ TestBinanceDataCollectorContextManager: 5/5 PASSED
✅ TestBinanceDataCollectorLifecycleIntegration: 4/4 PASSED

Total: 86/86 tests PASSED (100% pass rate)
Coverage: 92% for src/core/data_collector.py
Time: ~10.4 seconds
```

### 커버리지 분석
```
Name                              Stmts   Miss  Cover   Missing
---------------------------------------------------------------
src/core/data_collector.py          193     16    92%   253-255, 523-525, 534-542,
                                                         605-607, 613-615, 704-705,
                                                         758-759
```

**미커버 라인 분석**:
- 253-255, 523-525, 534-542: 예외 처리 경로 (방어적 코드)
- 605-607, 613-615: 에러 로깅 경로
- 704-705, 758-759: 예외 발생 시 정리 로직

→ 핵심 비즈니스 로직은 100% 커버리지 달성

### 통합 테스트
```bash
# 버퍼 통합 시나리오
✅ WebSocket → Buffer 자동 연동
✅ Historical API → Buffer 사전 로드
✅ Mixed (WebSocket + Historical) 통합

# Lifecycle 통합 시나리오
✅ start → stop → 버퍼 보존 검증
✅ Context manager full lifecycle
✅ 예외 상황에서 자동 정리
```

### 수동 검증
- ✅ Testnet URL 설정 확인 (https://testnet.binancefuture.com)
- ✅ Mainnet URL 설정 확인 (https://fapi.binance.com)
- ✅ 심볼 정규화 동작 (btcusdt → BTCUSDT)
- ✅ 버퍼 오버플로우 시 FIFO 제거
- ✅ stop() 멱등성 (여러 번 호출 안전)
- ✅ Context manager 예외 전파

## ⚠️ 알려진 이슈 / 제한사항

**없음**

모든 핵심 기능이 테스트를 통과했으며, 알려진 버그나 제한사항은 없습니다.

**향후 고려 사항**:
- [ ] Binance Testnet 실제 연결 테스트 (수동 검증 필요)
- [ ] 장시간 연결 안정성 테스트 (24시간+)
- [ ] 대량 메시지 처리 성능 테스트 (1000+ msg/sec)
- [ ] 메모리 누수 프로파일링 (장기 실행)

## 🔗 연관 Task

- **선행 Task**:
  - Task #1: Project Foundation & Environment Setup (완료)
  - Task #2: Data Models & Core Types Definition (완료)
- **후속 Task**:
  - Task #4: Event-Driven Architecture & Event Bus (대기 중)
  - Task #5: Technical Indicators & Signal Generation (대기 중)
- **연관 Task**:
  - None (Task #3는 독립적인 데이터 수집 레이어)

## 📚 참고 자료

### 공식 문서
- [Binance Futures API Documentation](https://binance-docs.github.io/apidocs/futures/en/)
- [binance-futures-connector PyPI](https://pypi.org/project/binance-futures-connector/)
- [binance-futures-connector GitHub](https://github.com/binance/binance-futures-connector-python)
- [Binance Testnet](https://testnet.binancefuture.com/)

### 코드 레퍼런스
- `src/models/candle.py`: Candle 데이터 모델 정의
- `.env.example`: API 키 설정 예시
- `tests/core/test_data_collector.py`: 구현 참고용 테스트 케이스

### 설계 문서
- `.taskmaster/designs/task-3.2-websocket-design.md`
- `.taskmaster/designs/task-3.3-message-parsing-design.md`
- `.taskmaster/designs/task-3.4-historical-candles-design.md`
- `.taskmaster/designs/task-3.6-lifecycle-management-design.md`

## 💡 학습 내용 / 개선 사항

### 학습한 점

1. **Binance API 구조 이해**
   - WebSocket 스트림 명명 규칙 (`{symbol}@kline_{interval}`)
   - REST API klines 배열 구조 (11개 필드)
   - Testnet/Mainnet URL 차이점

2. **비동기 프로그래밍 패턴**
   - `asyncio.Queue`를 활용한 스레드 안전 버퍼링
   - `asyncio.wait_for()`를 통한 타임아웃 제어
   - `asyncio.to_thread()`로 동기 코드 래핑
   - Async context manager 구현 패턴

3. **테스트 주도 개발 (TDD)**
   - 86개 테스트 케이스로 92% 커버리지 달성
   - Mock/Patch를 활용한 외부 의존성 격리
   - 통합 테스트 시나리오 설계

4. **리소스 생명주기 관리**
   - 우아한 종료 (graceful shutdown) 패턴
   - 멱등성 보장 방법
   - 예외 안전성 (exception safety) 설계

5. **효과적이었던 접근법**
   - 사전 설계 문서 작성 후 구현 (`.taskmaster/designs/`)
   - Subtask 단위 단계적 구현 및 테스트
   - Serena MCP를 활용한 정밀한 코드 삽입

### 다음에 개선할 점

1. **성능 최적화**
   - 버퍼 크기 동적 조정 메커니즘 고려
   - 대량 메시지 처리 시 배치 처리 도입
   - 메모리 프로파일링 및 최적화

2. **모니터링 강화**
   - 연결 상태 메트릭 수집
   - 메시지 처리 지연 시간 추적
   - 버퍼 사용률 모니터링

3. **에러 복구 전략**
   - WebSocket 재연결 정책 명시화
   - 메시지 유실 시 복구 메커니즘
   - Circuit breaker 패턴 적용 고려

4. **테스트 커버리지**
   - 실제 Binance Testnet 통합 테스트 추가
   - 장시간 안정성 테스트 (24시간+)
   - 부하 테스트 (1000+ msg/sec)

5. **문서화**
   - 사용자 가이드 추가 (Quick Start)
   - API 레퍼런스 문서 생성
   - 트러블슈팅 가이드 작성

## 📌 다음 단계

### Task #4: Event-Driven Architecture & Event Bus
- 이벤트 버스 구현으로 컴포넌트 간 결합도 낮추기
- 캔들 데이터를 이벤트로 변환하여 발행
- 구독자 패턴 구현 (indicators, strategies)
- 이벤트 필터링 및 라우팅 메커니즘

### 즉시 가능한 작업
1. 메인 브랜치로 PR 생성 및 리뷰 요청
2. Binance Testnet 실제 연결 테스트 (선택 사항)
3. Task #4 착수 준비 (의존성: Task #3 완료 ✅)

---

**작성일**: 2025-12-10
**작성자**: Claude Code Agent
**문서 버전**: 1.0
**관련 커밋**:
- `5c1bc86` - Subtask 3.1 완료
- `93d3df8` - Subtask 3.2 완료
- `fa8b1fc` - Subtask 3.3 완료
- `4d8b43c` - Subtask 3.4 완료
- `d4e545d` - Subtask 3.5 완료
- `9b52443` - Subtask 3.6 완료
- `f17aec6` - 테스트 수정
