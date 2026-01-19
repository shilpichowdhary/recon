"""FIFO Lot tracking models."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, List
from uuid import UUID, uuid4
from collections import deque

from .enums import AssetType, CurrencyCode


@dataclass
class Lot:
    """Represents a single tax lot for FIFO tracking."""

    lot_id: UUID = field(default_factory=uuid4)
    symbol: str = ""
    asset_type: AssetType = AssetType.EQUITY

    # Acquisition details
    acquisition_date: date = field(default_factory=date.today)
    acquisition_price: Decimal = Decimal("0")
    acquisition_quantity: Decimal = Decimal("0")
    acquisition_cost: Decimal = Decimal("0")  # Total cost basis including fees
    acquisition_fx_rate: Decimal = Decimal("1")
    currency: CurrencyCode = CurrencyCode.USD

    # Current state
    remaining_quantity: Decimal = Decimal("0")

    # Fees allocated to this lot
    allocated_fees: Decimal = Decimal("0")

    # Option-specific
    underlying_symbol: Optional[str] = None
    strike_price: Optional[Decimal] = None
    expiry_date: Optional[date] = None

    # Bond-specific
    face_value: Optional[Decimal] = None
    coupon_rate: Optional[Decimal] = None
    maturity_date: Optional[date] = None

    # Tracking
    transaction_id: Optional[UUID] = None

    def __post_init__(self):
        """Initialize remaining quantity to acquisition quantity."""
        if self.remaining_quantity == Decimal("0") and self.acquisition_quantity != Decimal("0"):
            self.remaining_quantity = self.acquisition_quantity

    @property
    def cost_per_unit(self) -> Decimal:
        """Calculate cost per unit including allocated fees."""
        if self.acquisition_quantity == Decimal("0"):
            return Decimal("0")
        return self.acquisition_cost / self.acquisition_quantity

    @property
    def remaining_cost_basis(self) -> Decimal:
        """Calculate remaining cost basis for unsold units."""
        return self.cost_per_unit * self.remaining_quantity

    @property
    def is_depleted(self) -> bool:
        """Check if lot has been fully disposed."""
        return self.remaining_quantity <= Decimal("0")

    @property
    def holding_period_days(self) -> int:
        """Calculate holding period in days from acquisition."""
        return (date.today() - self.acquisition_date).days

    @property
    def is_long_term(self) -> bool:
        """Check if lot qualifies for long-term capital gains (>1 year)."""
        return self.holding_period_days > 365

    def dispose(self, quantity: Decimal, sale_price: Decimal, sale_date: date,
                sale_fx_rate: Decimal = Decimal("1")) -> tuple[Decimal, Decimal]:
        """
        Dispose of units from this lot using FIFO.

        Returns:
            Tuple of (quantity_disposed, realized_pnl)
        """
        if quantity > self.remaining_quantity:
            quantity = self.remaining_quantity

        # Calculate realized P&L
        sale_proceeds = quantity * sale_price * sale_fx_rate
        cost_basis = self.cost_per_unit * quantity * self.acquisition_fx_rate
        realized_pnl = sale_proceeds - cost_basis

        # Reduce remaining quantity
        self.remaining_quantity -= quantity

        return quantity, realized_pnl

    def calculate_unrealized_pnl(self, current_price: Decimal,
                                   current_fx_rate: Decimal = Decimal("1")) -> Decimal:
        """Calculate unrealized P&L for remaining units."""
        if self.remaining_quantity <= Decimal("0"):
            return Decimal("0")

        current_value = self.remaining_quantity * current_price * current_fx_rate
        cost_basis = self.remaining_cost_basis * self.acquisition_fx_rate

        return current_value - cost_basis

    def __str__(self) -> str:
        """String representation of lot."""
        return (
            f"Lot({self.lot_id.hex[:8]}) {self.symbol}: "
            f"{self.remaining_quantity}/{self.acquisition_quantity} @ {self.acquisition_price}"
        )


class LotQueue:
    """FIFO queue for managing lots per security."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._lots: deque[Lot] = deque()
        self._realized_pnl: Decimal = Decimal("0")
        self._disposed_lots: List[tuple[Lot, Decimal, Decimal, date]] = []  # (lot, qty, pnl, date)

    @property
    def lots(self) -> List[Lot]:
        """Get list of active lots."""
        return [lot for lot in self._lots if not lot.is_depleted]

    @property
    def total_quantity(self) -> Decimal:
        """Get total quantity across all lots."""
        return sum(lot.remaining_quantity for lot in self._lots)

    @property
    def total_cost_basis(self) -> Decimal:
        """Get total cost basis across all lots."""
        return sum(lot.remaining_cost_basis for lot in self._lots)

    @property
    def average_cost(self) -> Decimal:
        """Calculate weighted average cost per unit."""
        if self.total_quantity == Decimal("0"):
            return Decimal("0")
        return self.total_cost_basis / self.total_quantity

    @property
    def realized_pnl(self) -> Decimal:
        """Get total realized P&L from disposed lots."""
        return self._realized_pnl

    def add_lot(self, lot: Lot) -> None:
        """Add a new lot to the queue."""
        self._lots.append(lot)

    def dispose_fifo(self, quantity: Decimal, sale_price: Decimal,
                     sale_date: date, sale_fx_rate: Decimal = Decimal("1")) -> Decimal:
        """
        Dispose of units using FIFO method.

        Returns:
            Total realized P&L from disposal
        """
        remaining_to_dispose = quantity
        total_realized_pnl = Decimal("0")

        for lot in self._lots:
            if remaining_to_dispose <= Decimal("0"):
                break

            if lot.is_depleted:
                continue

            qty_disposed, realized_pnl = lot.dispose(
                remaining_to_dispose, sale_price, sale_date, sale_fx_rate
            )

            remaining_to_dispose -= qty_disposed
            total_realized_pnl += realized_pnl

            self._disposed_lots.append((lot, qty_disposed, realized_pnl, sale_date))

        self._realized_pnl += total_realized_pnl

        # Clean up depleted lots
        self._lots = deque(lot for lot in self._lots if not lot.is_depleted)

        return total_realized_pnl

    def calculate_unrealized_pnl(self, current_price: Decimal,
                                   current_fx_rate: Decimal = Decimal("1")) -> Decimal:
        """Calculate total unrealized P&L for all lots."""
        return sum(
            lot.calculate_unrealized_pnl(current_price, current_fx_rate)
            for lot in self._lots
        )

    def get_disposal_history(self) -> List[dict]:
        """Get history of all disposals."""
        return [
            {
                "lot_id": str(lot.lot_id),
                "acquisition_date": lot.acquisition_date,
                "acquisition_price": lot.acquisition_price,
                "quantity_disposed": qty,
                "realized_pnl": pnl,
                "disposal_date": disposal_date,
            }
            for lot, qty, pnl, disposal_date in self._disposed_lots
        ]

    def __len__(self) -> int:
        """Return number of active lots."""
        return len([lot for lot in self._lots if not lot.is_depleted])

    def __str__(self) -> str:
        """String representation of lot queue."""
        return f"LotQueue({self.symbol}): {len(self)} lots, {self.total_quantity} units"
