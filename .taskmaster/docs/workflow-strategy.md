# Task Master & SuperClaude 복잡도별 워크플로우 전략

## 개요

이 문서는 Binance USDT-M Futures Trading System 프로젝트의 태스크를 효율적으로 구현하기 위한 복잡도별 워크플로우 전략을 제공합니다.

## 태스크 복잡도 분류

### 🟢 Low Complexity (1-4점)
- **Tasks**: #1 (Foundation), #2 (Data Models), #8 (Logging), #9 (Configuration)
- **특징**: 명확한 구조, 표준 패턴, 낮은 위험도
- **예상 시간**: 10-30분/태스크

### 🟡 Medium Complexity (5-7점)
- **Tasks**: #3 (Binance API), #4 (Event-Driven), #5 (Strategy), #7 (Risk), #10 (Main App)
- **특징**: 외부 API 통합, 비동기 처리, 중간 위험도
- **예상 시간**: 30분-1시간/태스크

### 🔴 High Complexity (8-10점)
- **Tasks**: #6 (Order Execution - 복잡도 8)
- **특징**: 금융 거래, 높은 위험도, 정밀한 오류 처리 필요
- **예상 시간**: 1-2시간/태스크

---

## 복잡도별 워크플로우

### 🟢 Low Complexity (1-4점) - 간소화 접근

#### 계획 단계 (5분)
```bash
task-master show <id>
/sc:design --serena
```
- **도구**: Serena만 사용 (Sequential 불필요)
- **목적**: 기본 구조 파악 및 파일 배치 확인
- **출력**: 디렉토리 구조 및 파일 템플릿

#### 구현 단계 (10-20분)
```bash
task-master set-status --id=<id> --status=in-progress
/sc:implement --serena
```
- **도구**: Serena로 빠른 구현
- **접근**: 직관적 구현, 최소한의 검증
- **기록**: update-subtask 선택적 사용

#### 검증 단계 (5분)
```bash
# 기본 테스트만 수행
task-master set-status --id=<id> --status=done
```
- **검증**: 기본 import 테스트, 문법 오류 확인
- **기록**: 간단한 완료 메모

#### 실전 예시: Task #1 (복잡도 4)
```bash
# 1. 계획
task-master show 1
/sc:design --serena
# Output: 디렉토리 구조 분석 (src/, tests/, docs/ 등)

# 2. 구현
task-master set-status --id=1 --status=in-progress
/sc:implement --serena
# 모든 서브태스크 순차 구현 (1.1 → 1.5)

# 3. 검증
python -c "import src; print('✅ Import successful')"
task-master set-status --id=1 --status=done
```

---

### 🟡 Medium Complexity (5-7점) - 서브태스크별 증분 접근

#### 초기 계획 단계 (10-15분)
```bash
task-master show <id>
/sc:design --serena --seq --think
```
- **도구**: Serena + Sequential + --think
- **목적**: 전체 태스크 아키텍처 이해, 서브태스크 간 의존성 파악
- **출력**: 전체 설계 개요, 서브태스크 실행 순서
- **범위**: 태스크 전체에 대한 높은 수준의 설계

#### 서브태스크별 반복 (각 15-20분)
```bash
task-master set-status --id=<id> --status=in-progress

# === 서브태스크 3.1 사이클 ===
task-master show 3.1  # 서브태스크 상세 확인
/sc:design --serena   # 3.1만 상세 설계 (서브태스크 ID 명시 불필요*)
/sc:implement --serena  # 3.1 구현 (서브태스크 ID 명시 불필요*)
pytest tests/test_specific.py::test_3_1 -v  # 3.1 즉시 검증
task-master update-subtask --id=3.1 --prompt="[구현 내용 + 테스트 결과]"
task-master set-status --id=3.1 --status=done

# === 서브태스크 3.2 사이클 ===
task-master show 3.2  # 다음 서브태스크 확인
/sc:design --serena   # 3.2만 상세 설계
/sc:implement --serena  # 3.2 구현
pytest tests/test_specific.py::test_3_2 -v  # 3.2 즉시 검증
task-master update-subtask --id=3.2 --prompt="[구현 내용 + 테스트 결과]"
task-master set-status --id=3.2 --status=done

# ... 나머지 서브태스크 동일 패턴 반복
```

