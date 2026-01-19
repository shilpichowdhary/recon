"""FX conversion utilities."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional
from functools import lru_cache

from models.enums import CurrencyCode


class FXConverter:
    """
    Foreign exchange rate conversion.

    Supports rate lookups and currency conversion with caching.
    Designed to work with ECB FX service for rate data.
    """

    def __init__(self, base_currency: str = "USD"):
        """
        Initialize FX converter.

        Args:
            base_currency: Base currency for conversions
        """
        self.base_currency = base_currency.upper()
        self._rates: Dict[str, Dict[date, Decimal]] = {}
        self._rate_cache: Dict[tuple, Decimal] = {}

    def set_rate(
        self,
        currency: str,
        rate_date: date,
        rate: Decimal
    ) -> None:
        """
        Set an exchange rate.

        Args:
            currency: Currency code
            rate_date: Date for the rate
            rate: Exchange rate (currency per base currency)
        """
        currency = currency.upper()
        if currency not in self._rates:
            self._rates[currency] = {}
        self._rates[currency][rate_date] = rate

        # Clear cache when rates change
        self._rate_cache.clear()

    def set_rates_bulk(
        self,
        rates: Dict[str, Dict[date, Decimal]]
    ) -> None:
        """
        Set multiple exchange rates.

        Args:
            rates: Dict of currency -> {date -> rate}
        """
        for currency, date_rates in rates.items():
            currency = currency.upper()
            if currency not in self._rates:
                self._rates[currency] = {}
            self._rates[currency].update(date_rates)

        self._rate_cache.clear()

    def get_rate(
        self,
        currency: str,
        rate_date: date,
        fallback_to_previous: bool = True
    ) -> Optional[Decimal]:
        """
        Get exchange rate for a currency and date.

        Args:
            currency: Currency code
            rate_date: Date for the rate
            fallback_to_previous: If True, use previous business day if rate not found

        Returns:
            Exchange rate or None if not found
        """
        currency = currency.upper()

        # Same currency = rate of 1
        if currency == self.base_currency:
            return Decimal("1")

        # Check cache
        cache_key = (currency, rate_date)
        if cache_key in self._rate_cache:
            return self._rate_cache[cache_key]

        # Look up rate
        if currency in self._rates:
            if rate_date in self._rates[currency]:
                rate = self._rates[currency][rate_date]
                self._rate_cache[cache_key] = rate
                return rate

            # Try previous days if allowed
            if fallback_to_previous:
                for days_back in range(1, 8):  # Try up to 7 days back
                    prev_date = rate_date - timedelta(days=days_back)
                    if prev_date in self._rates[currency]:
                        rate = self._rates[currency][prev_date]
                        self._rate_cache[cache_key] = rate
                        return rate

        return None

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        rate_date: date
    ) -> Optional[Decimal]:
        """
        Convert amount from one currency to another.

        Args:
            amount: Amount to convert
            from_currency: Source currency
            to_currency: Target currency
            rate_date: Date for exchange rate

        Returns:
            Converted amount or None if rate not available
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        # Same currency
        if from_currency == to_currency:
            return amount

        # Convert to base currency first, then to target
        if from_currency == self.base_currency:
            # Direct conversion from base
            to_rate = self.get_rate(to_currency, rate_date)
            if to_rate is None:
                return None
            return amount * to_rate

        elif to_currency == self.base_currency:
            # Direct conversion to base
            from_rate = self.get_rate(from_currency, rate_date)
            if from_rate is None:
                return None
            return amount / from_rate

        else:
            # Cross rate: from -> base -> to
            from_rate = self.get_rate(from_currency, rate_date)
            to_rate = self.get_rate(to_currency, rate_date)

            if from_rate is None or to_rate is None:
                return None

            # Convert to base then to target
            base_amount = amount / from_rate
            return base_amount * to_rate

    def convert_to_base(
        self,
        amount: Decimal,
        currency: str,
        rate_date: date
    ) -> Optional[Decimal]:
        """
        Convert amount to base currency.

        Args:
            amount: Amount to convert
            currency: Source currency
            rate_date: Date for exchange rate

        Returns:
            Amount in base currency or None
        """
        return self.convert(amount, currency, self.base_currency, rate_date)

    def get_cross_rate(
        self,
        from_currency: str,
        to_currency: str,
        rate_date: date
    ) -> Optional[Decimal]:
        """
        Calculate cross rate between two currencies.

        Args:
            from_currency: Source currency
            to_currency: Target currency
            rate_date: Date for exchange rate

        Returns:
            Cross rate or None if not calculable
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        if from_currency == to_currency:
            return Decimal("1")

        from_rate = self.get_rate(from_currency, rate_date)
        to_rate = self.get_rate(to_currency, rate_date)

        if from_rate is None or to_rate is None:
            return None

        # Cross rate = to_rate / from_rate
        if from_rate == Decimal("0"):
            return None

        return to_rate / from_rate

    def get_available_currencies(self) -> list[str]:
        """Get list of currencies with rates."""
        return list(self._rates.keys())

    def get_available_dates(self, currency: str) -> list[date]:
        """Get list of dates with rates for a currency."""
        currency = currency.upper()
        if currency not in self._rates:
            return []
        return sorted(self._rates[currency].keys())

    def get_latest_rate(self, currency: str) -> Optional[tuple[date, Decimal]]:
        """
        Get the most recent rate for a currency.

        Returns:
            Tuple of (date, rate) or None
        """
        currency = currency.upper()
        if currency not in self._rates or not self._rates[currency]:
            return None

        latest_date = max(self._rates[currency].keys())
        return (latest_date, self._rates[currency][latest_date])

    def validate_rate(
        self,
        calculated_rate: Decimal,
        expected_rate: Decimal,
        tolerance: Decimal = Decimal("0.0001")
    ) -> bool:
        """
        Validate that calculated rate is within tolerance of expected.

        Args:
            calculated_rate: Calculated exchange rate
            expected_rate: Expected exchange rate
            tolerance: Allowed difference

        Returns:
            True if within tolerance
        """
        return abs(calculated_rate - expected_rate) <= tolerance


# Singleton instance for global use
_default_converter: Optional[FXConverter] = None


def get_fx_converter(base_currency: str = "USD") -> FXConverter:
    """
    Get or create default FX converter.

    Args:
        base_currency: Base currency for conversions

    Returns:
        FXConverter instance
    """
    global _default_converter
    if _default_converter is None:
        _default_converter = FXConverter(base_currency)
    return _default_converter
