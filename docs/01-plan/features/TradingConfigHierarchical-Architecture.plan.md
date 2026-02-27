# PDCA Plan: TradingConfigHierarchical 아키텍처 일관성 개선

## 1. 개요
- **배경**: `ConfigManager`의 하위 계층인 `TradingConfigHierarchical`이 다른 설정 클래스들과 달리 별도 파일(`symbol_config.py`)에 위치함에 따른 구조적 불일치 발생.
- **목표**: 설정 클래스들의 위치를 재조정하여 아키텍처 일관성을 확보하고 가독성 및 유지보수성을 향상함.

## 2. 분석 내용
- **현상**: `APIConfig`, `BinanceConfig`는 `utils/config_manager.py`에 정의됨. `TradingConfigHierarchical`은 `config/symbol_config.py`에 정의됨.
- **원인**: 전략(Strategy) 도메인과의 의존성 및 계층적 로직의 복잡성으로 인해 분리 설계됨.
- **문제점**: 설정 객체 정의 위치의 파편화로 인한 탐색 비용 증가 및 일관성 부족.

## 3. 실행 전략 (Strategy)
### 대안 A: TradingConfigHierarchical을 config_manager.py로 통합
- **장점**: 모든 설정 정의를 한 곳에서 확인 가능.
- **단점**: `config_manager.py` 비대화, 전략 모듈과의 순환 참조 위험.

### 대안 B: 모든 설정 객체를 src/config/ 모듈로 분리 (권장)
- **장점**: `ConfigManager`는 로드 및 관리 로직에만 집중(Single Responsibility), 도메인별 설정 분리로 응집도 향상.
- **구조 예시**:
    - `src/config/api_config.py`
    - `src/config/binance_config.py`
    - `src/config/symbol_config.py` (유지)

## 4. 상세 단계 (Checklist)
- [ ] [Plan] 각 설정 클래스의 도메인 의존성 정밀 분석
- [ ] [Plan] 순환 참조 발생 가능성 검증 (특히 전략 레지스트리 관련)
- [ ] [Design] 개선된 설정 디렉토리 구조 설계 및 공유
- [ ] [Do] 클래스 이동 및 참조(Import) 경로 수정
- [ ] [Check] 단위 테스트 및 시스템 초기화 로직 정상 작동 확인
- [ ] [Act] 리팩토링 결과 보고 및 문서 업데이트

## 5. 예상 결과
- 설정 관련 코드의 응집도 향상 및 `ConfigManager`의 책임 명확화.
- 신규 설정 추가 시 일관된 패턴 제공.
