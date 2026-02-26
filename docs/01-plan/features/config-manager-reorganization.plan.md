# PDCA Plan: ConfigManager Class Reorganization

## 1. 개요 (Background)
`src/utils/config_manager.py`의 `ConfigManager` 클래스는 현재 메서드 배치가 비논리적이며, 특히 일부 프로퍼티가 중복 정의되어 있어 유지보수 및 가독성에 문제가 있습니다. 이를 깔끔하게 정리하여 코드 품질을 향상시킵니다.

## 2. 현재 상태 분석 (Analysis)
- **중복 정의**: `api_config`, `trading_config`, `logging_config` 프로퍼티가 클래스 내에서 두 번씩 정의됨.
- **순서 불일치**: 비공개 로더와 공개 프로퍼티가 임의의 순서로 배치됨.
- **순환 참조 방지**: `_load_hierarchical_config` 내의 지역 임포트(`src.config.symbol_config`) 유지 필요.

## 3. 목표 (Objectives)
- 모든 공개 프로퍼티를 상단(초기화 메서드 다음)으로 모으기.
- 중복 정의된 프로퍼티 제거.
- 비공개 로더 메서드들을 하단으로 모으기.
- 논리적 그룹화(Initialization -> Properties -> Public Methods -> Private Loaders).

## 4. 상세 실행 계획 (Execution Plan)
1. **Research**: 현재 클래스의 모든 멤버 메서드 목록 및 위치 기록 (완료).
2. **Strategy**: 제안된 논리적 순서에 따라 코드를 블록 단위로 이동.
3. **Execution**:
    - `__init__`, `_load_configs` 유지.
    - 모든 `@property` 메서드 이동 및 중복 제거.
    - `validate` 메서드 이동.
    - 모든 `_load_*` 비공개 메서드 하단 배치.
4. **Validation**: `pytest`를 실행하여 설정 로드 기능에 문제가 없는지 확인.

## 5. 검증 계획 (Validation Plan)
- `tests/test_config_validation.py` 또는 관련 설정 테스트 실행.
- 중복 정의 제거 후 정적 분석 도구(mypy 등)로 체크 (필요 시).

## 6. 일정 (Schedule)
- 2026-02-26: 계획 수립 및 실행
- 2026-02-26: 검증 및 완료 보고
