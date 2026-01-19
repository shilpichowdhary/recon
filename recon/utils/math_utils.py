"""Mathematical utilities for financial calculations."""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Tuple, Optional


def round_decimal(value: Decimal, places: int = 2) -> Decimal:
    """
    Round a Decimal to specified decimal places.

    Args:
        value: Decimal value to round
        places: Number of decimal places

    Returns:
        Rounded Decimal
    """
    quantize_str = "0." + "0" * places
    return value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)


def safe_divide(numerator: Decimal, denominator: Decimal, default: Decimal = Decimal("0")) -> Decimal:
    """
    Safely divide two Decimals, returning default if denominator is zero.

    Args:
        numerator: Numerator
        denominator: Denominator
        default: Value to return if denominator is zero

    Returns:
        Result of division or default
    """
    if denominator == Decimal("0"):
        return default
    return numerator / denominator


def calculate_weighted_average(
    values: List[Decimal],
    weights: List[Decimal]
) -> Optional[Decimal]:
    """
    Calculate weighted average of values.

    Args:
        values: List of values
        weights: List of weights (must be same length as values)

    Returns:
        Weighted average or None if no weights
    """
    if len(values) != len(weights):
        raise ValueError("Values and weights must have same length")

    total_weight = sum(weights)
    if total_weight == Decimal("0"):
        return None

    weighted_sum = sum(v * w for v, w in zip(values, weights))
    return weighted_sum / total_weight


def calculate_compound_return(returns: List[Decimal]) -> Decimal:
    """
    Calculate compound return from a series of periodic returns.

    Formula: (1 + R1) * (1 + R2) * ... * (1 + Rn) - 1

    Args:
        returns: List of periodic returns as decimals (e.g., 0.05 for 5%)

    Returns:
        Compound return as decimal
    """
    if not returns:
        return Decimal("0")

    compound = Decimal("1")
    for r in returns:
        compound *= (Decimal("1") + r)

    return compound - Decimal("1")


def annualize_return(total_return: Decimal, days: int) -> Decimal:
    """
    Annualize a return based on number of days.

    Formula: (1 + total_return) ^ (365 / days) - 1

    Args:
        total_return: Total return as decimal
        days: Number of days in period

    Returns:
        Annualized return as decimal
    """
    import math

    if days <= 0:
        return Decimal("0")

    # Use float for power operation, then convert back
    base = float(Decimal("1") + total_return)

    # Handle edge cases
    if base <= 0:
        return Decimal("0")

    exponent = 365.0 / days

    try:
        annualized = base ** exponent - 1
        # Check for invalid results
        if math.isnan(annualized) or math.isinf(annualized):
            return Decimal("0")
        return Decimal(str(round(annualized, 10)))
    except (OverflowError, ValueError):
        return Decimal("0")


def calculate_standard_deviation(values: List[Decimal]) -> Decimal:
    """
    Calculate standard deviation of values.

    Args:
        values: List of Decimal values

    Returns:
        Standard deviation as Decimal
    """
    if len(values) < 2:
        return Decimal("0")

    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)

    # Square root using Newton's method
    std_dev = variance ** Decimal("0.5")
    return std_dev


def calculate_sharpe_ratio(
    returns: List[Decimal],
    risk_free_rate: Decimal = Decimal("0.02")
) -> Optional[Decimal]:
    """
    Calculate Sharpe ratio.

    Formula: (Mean Return - Risk Free Rate) / Standard Deviation

    Args:
        returns: List of periodic returns
        risk_free_rate: Annual risk-free rate

    Returns:
        Sharpe ratio or None if insufficient data
    """
    if len(returns) < 2:
        return None

    mean_return = sum(returns) / len(returns)
    std_dev = calculate_standard_deviation(returns)

    if std_dev == Decimal("0"):
        return None

    # Adjust risk-free rate to match return period (assume daily returns)
    daily_rf = risk_free_rate / Decimal("252")

    return (mean_return - daily_rf) / std_dev


def calculate_max_drawdown(values: List[Decimal]) -> Decimal:
    """
    Calculate maximum drawdown from a series of portfolio values.

    Args:
        values: List of portfolio values over time

    Returns:
        Maximum drawdown as decimal (positive value)
    """
    if len(values) < 2:
        return Decimal("0")

    max_drawdown = Decimal("0")
    peak = values[0]

    for value in values[1:]:
        if value > peak:
            peak = value
        else:
            drawdown = (peak - value) / peak
            max_drawdown = max(max_drawdown, drawdown)

    return max_drawdown


def npv(rate: float, cash_flows: List[Tuple[float, float]]) -> float:
    """
    Calculate Net Present Value.

    Args:
        rate: Discount rate as decimal
        cash_flows: List of (time_in_years, cash_flow_amount) tuples

    Returns:
        NPV as float
    """
    total = 0.0
    for t, cf in cash_flows:
        if rate == -1 and t > 0:
            return float('inf')
        total += cf / ((1 + rate) ** t)
    return total


def npv_derivative(rate: float, cash_flows: List[Tuple[float, float]]) -> float:
    """
    Calculate derivative of NPV with respect to rate.

    Used in Newton-Raphson iteration for IRR.

    Args:
        rate: Discount rate as decimal
        cash_flows: List of (time_in_years, cash_flow_amount) tuples

    Returns:
        NPV derivative as float
    """
    total = 0.0
    for t, cf in cash_flows:
        if t > 0:
            total -= t * cf / ((1 + rate) ** (t + 1))
    return total
