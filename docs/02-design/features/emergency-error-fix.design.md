# PDCA Design: Emergency Binance API & SSL Connection Fix

## 1. 개요
에러의 원인을 분석하고, 이를 해결하기 위한 구체적인 코드 수정 사양을 정의함.

## 2. 세부 설계 내역

### 2.1. SL 주문 충돌(-4130) 방어 로직 강화
- **수정 위치:** `src/execution/order_gateway.py` 내 `update_stop_loss` 메서드
- **설계:**
  - `max_place_retries`를 **5회**로 상향 (기존 2회).
  - 재시도 시 기존 알고 주문 취소 후 대기 시간(`asyncio.sleep`)을 **1.5초**로 상향 (기존 0.5s~1.0s).
  - 로그에 `Recovery: Cancelled conflicting order {algo_id}` 문구 추가하여 추적성 확보.

### 2.2. REST API SSL 인증서 검증 보완
- **수정 위치:** `src/core/async_binance_client.py` 내 `start` 메서드
- **설계:**
  - `ssl` 및 `certifi` 모듈 임포트.
  - `ssl.create_default_context(cafile=certifi.where())`를 통해 표준 CA 번들 로딩.
  - `aiohttp.TCPConnector(ssl=ssl_context)`를 `ClientSession` 생성 시 주입.

### 2.3. WebSocket SSL 인증서 검증 보완
- **수정 위치:** `src/core/public_market_streamer.py` 내 `__init__` 메서드
- **설계:**
  - `os.environ['SSL_CERT_FILE'] = certifi.where()` 설정 추가.
  - 이를 통해 내부적으로 사용하는 모든 통신 라이브러리가 동일한 인증서를 참조하도록 강제.

### 2.4. 패키지 의존성 업데이트
- **수정 위치:** `requirements.txt`
- **설계:**
  - `certifi` 패키지를 명시적으로 추가하여 환경 전이 시 자동 설치 보장.

## 3. 검증 전략
- **Log Analysis:** `trading.log`에서 `-4130` 발생 시 `Recovery` 로그와 함께 재시도가 성공하는지 확인.
- **Connection Test:** 봇 실행 시 `Exchange info fetch failed` 에러 없이 데이터 수신이 시작되는지 확인.
- **Portability Check:** `requirements.txt` 내 `certifi` 포함 여부 확인.
