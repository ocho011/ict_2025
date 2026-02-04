"""
Account models for User Data Stream events.

This module contains models for ACCOUNT_UPDATE WebSocket events,
including balance changes, margin updates, and account-level data.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BalanceUpdate:
    """
    Balance update data from ACCOUNT_UPDATE WebSocket event.

    Represents changes to wallet balance for a specific asset.

    Attributes:
        asset: Asset symbol (e.g., "USDT", "BTC")
        wallet_balance: Total wallet balance
        cross_wallet_balance: Cross margin wallet balance
        balance_change: Change in balance (deposit/withdrawal/PnL)

    Binance ACCOUNT_UPDATE balance structure:
        {
            "a": "USDT",         // Asset
            "wb": "1000.0",      // Wallet balance
            "cw": "900.0",       // Cross wallet balance
            "bc": "10.0"         // Balance change
        }
    """

    asset: str
    wallet_balance: float
    cross_wallet_balance: float
    balance_change: float = 0.0

    @classmethod
    def from_websocket_data(cls, data: dict) -> "BalanceUpdate":
        """
        Create BalanceUpdate from raw WebSocket balance data.

        Args:
            data: Balance object from ACCOUNT_UPDATE 'a.B' array

        Returns:
            BalanceUpdate instance
        """
        return cls(
            asset=data.get("a", ""),
            wallet_balance=float(data.get("wb", 0)),
            cross_wallet_balance=float(data.get("cw", 0)),
            balance_change=float(data.get("bc", 0)) if data.get("bc") else 0.0,
        )


@dataclass
class AccountUpdate:
    """
    Account update data from ACCOUNT_UPDATE WebSocket event.

    Encapsulates balance updates, position changes, and margin information
    from a single ACCOUNT_UPDATE event (Issue #93).

    Attributes:
        event_time: Event timestamp (milliseconds)
        transaction_time: Transaction timestamp (milliseconds)
        update_reason: Reason for update (ORDER, DEPOSIT, WITHDRAW, etc.)
        balances: List of balance updates
        positions: List of position updates (PositionUpdate from position.py)

    Update Reasons:
        - "DEPOSIT": Balance increased from deposit
        - "WITHDRAW": Balance decreased from withdrawal
        - "ORDER": Balance/position changed from order fill
        - "FUNDING_FEE": Funding fee applied
        - "WITHDRAW_REJECT": Withdrawal rejected
        - "ADJUSTMENT": Manual adjustment
        - "INSURANCE_CLEAR": Insurance fund cleared
        - "ADMIN_DEPOSIT": Admin deposit
        - "ADMIN_WITHDRAW": Admin withdrawal
        - "MARGIN_TRANSFER": Cross/isolated margin transfer
        - "MARGIN_TYPE_CHANGE": Margin type changed
        - "ASSET_TRANSFER": Asset transfer between accounts
        - "OPTIONS_PREMIUM_FEE": Options premium
        - "OPTIONS_SETTLE_PROFIT": Options settlement profit
        - "AUTO_EXCHANGE": Auto exchange

    Binance ACCOUNT_UPDATE structure:
        {
            "e": "ACCOUNT_UPDATE",
            "E": 1234567890123,      // Event time
            "T": 1234567890123,      // Transaction time
            "a": {
                "m": "ORDER",        // Event reason
                "B": [...],          // Balances array
                "P": [...]           // Positions array
            }
        }
    """

    event_time: int
    transaction_time: int
    update_reason: str
    balances: List[BalanceUpdate] = field(default_factory=list)
    # Note: positions use PositionUpdate from src/models/position.py
    # Kept as separate list to maintain type consistency

    @classmethod
    def from_websocket_data(cls, data: dict) -> "AccountUpdate":
        """
        Create AccountUpdate from raw WebSocket ACCOUNT_UPDATE event.

        Args:
            data: Full ACCOUNT_UPDATE event data

        Returns:
            AccountUpdate instance

        Note:
            Position data should be parsed separately using PositionUpdate
            from src/models/position.py for consistency.
        """
        account_data = data.get("a", {})

        # Parse balance updates
        balances = []
        for balance_data in account_data.get("B", []):
            try:
                balance = BalanceUpdate.from_websocket_data(balance_data)
                balances.append(balance)
            except (ValueError, TypeError):
                continue  # Skip malformed balance data

        return cls(
            event_time=int(data.get("E", 0)),
            transaction_time=int(data.get("T", 0)),
            update_reason=account_data.get("m", "unknown"),
            balances=balances,
        )

    @property
    def has_balance_changes(self) -> bool:
        """Check if this update includes balance changes."""
        return len(self.balances) > 0

    def get_balance(self, asset: str) -> Optional[BalanceUpdate]:
        """
        Get balance update for a specific asset.

        Args:
            asset: Asset symbol (e.g., "USDT")

        Returns:
            BalanceUpdate for the asset, or None if not found
        """
        for balance in self.balances:
            if balance.asset == asset:
                return balance
        return None
