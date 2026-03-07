# PDCA Plan: Emergency Binance API & SSL Connection Fix

## 1. 개요
최근 바이낸스 선물 거래소와의 통신 과정에서 발생하는 치명적인 에러(-4130 주문 충돌 및 SSL 인증서 검증 실패)를 해결하여 봇의 가동성을 확보함.

## 2. 해결 목표
- **주문 충돌(-4130):** SL 갱신 시 발생하는 중복 주문 에러를 완전히 해결하여 트레일링 스탑의 안정성 확보.
- **SSL 인증서 에러:** macOS 및 클라우드 환경에서 발생하는 SSL 검증 실패 문제를 해결하여 REST API 및 WebSocket 연결 보장.
- **환경 이식성:** 다른 운영체제로 이전 시에도 추가 설정 없이 동작하도록 패키지 의존성 관리 보완.

## 3. 세부 계획
- **Step 1:** `src/execution/order_gateway.py` 내 SL 업데이트 로직 보완 (재시도 횟수 상향, 대기 시간 최적화).
- **Step 2:** `src/core/async_binance_client.py` 내 REST API 세션 초기화 시 `certifi` 인증서 주입.
- **Step 3:** `src/core/public_market_streamer.py` 내 WebSocket 연결 시 환경 변수(`SSL_CERT_FILE`) 설정.
- **Step 4:** `requirements.txt`에 `certifi` 패키지 추가하여 이식성 강화.

## 4. 일정
- **작업 시작:** 2026-03-07 04:00 (KST)
- **작업 완료:** 2026-03-07 08:30 (KST)

## 5. 기대 결과
봇이 에러 없이 구동되며, 실시간 시세 수신 및 자동 주문 갱신이 안정적으로 수행됨.
