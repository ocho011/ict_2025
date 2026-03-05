"""
Asynchronous Binance API client using aiohttp.

Compliant with Real-time Trading Guidelines:
- Non-blocking IO for minimized latency
- Session pooling for TCP reuse
- Context manager for safe lifecycle management
"""

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

import aiohttp


class AsyncBinanceClient:
    """
    Async client for Binance Futures REST API.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        is_testnet: bool = True,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_testnet = is_testnet
        
        if base_url:
            self.base_url = base_url
        else:
            self.base_url = (
                "https://testnet.binancefuture.com"
                if is_testnet
                else "https://fapi.binance.com"
            )
            
        self._session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(self.__class__.__name__)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Initialize the aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=aiohttp.ClientTimeout(total=10)
            )
            self.logger.info("Async Binance session started (testnet=%s)", self.is_testnet)

    async def stop(self):
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
            self.logger.info("Async Binance session closed")

    def _get_signature(self, params: Dict[str, Any]) -> str:
        """Calculate HMAC SHA256 signature for parameters."""
        query_string = urlencode(params)
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    async def request(
        self,
        method: str,
        path: str,
        signed: bool = False,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Execute an async HTTP request."""
        if self._session is None:
            await self.start()

        url = f"{self.base_url}{path}"
        
        # Normalize params: convert bools to strings for aiohttp/yarl and Binance API
        request_params = {}
        if params:
            for k, v in params.items():
                if isinstance(v, bool):
                    request_params[k] = str(v).lower()
                elif v is not None:
                    request_params[k] = v

        if signed:
            request_params["timestamp"] = int(time.time() * 1000)
            request_params["signature"] = self._get_signature(request_params)

        async with self._session.request(method, url, params=request_params) as response:
            data = await response.json()
            if response.status != 200:
                # Do not log here at ERROR level to avoid polluting logs with benign errors
                # like "No need to change margin type" (-4046).
                # The caller will handle logging with proper context.
                raise Exception(f"Binance API error: {data}")
            return data

    # Convenience methods for common API calls

    async def get_exchange_info(self) -> Dict[str, Any]:
        """GET /fapi/v1/exchangeInfo"""
        return await self.request("GET", "/fapi/v1/exchangeInfo")

    async def get_mark_price(self, symbol: str) -> float:
        """GET /fapi/v1/premiumIndex"""
        data = await self.request("GET", "/fapi/v1/premiumIndex", params={"symbol": symbol})
        return float(data.get("markPrice", 0))

    async def get_klines(
        self, symbol: str, interval: str, limit: int = 100
    ) -> Any:
        """GET /fapi/v1/klines"""
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return await self.request("GET", "/fapi/v1/klines", params=params)

    async def get_position_risk(self, symbol: Optional[str] = None) -> Any:
        """GET /fapi/v2/positionRisk (Signed)"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self.request("GET", "/fapi/v2/positionRisk", signed=True, params=params)

    async def new_order(
        self,
        symbol: str,
        side: str,
        type: str,
        quantity: float,
        price: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """POST /fapi/v1/order (Signed)"""
        params = {
            "symbol": symbol,
            "side": side,
            "type": type,
            "quantity": quantity,
            **kwargs
        }
        if price:
            params["price"] = price
        return await self.request("POST", "/fapi/v1/order", signed=True, params=params)

    async def new_algo_order(
        self,
        symbol: str,
        side: str,
        type: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        POST /fapi/v1/algoOrder (Signed)
        Used for conditional orders (STOP_MARKET, TAKE_PROFIT_MARKET, etc.)
        """
        params = {
            "symbol": symbol,
            "side": side,
            "algoType": "CONDITIONAL",
            "type": type,
            **kwargs
        }
        return await self.request("POST", "/fapi/v1/algoOrder", signed=True, params=params)

    async def cancel_all_orders(self, symbol: str) -> Any:
        """DELETE /fapi/v1/allOpenOrders (Signed)"""
        return await self.request(
            "DELETE", "/fapi/v1/allOpenOrders", signed=True, params={"symbol": symbol}
        )

    async def cancel_all_algo_orders(self, symbol: str) -> Any:
        """DELETE /fapi/v1/algoOpenOrders (Signed) - For Strategy Orders (VP/TWAP)"""
        return await self.request(
            "DELETE", "/fapi/v1/algoOpenOrders", signed=True, params={"symbol": symbol}
        )

    async def get_open_algo_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /fapi/v1/openAlgoOrders (Signed) - Get open conditional/strategy orders"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self.request("GET", "/fapi/v1/openAlgoOrders", signed=True, params=params)

    async def cancel_algo_order(self, symbol: str, algoId: str) -> Dict[str, Any]:
        """DELETE /fapi/v1/algoOrder (Signed) - Cancel a specific conditional order"""
        params = {"symbol": symbol, "algoId": algoId}
        return await self.request("DELETE", "/fapi/v1/algoOrder", signed=True, params=params)

    async def cancel_algo_orders_by_type(self, symbol: str, types: List[str]) -> List[Dict[str, Any]]:
        """
        Cancel open algo orders filtered by type.
        Since Binance doesn't have a direct 'by type' endpoint for all types,
        we fetch all open algo orders and cancel the ones matching the requested types.
        """
        results = []
        try:
            # 1. Fetch all open algo orders for the symbol
            open_orders = await self.get_open_algo_orders(symbol)
            if not open_orders:
                return []

            # 2. Filter and cancel matching orders
            for order in open_orders:
                # 'type' field exists for CONDITIONAL orders
                order_type = order.get("type")
                if order_type in types:
                    algo_id = order.get("algoId")
                    if algo_id:
                        try:
                            cancel_res = await self.cancel_algo_order(symbol, str(algo_id))
                            results.append(cancel_res)
                        except Exception as e:
                            self.logger.warning(f"Failed to cancel specific algo order {algo_id}: {e}")

            # 3. If no specific type matches but we have types, fallback to generic cancel
            # (Optional: Only if we want to ensure everything is cleared)
            if not results and ("STOP" in types or "TAKE_PROFIT" in types):
                # We tried specific cancellation, if it didn't find anything, we're likely clear.
                pass

            return results
            
        except Exception as e:
            self.logger.warning(f"Failed to cancel algo orders by type: {e}")
            return []

    # Listen Key management
    async def new_listen_key(self) -> Dict[str, Any]:
        """POST /fapi/v1/listenKey"""
        return await self.request("POST", "/fapi/v1/listenKey")

    async def renew_listen_key(self, listen_key: str) -> Dict[str, Any]:
        """PUT /fapi/v1/listenKey"""
        return await self.request("PUT", "/fapi/v1/listenKey", params={"listenKey": listen_key})

    async def close_listen_key(self, listen_key: str) -> Dict[str, Any]:
        """DELETE /fapi/v1/listenKey"""
        return await self.request("DELETE", "/fapi/v1/listenKey", params={"listenKey": listen_key})
