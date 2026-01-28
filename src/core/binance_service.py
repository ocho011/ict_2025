"""
Centralized Binance API client service with rate limit tracking.
"""

import logging
from typing import Any, Dict, Optional

from binance.um_futures import UMFutures


class RequestWeightTracker:
    """
    Tracks API request weight to prevent rate limit violations.

    Binance provides weight usage in response headers when client is initialized
    with show_limit_usage=True. This tracker monitors the usage and warns when
    approaching limits.
    """

    def __init__(self):
        """Initialize weight tracker."""
        self.current_weight = 0
        self.weight_limit = 2400  # Binance limit: 2400 requests/minute
        self.logger = logging.getLogger(__name__)

    def update_from_headers(self, headers: Optional[Dict] = None):
        """
        Update weight tracking from API response headers.

        Binance returns weight information in headers:
        - 'X-MBX-USED-WEIGHT-1M': Current weight used in 1-minute window

        Args:
            headers: Response headers from Binance API
        """
        if not headers:
            return

        # Extract weight from headers
        weight_str = headers.get("X-MBX-USED-WEIGHT-1M")
        if weight_str:
            try:
                self.current_weight = int(weight_str)

                # Log warning if approaching limit (80% threshold)
                if self.current_weight > self.weight_limit * 0.8:
                    self.logger.warning(
                        f"Approaching Binance rate limit: {self.current_weight}/{self.weight_limit} "
                        f"({self.current_weight / self.weight_limit * 100:.1f}%)"
                    )
            except ValueError:
                self.logger.error(f"Invalid weight value in header: {weight_str}")

    def check_limit(self) -> bool:
        """
        Check if we're approaching rate limit.

        Returns:
            True if safe to proceed, False if should wait
        """
        # Allow up to 90% of limit
        return self.current_weight < self.weight_limit * 0.9

    def get_status(self) -> Dict[str, Any]:
        """
        Get current weight tracking status.

        Returns:
            Dictionary with weight usage information
        """
        return {
            "current_weight": self.current_weight,
            "weight_limit": self.weight_limit,
            "usage_percent": (self.current_weight / self.weight_limit * 100)
            if self.weight_limit > 0
            else 0,
            "safe_to_proceed": self.check_limit(),
        }


