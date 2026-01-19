"""CSV file loader for transaction data."""

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union

from models.transaction import Transaction
from models.enums import TransactionType, AssetType, CurrencyCode
from .validators import DataValidator, ValidationResult
from utils.date_utils import parse_date


class CSVLoader:
    """Load and validate transaction data from CSV files."""

    def __init__(self, validator: Optional[DataValidator] = None):
        """
        Initialize CSV loader.

        Args:
            validator: Optional DataValidator instance
        """
        self.validator = validator or DataValidator()
        self.raw_data: List[Dict[str, Any]] = []
        self.transactions: List[Transaction] = []
        self.validation_result: Optional[ValidationResult] = None

    def load(self, file_path: Union[str, Path]) -> Tuple[List[Transaction], ValidationResult]:
        """
        Load transactions from CSV file.

        Args:
            file_path: Path to CSV file

        Returns:
            Tuple of (transactions list, validation result)
        """
        file_path = Path(file_path)

        if not file_path.exists():
            result = ValidationResult(is_valid=False)
            result.add_error("file", f"File not found: {file_path}")
            return [], result

        if not file_path.suffix.lower() == ".csv":
            result = ValidationResult(is_valid=False)
            result.add_error("file", f"Not a CSV file: {file_path}")
            return [], result

        # Read raw data
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                self.raw_data = list(reader)
        except Exception as e:
            result = ValidationResult(is_valid=False)
            result.add_error("file", f"Error reading file: {str(e)}")
            return [], result

        if not self.raw_data:
            result = ValidationResult(is_valid=False)
            result.add_error("file", "CSV file is empty")
            return [], result

        # Validate schema
        columns = set(self.raw_data[0].keys())
        self.validation_result = self.validator.validate_schema(columns)

        # Validate and parse each row
        self.transactions = []
        for i, row in enumerate(self.raw_data, start=2):  # Row 2 is first data row after header
            row_result = self.validator.validate_transaction_row(row, i)
            self.validation_result.merge(row_result)

            # Only parse valid rows
            if row_result.is_valid:
                try:
                    transaction = self._parse_row(row)
                    self.transactions.append(transaction)
                except Exception as e:
                    self.validation_result.add_error(
                        "parsing", f"Error parsing row: {str(e)}", i
                    )

        return self.transactions, self.validation_result

    def _parse_row(self, row: Dict[str, Any]) -> Transaction:
        """
        Parse a row dictionary into a Transaction object.

        Args:
            row: Dictionary of field values

        Returns:
            Transaction object
        """
        # Normalize keys
        row = {k.lower().strip().replace(" ", "_"): v for k, v in row.items()}

        # Parse dates
        transaction_date = parse_date(row["transaction_date"])
        settlement_date = parse_date(row.get("settlement_date") or row["transaction_date"])

        # Parse enums
        transaction_type = self.validator.parse_transaction_type(row["transaction_type"])
        asset_type = self.validator.parse_asset_type(row.get("asset_type", "EQUITY"))
        currency = CurrencyCode.from_string(row["currency"])

        # Parse numeric fields
        quantity = self._parse_decimal(row["quantity"])
        price = self._parse_decimal(row["price"])
        commission = self._parse_decimal(row.get("commission", "0"))
        fees = self._parse_decimal(row.get("fees", "0"))
        taxes = self._parse_decimal(row.get("taxes", "0"))
        fx_rate = self._parse_decimal(row.get("fx_rate", "1"))

        # Build transaction
        transaction = Transaction(
            transaction_date=transaction_date,
            settlement_date=settlement_date,
            transaction_type=transaction_type,
            asset_type=asset_type,
            symbol=str(row["symbol"]).strip().upper(),
            quantity=quantity,
            price=price,
            currency=currency,
            commission=commission,
            fees=fees,
            taxes=taxes,
            fx_rate=fx_rate,
            account_id=row.get("account_id"),
            cusip=row.get("cusip"),
            isin=row.get("isin"),
            description=row.get("description"),
        )

        # Handle option-specific fields
        if AssetType.is_option(asset_type):
            if row.get("strike_price"):
                transaction.strike_price = self._parse_decimal(row["strike_price"])
            if row.get("expiry_date"):
                transaction.expiry_date = parse_date(row["expiry_date"])
            if row.get("underlying_symbol"):
                transaction.underlying_symbol = str(row["underlying_symbol"]).upper()

        # Handle bond-specific fields
        if AssetType.is_fixed_income(asset_type):
            if row.get("coupon_rate"):
                transaction.coupon_rate = self._parse_decimal(row["coupon_rate"])
            if row.get("maturity_date"):
                transaction.maturity_date = parse_date(row["maturity_date"])
            if row.get("accrued_interest"):
                transaction.accrued_interest = self._parse_decimal(row["accrued_interest"])
            if row.get("face_value"):
                transaction.face_value = self._parse_decimal(row["face_value"])

        return transaction

    def _parse_decimal(self, value: Any) -> Decimal:
        """
        Parse a value to Decimal.

        Args:
            value: Value to parse

        Returns:
            Decimal value
        """
        if value is None or value == "":
            return Decimal("0")

        if isinstance(value, Decimal):
            return value

        # Clean string values
        if isinstance(value, str):
            value = value.replace(",", "").replace("$", "").replace("€", "").strip()
            if value == "":
                return Decimal("0")

        return Decimal(str(value))

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics of loaded data.

        Returns:
            Dictionary of summary statistics
        """
        if not self.transactions:
            return {"loaded": False, "count": 0}

        dates = [t.transaction_date for t in self.transactions]
        symbols = set(t.symbol for t in self.transactions)
        types = {}
        for t in self.transactions:
            type_name = t.transaction_type.name
            types[type_name] = types.get(type_name, 0) + 1

        return {
            "loaded": True,
            "count": len(self.transactions),
            "date_range": {
                "start": min(dates).isoformat(),
                "end": max(dates).isoformat(),
            },
            "unique_symbols": len(symbols),
            "symbols": sorted(symbols),
            "transaction_types": types,
            "validation": {
                "is_valid": self.validation_result.is_valid if self.validation_result else None,
                "errors": self.validation_result.errors_count if self.validation_result else 0,
                "warnings": self.validation_result.warnings_count if self.validation_result else 0,
            },
        }