**\*중요**: `/sc:design`과 `/sc:implement` 명령어는 **서브태스크 ID를 명시하지 않아도** Claude가 `task-master show 3.1`로 표시된 컨텍스트를 기반으로 해당 서브태스크만 작업합니다.

- **도구**: Serena로 서브태스크별 점진적 구현
- **접근**: 각 서브태스크마다 설계 → 구현 → 검증 사이클 완료
- **기록**: 각 서브태스크 완료 시 즉시 상세 기록
- **장점**:
  - 증분 검증으로 오류 조기 발견
  - 각 서브태스크가 "작동하는 상태" 유지
  - 다음 서브태스크가 검증된 기반 위에 구축됨

#### 최종 통합 검증 (10-15분)
```bash
# 통합 테스트 (서브태스크 간 상호작용 확인)
python -m pytest tests/test_integration.py -v

# 최종 기록
task-master update-subtask --id=<id.last> --prompt="[통합 테스트 결과]"
task-master set-status --id=<id> --status=done
```
- **검증**: 서브태스크 간 통합 테스트
- **기록**: 전체 통합 테스트 커버리지, 발견된 이슈, 해결 방법

#### 실전 예시: Task #3 (Binance WebSocket, 복잡도 7)
```bash
# 1. 초기 계획 (15분) - 전체 태스크 아키텍처
task-master show 3
/sc:design --c7 --seq --think
# Context7로 Binance WebSocket API 문서 참조
# Sequential로 연결 관리 전략 수립
# 출력: 전체 아키텍처 설계, 서브태스크 간 의존성

# 2. 서브태스크별 반복 사이클 (각 10-15분)
task-master set-status --id=3 --status=in-progress

# === 서브태스크 3.1: BinanceDataCollector 클래스 설정 ===
task-master show 3.1
/sc:design --c7 --serena  # 3.1만 상세 설계 (ID 명시 불필요)
/sc:implement --c7 --serena  # 3.1 구현 (ID 명시 불필요)
pytest tests/test_binance_collector.py::test_init -v  # 즉시 검증
task-master update-subtask --id=3.1 --prompt="BinanceDataCollector 초기화 완료
- REST/WebSocket URL 설정 검증
- API 키 로딩 테스트 통과"
task-master set-status --id=3.1 --status=done

# === 서브태스크 3.2: WebSocket 연결 관리 ===
task-master show 3.2
/sc:design --c7 --serena  # 3.2만 상세 설계
/sc:implement --c7 --serena  # 3.2 구현
pytest tests/test_binance_collector.py::test_connect -v  # 즉시 검증
task-master update-subtask --id=3.2 --prompt="WebSocket 연결 구현 완료
- kline 스트림 구독 성공
- auto-reconnect 로직 검증됨"
task-master set-status --id=3.2 --status=done

# === 서브태스크 3.3: 메시지 핸들러 ===
task-master show 3.3
/sc:design --serena  # 3.3만 상세 설계
/sc:implement --serena  # 3.3 구현
pytest tests/test_binance_collector.py::test_handler -v  # 즉시 검증
task-master update-subtask --id=3.3 --prompt="_handle_kline_message 구현 완료
- Candle 객체 변환 성공
- 이벤트 발행 검증됨"
task-master set-status --id=3.3 --status=done

# ... 서브태스크 3.4, 3.5, 3.6 동일 패턴

# 3. 최종 통합 검증 (15분)
python -m pytest tests/test_binance_collector.py -v  # 전체 통합 테스트
task-master update-subtask --id=3.6 --prompt="통합 테스트 완료
- 연결 관리: ✅
- 재연결 로직: ✅
- Graceful shutdown: ✅
- 전체 커버리지: 95%"
task-master set-status --id=3 --status=done
```