class BinanceServiceClient:
    """
    Centralized service for interacting with Binance Futures REST API.

    Features:
    - Single UMFutures client instance shared across components
    - Integrated Request Weight tracking for all API calls
    - Automatic response unwrapping when show_limit_usage=True
    """

    def __init__(self, api_key: str, api_secret: str, is_testnet: bool = True) -> None:
        """
        Initialize Binance service.

        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            is_testnet: Whether to use testnet (default: True)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_testnet = is_testnet
        self.base_url = (
            "https://testnet.binancefuture.com"
            if is_testnet
            else "https://fapi.binance.com"
        )

        # Initialize underlying UMFutures client
        # show_limit_usage=True ensures weight information is returned in headers
        self.client = UMFutures(
            key=api_key,
            secret=api_secret,
            base_url=self.base_url,
            show_limit_usage=True,
        )

        self.weight_tracker = RequestWeightTracker()
        self.logger = logging.getLogger(__name__)

    def _handle_response(self, response: Any) -> Any:
        """
        Update weight tracker and unwrap data from response.

        Args:
            response: Response from UMFutures client

        Returns:
            Unwrapped data content
        """
        # Update weight tracker if headers are present
        if isinstance(response, dict) and "headers" in response:
            self.weight_tracker.update_from_headers(response["headers"])

        # Unwrap data if present
        if isinstance(response, dict) and "data" in response:
            return response["data"]

        return response

    def __getattr__(self, name: str) -> Any:
        """
        Dynamic Proxy Implementation:
        Proxies method calls to the underlying UMFutures client to intercept 
        requests and inject cross-cutting concerns.

        Role & Logic:
        1. Acting as a Proxy: This class does not implement every Binance API 
           method. Instead, it intercepts calls to undefined methods and 
           delegates them to 'self.client' (the Real Subject).
        2. Interception (Wrapping): It wraps the returned callable from the 
           underlying client with a 'wrapper' function.
        3. Feature Injection: This allows the service to automatically execute 
           post-processing logic (Weight Tracking and Response Unwrapping) 
           via '_handle_response' for every proxied API call.

        Args:
            name: Method name to call on UMFutures client

        Returns:
            Wrapped callable or attribute from UMFutures client
        """
        attr = getattr(self.client, name)

        if callable(attr):

            def wrapper(*args, **kwargs):
                # Execute the actual API call
                response = attr(*args, **kwargs)
                # Apply weight tracking and data unwrapping
                return self._handle_response(response)

            return wrapper

        return attr

    # User Data Stream Listen Key Methods
    # Explicitly defined despite proxy support:
    # these methods handle semantically critical and high-risk APIs
    # (listen keys, algo orders), so intent and usage must be explicit.

    def new_listen_key(self) -> Dict[str, Any]:
        """
        Create a new listen key for User Data Stream.

        POST /fapi/v1/listenKey

        Listen keys are valid for 60 minutes. Use renew_listen_key() to extend.

        Returns:
            Dict containing {"listenKey": "abc123..."}

        Raises:
            Exception: If API request fails
        """
        response = self.client.new_listen_key()
        return self._handle_response(response)

    def renew_listen_key(self, listen_key: str) -> Dict[str, Any]:
        """
        Keep-alive ping for listen key (prevents expiration).

        PUT /fapi/v1/listenKey

        Should be called at least once per 60 minutes. Recommended: every 30 minutes.

        Args:
            listen_key: The listen key to renew

        Returns:
            Dict containing {"listenKey": "abc123..."} or empty dict on success

        Raises:
            Exception: If API request fails
        """
        response = self.client.renew_listen_key(listenKey=listen_key)
        return self._handle_response(response)

    def close_listen_key(self, listen_key: str) -> Dict[str, Any]:
        """
        Close/delete listen key on shutdown.

        DELETE /fapi/v1/listenKey

        Call this when shutting down the User Data Stream to clean up resources.

        Args:
            listen_key: The listen key to close/delete

        Returns:
            Empty dict on success

        Raises:
            Exception: If API request fails
        """
        response = self.client.close_listen_key(listenKey=listen_key)
        return self._handle_response(response)

    # Algo Order API Methods
    # Required since 2025-12-09 for conditional orders (STOP_MARKET, TAKE_PROFIT_MARKET, etc.)

    def new_algo_order(
        self,
        symbol: str,
        side: str,
        type: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Place a new algo order (conditional order).

        POST /fapi/v1/algoOrder

        Required for STOP_MARKET, TAKE_PROFIT_MARKET, STOP, TAKE_PROFIT,
        and TRAILING_STOP_MARKET orders since Binance migrated these to
        the Algo Service on 2025-12-09.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            side: Order side ("BUY" or "SELL")
            type: Order type (e.g., "STOP_MARKET", "TAKE_PROFIT_MARKET")
            **kwargs: Additional parameters:
                - triggerPrice: Price to trigger the order (required)
                - quantity: Position size (cannot use with closePosition=true)
                - closePosition: "true" to close entire position
                - workingType: "MARK_PRICE" or "CONTRACT_PRICE" (default)
                - positionSide: "LONG", "SHORT", or "BOTH" (for hedge mode)
                - priceProtect: "TRUE" or "FALSE"
                - recvWindow: Request validity window in ms

        Returns:
            Dict containing algo order details including algoId

        Raises:
            ClientError: If API request fails
        """
        # Build payload with required algoType
        payload = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": side,
            "type": type,
            **kwargs,
        }

        # Use sign_request to call the algo order endpoint
        response = self.client.sign_request(
            http_method="POST",
            url_path="/fapi/v1/algoOrder",
            payload=payload,
        )
        return self._handle_response(response)
