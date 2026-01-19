"""Reconciliation tolerance thresholds."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Tolerances:
    """Tolerance thresholds for reconciliation comparisons."""

    # Performance metrics (as percentages)
    irr: Decimal = Decimal("0.0001")      # ±0.01% (1 basis point)
    xirr: Decimal = Decimal("0.0001")     # ±0.01% (1 basis point)
    twr: Decimal = Decimal("0.0001")      # ±0.01% (1 basis point)
    ytm: Decimal = Decimal("0.0001")      # ±0.01% (1 basis point)

    # P&L tolerances (in base currency)
    realized_pnl: Decimal = Decimal("0.01")     # ±$0.01
    unrealized_pnl: Decimal = Decimal("0.01")   # ±$0.01
    total_pnl_position: Decimal = Decimal("0.01")  # ±$0.01 per position
    total_pnl_portfolio: Decimal = Decimal("1.00") # ±$1.00 for portfolio

    # FX tolerances
    fx_rate: Decimal = Decimal("0.0001")  # ±0.0001

    # Position tolerances
    quantity: Decimal = Decimal("0.0001")  # ±0.0001 units
    market_value: Decimal = Decimal("0.01")  # ±$0.01

    # Accrued interest
    accrued_interest: Decimal = Decimal("0.01")  # ±$0.01

    def within_tolerance(self, calculated: Decimal, expected: Decimal, tolerance: Decimal) -> bool:
        """Check if calculated value is within tolerance of expected value."""
        return abs(calculated - expected) <= tolerance

    def check_irr(self, calculated: Decimal, expected: Decimal) -> bool:
        """Check if IRR is within tolerance."""
        return self.within_tolerance(calculated, expected, self.irr)

    def check_twr(self, calculated: Decimal, expected: Decimal) -> bool:
        """Check if TWR is within tolerance."""
        return self.within_tolerance(calculated, expected, self.twr)

    def check_pnl(self, calculated: Decimal, expected: Decimal, is_portfolio: bool = False) -> bool:
        """Check if P&L is within tolerance."""
        tol = self.total_pnl_portfolio if is_portfolio else self.total_pnl_position
        return self.within_tolerance(calculated, expected, tol)

    def check_fx_rate(self, calculated: Decimal, expected: Decimal) -> bool:
        """Check if FX rate is within tolerance."""
        return self.within_tolerance(calculated, expected, self.fx_rate)


# Global tolerances instance
tolerances = Tolerances()
