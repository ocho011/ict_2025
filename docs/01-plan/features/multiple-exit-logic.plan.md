# Plan: Multiple Exit Strategy Logic Refactoring

- **Status:** Planning
- **Date:** 2026-02-25
- **Author:** Gemini CLI Agent

## 1. 문제 정의 (Objective)

현재 `ICTExitDeterminer`의 `should_exit` 메서드는 `if-elif` 구조로 되어 있어, `exit_strategy` 설정에 따라 단 하나의 탈출 전략만 활성화할 수 있습니다. 
예를 들어, `trailing_stop`을 사용하면 `timed` (시간 기반) 종료나 `breakeven` (본절가 이동) 로직이 동시에 작동하지 않는 제약이 있습니다.

## 2. 해결 방안 (Proposed Solution)

사용자의 요구사항(All-Enabled Flags, First-Triggered, Hard Stop + Dynamic)을 반영하여, 여러 탈출 조건을 동시에 감시하고 가장 먼저 도달하는 조건으로 포지션을 종료하도록 구조를 개선합니다.

### 2.1 로직 구조 변경
- `if-elif` 배타적 선택 구조를 독립적인 `if` 문 순차 실행 구조로 변경합니다.
- `trailing_stop`, `breakeven`, `timed`, `indicator_based` 중 `enabled` 플래그가 `True`인 모든 전략을 루프를 돌며 체크합니다.
- 어떤 전략이라도 종료 신호(`Signal`)를 반환하면 즉시 해당 신호를 채택하여 반환합니다 (First-Triggered 방식).

### 2.2 설정 호환성 및 확장성
- 특정 `exit_strategy` 변수값에 의존하지 않고, 각 전략 섹션의 `enabled` 플래그(예: `breakeven_enabled`, `timeout_enabled`)를 최우선으로 참조합니다.
- 거래소의 기본 SL/TP(Hard Stop)는 항상 유지하며, 봇 내부의 이 로직들은 '보조적인 실시간 탈출' 장치로 작동합니다.

## 3. 상세 작업 내역 (Tasks)

- [ ] **Task 1: ExitConfig 모델 보완** - 각 전략별 `enabled` 플래그가 명확히 파싱되도록 `ExitConfig` 데이터 클래스 및 파싱 로직 확인.
- [ ] **Task 2: ICTExitDeterminer.should_exit 리팩토링** - `if-elif` 구조를 제거하고, 활성화된 모든 전략을 순차적으로 호출하는 구조로 변경.
- [ ] **Task 3: 전략 우선순위 정의** - 호출 순서를 '위험 관리(SL)' -> '수익 보전(Trailing/BE)' -> '시간/지표 종료' 순으로 배치하여 안전성을 강화.
- [ ] **Task 4: 로깅 강화** - 어떤 전략에 의해 탈출이 결정되었는지 명확하게 로그에 남기도록 `exit_reason` 필드 활용.

## 4. 검증 계획 (Verification)

- **단위 테스트:** `timed` 종료와 `trailing_stop`이 동시에 활성화된 환경에서 각각의 트리거 상황 시뮬레이션.
- **통합 테스트:** 여러 플래그를 동시에 `True`로 설정하고 시스템이 정상적으로 모든 조건을 감시하는지 확인.
- **백테스트:** 과거 데이터를 통해 복합 전략 적용 시의 수익성 및 리스크 관리 효율 비교.

## 5. 기대 효과 (Expected Outcome)

- 단일 전략의 한계를 극복하고 유연한 리스크 관리 가능.
- 시간 기반 강제 종료와 수익 추적을 결합하여 자본 효율성 증대.
- 다양한 시장 상황에 대응할 수 있는 다중 방어막 구축.
