# 📋 [PLAN] src/utils/config_manager.py 내 도달 불가능한 코드 수정

## 🎯 목표 (Goal)
`ConfigManager._load_trading_config` 메서드에서 `max_symbols` 유효성 검사 및 리소스 경고 로직이 `return` 문 뒤에 있어 실행되지 않는 문제를 수정하고, 설정의 안전성을 확보합니다.

## 🛠️ 작업 내용 (Tasks)
- [ ] `src/utils/config_manager.py`의 `_load_trading_config` 메서드 분석
- [ ] `return TradingConfig(...)` 문장을 메서드 가장 하단으로 이동시키거나 검증 로직을 위로 올림
- [ ] `max_symbols` 유효성 검사 및 리소스 경고 로직이 정상 동작하는지 확인
- [ ] 관련 단위 테스트 추가 또는 수정

## 🔍 검증 계획 (Verification)
- [ ] `max_symbols`를 20 초과(예: 25)로 설정했을 때 `ConfigurationError`가 발생하는지 확인
- [ ] `max_symbols`를 15 이상(예: 16)으로 설정했을 때 리소스 사용량 경고 로그가 출력되는지 확인

---
*Created: 2026-02-26 15:00:00*