---

### 🔴 High Complexity (8-10점) - 서브태스크별 강화된 접근

#### 초기 계획 단계 (20-30분)
```bash
task-master show <id>
/sc:design --c7 --seq --ultrathink --focus <domain>
```
- **도구**: Context7 + Sequential + --ultrathink + 도메인 집중
- **목적**: 심층 아키텍처 분석, 위험 요소 식별, 보안/성능/금융 로직 검토
- **출력**: 상세 설계 문서, 위험 평가, 테스트 전략, 보안 체크리스트
- **범위**: 태스크 전체에 대한 심층 설계 + 서브태스크 실행 계획

#### 서브태스크별 강화된 반복 (각 15-25분)
```bash
task-master set-status --id=<id> --status=in-progress

# === 서브태스크 6.1 사이클 ===
task-master show 6.1
/sc:design --c7 --serena  # 6.1 상세 설계 (ID 명시 불필요)
/sc:implement --c7 --serena --validate  # 6.1 구현 + 검증 (ID 명시 불필요)
pytest tests/test_order_execution.py::test_init -v --cov  # 즉시 단위 테스트
task-master update-subtask --id=6.1 --prompt="[구현 내용 + 테스트 + 보안 체크]"
task-master set-status --id=6.1 --status=done

# === 서브태스크 6.2 사이클 ===
task-master show 6.2
/sc:design --c7 --serena  # 6.2 상세 설계
/sc:implement --c7 --serena --validate  # 6.2 구현 + 검증
pytest tests/test_order_execution.py::test_execute -v --cov  # 즉시 단위 테스트
task-master update-subtask --id=6.2 --prompt="[구현 내용 + 테스트 + 보안 체크]"
task-master set-status --id=6.2 --status=done

# ... 나머지 서브태스크 동일 패턴
```

**\*중요**: `/sc:design`과 `/sc:implement` 명령어는 **서브태스크 ID를 명시하지 않아도** Claude가 `task-master show 6.1`로 표시된 컨텍스트를 기반으로 해당 서브태스크만 작업합니다.

- **도구**: Context7 + Serena + --validate
- **접근**: 각 서브태스크마다 설계 → 구현 → 검증 + 보안 체크 사이클
- **기록**: 구현 세부사항, 의사결정 근거, 테스트 결과, 보안 체크리스트 필수
- **장점**:
  - 금융/보안 리스크 조기 발견 및 차단
  - 각 서브태스크가 완전히 검증된 상태로 진행
  - 오류 발생 시 영향 범위 최소화

#### 최종 통합 + E2E 검증 (20-30분)
```bash
# 통합 테스트 (서브태스크 간 상호작용)
python -m pytest tests/test_order_execution.py -v --cov

# E2E 테스트 (실제 환경 시뮬레이션)
/sc:test --play  # Playwright로 testnet E2E 시나리오

# 보안 감사 체크리스트
# ✅ API 키 환경변수 로딩 확인
# ✅ 주문 파라미터 검증 확인
# ✅ Rate limiting 준수 확인
# ✅ 민감 정보 로깅 제외 확인

# 최종 검증 기록
task-master update-subtask --id=<id.last> --prompt="[통합+E2E 테스트 결과 + 성능 지표 + 보안 감사 결과]"
task-master set-status --id=<id> --status=done
```
- **검증**: 단위(각 서브태스크) + 통합 + E2E + 보안 감사
- **기록**: 테스트 커버리지, 성능 벤치마크, 보안 체크리스트 완료 여부, 알려진 제약사항

