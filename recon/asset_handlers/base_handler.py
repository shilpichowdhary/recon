"""Base asset handler interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Any

from models.transaction import Transaction
from models.lot import Lot


@dataclass
class AssetValuation:
    """Valuation result for an asset."""
    symbol: str
    valuation_date: date
    quantity: Decimal
    price: Decimal
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal
    currency: str
    additional_fields: Dict[str, Any] = None

    def __post_init__(self):
        if self.additional_fields is None:
            self.additional_fields = {}


@dataclass
class AssetIncome:
    """Income from an asset."""
    symbol: str
    income_date: date
    income_type: str  # "dividend", "coupon", "interest"
    gross_amount: Decimal
    withholding_tax: Decimal = Decimal("0")
    net_amount: Decimal = None
    currency: str = "USD"

    def __post_init__(self):
        if self.net_amount is None:
            self.net_amount = self.gross_amount - self.withholding_tax


class BaseAssetHandler(ABC):
    """
    Abstract base class for asset-specific handlers.

    Each asset type (equity, bond, option, etc.) implements this interface
    to provide specialized calculations and valuations.
    """

    @property
    @abstractmethod
    def asset_types(self) -> List[str]:
        """Return list of asset types this handler supports."""
        pass

    @abstractmethod
    def calculate_valuation(
        self,
        lots: List[Lot],
        current_price: Decimal,
        valuation_date: date,
        fx_rate: Decimal = Decimal("1")
    ) -> AssetValuation:
        """
        Calculate current valuation for a position.

        Args:
            lots: List of lots for this position
            current_price: Current market price
            valuation_date: Date of valuation
            fx_rate: FX rate to base currency

        Returns:
            AssetValuation with calculated values
        """
        pass

    @abstractmethod
    def calculate_unrealized_pnl(
        self,
        lots: List[Lot],
        current_price: Decimal,
        fx_rate: Decimal = Decimal("1")
    ) -> Decimal:
        """
        Calculate unrealized P&L for lots.

        Args:
            lots: List of lots
            current_price: Current market price
            fx_rate: FX rate to base currency

        Returns:
            Unrealized P&L
        """
        pass

    @abstractmethod
    def process_transaction(
        self,
        transaction: Transaction
    ) -> Dict[str, Any]:
        """
        Process a transaction for this asset type.

        Args:
            transaction: Transaction to process

        Returns:
            Dict with processing results
        """
        pass

    def calculate_income(
        self,
        lots: List[Lot],
        income_date: date,
        income_per_unit: Decimal
    ) -> Optional[AssetIncome]:
        """
        Calculate income (dividends, coupons) for a position.

        Default implementation for assets that generate income.
        Override for specialized calculations.

        Args:
            lots: List of lots
            income_date: Date of income payment
            income_per_unit: Income per unit held

        Returns:
            AssetIncome or None
        """
        total_quantity = sum(lot.remaining_quantity for lot in lots)
        if total_quantity <= 0:
            return None

        gross_amount = total_quantity * income_per_unit

        return AssetIncome(
            symbol=lots[0].symbol if lots else "UNKNOWN",
            income_date=income_date,
            income_type="dividend",
            gross_amount=gross_amount,
            currency=lots[0].currency.value if lots else "USD",
        )

    def validate_transaction(
        self,
        transaction: Transaction
    ) -> List[str]:
        """
        Validate a transaction for this asset type.

        Args:
            transaction: Transaction to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if transaction.quantity <= 0:
            errors.append("Quantity must be positive")

        if transaction.price < 0:
            errors.append("Price cannot be negative")

        return errors

    def get_holding_period_days(self, lot: Lot, as_of_date: date = None) -> int:
        """
        Calculate holding period in days.

        Args:
            lot: Lot to calculate for
            as_of_date: Optional reference date (default: today)

        Returns:
            Number of days held
        """
        ref_date = as_of_date or date.today()
        return (ref_date - lot.acquisition_date).days

    def is_long_term(self, lot: Lot, as_of_date: date = None) -> bool:
        """
        Check if lot qualifies for long-term capital gains.

        Args:
            lot: Lot to check
            as_of_date: Optional reference date

        Returns:
            True if held > 365 days
        """
        return self.get_holding_period_days(lot, as_of_date) > 365
