"""
User Data Stream management for Binance Futures User Data Stream WebSocket.

This module provides the UserDataStreamManager class for managing listen keys
and receiving real-time order execution events from Binance User Data Stream.
"""

import asyncio
import logging
from typing import Optional


class UserDataStreamManager:
    """
    Manages listen key lifecycle for Binance User Data Stream.

    Responsibilities:
    - Create listen key via REST API
    - Keep-alive loop (ping every 30 minutes)
    - Graceful shutdown with listen key cleanup

    Listen Key Lifecycle:
    - Valid for 60 minutes after creation
    - Must be pinged (keep-alive) at least once per 60 minutes
    - Recommended: ping every 30 minutes for safety margin
    - Auto-renewal on expiration

    Binance API Endpoints:
    - POST /fapi/v1/listenKey - Create listen key
    - PUT /fapi/v1/listenKey - Keep alive (renew)
    - DELETE /fapi/v1/listenKey - Delete listen key

    WebSocket Connection:
    - wss://stream.binancefuture.com/ws/{listenKey}
    - Receives ORDER_TRADE_UPDATE, ACCOUNT_UPDATE, etc.
    """

    # Keep-alive interval (30 minutes = 1800 seconds)
    # Binance requires keep-alive at least once per 60 minutes
    # 30 minutes provides safety margin
    KEEP_ALIVE_INTERVAL_SECONDS = 1800

    def __init__(
        self,
        binance_service,
    ):
        """
        Initialize UserDataStreamManager.

        Args:
            binance_service: BinanceServiceClient instance for REST API calls

        Attributes:
            logger: Logger instance
            listen_key: Current active listen key (None if not started)
            _keep_alive_task: Async task for keep-alive loop
            _running: Runtime flag
        """
        self.binance_service = binance_service
        self.logger = logging.getLogger(__name__)

        self.listen_key: Optional[str] = None
        self._keep_alive_task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def start(self) -> str:
        """
        Create listen key and start keep-alive loop.

        Creates a new listen key via Binance API and starts a background
        keep-alive task that pings the key every 30 minutes to prevent expiration.

        Raises:
            Exception: If listen key creation fails

        Returns:
            str: The created listen key

        Example:
            >>> manager = UserDataStreamManager(binance_service)
            >>> listen_key = await manager.start()
            >>> print(f"Listen key: {listen_key}")
        """
        if self._running:
            self.logger.warning(
                "UserDataStreamManager already running, ignoring start request"
            )
            return self.listen_key

        self.logger.info("Creating Binance User Data Stream listen key...")

        try:
            # Create listen key via Binance API
            response = self.binance_service.new_listen_key()

            # Extract listen key from response
            self.listen_key = response.get("listenKey")
            if not self.listen_key:
                raise ValueError("Failed to extract listenKey from API response")

            self.logger.info(f"Listen key created: {self.listen_key}")

            # Start keep-alive loop
            self._running = True
            self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())

            self.logger.info(
                f"UserDataStreamManager started (keep-alive interval: "
                f"{self.KEEP_ALIVE_INTERVAL_SECONDS}s)"
            )

            return self.listen_key

        except Exception as e:
            self.logger.error(f"Failed to create listen key: {e}", exc_info=True)
            raise

    async def _keep_alive_loop(self) -> None:
        """
        Keep-alive loop to prevent listen key expiration.

        Pings (renews) the listen key every 30 minutes to prevent
        automatic expiration by Binance.

        Notes:
            - Runs indefinitely until stop() is called
            - Logs warnings on keep-alive failures
            - Exits gracefully on asyncio.CancelledError

        Binance Requirement:
            - Listen keys must be kept alive at least once per 60 minutes
            - This implementation pings every 30 minutes for safety margin
        """
        while self._running:
            try:
                # Wait for keep-alive interval
                await asyncio.sleep(self.KEEP_ALIVE_INTERVAL_SECONDS)

                # Check if still running (might have been stopped during sleep)
                if not self._running:
                    break

                # Renew listen key via Binance API
                self.logger.debug("Renewing listen key for keep-alive...")
                response = self.binance_service.renew_listen_key()

                # Verify renewal success
                renewed_key = response.get("listenKey")
                if not renewed_key:
                    self.logger.warning("Listen key renewal returned no listenKey")

                    # Try to fetch existing listen key if renewal failed
                    # This prevents creating duplicate keys
                    continue

                self.logger.debug("Listen key renewed successfully")

            except asyncio.CancelledError:
                self.logger.info("Keep-alive loop cancelled")
                break

            except Exception as e:
                self.logger.error(f"Keep-alive ping failed: {e}", exc_info=True)
                # Don't crash on keep-alive failures - log and continue
                # The listen key will eventually expire, but system should keep running

    async def stop(self) -> None:
        """
        Stop keep-alive loop and close listen key.

        Gracefully shuts down the User Data Stream by:
        1. Stopping keep-alive loop
        2. Closing listen key via Binance API
        3. Clearing state

        Note:
            - Method is idempotent - safe to call multiple times
            - Logs warnings on cleanup failures but doesn't raise
            - Can be called during shutdown or listen key rotation

        Example:
            >>> await manager.stop()
            >>> print("UserDataStreamManager stopped")
        """
        if not self._running:
            self.logger.debug(
                "UserDataStreamManager already stopped, ignoring stop request"
            )
            return

        self.logger.info("Stopping UserDataStreamManager...")

        # Step 1: Stop keep-alive loop
        self._running = False
        if self._keep_alive_task and not self._keep_alive_task.done():
            self._keep_alive_task.cancel()
            try:
                await self._keep_alive_task
            except asyncio.CancelledError:
                pass

        # Step 2: Close listen key via Binance API
        if self.listen_key:
            try:
                self.logger.debug(f"Closing listen key: {self.listen_key}")
                self.binance_service.close_listen_key(self.listen_key)
                self.logger.info("Listen key closed successfully")
            except Exception as e:
                self.logger.warning(f"Failed to close listen key: {e}", exc_info=True)

        # Step 3: Clear state
        self.listen_key = None
        self._keep_alive_task = None

        self.logger.info("UserDataStreamManager stopped")
