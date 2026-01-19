"""IRR and XIRR calculator using Newton-Raphson method."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Tuple, Optional

from config.settings import settings


@dataclass
class CashFlow:
    """Represents a cash flow for IRR calculation."""
    date: date
    amount: Decimal

    def __post_init__(self):
        """Ensure amount is Decimal."""
        if not isinstance(self.amount, Decimal):
            self.amount = Decimal(str(self.amount))


class IRRCalculator:
    """
    Calculate Internal Rate of Return using Newton-Raphson iteration.

    XIRR Formula: NPV = Σ [CFᵢ / (1 + IRR)^(tᵢ/365)] = 0

    Where:
        CFᵢ = Cash flow at time i
        tᵢ = Days from first cash flow to cash flow i
        IRR = Internal rate of return (annualized)
    """

    def __init__(
        self,
        max_iterations: int = None,
        precision: float = None,
        initial_guess: float = None
    ):
        """
        Initialize IRR calculator.

        Args:
            max_iterations: Maximum iterations for convergence
            precision: Required precision for convergence
            initial_guess: Initial IRR guess
        """
        self.max_iterations = max_iterations or settings.irr_max_iterations
        self.precision = precision or settings.newton_raphson_precision
        self.initial_guess = initial_guess or settings.irr_initial_guess

    def calculate_xirr(
        self,
        cash_flows: List[CashFlow],
        guess: Optional[float] = None
    ) -> Optional[Decimal]:
        """
        Calculate XIRR (Extended Internal Rate of Return).

        Args:
            cash_flows: List of CashFlow objects with dates and amounts
            guess: Initial guess for rate (default: 0.1)

        Returns:
            XIRR as Decimal, or None if no solution found
        """
        if not cash_flows or len(cash_flows) < 2:
            return None

        # Sort cash flows by date
        sorted_cfs = sorted(cash_flows, key=lambda x: x.date)

        # Need at least one positive and one negative cash flow
        amounts = [float(cf.amount) for cf in sorted_cfs]
        if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
            return None

        # Calculate time fractions (years from first date)
        base_date = sorted_cfs[0].date
        time_fractions = [
            (cf.date - base_date).days / 365.0
            for cf in sorted_cfs
        ]

        # Newton-Raphson iteration
        rate = guess if guess is not None else self.initial_guess

        for iteration in range(self.max_iterations):
            # Calculate NPV and derivative at current rate
            npv = self._npv(amounts, time_fractions, rate)
            npv_derivative = self._npv_derivative(amounts, time_fractions, rate)

            if abs(npv_derivative) < 1e-12:
                # Derivative too small, try adjusting rate
                rate = rate * 0.9 if rate > 0 else 0.1
                continue

            # Newton-Raphson update
            new_rate = rate - npv / npv_derivative

            # Check for convergence
            if abs(new_rate - rate) < self.precision:
                return Decimal(str(round(new_rate, 10)))

            rate = new_rate

            # Bound the rate to prevent divergence
            if rate < -0.9999:
                rate = -0.9999
            elif rate > 10:
                rate = 10

        # Try alternative initial guesses if first attempt failed
        for alt_guess in [-0.5, 0.5, 0.01, -0.01, 1.0, -0.9]:
            result = self._try_converge(amounts, time_fractions, alt_guess)
            if result is not None:
                return Decimal(str(round(result, 10)))

        return None

    def _try_converge(
        self,
        amounts: List[float],
        time_fractions: List[float],
        guess: float
    ) -> Optional[float]:
        """Try to converge with a specific initial guess."""
        rate = guess

        for _ in range(self.max_iterations):
            npv = self._npv(amounts, time_fractions, rate)
            npv_derivative = self._npv_derivative(amounts, time_fractions, rate)

            if abs(npv_derivative) < 1e-12:
                return None

            new_rate = rate - npv / npv_derivative

            if abs(new_rate - rate) < self.precision:
                return new_rate

            rate = new_rate

            if rate < -0.9999 or rate > 10:
                return None

        return None

    def _npv(
        self,
        amounts: List[float],
        time_fractions: List[float],
        rate: float
    ) -> float:
        """
        Calculate NPV at given rate.

        NPV = Σ [CFᵢ / (1 + rate)^tᵢ]
        """
        total = 0.0
        for amount, t in zip(amounts, time_fractions):
            if rate <= -1 and t > 0:
                return float('inf')
            try:
                total += amount / ((1 + rate) ** t)
            except (OverflowError, ZeroDivisionError):
                return float('inf')
        return total

    def _npv_derivative(
        self,
        amounts: List[float],
        time_fractions: List[float],
        rate: float
    ) -> float:
        """
        Calculate derivative of NPV with respect to rate.

        d(NPV)/d(rate) = Σ [-tᵢ × CFᵢ / (1 + rate)^(tᵢ + 1)]
        """
        total = 0.0
        for amount, t in zip(amounts, time_fractions):
            if rate <= -1 and t > 0:
                return float('inf')
            try:
                total -= t * amount / ((1 + rate) ** (t + 1))
            except (OverflowError, ZeroDivisionError):
                return float('inf')
        return total

    def calculate_irr(
        self,
        cash_flows: List[Decimal],
        periods_per_year: int = 1
    ) -> Optional[Decimal]:
        """
        Calculate periodic IRR for equally-spaced cash flows.

        Args:
            cash_flows: List of cash flow amounts (first is typically negative)
            periods_per_year: Number of periods per year (for annualization)

        Returns:
            Annualized IRR as Decimal, or None if no solution
        """
        if not cash_flows or len(cash_flows) < 2:
            return None

        amounts = [float(cf) for cf in cash_flows]

        # Need sign change
        if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
            return None

        # Create time fractions (assume equally spaced)
        time_fractions = [i / periods_per_year for i in range(len(amounts))]

        # Use XIRR calculation
        rate = self.initial_guess

        for _ in range(self.max_iterations):
            npv = self._npv(amounts, time_fractions, rate)
            npv_derivative = self._npv_derivative(amounts, time_fractions, rate)

            if abs(npv_derivative) < 1e-12:
                break

            new_rate = rate - npv / npv_derivative

            if abs(new_rate - rate) < self.precision:
                return Decimal(str(round(new_rate, 10)))

            rate = new_rate

        return None

    def calculate_npv(
        self,
        cash_flows: List[CashFlow],
        discount_rate: Decimal
    ) -> Decimal:
        """
        Calculate Net Present Value at a given discount rate.

        Args:
            cash_flows: List of CashFlow objects
            discount_rate: Discount rate as decimal

        Returns:
            NPV as Decimal
        """
        if not cash_flows:
            return Decimal("0")

        sorted_cfs = sorted(cash_flows, key=lambda x: x.date)
        base_date = sorted_cfs[0].date
        rate = float(discount_rate)

        total = Decimal("0")
        for cf in sorted_cfs:
            t = (cf.date - base_date).days / 365.0
            discount_factor = Decimal(str((1 + rate) ** t))
            total += cf.amount / discount_factor

        return total


def calculate_xirr(
    dates: List[date],
    amounts: List[Decimal]
) -> Optional[Decimal]:
    """
    Convenience function to calculate XIRR.

    Args:
        dates: List of cash flow dates
        amounts: List of cash flow amounts

    Returns:
        XIRR as Decimal or None
    """
    if len(dates) != len(amounts):
        raise ValueError("Dates and amounts must have same length")

    cash_flows = [CashFlow(d, a) for d, a in zip(dates, amounts)]
    calculator = IRRCalculator()
    return calculator.calculate_xirr(cash_flows)