#### 실전 예시: Task #6 (Order Execution, 복잡도 8)
```bash
# 1. 초기 계획 (30분) - 심층 아키텍처 분석
task-master show 6
/sc:design --c7 --seq --ultrathink --focus security
# Context7로 Binance Futures API 문서 심층 분석
# Sequential로 주문 실행 흐름, 오류 처리, 재시도 로직 설계
# 보안 집중: API 키 관리, 주문 검증, rate limiting
# 출력: 전체 설계 + 위험 평가 + 보안 체크리스트

# 2. 서브태스크별 강화된 반복 사이클 (각 15-20분)
task-master set-status --id=6 --status=in-progress

# === 서브태스크 6.1: OrderExecutionManager 클래스 설정 ===
task-master show 6.1
/sc:design --c7 --serena  # 6.1 상세 설계 (ID 명시 불필요)
/sc:implement --c7 --serena --validate  # 6.1 구현 (ID 명시 불필요)
pytest tests/test_order_execution.py::test_init -v --cov
task-master update-subtask --id=6.1 --prompt="OrderExecutionManager 초기화 완료
- REST 클라이언트 설정 (testnet/mainnet) ✅
- leverage/margin 설정 메서드 ✅
- API 키 환경변수 로딩 ✅
- 보안: API 키 하드코딩 없음 확인 ✅
- 테스트: 초기화 및 leverage 설정 통과"
task-master set-status --id=6.1 --status=done

# === 서브태스크 6.2: execute_signal 메서드 ===
task-master show 6.2
/sc:design --c7 --serena
/sc:implement --c7 --serena --validate
pytest tests/test_order_execution.py::test_execute_signal -v --cov
task-master update-subtask --id=6.2 --prompt="execute_signal 구현 완료
- Signal → 시장가 주문 변환 로직 ✅
- 주문 파라미터 검증 (가격, 수량, 방향) ✅
- 보안: 파라미터 범위 검증 추가 ✅
- 테스트: LONG/SHORT 시나리오 통과"
task-master set-status --id=6.2 --status=done

# === 서브태스크 6.3: TP/SL 주문 배치 ===
task-master show 6.3
/sc:design --c7 --serena
/sc:implement --c7 --serena --validate
pytest tests/test_order_execution.py::test_tp_sl -v --cov
task-master update-subtask --id=6.3 --prompt="TP/SL 주문 구현 완료
- TAKE_PROFIT_MARKET, STOP_MARKET 타입 ✅
- TP/SL 가격 검증 (방향별) ✅
- reduce-only 연결 로직 ✅
- 테스트: TP/SL 배치 및 검증 통과"
task-master set-status --id=6.3 --status=done

# === 서브태스크 6.4: 포지션/잔고 조회 ===
task-master show 6.4
/sc:design --c7 --serena
/sc:implement --c7 --serena --validate
pytest tests/test_order_execution.py::test_queries -v --cov
task-master update-subtask --id=6.4 --prompt="조회 메서드 구현 완료
- get_position_info(), get_account_balance() ✅
- 응답 파싱 및 에러 처리 ✅
- 테스트: 정상/오류 케이스 통과"
task-master set-status --id=6.4 --status=done

# === 서브태스크 6.5: 가격 포맷팅 ===
task-master show 6.5
/sc:design --c7 --serena
/sc:implement --c7 --serena --validate
pytest tests/test_order_execution.py::test_formatting -v --cov
task-master update-subtask --id=6.5 --prompt="가격 포맷팅 구현 완료
- symbol별 tick size 조회 ✅
- 가격/수량 반올림 로직 ✅
- 테스트: BTCUSDT, ETHUSDT 검증 통과"
task-master set-status --id=6.5 --status=done

# === 서브태스크 6.6: 오류 처리 및 재시도 ===
task-master show 6.6
/sc:design --c7 --serena
/sc:implement --c7 --serena --validate
pytest tests/test_order_execution.py::test_error_handling -v --cov
task-master update-subtask --id=6.6 --prompt="오류 처리 구현 완료
- Rate limit (429) + exponential backoff ✅
- Network 재시도 (최대 3회) ✅
- API 거부 로깅 ✅
- 테스트: 모든 오류 시나리오 통과"
task-master set-status --id=6.6 --status=done

# 3. 최종 통합 + E2E 검증 (30분)
# 통합 테스트
python -m pytest tests/test_order_execution.py -v --cov

# E2E 테스트 (Binance Testnet)
/sc:test --play
# - LONG 주문 → TP/SL → 포지션 확인 ✅
# - SHORT 주문 → TP/SL → 포지션 확인 ✅
# - 오류 시나리오: 잔고 부족, rate limit ✅

# 보안 감사 체크리스트
# ✅ API 키 환경변수로만 로딩
# ✅ 주문 파라미터 검증
# ✅ Rate limiting 준수
# ✅ 민감 정보 로깅 제외
# ✅ SSL 인증서 검증 활성화

# 최종 기록
task-master update-subtask --id=6.6 --prompt="Task #6 완료 및 최종 검증 완료
테스트 결과:
- 단위 테스트: 48/48 통과 (100% 커버리지)
- 통합 테스트: 12/12 통과
- E2E 테스트: LONG/SHORT 시나리오 성공
- 성능: 주문 배치 평균 200ms, 재시도 최대 3초
- 보안: 체크리스트 5/5 항목 준수
알려진 제약사항:
- Testnet 검증 완료 (Mainnet 배포 전 추가 검토 필요)
- Rate limit: 1200 req/min (Binance 공식)"

task-master set-status --id=6 --status=done
```

