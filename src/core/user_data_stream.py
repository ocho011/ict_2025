"""
User Data Stream management for Binance Futures User Data Stream WebSocket.

This module provides the UserDataStreamManager class for managing listen keys
and receiving real-time order execution events from Binance User Data Stream.
"""

import asyncio
import logging
from typing import Callable, Optional

from binance.error import ClientError


class ExponentialBackoff:
    """
    Exponential backoff for retry logic with jitter.

    Provides progressively increasing wait times for retry attempts,
    with a maximum cap to prevent excessive delays.
    """

    def __init__(self, base: float = 1.0, max_wait: float = 60.0, factor: float = 2.0):
        """
        Initialize exponential backoff.

        Args:
            base: Initial backoff time in seconds
            max_wait: Maximum backoff time in seconds
            factor: Multiplication factor for each retry
        """
        self.base = base
        self.max_wait = max_wait
        self.factor = factor
        self._attempts = 0

    def reset(self) -> None:
        """Reset attempt counter."""
        self._attempts = 0

    def next(self) -> float:
        """
        Get next backoff time.

        Returns:
            Backoff time in seconds (capped at max_wait)
        """
        backoff = min(self.base * (self.factor**self._attempts), self.max_wait)
        self._attempts += 1
        return backoff


class UserDataStreamManager:
    """
    Manages listen key lifecycle for Binance User Data Stream.

    Responsibilities:
    - Create listen key via REST API
    - Keep-alive loop (ping every 30 minutes)
    - Auto-recovery from listen key expiration (error -1125)
    - Notify listeners when listen key is rotated
    - Graceful shutdown with listen key cleanup

    Listen Key Lifecycle:
    - Valid for 60 minutes after creation
    - Must be pinged (keep-alive) at least once per 60 minutes
    - Recommended: ping every 30 minutes for safety margin
    - Auto-renewal on expiration via keep-alive recovery logic

    Listen Key Rotation:
    - When keep-alive fails with error -1125, creates new listen key
    - Notifies listeners via callback to reconnect WebSocket
    - Implements exponential backoff for rate limiting
    - Logs all rotation events for monitoring

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
        listen_key_changed_callback: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Initialize UserDataStreamManager.

        Args:
            binance_service: BinanceServiceClient instance for REST API calls
            listen_key_changed_callback: Optional callback function invoked when
                listen key is rotated. Called with (old_key, new_key) parameters.

        Attributes:
            logger: Logger instance
            listen_key: Current active listen key (None if not started)
            _keep_alive_task: Async task for keep-alive loop
            _running: Runtime flag
            _listen_key_changed_callback: Callback for listen key rotation
            _reconnection_backoff: Exponential backoff for rate limiting
        """
        self.binance_service = binance_service
        self.logger = logging.getLogger(__name__)

        self.listen_key: Optional[str] = None
        self._keep_alive_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._listen_key_changed_callback = listen_key_changed_callback

        # Exponential backoff for listen key creation (rate limit recovery)
        self._reconnection_backoff = ExponentialBackoff(base=1, max_wait=60)

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
            if self.listen_key is None:
                raise RuntimeError("Manager is running but listen_key is None")
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
        automatic expiration by Binance. Automatically recovers from
        listen key expiration by creating a new key and notifying listeners.

        Notes:
            - Runs indefinitely until stop() is called
            - Auto-recovers from listen key expiration (error -1125)
            - Notifies listeners via callback when listen key is rotated
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
                self.logger.debug(
                    f"Renewing listen key {self.listen_key} for keep-alive..."
                )
                self.binance_service.renew_listen_key(self.listen_key)

                self.logger.debug("Listen key renewed successfully")
                # Reset backoff counter on successful renewal
                self._reconnection_backoff.reset()

            except asyncio.CancelledError:
                self.logger.info("Keep-alive loop cancelled")
                break

            except ClientError as e:
                # Error code -1125: "This listenKey does not exist"
                # This indicates the listen key has expired and needs rotation
                if e.error_code == -1125:
                    self.logger.warning(
                        "ListenKey expired (error -1125), creating new one..."
                    )
                    await self._handle_listen_key_expiration()
                else:
                    # Log other client errors but don't crash
                    self.logger.error(
                        f"Keep-alive ping failed (ClientError): {e}", exc_info=True
                    )

            except Exception as e:
                # Don't crash on other keep-alive failures - log and continue
                # The listen key will eventually expire, but system should keep running
                self.logger.error(f"Keep-alive ping failed: {e}", exc_info=True)

    async def _handle_listen_key_expiration(self) -> None:
        """
        Handle listen key expiration by creating a new key and notifying listeners.

        This method is called when error -1125 is detected, indicating the
        listen key has expired. It creates a new listen key and triggers
        the callback to notify listeners (e.g., WebSocket streamer).

        Implements exponential backoff to handle rate limiting during recovery.
        """
        # Get backoff time for rate limiting
        backoff_time = self._reconnection_backoff.next()
        if backoff_time >= 1.0:
            self.logger.info(f"Applying backoff: {backoff_time:.1f}s before retry")
            await asyncio.sleep(backoff_time)

        try:
            # Store old listen key for logging
            old_key = self.listen_key
            # Type assertion: old_key should not be None when handling expiration
            assert old_key is not None, (
                "listen_key should not be None during expiration handling"
            )
            self.logger.info(f"Creating new listenKey to replace expired: {old_key}")

            # Create new listen key via Binance API
            response = self.binance_service.new_listen_key()
            new_key = response.get("listenKey")

            if not new_key:
                raise ValueError("Failed to extract listenKey from API response")

            # Update listen key
            self.listen_key = new_key
            self.logger.info(f"New listenKey created: {new_key}")

            # Reset backoff on success
            self._reconnection_backoff.reset()

            # Notify listeners via callback (e.g., to reconnect WebSocket)
            if self._listen_key_changed_callback:
                try:
                    self._listen_key_changed_callback(old_key, new_key)
                    self.logger.info("Notified listeners of listenKey rotation")
                except Exception as callback_error:
                    self.logger.error(
                        f"Error in listenKey rotation callback: {callback_error}",
                        exc_info=True,
                    )

        except Exception as e:
            self.logger.error(f"Failed to create new listenKey: {e}", exc_info=True)
            # Don't crash - continue loop and retry next iteration
            # The backoff will continue increasing to prevent rate limit violations

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
            except ClientError as e:
                # Error code -1125: "This listenKey does not exist"
                # This is expected when listen key has already expired or been invalidated
                if e.error_code == -1125:
                    self.logger.debug(
                        f"Listen key already expired or invalidated (code: {e.error_code})"
                    )
                else:
                    self.logger.warning(f"Failed to close listen key: {e}")
            except Exception as e:
                self.logger.warning(f"Failed to close listen key: {e}")

        # Step 3: Clear state
        self.listen_key = None
        self._keep_alive_task = None
        self._reconnection_backoff.reset()

        self.logger.info("UserDataStreamManager stopped")
