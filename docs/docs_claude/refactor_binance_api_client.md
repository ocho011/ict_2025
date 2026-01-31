## Issue: Refactor Binance API Client for Centralized Management and Rate Limit Handling

### Problem Description

Currently, our application initializes multiple independent instances of the `binance.um_futures.UMFutures` client. Specifically:
- `src/core/data_collector.py` (BinanceDataCollector) creates its own `UMFutures` client for historical REST API calls (`self.rest_client`).
- `src/execution/order_manager.py` (OrderExecutionManager) creates its own `UMFutures` client for order execution and account queries (`self.client`).

While this approach provides modularity, it leads to several drawbacks:
1.  **Redundant API Connections:** Each component establishes its own HTTP connection pool to the Binance REST API, potentially increasing resource consumption and connection overhead.
2.  **Uncoordinated Rate Limit Management:** Although `OrderExecutionManager` implements a `RequestWeightTracker`, `BinanceDataCollector` does not explicitly manage API rate limits for its REST calls. With independent clients, there's no centralized mechanism to coordinate API requests across components, making the application vulnerable to rate limit violations if both components are actively making requests, especially for `DataCollector`'s `get_historical_candles` method. A heavy load from one client could inadvertently cause the other to be rate-limited.
3.  **Configuration Duplication:** API keys, secrets, and testnet/mainnet settings are passed and managed separately for each client instance, leading to redundant configuration and potential for inconsistencies.
4.  **Inconsistent Behavior:** Different `UMFutures` client instances might be configured with slightly different parameters (e.g., `show_limit_usage` is explicitly set for `OrderExecutionManager` but not for `BinanceDataCollector`), potentially leading to subtle differences in behavior or observability.

### Proposed Solution: Centralized Binance API Client Service

We propose refactoring to a single, centralized Binance API client instance or a dedicated service that manages this client. This service would be responsible for:
1.  **Single Instance Management:** Creating and holding a single instance of `binance.um_futures.UMFutures`.
2.  **Centralized Configuration:** Loading API keys, secrets, and environment settings (testnet/mainnet) from a single source.
3.  **Coordinated Rate Limit Handling:** Implementing a comprehensive `RequestWeightTracker` or similar mechanism at the service level to manage all outgoing Binance REST API requests, ensuring the entire application stays within Binance's rate limits. This could involve queues, exponential backoff, or token bucket algorithms.
4.  **Dependency Injection:** Providing the shared client instance or the client service to `BinanceDataCollector`, `OrderExecutionManager`, and any other component requiring Binance REST API access via dependency injection.

### Benefits

-   **Improved Rate Limit Management:** Centralized tracking and control of API weight across all components, significantly reducing the risk of rate limit violations.
-   **Reduced Resource Usage:** Fewer HTTP connection pools and potentially lower memory footprint.
-   **Simplified Configuration:** API credentials and environment settings are managed in one place.
-   **Enhanced Consistency:** Ensures all components use the same API client configuration and behavior.
-   **Easier Maintenance:** Changes or updates to the API client configuration or logic only need to be applied in one central location.
-   **Better Observability:** A single point for monitoring all Binance API interactions and rate limit status.

### Considerations / Challenges

-   **Asynchronous Operations and Thread Safety:** The `UMFutures` client might need to be shared across multiple asynchronous tasks. We need to ensure that the shared instance is thread-safe and can handle concurrent access without issues. `binance.um_futures.UMFutures` is generally safe for concurrent *requests* but needs careful consideration for *stateful* operations if any.
-   **Dependency Injection Implementation:** Determine the best pattern for injecting the shared client/service (e.g., constructor injection, service locator) to avoid tight coupling.
-   **Impact on Existing Codebase:** Identify all locations where `UMFutures` clients are currently instantiated and update them to use the new centralized service. This will require careful refactoring and testing.
-   **Error Handling:** Ensure the centralized service gracefully handles API errors and propagates them appropriately to calling components.
-   **Show Limit Usage:** The `show_limit_usage=True` option is crucial for `OrderExecutionManager`. This feature should be maintained and integrated into the centralized rate limit tracking.

### Next Steps

1.  Conduct a detailed design review for the proposed centralized API client service.
2.  Identify all code locations that instantiate `UMFutures` and outline the changes required.
3.  Propose a phased implementation plan.
4.  Develop unit and integration tests for the new service and updated components.

---
**Labels:** `refactoring`, `api`, `binance`, `technical-debt`, `performance`
**Assignees:** (To be assigned)
**Milestone:** (To be determined)