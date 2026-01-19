"""Transaction data model."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from .enums import TransactionType, AssetType, CurrencyCode


@dataclass
class Transaction:
    """Represents a portfolio transaction."""

    # Mandatory fields
    transaction_date: date
    settlement_date: date
    transaction_type: TransactionType
    asset_type: AssetType
    symbol: str
    quantity: Decimal
    price: Decimal
    currency: CurrencyCode

    # Calculated/derived fields
    gross_amount: Decimal = field(default=Decimal("0"))
    net_amount: Decimal = field(default=Decimal("0"))

    # Optional fields
    transaction_id: UUID = field(default_factory=uuid4)
    account_id: Optional[str] = None
    cusip: Optional[str] = None
    isin: Optional[str] = None
    sedol: Optional[str] = None
    description: Optional[str] = None

    # Fee fields
    commission: Decimal = field(default=Decimal("0"))
    fees: Decimal = field(default=Decimal("0"))
    taxes: Decimal = field(default=Decimal("0"))

    # FX fields
    fx_rate: Decimal = field(default=Decimal("1"))
    base_currency_amount: Optional[Decimal] = None

    # Option-specific fields
    strike_price: Optional[Decimal] = None
    expiry_date: Optional[date] = None
    underlying_symbol: Optional[str] = None
    contract_multiplier: Decimal = field(default=Decimal("100"))

    # Bond-specific fields
    coupon_rate: Optional[Decimal] = None
    maturity_date: Optional[date] = None
    accrued_interest: Decimal = field(default=Decimal("0"))
    face_value: Optional[Decimal] = None

    # Lot tracking
    lot_id: Optional[str] = None
    original_lot_id: Optional[str] = None

    def __post_init__(self):
        """Calculate derived fields after initialization."""
        # Calculate gross amount if not provided
        if self.gross_amount == Decimal("0"):
            self.gross_amount = abs(self.quantity * self.price)

            # Add accrued interest for bonds
            if AssetType.is_fixed_income(self.asset_type):
                self.gross_amount += self.accrued_interest

        # Calculate net amount (including fees)
        if self.net_amount == Decimal("0"):
            total_fees = self.commission + self.fees + self.taxes

            if TransactionType.is_buy(self.transaction_type):
                self.net_amount = self.gross_amount + total_fees
            else:
                self.net_amount = self.gross_amount - total_fees

        # Calculate base currency amount
        if self.base_currency_amount is None:
            self.base_currency_amount = self.net_amount * self.fx_rate

    @property
    def total_fees(self) -> Decimal:
        """Get total fees for transaction."""
        return self.commission + self.fees + self.taxes

    @property
    def is_buy(self) -> bool:
        """Check if this is a buy transaction."""
        return TransactionType.is_buy(self.transaction_type)

    @property
    def is_sell(self) -> bool:
        """Check if this is a sell transaction."""
        return TransactionType.is_sell(self.transaction_type)

    @property
    def is_cash_flow(self) -> bool:
        """Check if this transaction represents a cash flow."""
        return self.transaction_type in {
            TransactionType.DEPOSIT,
            TransactionType.WITHDRAWAL,
            TransactionType.DIVIDEND,
            TransactionType.INTEREST,
            TransactionType.COUPON,
        }

    def to_cash_flow(self) -> Decimal:
        """Convert transaction to cash flow value (negative for outflows)."""
        if self.transaction_type in {TransactionType.DEPOSIT, TransactionType.BUY, TransactionType.OPTION_BUY}:
            return -self.net_amount
        elif self.transaction_type in {TransactionType.WITHDRAWAL, TransactionType.SELL, TransactionType.OPTION_SELL}:
            return self.net_amount
        elif TransactionType.is_income(self.transaction_type):
            return self.net_amount
        else:
            return Decimal("0")

    def __str__(self) -> str:
        """String representation of transaction."""
        return (
            f"{self.transaction_date} | {self.transaction_type.name} | "
            f"{self.symbol} | {self.quantity} @ {self.price} {self.currency.value}"
        )
