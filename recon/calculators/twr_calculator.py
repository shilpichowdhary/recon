"""Time-Weighted Return (TWR) calculator."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Optional, Tuple

from utils.math_utils import calculate_compound_return, annualize_return


@dataclass
class DailyValue:
    """Represents a daily portfolio value."""
    date: date
    value: Decimal
    cash_flow: Decimal = Decimal("0")  # External cash flow on this day


@dataclass
class SubPeriodReturn:
    """Represents a return for a sub-period."""
    start_date: date
    end_date: date
    start_value: Decimal
    end_value: Decimal
    cash_flow: Decimal
    return_value: Decimal


class TWRCalculator:
    """
    Calculate Time-Weighted Return (TWR).

    TWR removes the impact of external cash flows to measure
    the portfolio manager's performance.

    Formula: TWR = [(1 + R₁) × (1 + R₂) × ... × (1 + Rₙ)] - 1

    Where Rᵢ = (Vᵢ - Vᵢ₋₁ - CFᵢ) / (Vᵢ₋₁ + wᵢ × CFᵢ)
        Vᵢ = Portfolio value at end of period i
        CFᵢ = Cash flow during period i
        wᵢ = Weight factor for cash flow timing (Modified Dietz)
    """

    def __init__(self, use_modified_dietz: bool = True):
        """
        Initialize TWR calculator.

        Args:
            use_modified_dietz: If True, use Modified Dietz weighting for cash flows
        """
        self.use_modified_dietz = use_modified_dietz

    def calculate_twr(
        self,
        daily_values: List[DailyValue],
        cash_flows: Optional[List[Tuple[date, Decimal]]] = None
    ) -> Optional[Decimal]:
        """
        Calculate Time-Weighted Return from daily values.

        Args:
            daily_values: List of DailyValue objects
            cash_flows: Optional list of (date, amount) tuples for cash flows

        Returns:
            TWR as Decimal, or None if insufficient data
        """
        if not daily_values or len(daily_values) < 2:
            return None

        # Sort by date
        sorted_values = sorted(daily_values, key=lambda x: x.date)

        # Apply cash flows to daily values if provided separately
        if cash_flows:
            cf_dict = {d: a for d, a in cash_flows}
            for dv in sorted_values:
                if dv.date in cf_dict:
                    dv.cash_flow = cf_dict[dv.date]

        # Calculate sub-period returns (split at each cash flow)
        sub_periods = self._calculate_sub_periods(sorted_values)

        if not sub_periods:
            # No cash flows, simple return
            start_val = float(sorted_values[0].value)
            end_val = float(sorted_values[-1].value)
            if start_val == 0:
                return None
            return Decimal(str((end_val - start_val) / start_val))

        # Compound sub-period returns
        returns = [sp.return_value for sp in sub_periods]
        twr = calculate_compound_return(returns)

        return twr

    def _calculate_sub_periods(
        self,
        daily_values: List[DailyValue]
    ) -> List[SubPeriodReturn]:
        """
        Split into sub-periods at each cash flow.

        Returns:
            List of SubPeriodReturn objects
        """
        sub_periods = []
        period_start_idx = 0

        for i in range(1, len(daily_values)):
            # Check if there's a cash flow on this day
            if daily_values[i].cash_flow != Decimal("0"):
                # End current sub-period just before the cash flow
                sp = self._calculate_sub_period_return(
                    daily_values[period_start_idx],
                    daily_values[i],
                    daily_values[i].cash_flow
                )
                sub_periods.append(sp)
                period_start_idx = i

        # Final sub-period (from last cash flow to end)
        if period_start_idx < len(daily_values) - 1:
            sp = self._calculate_sub_period_return(
                daily_values[period_start_idx],
                daily_values[-1],
                Decimal("0")
            )
            sub_periods.append(sp)

        return sub_periods

    def _calculate_sub_period_return(
        self,
        start: DailyValue,
        end: DailyValue,
        cash_flow: Decimal
    ) -> SubPeriodReturn:
        """
        Calculate return for a single sub-period.

        Uses Modified Dietz method if enabled.
        """
        start_value = float(start.value)
        end_value = float(end.value)
        cf = float(cash_flow)

        if self.use_modified_dietz and cf != 0:
            # Calculate weight based on timing within period
            total_days = (end.date - start.date).days
            if total_days > 0:
                # Assume cash flow happens at start of day
                # Weight = (total_days - days_from_start) / total_days
                weight = 1.0  # Cash flow at end, full weight
            else:
                weight = 0.5

            denominator = start_value + weight * cf
        else:
            # Simple method: cash flow added to start value
            denominator = start_value + cf

        if denominator == 0:
            return_val = Decimal("0")
        else:
            return_val = Decimal(str((end_value - start_value - cf) / denominator))

        return SubPeriodReturn(
            start_date=start.date,
            end_date=end.date,
            start_value=start.value,
            end_value=end.value,
            cash_flow=Decimal(str(cf)),
            return_value=return_val
        )

    def calculate_twr_from_transactions(
        self,
        start_value: Decimal,
        end_value: Decimal,
        start_date: date,
        end_date: date,
        cash_flows: List[Tuple[date, Decimal]]
    ) -> Optional[Decimal]:
        """
        Calculate TWR when only start/end values and cash flows are known.

        Uses Modified Dietz approximation.

        Args:
            start_value: Portfolio value at start
            end_value: Portfolio value at end
            start_date: Start date
            end_date: End date
            cash_flows: List of (date, amount) tuples

        Returns:
            TWR as Decimal
        """
        total_days = (end_date - start_date).days
        if total_days <= 0:
            return None

        start_val = float(start_value)
        end_val = float(end_value)

        if not cash_flows:
            # No cash flows, simple return
            if start_val == 0:
                return None
            return Decimal(str((end_val - start_val) / start_val))

        # Calculate weighted cash flows (Modified Dietz)
        total_cf = 0.0
        weighted_cf = 0.0

        for cf_date, cf_amount in cash_flows:
            cf = float(cf_amount)
            total_cf += cf

            days_remaining = (end_date - cf_date).days
            weight = days_remaining / total_days
            weighted_cf += weight * cf

        # Modified Dietz return
        denominator = start_val + weighted_cf

        if denominator == 0:
            return None

        return_val = (end_val - start_val - total_cf) / denominator

        return Decimal(str(return_val))

    def calculate_annualized_twr(
        self,
        twr: Decimal,
        start_date: date,
        end_date: date
    ) -> Decimal:
        """
        Annualize a TWR based on the period length.

        Args:
            twr: Total return for period
            start_date: Start date
            end_date: End date

        Returns:
            Annualized TWR
        """
        days = (end_date - start_date).days
        return annualize_return(twr, days)

    def calculate_daily_returns(
        self,
        daily_values: List[DailyValue]
    ) -> List[Tuple[date, Decimal]]:
        """
        Calculate daily returns from daily values.

        Args:
            daily_values: List of DailyValue objects

        Returns:
            List of (date, return) tuples
        """
        if len(daily_values) < 2:
            return []

        sorted_values = sorted(daily_values, key=lambda x: x.date)
        returns = []

        for i in range(1, len(sorted_values)):
            prev = sorted_values[i - 1]
            curr = sorted_values[i]

            prev_val = float(prev.value)
            curr_val = float(curr.value)
            cf = float(curr.cash_flow)

            # Adjust for cash flow
            adjusted_prev = prev_val + cf

            if adjusted_prev != 0:
                daily_return = (curr_val - adjusted_prev) / adjusted_prev
            else:
                daily_return = 0

            returns.append((curr.date, Decimal(str(daily_return))))

        return returns


def calculate_twr(
    start_value: Decimal,
    end_value: Decimal,
    start_date: date,
    end_date: date,
    cash_flows: List[Tuple[date, Decimal]] = None
) -> Optional[Decimal]:
    """
    Convenience function to calculate TWR.

    Args:
        start_value: Portfolio value at start
        end_value: Portfolio value at end
        start_date: Start date
        end_date: End date
        cash_flows: Optional list of (date, amount) tuples

    Returns:
        TWR as Decimal
    """
    calculator = TWRCalculator()
    return calculator.calculate_twr_from_transactions(
        start_value, end_value, start_date, end_date, cash_flows or []
    )
