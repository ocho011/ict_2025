# Q&A Log: 2025-12-19 Order Filled Event Handling

## ORDER_PLACED 이후 ORDER_FILLED 이벤트 처리 방식
**Q:** `ORDER_PLACED`에서 `ORDER_FILLED`로 이어지는 이벤트 발생은 프로젝트에 의한 '적극적인 조작'이라기보다는 '외부(거래소) 처리 결과에 대한 인식'의 성격이 강하다. 그렇다면 거래소 상황을 주기적으로 체크(Polling)하여 주문이 체결되었는지 감시하고, 이를 인식했을 때 이벤트 버스에 Publish 해야 하는 방식인가?

**A:**
주기적 체크(Polling)보다는 **웹소켓 스트림(Event-Driven)** 방식이 권장되며, 본 프로젝트도 이를 채택할 예정입니다.

1. **Polling 방식 (비효율적):** 
   HTTP API로 "체결됐니?"라고 계속 물어보는 방식은 API 제한(Rate Limit) 문제와 딜레이가 있어 실시간 트레이딩에 부적합합니다.
   
2. **User Data Stream 방식 (프로젝트 예정):**
   바이낸스는 계정 변동사항(체결, 잔고 등)을 실시간으로 푸시해주는 **User Data Stream**을 제공합니다.
   향후 구현될 **`UserDataCollector`** (또는 `AccountManager`)가 이 스트림을 구독하고 있다가, 거래소로부터 체결 메시지(`executionReport`)가 날아오는 즉시 `ORDER_FILLED` 이벤트를 생성하여 버스에 태우는 구조가 될 것입니다.