---

## 도구 선택 매트릭스

| 복잡도 | 계획 단계 | 구현 단계 | 검증 단계 |
|--------|-----------|-----------|-----------|
| **🟢 Low (1-4)** | `--serena` | `--serena` | 기본 테스트 |
| **🟡 Medium (5-7)** | `--serena --seq --think` | `--serena` | 단위 + 통합 테스트 |
| **🔴 High (8-10)** | `--c7 --seq --ultrathink --focus <domain>` | `--c7 --serena --validate` | 단위 + 통합 + E2E + 보안 |

### Context7 사용 시점
- **외부 API 통합**: Binance API, 라이브러리 문서 참조 필요 시
- **Tasks**: #3 (Binance API), #6 (Order Execution)

### Sequential 사용 시점
- **복잡한 아키텍처**: 다층 시스템, 비동기 처리, 이벤트 기반
- **Tasks**: #3, #4, #6, #10

### Serena 사용 시점
- **모든 구현 단계**: 코드 탐색, 심볼 분석, 프로젝트 구조 파악
- **Tasks**: 전체 (1-10)

---

## 실전 적용 순서

### Phase 1: Foundation (Low Complexity)
```bash
1. Task #1: Project Foundation (15분)
   - 간소화 접근

2. Task #2: Data Models (20분)
   - 간소화 접근
```

### Phase 2: Core Infrastructure (Medium-High Complexity)
```bash
3. Task #3: Binance API (1시간)
   - 표준 3단계 + Context7

4. Task #4: Event-Driven Architecture (1시간)
   - 표준 3단계

5. Task #6: Order Execution (2시간)
   - 강화된 접근 + 보안 집중
```

### Phase 3: Business Logic (Medium Complexity)
```bash
6. Task #5: Mock Strategy (45분)
   - 표준 3단계

7. Task #7: Risk Management (45분)
   - 표준 3단계
```

### Phase 4: Supporting Systems (Low-Medium Complexity)
```bash
8. Task #8: Logging (30분)
   - 간소화 접근

9. Task #9: Configuration (30분)
   - 간소화 접근
```

### Phase 5: Integration (Medium Complexity)
```bash
10. Task #10: Main Application (1시간)
    - 표준 3단계
```

**총 예상 시간**: 8-10시간

---

## 주요 원칙

### ✅ DO (권장사항)
1. **복잡도에 따라 접근 조정** - 모든 태스크에 동일한 방식 적용하지 않기
2. **Medium 이상(5+)은 서브태스크별 반복** - 각 서브태스크마다 설계→구현→검증 사이클
3. **task-master show로 컨텍스트 설정** - `/sc:design`, `/sc:implement`는 show된 서브태스크 자동 인식
4. **각 서브태스크 완료 시 즉시 검증** - 증분 검증으로 오류 조기 발견
5. **서브태스크 완료 시 상세 기록** - update-subtask로 구현 내용 + 테스트 결과 기록
6. **외부 API는 Context7 활용** - 공식 문서 기반 구현
7. **금융/보안 태스크는 보안 집중** - --focus security 플래그 + 보안 체크리스트

