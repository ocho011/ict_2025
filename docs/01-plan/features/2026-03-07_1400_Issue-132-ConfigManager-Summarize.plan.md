# ConfigManager Validate Refactoring Plan (Issue #132)

> **Feature**: config-summarize
> **Status**: Draft
> **Author**: Gemini CLI (PDCA Plan)
> **Created**: 2026-03-07
> **PDCA Phase**: Plan

---

## 1. Overview

### 1.1 목적

`src/utils/config_manager.py`의 `ConfigManager.validate()` 메서드를 리팩토링하여, 실질적인 데이터 검증보다는 시스템 시작 시 현재 환경(TESTNET/PRODUCTION) 및 주요 설정값들을 한눈에 보여주는 **'환경 요약 리포트'** 기능으로 전환한다.

### 1.2 배경

- **현상**: 현재 `ConfigManager.validate()`는 레버리지 경고와 환경 모드 로깅 역할만 수행하고 있으며, 실제 데이터 검증은 각 설정 클래스(`APIConfig`, `TradingConfig` 등)의 `__post_init__`에서 이미 수행되고 있다.
- **문제점**: 메서드 이름(`validate`)과 실제 동작(로깅/요약) 간의 불일치가 존재하며, 시스템 시작 시 사용자에게 제공되는 정보가 제한적이다.
- **해결책**: 메서드 이름을 명확하게 변경하고, 활성화된 심볼, 레버리지, 전략 설정 등을 포함한 통합 리포트 출력 기능을 강화한다.

### 1.3 범위

| 항목 | 포함 | 제외 |
|------|------|------|
| `ConfigManager.validate()` 이름 변경 (`summarize_config`) | O | - |
| 통합 환경 리포트 출력 로직 구현 (심볼별 전략, 레버리지 등) | O | - |
| `src/main.py` 호출부 업데이트 | O | - |
| 관련 테스트 코드(`tests/`) 업데이트 및 정리 | O | - |
| 개별 설정 클래스의 `__post_init__` 검증 로직 강화 | - | X (기존 로직 유지) |
| 설정 파일(`base.yaml`) 구조 변경 | - | X (기존 구조 유지) |

---

## 2. 사용자 결정사항

| # | 질문 | 결정 |
|---|------|------|
| 1 | 새로운 메서드 이름 | `summarize_config` (또는 `check_environment`) |
| 2 | 리포트 출력 형식 | 로거(logging)를 통한 구조화된 텍스트 출력 |
| 3 | 포함될 정보 수준 | 심볼 목록, 각 심볼별 전략/레버리지, 테스트넷 여부, 로그 레벨 등 |

---

## 3. AS-IS / TO-BE

### 3.1 AS-IS: 현재 validate() 동작

```python
def validate(self) -> bool:
    # ... (생략) ...
    if self._trading_config.leverage > 1 and self._api_config.is_testnet:
        logger.warning(f"Using {self._trading_config.leverage}x leverage in testnet mode")

    if self._api_config.is_testnet:
        logger.info("⚠️  Running in TESTNET mode")
    else:
        logger.warning("⚠️  Running in PRODUCTION mode with real funds!")
    # ... (생략) ...
    return len(errors) == 0
```

### 3.2 TO-BE: 목표 summarize_config() 동작

```python
def summarize_config(self) -> None:
    """
    시스템 시작 시 현재 설정 상태를 요약하여 출력한다.
    """
    # 1. 환경 모드 출력 (TESTNET/PRODUCTION)
    # 2. API 설정 요약 (Key 일부 마스킹 처리 등)
    # 3. 트레이딩 설정 요약 (활성화된 심볼 목록, 전략, 레버리지 등)
    # 4. 리스크 설정 요약 (Max Risk, SL/TP 등)
    # 5. 로깅 및 기타 설정 요약
    pass
```

---

## 4. 구현 단계 (Phases)

### Phase 1: 메서드 리팩토링 및 요약 로직 구현

**목표**: `ConfigManager` 내에 새로운 요약 메서드를 구현하고 기존 `validate()`를 대체하거나 정리한다.

**변경 파일:**
| 파일 | 변경 내용 |
|------|-----------|
| `src/utils/config_manager.py` | `validate()` 메서드를 `summarize_config()`로 리네임 및 리포트 출력 로직 강화 |

### Phase 2: 시스템 진입점 및 호출부 업데이트

**목표**: 시스템 시작 시 새로운 요약 메서드가 호출되도록 수정한다.

**변경 파일:**
| 파일 | 변경 내용 |
|------|-----------|
| `src/main.py` | `config_manager.validate()` 호출을 `config_manager.summarize_config()`로 변경 |

### Phase 3: 테스트 코드 업데이트 및 검증

**목표**: 변경된 메서드 이름과 동작에 맞춰 기존 테스트 코드를 수정하고 정상 동작을 확인한다.

**변경 파일:**
| 파일 | 변경 내용 |
|------|-----------|
| `tests/test_config_validation.py` | `validate()` 관련 테스트를 `summarize_config()` 테스트로 변경 |
| `tests/test_config_environments.py` | 호출부 업데이트 |

---

## 5. 의존성 및 순서

1. **Phase 1 (Refactor)** -> **Phase 2 (Main Update)** -> **Phase 3 (Test Update)** 순서로 진행.
2. 기존 `validate()`가 `bool`을 반환하여 프로세스 중단 여부를 결정했다면, 새 방식에서는 각 설정 클래스의 예외 발생으로 프로세스가 중단되므로 호출부의 조건문 처리가 필요함.

---

## 6. 리스크 및 완화

| 리스크 | 영향 | 완화 방안 |
|--------|------|-----------|
| `validate()` 제거 시 기존 검증 로직 누락 | Medium | 모든 검증이 `__post_init__`에 포함되어 있는지 전수 조사 |
| 테스트 코드 대량 수정 부담 | Low | 단순 이름 변경 및 호출 방식 변경이므로 자동화된 리팩토링 도구 활용 가능 |
| 시작 시 로그 양 과다 | Low | `INFO` 레벨로 필요한 정보만 선별하여 출력 |

---

## 7. 성공 기준 (Acceptance Criteria)

- [ ] `ConfigManager.validate()`가 `summarize_config()`로 성공적으로 변경됨.
- [ ] 시스템 시작 시 활성화된 심볼, 레버리지, 전략 정보를 포함한 환경 리포트가 출력됨.
- [ ] `src/main.py`가 정상적으로 실행되며, 설정 오류 시 기존과 동일하게 프로세스가 중단됨.
- [ ] 모든 관련 테스트(`pytest`)가 통과함.

---

## 8. 영향받는 파일 요약

| 파일 | Phase | 변경 유형 |
|------|-------|-----------|
| `src/utils/config_manager.py` | 1 | 메서드 리네임 및 구현 |
| `src/main.py` | 2 | 호출부 수정 |
| `tests/test_config_validation.py` | 3 | 테스트 코드 수정 |
| `tests/test_config_environments.py` | 3 | 테스트 코드 수정 |
