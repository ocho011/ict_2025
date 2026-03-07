# ConfigManager Validate Refactoring Design (Issue #132)

> **Feature**: config-summarize
> **Status**: Draft
> **Author**: Gemini CLI (PDCA Design)
> **Created**: 2026-03-07
> **PDCA Phase**: Design

---

## 1. 개요 (Overview)

본 설계서는 `ConfigManager.validate()` 메서드를 `summarize_config()`로 리팩토링하고, 시스템 시작 시 풍부한 환경 정보를 제공하는 '환경 요약 리포트' 기능을 구현하는 것을 목표로 한다.

## 2. 상세 설계 (Detailed Design)

### 2.1 메서드 시그니처 변경

- **기존**: `validate(self) -> bool`
- **변경**: `summarize_config(self) -> None`
- **사유**: 현재 `validate()`는 내부적으로 에러를 축적만 하고 실제 검증 실패 시 `False`를 반환하지만, 실질적인 검증은 각 설정 클래스의 `__post_init__`에서 예외(`ConfigurationError`)를 발생시켜 프로세스를 중단시키고 있다. 따라서 이름을 '요약(summarize)'으로 변경하여 역할을 명확히 한다.

### 2.2 환경 요약 리포트 구현 (Summarize Logic)

`summarize_config()` 메서드는 다음과 같은 정보를 로거(`logging.info`)를 통해 출력한다.

1.  **Environment Mode**: `TESTNET` (⚠️ 경고 아이콘 포함) 또는 `PRODUCTION` (🚨 크리티컬 아이콘 포함) 표시.
2.  **API Status**: API Key의 앞 4자리와 뒤 4자리만 노출하여 마스킹 처리 (예: `abcd...wxyz`).
3.  **Symbol Summary Table**:
    *   활성화된 모든 심볼 목록.
    *   각 심볼별 적용된 전략(`strategy`) 및 전략 타입(`composable`/`monolithic`).
    *   각 심볼별 설정된 레버리지(`leverage`).
4.  **Global Risk Defaults**:
    *   `max_risk_per_trade`, `stop_loss_percent`, `take_profit_ratio`.
5.  **Logging & Liquidation**:
    *   현재 로그 레벨, 로그 디렉토리.
    *   비상 청산(`emergency_liquidation`) 활성화 여부.

### 2.3 시스템 진입점 수정 (src/main.py)

`src/main.py`의 초기화 로직에서 `config_manager.validate()` 호출부를 제거하고 `config_manager.summarize_config()` 호출로 대체한다.

```python
# AS-IS
if not self.config_manager.validate():
    logger.error("Configuration validation failed")
    return False

# TO-BE
try:
    # 설정 로딩 과정에서 이미 __post_init__ 검증이 수행됨
    self.config_manager.summarize_config()
except ConfigurationError as e:
    logger.error(f"Configuration error: {e}")
    return False
```

## 3. 구현 세부 사항 (Implementation Details)

### 3.1 ConfigManager 변경 (src/utils/config_manager.py)

```python
def summarize_config(self) -> None:
    logger = logging.getLogger(__name__)
    
    # 1. 환경 정보
    mode_str = "TESTNET" if self.is_testnet else "PRODUCTION"
    mode_icon = "⚠️" if self.is_testnet else "🚨"
    logger.info(f"{mode_icon} Running in {mode_str} mode")
    
    # 2. API 정보 (마스킹)
    api_key = self.api_config.api_key
    masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "****"
    logger.info(f"🔑 API Key: {masked_key}")
    
    # 3. 심볼 및 전략 정보
    enabled_symbols = self.hierarchical_config.get_enabled_symbols()
    logger.info(f"📈 Active Symbols ({len(enabled_symbols)}):")
    for symbol in enabled_symbols:
        config = self.hierarchical_config.get_symbol_config(symbol)
        logger.info(f"  - {symbol:8} | Strategy: {config.strategy:15} | Leverage: {config.leverage}x")
    
    # 4. 리스크 및 기타 설정
    tc = self.trading_config
    logger.info(f"🛡️  Risk: Max Risk {tc.max_risk_per_trade*100:.1f}%, SL {tc.stop_loss_percent*100:.1f}%, TP Ratio {tc.take_profit_ratio}")
    
    liq = self.liquidation_config
    liq_status = "ENABLED" if liq.emergency_liquidation else "DISABLED"
    logger.info(f"⛑️  Emergency Liquidation: {liq_status}")
```

## 4. 테스트 전략 (Testing Strategy)

### 4.1 단위 테스트 업데이트

*   `tests/test_config_validation.py`: `test_validate_method`를 `test_summarize_config_method`로 변경하고, 로깅이 정상적으로 발생하는지(또는 예외가 발생하지 않는지) 확인한다.
*   `tests/test_config_environments.py`: `validate()` 호출부를 `summarize_config()`로 수정한다.

### 4.2 통합 테스트

*   `python src/main.py`를 실행하여 시작 시 요약 리포트가 콘솔에 예쁘게 출력되는지 확인한다.

## 5. 영향 범위 (Scope of Impact)

*   `src/utils/config_manager.py`: 메서드 리네임 및 로직 추가.
*   `src/main.py`: 호출 방식 변경.
*   `tests/`: 관련 테스트 케이스 수정.

---

## 6. 보안 고려 사항 (Security Considerations)

*   API Secret은 절대 출력하지 않는다.
*   API Key는 마스킹 처리하여 로그 파일에 전체 노출되지 않도록 한다.