### ❌ DON'T (피해야 할 사항)
1. **간단한 태스크에 과도한 분석** - Task #1 같은 Low Complexity는 일괄 처리
2. **Medium 이상을 일괄 처리** - Task #3 이상은 반드시 서브태스크별 반복
3. **서브태스크 검증 생략** - 다음 서브태스크로 넘어가기 전 반드시 테스트
4. **서브태스크 ID를 명령어에 명시** - task-master show로 컨텍스트 설정하면 자동 인식
5. **Context7 없이 API 통합** - Binance API 문서 참조 필수
6. **update-subtask 누락** - 각 서브태스크 완료 시 진행 기록 필수

---

## 체크리스트

### 계획 단계 완료 기준
- [ ] 태스크 요구사항 이해 (`task-master show <id>`)
- [ ] 설계 문서 생성 (`/sc:design`)
- [ ] 의존성 및 위험 요소 파악
- [ ] 복잡도에 맞는 도구 선택 확인

### 구현 단계 완료 기준
- [ ] 상태를 `in-progress`로 변경
- [ ] 모든 서브태스크 구현 완료
- [ ] 중간 이상 복잡도: 각 서브태스크 기록
- [ ] 단위 테스트 통과

### 검증 단계 완료 기준
- [ ] 단위 테스트 실행 및 통과
- [ ] 중간 이상: 통합 테스트 통과
- [ ] 고복잡도: E2E 테스트 + 보안 체크
- [ ] 최종 기록 완료 (`update-subtask`)
- [ ] 상태를 `done`으로 변경

---

## 참고 자료

- **Task Master 문서**: `.taskmaster/CLAUDE.md`
- **복잡도 리포트**: `.taskmaster/reports/task-complexity-report.json`
- **PRD 문서**: `.taskmaster/docs/prd.txt`
- **SuperClaude 문서**: `~/.claude/CLAUDE.md`

---

---

## 핵심 변경사항 (v1.1)

### 📌 서브태스크별 증분 접근 (Medium/High Complexity)

**핵심 개념**: Medium 이상의 복잡도에서는 **서브태스크마다 설계→구현→검증 사이클을 반복**합니다.

**워크플로우 패턴**:
```bash
# 1. 초기 계획: 전체 태스크 아키텍처 이해
task-master show <task-id>
/sc:design --serena --seq --think

# 2. 서브태스크별 반복
task-master set-status --id=<task-id> --status=in-progress

# 서브태스크 X.1
task-master show X.1  # 컨텍스트 설정
/sc:design --serena   # X.1 상세 설계 (ID 명시 불필요)
/sc:implement --serena  # X.1 구현 (ID 명시 불필요)
pytest tests/test_X.py::test_X_1 -v  # X.1 즉시 검증
task-master update-subtask --id=X.1 --prompt="[구현+테스트 결과]"
task-master set-status --id=X.1 --status=done

# 서브태스크 X.2 (동일 패턴 반복)
task-master show X.2
/sc:design --serena
/sc:implement --serena
pytest tests/test_X.py::test_X_2 -v
task-master update-subtask --id=X.2 --prompt="[구현+테스트 결과]"
task-master set-status --id=X.2 --status=done

# 3. 최종 통합 검증
pytest tests/test_X.py -v  # 전체 통합 테스트
task-master set-status --id=<task-id> --status=done
```

**중요**: `/sc:design`과 `/sc:implement`는 **서브태스크 ID를 명시하지 않습니다**. `task-master show X.1`로 표시된 컨텍스트를 Claude가 자동으로 인식합니다.

---

**마지막 업데이트**: 2025-12-05
**프로젝트**: Binance USDT-M Futures Trading System
**버전**: 1.1 (서브태스크별 증분 접근 추가)
