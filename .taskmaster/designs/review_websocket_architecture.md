# WebSocket Architecture Review: Connection & Data Flow

## 1. Connection Maintenance (Keep-Alive Mechanism)
The WebSocket connection is maintained autonomously by the `binance-futures-connector` library.

*   **Background Thread:** Upon initialization, the library spawns a dedicated background thread that manages the socket connection. This separates network I/O from the main application logic.
*   **Heartbeat (Ping/Pong):** The background thread automatically handles the Ping/Pong heartbeat mechanism with the Binance server. This ensures the connection remains active even during periods of market inactivity (no data flow).
*   **Reconnection:** If the connection drops, the library's internal logic (depending on configuration) typically handles reconnection attempts, isolating this complexity from the `DataCollector`.

## 2. Connection Timing
The physical WebSocket connection is established explicitly when the `start_streaming()` method is called.

*   **Trigger:** `await collector.start_streaming()`
*   **Process:**
    1.  `ws_client` object is initialized.
    2.  Connection to the Binance WebSocket server (stream URL) is opened.
    3.  Subscription requests for specific streams (e.g., `btcusdt@kline_1m`) are sent immediately after connection.

## 3. Data Reception Timing & Flow
Data reception begins **asynchronously** immediately after the subscription requests are processed by the server.

*   **Trigger:** Market events (trades, price updates) on the exchange.
*   **Flow:**
    1.  **Binance Server:** Pushes a payload via the established socket.
    2.  **Background Thread:** Receives the raw message.
    3.  **Callback Dispatch:** The thread calls the registered `on_message` handler (`_handle_kline_message`).
    4.  **Processing:**
        *   The message is parsed into a `Candle` object.
        *   The candle is stored in the internal `buffer`.
        *   The `on_candle_callback` (if configured) is executed.
    5.  **Integration (Bridge):** The `on_candle_callback` serves as the bridge, typically publishing the candle as an `Event` to the `EventBus` for the rest of the system to consume.
