"""ECB (European Central Bank) FX rate service."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, Optional, List
from pathlib import Path
import xml.etree.ElementTree as ET

import httpx

from config.settings import settings
from calculators.fx_converter import FXConverter


class ECBFXService:
    """
    Service to fetch and cache exchange rates from ECB.

    ECB provides daily reference rates against EUR.
    Rates are typically published around 16:00 CET on business days.
    """

    # ECB SDMX API endpoint
    ECB_API_URL = "https://data-api.ecb.europa.eu/service/data/EXR"

    # Common currency codes
    SUPPORTED_CURRENCIES = [
        "USD", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD",
        "HKD", "SGD", "CNY", "INR", "SEK", "NOK", "DKK"
    ]

    def __init__(
        self,
        cache_directory: Optional[Path] = None,
        cache_hours: int = None
    ):
        """
        Initialize ECB FX service.

        Args:
            cache_directory: Directory for caching rates
            cache_hours: Hours to cache rates before refreshing
        """
        self.cache_dir = cache_directory or Path(settings.output_directory) / "fx_cache"
        self.cache_hours = cache_hours or settings.fx_cache_hours
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._converter = FXConverter(base_currency="EUR")
        self._rates_loaded = False
        self._last_fetch: Optional[datetime] = None

    @property
    def converter(self) -> FXConverter:
        """Get the FX converter with loaded rates."""
        return self._converter

    async def fetch_rates_async(
        self,
        currencies: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Dict[date, Decimal]]:
        """
        Fetch exchange rates from ECB API asynchronously.

        Args:
            currencies: List of currency codes to fetch (default: all supported)
            start_date: Start date for historical rates
            end_date: End date (default: today)

        Returns:
            Dict of currency -> {date -> rate}
        """
        currencies = currencies or self.SUPPORTED_CURRENCIES
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=30))

        # Build API URL
        # ECB SDMX format: /EXR/D.{currency}.EUR.SP00.A
        currency_list = "+".join(currencies)
        url = f"{self.ECB_API_URL}/D.{currency_list}.EUR.SP00.A"

        params = {
            "startPeriod": start_date.isoformat(),
            "endPeriod": end_date.isoformat(),
            "format": "jsondata"
        }

        rates: Dict[str, Dict[date, Decimal]] = {}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json()
                rates = self._parse_ecb_json(data)

        except httpx.HTTPError as e:
            # Log error but don't fail - try cache
            print(f"Warning: ECB API error: {e}")
            rates = self._load_from_cache()

        except Exception as e:
            print(f"Warning: Error fetching ECB rates: {e}")
            rates = self._load_from_cache()

        if rates:
            self._converter.set_rates_bulk(rates)
            self._save_to_cache(rates)
            self._rates_loaded = True
            self._last_fetch = datetime.now()

        return rates

    def fetch_rates(
        self,
        currencies: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Dict[date, Decimal]]:
        """
        Fetch exchange rates synchronously.

        Args:
            currencies: List of currency codes to fetch
            start_date: Start date for historical rates
            end_date: End date (default: today)

        Returns:
            Dict of currency -> {date -> rate}
        """
        currencies = currencies or self.SUPPORTED_CURRENCIES
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=30))

        # Check cache first
        if self._is_cache_valid():
            cached_rates = self._load_from_cache()
            if cached_rates:
                self._converter.set_rates_bulk(cached_rates)
                self._rates_loaded = True
                return cached_rates

        currency_list = "+".join(currencies)
        url = f"{self.ECB_API_URL}/D.{currency_list}.EUR.SP00.A"

        params = {
            "startPeriod": start_date.isoformat(),
            "endPeriod": end_date.isoformat(),
            "format": "jsondata"
        }

        rates: Dict[str, Dict[date, Decimal]] = {}

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params)
                response.raise_for_status()

                data = response.json()
                rates = self._parse_ecb_json(data)

        except httpx.HTTPError as e:
            print(f"Warning: ECB API error: {e}")
            rates = self._load_from_cache()

        except Exception as e:
            print(f"Warning: Error fetching ECB rates: {e}")
            rates = self._load_from_cache()

        if rates:
            self._converter.set_rates_bulk(rates)
            self._save_to_cache(rates)
            self._rates_loaded = True
            self._last_fetch = datetime.now()

        return rates

    def _parse_ecb_json(self, data: dict) -> Dict[str, Dict[date, Decimal]]:
        """Parse ECB SDMX JSON response."""
        rates: Dict[str, Dict[date, Decimal]] = {}

        try:
            # Navigate SDMX JSON structure
            data_sets = data.get("dataSets", [])
            if not data_sets:
                return rates

            structure = data.get("structure", {})
            dimensions = structure.get("dimensions", {})
            observation_dims = dimensions.get("observation", [])

            # Get time periods
            time_dim = None
            for dim in observation_dims:
                if dim.get("id") == "TIME_PERIOD":
                    time_dim = dim
                    break

            if not time_dim:
                return rates

            time_values = [v.get("id") for v in time_dim.get("values", [])]

            # Get series dimensions
            series_dims = dimensions.get("series", [])
            currency_dim = None
            for dim in series_dims:
                if dim.get("id") == "CURRENCY":
                    currency_dim = dim
                    break

            if not currency_dim:
                return rates

            currency_values = [v.get("id") for v in currency_dim.get("values", [])]

            # Parse observations
            series = data_sets[0].get("series", {})

            for series_key, series_data in series.items():
                # Parse series key to get currency index
                key_parts = series_key.split(":")
                if len(key_parts) < 2:
                    continue

                currency_idx = int(key_parts[0])
                if currency_idx >= len(currency_values):
                    continue

                currency = currency_values[currency_idx]
                if currency not in rates:
                    rates[currency] = {}

                observations = series_data.get("observations", {})
                for time_idx, obs_values in observations.items():
                    if int(time_idx) >= len(time_values):
                        continue

                    date_str = time_values[int(time_idx)]
                    try:
                        rate_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        rate_value = Decimal(str(obs_values[0]))
                        rates[currency][rate_date] = rate_value
                    except (ValueError, IndexError):
                        continue

        except Exception as e:
            print(f"Warning: Error parsing ECB response: {e}")

        return rates

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        cache_file = self.cache_dir / "fx_rates.json"
        if not cache_file.exists():
            return False

        # Check file age
        file_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
        age_hours = (datetime.now() - file_time).total_seconds() / 3600

        return age_hours < self.cache_hours

    def _load_from_cache(self) -> Dict[str, Dict[date, Decimal]]:
        """Load rates from cache file."""
        cache_file = self.cache_dir / "fx_rates.json"
        if not cache_file.exists():
            return {}

        try:
            with open(cache_file, "r") as f:
                data = json.load(f)

            rates: Dict[str, Dict[date, Decimal]] = {}
            for currency, date_rates in data.items():
                rates[currency] = {}
                for date_str, rate in date_rates.items():
                    rate_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    rates[currency][rate_date] = Decimal(str(rate))

            return rates

        except Exception as e:
            print(f"Warning: Error loading cache: {e}")
            return {}

    def _save_to_cache(self, rates: Dict[str, Dict[date, Decimal]]) -> None:
        """Save rates to cache file."""
        cache_file = self.cache_dir / "fx_rates.json"

        try:
            data = {}
            for currency, date_rates in rates.items():
                data[currency] = {
                    d.isoformat(): float(r) for d, r in date_rates.items()
                }

            with open(cache_file, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            print(f"Warning: Error saving cache: {e}")

    def get_rate(
        self,
        currency: str,
        rate_date: date,
        base_currency: str = "EUR"
    ) -> Optional[Decimal]:
        """
        Get exchange rate for a specific date.

        Args:
            currency: Target currency
            rate_date: Date for the rate
            base_currency: Base currency (default: EUR)

        Returns:
            Exchange rate or None
        """
        if not self._rates_loaded:
            self.fetch_rates()

        if base_currency == "EUR":
            return self._converter.get_rate(currency, rate_date)
        else:
            # Need to calculate cross rate
            return self._converter.get_cross_rate(base_currency, currency, rate_date)

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        rate_date: date
    ) -> Optional[Decimal]:
        """
        Convert amount between currencies.

        Args:
            amount: Amount to convert
            from_currency: Source currency
            to_currency: Target currency
            rate_date: Date for rate

        Returns:
            Converted amount or None
        """
        if not self._rates_loaded:
            self.fetch_rates()

        return self._converter.convert(amount, from_currency, to_currency, rate_date)

    def set_manual_rate(
        self,
        currency: str,
        rate_date: date,
        rate: Decimal
    ) -> None:
        """
        Set a manual exchange rate (overrides ECB data).

        Args:
            currency: Currency code
            rate_date: Date for the rate
            rate: Exchange rate vs EUR
        """
        self._converter.set_rate(currency, rate_date, rate)
