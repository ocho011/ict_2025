# PDCA Plan: 계층적 전략 주입(Hierarchical Injection) 아키텍처 리팩토링

**작성일**: 2026년 2월 26일 목요일
**상태**: 계획(Plan) 승인 대기 중

## 1. 목적 (Goal)
- **현재 문제**: `trading_config.ini` 기반의 평면적 구조로 인해 모든 심볼에 동일한 전략 파라미터가 강제됨 (1:N Relay).
- **목표**: `TradingConfigHierarchical`을 활용하여 각 심볼(BTC, ETH 등)이 독립적인 전략과 파라미터로 작동하도록 시스템 구조를 혁파 (Injection).

## 2. 주요 작업 범위 (Scope)
- **데이터 레이어**: `ConfigManager` 내 YAML 로딩 로직 고도화 및 INI 설정을 `Hierarchical` 구조로 자동 변환하는 어댑터 구현.
- **팩토리 레이어**: 심볼명을 인자로 받아 해당 심볼에 최적화된 `StrategyConfig` 객체 또는 조립된 전략 인스턴스를 반환하는 `StrategyFactory` 강화.
- **실행 레이어**: `TradingEngine`의 전략 초기화 루프를 수정하여, 전역 설정을 참조하는 대신 팩토리로부터 주입(Injection)받는 구조로 변경.

## 3. 성공 기준 (Success Criteria)
- [ ] **독립성 검증**: BTCUSDT와 ETHUSDT에 서로 다른 전략(예: ICT vs SMA) 또는 서로 다른 레버리지를 설정했을 때 각기 다르게 작동하는 로그 확인.
- [ ] **회귀 테스트**: 리팩토링 후에도 단일 심볼 백테스트 결과가 기존과 100% 일치해야 함.
- [ ] **구조적 개선**: `TradingEngine` 코드 내에서 특정 전략(예: `ict_strategy`)에 대한 하드코딩된 참조가 제거되고 추상화된 인터페이스를 통해 주입되어야 함.

## 4. 위험 요소 및 대응 (Risk & Mitigation)
- **위험**: 대규모 리팩토링으로 인한 기존 백테스트 로직 파손.
- **대응**: `git worktree`를 활용한 병렬 환경 유지 및 `zero-script-qa`를 통한 로그 기반 패턴 대조 검증.

## 5. 다음 단계 (Next Steps)
- [ ] `docs/02-design/features/hierarchical_injection_design.md` 상세 설계서 작성.
- [ ] `ConfigManager` 인터페이스 변경안 확정.
