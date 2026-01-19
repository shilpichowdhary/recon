"""Date handling utilities."""

from datetime import date, timedelta
from typing import Optional, Union
from dateutil import parser as date_parser


def parse_date(date_input: Union[str, date], date_format: Optional[str] = None) -> date:
    """
    Parse a date from string or return date object.

    Args:
        date_input: Date string or date object
        date_format: Optional specific format string

    Returns:
        Parsed date object
    """
    if isinstance(date_input, date):
        return date_input

    if date_format:
        from datetime import datetime
        return datetime.strptime(date_input, date_format).date()

    # Use dateutil for flexible parsing
    return date_parser.parse(date_input).date()


def is_weekend(d: date) -> bool:
    """Check if date is a weekend (Saturday=5, Sunday=6)."""
    return d.weekday() >= 5


def get_business_day(d: date, direction: str = "following") -> date:
    """
    Adjust date to business day.

    Args:
        d: Date to adjust
        direction: "following" (next business day) or "preceding" (previous business day)

    Returns:
        Adjusted business day
    """
    if direction == "following":
        while is_weekend(d):
            d += timedelta(days=1)
    elif direction == "preceding":
        while is_weekend(d):
            d -= timedelta(days=1)
    return d


def get_previous_business_day(d: date) -> date:
    """Get the previous business day (excluding weekends)."""
    d = d - timedelta(days=1)
    while is_weekend(d):
        d -= timedelta(days=1)
    return d


def day_count_30_360(start_date: date, end_date: date) -> int:
    """
    Calculate day count using 30/360 convention.

    Used primarily for bond accrued interest calculations.
    """
    d1 = min(start_date.day, 30)
    d2 = end_date.day if d1 < 30 else min(end_date.day, 30)

    return (
        360 * (end_date.year - start_date.year)
        + 30 * (end_date.month - start_date.month)
        + (d2 - d1)
    )


def day_count_actual_365(start_date: date, end_date: date) -> int:
    """Calculate actual day count (Actual/365 convention)."""
    return (end_date - start_date).days


def day_count_actual_360(start_date: date, end_date: date) -> int:
    """Calculate actual day count (Actual/360 convention)."""
    return (end_date - start_date).days


def year_fraction(start_date: date, end_date: date, convention: str = "actual_365") -> float:
    """
    Calculate year fraction between two dates.

    Args:
        start_date: Start date
        end_date: End date
        convention: Day count convention ("actual_365", "actual_360", "30_360")

    Returns:
        Year fraction as float
    """
    if convention == "actual_365":
        days = day_count_actual_365(start_date, end_date)
        return days / 365.0
    elif convention == "actual_360":
        days = day_count_actual_360(start_date, end_date)
        return days / 360.0
    elif convention == "30_360":
        days = day_count_30_360(start_date, end_date)
        return days / 360.0
    else:
        raise ValueError(f"Unknown day count convention: {convention}")


def get_month_end(d: date) -> date:
    """Get the last day of the month for given date."""
    if d.month == 12:
        return date(d.year + 1, 1, 1) - timedelta(days=1)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def get_quarter_end(d: date) -> date:
    """Get the last day of the quarter for given date."""
    quarter = (d.month - 1) // 3 + 1
    quarter_end_month = quarter * 3
    if quarter_end_month == 12:
        return date(d.year, 12, 31)
    return date(d.year, quarter_end_month + 1, 1) - timedelta(days=1)


def get_year_end(d: date) -> date:
    """Get the last day of the year for given date."""
    return date(d.year, 12, 31)


def generate_date_range(start_date: date, end_date: date, business_days_only: bool = False) -> list[date]:
    """
    Generate a list of dates between start and end dates.

    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        business_days_only: If True, exclude weekends

    Returns:
        List of dates
    """
    dates = []
    current = start_date

    while current <= end_date:
        if not business_days_only or not is_weekend(current):
            dates.append(current)
        current += timedelta(days=1)

    return dates
