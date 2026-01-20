# Trading Log Analysis Report (2026-01-21)

주 요청 사항인 `logs/trading.log` 및 `logs/audit/audit_20260120.jsonl` 파일(약 12시간 분량)을 정밀 분석한 결과입니다.

## 1. 기본 동작 확인 (Session Details)
- **세션 기간**: 2026-01-20 07:30:29 ~ 19:16:41 (약 11시간 46분)
- **운영 환경**: Binance Testnet, Isolated Margin, 1x Leverage
- **대상 심볼**: BTCUSDT, ETHUSDT, ZECUSDT
- **정상 작동**:
    - 멀티 코인 및 멀티 인터벌(1m, 5m, 15m) 캔들 데이터 수집 및 분석 정상.
    - `ict_strategy`에 기반한 신호 생성 및 리스크 검증 로직 정상 작동.
    - Ctrl+C 입력에 따른 `Graceful Shutdown` 및 `LiquidationManager`를 통한 포지션 정리 확인.

## 2. 주요 문제점 확인 (Critical Issues)

### A. 고아 주문(Orphaned Orders) 문제 미해결
분석 결과, TP/SL 주문이 완전히 해결되지 않고 거래소에 남아 있는 현상이 확인되었습니다.
- **증거**: ETHUSDT (07:31) 거래에서 주문 ID `8137650338`(TP)와 `8137650345`(SL)가 생성되었으나, 포지션이 종료된 이후에도 취소 로그(`Order canceled`)가 나타나지 않았습니다.
- **원인**: 현재 봇 아키텍처에 **User Data Stream(WebSocket) 리스너가 부재**합니다. 봇은 자신이 보낸 주문의 즉시 응답만 알고 있을 뿐, 이후 거래소 측에서 발생하는 체결(TP/SL 히트)을 실시간으로 감지하지 못합니다.
- **위험**: 한쪽(TP)이 체결되어 포지션이 종료되어도 반대쪽(SL)이 살아 있어, 이후 가격 변동 시 원치 않는 역방향 포지션이 새로 열릴 위험이 큽니다.

### B. 불합리한 손익비 (Unreasonable Risk-Reward Ratio)
전반적인 거래들의 손익비(Risk-Reward)가 지나치게 낮거나 음수 기대값을 보입니다.
- **사례**:
    - **ZECUSDT (07:32)**: RR = 0.13 (익절 0.1 pts vs 손절 0.76 pts)
    - **BTCUSDT (13:00)**: RR = 0.018 (익절 15.4 pts vs 손절 826.1 pts)
- **원인**: `ICTStrategy` 혹은 `RiskManager` 내의 익절(TP) 타겟 설정 로직이 현재 시장 변동성이나 스윙 폭에 비해 너무 보수적으로 잡혀 있습니다. 승률이 매우 높지 않은 이상 장기적으로 자산이 우하향할 구조입니다.

### C. 실시간 체결 로그 누락
- **현상**: `Side=SELL` (진입) 체결 로그는 존재하나, `Side=BUY` (청산) 체결 로그가 거의 없습니다.
- **이유**: `TradingEngine._on_order_filled` 이벤트가 봇이 직접 시장가 주문을 던졌을 때만 수동으로 발행되기 때문입니다. 거래소에 걸려 있던 TP/SL 주문이 체결될 때는 이 이벤트가 트리거되지 않습니다.

## 3. 수익률 개선을 위한 제안

1. **User Data Stream 도입**: `Execution Report`를 실시간 수신하여 TP/SL 체결 시 즉각 반대 주문을 취소하는 로직을 강화해야 합니다.
2. **TP 로직 최적화**: 단순히 고정 포인트가 아닌, 시장 구조(Swing High/Low)나 ATR 기반의 유동적인 TP를 설정하여 최소 1.5 이상의 RR을 확보해야 합니다.
3. **포지션 폴링 간격 조정**: 현재 1분 단위 폴링(`No position data...` 경고 원인)은 너무 느립니다. 스트림이 도입되기 전까지는 폴링 주기를 단축하거나, 스트림 기반으로 전환하여 실시간 성을 확보해야 합니다.

## 4. 기타 관찰 사항
- `No position data returned for SYMBOL` 경고가 매 분 발생합니다. 이는 진입 시도 전후에 포지션 여부를 체크할 때 데이터 응답 지연 혹은 부재를 경고 수준(WARNING)으로 처리하고 있기 때문입니다. (INFO 수준이 더 적절해 보입니다.)
- 세션 종료 시 `LiquidationManager`가 남은 포지션을 시장가로 잘 정리하고 있음을 확인했습니다. (BTCUSDT 청산 로그 확인)
