"""Excel file loader for transaction and portfolio data."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union

import pandas as pd

from models.transaction import Transaction
from models.enums import TransactionType, AssetType, CurrencyCode
from .validators import DataValidator, ValidationResult
from utils.date_utils import parse_date


class ExcelLoader:
    """Load and validate transaction data from Excel files."""

    # Default sheet names to look for
    DEFAULT_TRANSACTION_SHEETS = ["Transactions", "transactions", "Trans", "trades", "Trades"]
    DEFAULT_POSITION_SHEETS = ["Positions", "positions", "Holdings", "holdings"]
    DEFAULT_EXPECTED_SHEETS = ["Expected", "expected", "PMS", "pms"]

    def __init__(self, validator: Optional[DataValidator] = None):
        """
        Initialize Excel loader.

        Args:
            validator: Optional DataValidator instance
        """
        self.validator = validator or DataValidator()
        self.raw_data: Dict[str, pd.DataFrame] = {}
        self.transactions: List[Transaction] = []
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.expected_values: Dict[str, Any] = {}
        self.validation_result: Optional[ValidationResult] = None

    def load(
        self,
        file_path: Union[str, Path],
        transaction_sheet: Optional[str] = None,
        position_sheet: Optional[str] = None,
        expected_sheet: Optional[str] = None,
    ) -> Tuple[List[Transaction], ValidationResult]:
        """
        Load transactions from Excel file.

        Args:
            file_path: Path to Excel file
            transaction_sheet: Optional specific sheet name for transactions
            position_sheet: Optional specific sheet name for positions
            expected_sheet: Optional specific sheet name for expected values

        Returns:
            Tuple of (transactions list, validation result)
        """
        file_path = Path(file_path)

        if not file_path.exists():
            result = ValidationResult(is_valid=False)
            result.add_error("file", f"File not found: {file_path}")
            return [], result

        if file_path.suffix.lower() not in [".xlsx", ".xls", ".xlsm"]:
            result = ValidationResult(is_valid=False)
            result.add_error("file", f"Not an Excel file: {file_path}")
            return [], result

        # Load Excel file
        try:
            excel_file = pd.ExcelFile(file_path)
            sheet_names = excel_file.sheet_names
        except Exception as e:
            result = ValidationResult(is_valid=False)
            result.add_error("file", f"Error reading Excel file: {str(e)}")
            return [], result

        self.validation_result = ValidationResult(is_valid=True)

        # Find and load transaction sheet
        txn_sheet = self._find_sheet(sheet_names, transaction_sheet, self.DEFAULT_TRANSACTION_SHEETS)
        if txn_sheet:
            self._load_transactions(excel_file, txn_sheet)
        else:
            self.validation_result.add_error("sheet", "No transaction sheet found in workbook")

        # Find and load position sheet (optional)
        pos_sheet = self._find_sheet(sheet_names, position_sheet, self.DEFAULT_POSITION_SHEETS)
        if pos_sheet:
            self._load_positions(excel_file, pos_sheet)

        # Find and load expected values sheet (optional)
        exp_sheet = self._find_sheet(sheet_names, expected_sheet, self.DEFAULT_EXPECTED_SHEETS)
        if exp_sheet:
            self._load_expected_values(excel_file, exp_sheet)

        return self.transactions, self.validation_result

    def _find_sheet(
        self,
        available_sheets: List[str],
        specified_sheet: Optional[str],
        default_names: List[str]
    ) -> Optional[str]:
        """
        Find appropriate sheet name.

        Args:
            available_sheets: List of sheet names in workbook
            specified_sheet: User-specified sheet name (if any)
            default_names: List of default names to try

        Returns:
            Sheet name if found, None otherwise
        """
        if specified_sheet:
            if specified_sheet in available_sheets:
                return specified_sheet
            return None

        for name in default_names:
            if name in available_sheets:
                return name

        return None

    def _load_transactions(self, excel_file: pd.ExcelFile, sheet_name: str) -> None:
        """Load transactions from specified sheet."""
        try:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            self.raw_data["transactions"] = df

            # Convert to list of dicts
            rows = df.to_dict("records")

            if not rows:
                self.validation_result.add_error("sheet", f"Transaction sheet '{sheet_name}' is empty")
                return

            # Validate schema
            columns = set(df.columns)
            schema_result = self.validator.validate_schema(columns)
            self.validation_result.merge(schema_result)

            # Validate and parse each row
            for i, row in enumerate(rows, start=2):
                # Skip rows with all NaN
                if all(pd.isna(v) for v in row.values()):
                    continue

                row_result = self.validator.validate_transaction_row(row, i)
                self.validation_result.merge(row_result)

                if row_result.is_valid:
                    try:
                        transaction = self._parse_row(row)
                        self.transactions.append(transaction)
                    except Exception as e:
                        self.validation_result.add_error(
                            "parsing", f"Error parsing row: {str(e)}", i
                        )

        except Exception as e:
            self.validation_result.add_error("sheet", f"Error reading sheet '{sheet_name}': {str(e)}")

    def _load_positions(self, excel_file: pd.ExcelFile, sheet_name: str) -> None:
        """Load positions from specified sheet."""
        try:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            self.raw_data["positions"] = df

            for _, row in df.iterrows():
                row_dict = row.to_dict()
                symbol = str(row_dict.get("symbol", row_dict.get("Symbol", ""))).upper()

                if symbol:
                    self.positions[symbol] = {
                        "quantity": self._parse_value(row_dict.get("quantity", row_dict.get("Quantity", 0))),
                        "market_value": self._parse_value(row_dict.get("market_value", row_dict.get("Market Value", 0))),
                        "cost_basis": self._parse_value(row_dict.get("cost_basis", row_dict.get("Cost Basis", 0))),
                        "unrealized_pnl": self._parse_value(row_dict.get("unrealized_pnl", row_dict.get("Unrealized P&L", 0))),
                        "current_price": self._parse_value(row_dict.get("price", row_dict.get("Price", 0))),
                    }

        except Exception as e:
            self.validation_result.add_warning("positions", f"Error reading positions: {str(e)}")

    def _load_expected_values(self, excel_file: pd.ExcelFile, sheet_name: str) -> None:
        """Load expected values (PMS values) from specified sheet."""
        try:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            self.raw_data["expected"] = df

            # Expected sheet might be key-value pairs
            for _, row in df.iterrows():
                row_dict = row.to_dict()

                # Handle key-value format
                if "metric" in row_dict or "Metric" in row_dict:
                    metric = str(row_dict.get("metric", row_dict.get("Metric", "")))
                    value = row_dict.get("value", row_dict.get("Value", 0))
                    self.expected_values[metric.lower()] = self._parse_value(value)

                # Handle columnar format
                else:
                    for key, value in row_dict.items():
                        if pd.notna(value):
                            self.expected_values[str(key).lower()] = self._parse_value(value)

        except Exception as e:
            self.validation_result.add_warning("expected", f"Error reading expected values: {str(e)}")

    def _parse_row(self, row: Dict[str, Any]) -> Transaction:
        """Parse a row dictionary into a Transaction object."""
        # Normalize keys
        row = {str(k).lower().strip().replace(" ", "_"): v for k, v in row.items()}

        # Parse dates - handle pandas Timestamp
        transaction_date = self._parse_date(row["transaction_date"])
        settlement_date = self._parse_date(row.get("settlement_date") or row["transaction_date"])

        # Parse enums
        transaction_type = self.validator.parse_transaction_type(row["transaction_type"])
        asset_type = self.validator.parse_asset_type(row.get("asset_type", "EQUITY"))
        currency = CurrencyCode.from_string(str(row["currency"]))

        # Parse numeric fields
        quantity = self._parse_decimal(row["quantity"])
        price = self._parse_decimal(row["price"])
        commission = self._parse_decimal(row.get("commission", 0))
        fees = self._parse_decimal(row.get("fees", 0))
        taxes = self._parse_decimal(row.get("taxes", 0))
        fx_rate = self._parse_decimal(row.get("fx_rate", 1))

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
            account_id=str(row.get("account_id", "")) if pd.notna(row.get("account_id")) else None,
            cusip=str(row.get("cusip", "")) if pd.notna(row.get("cusip")) else None,
            isin=str(row.get("isin", "")) if pd.notna(row.get("isin")) else None,
            description=str(row.get("description", "")) if pd.notna(row.get("description")) else None,
        )

        # Handle option-specific fields
        if AssetType.is_option(asset_type):
            if pd.notna(row.get("strike_price")):
                transaction.strike_price = self._parse_decimal(row["strike_price"])
            if pd.notna(row.get("expiry_date")):
                transaction.expiry_date = self._parse_date(row["expiry_date"])
            if pd.notna(row.get("underlying_symbol")):
                transaction.underlying_symbol = str(row["underlying_symbol"]).upper()

        # Handle bond-specific fields
        if AssetType.is_fixed_income(asset_type):
            if pd.notna(row.get("coupon_rate")):
                transaction.coupon_rate = self._parse_decimal(row["coupon_rate"])
            if pd.notna(row.get("maturity_date")):
                transaction.maturity_date = self._parse_date(row["maturity_date"])
            if pd.notna(row.get("accrued_interest")):
                transaction.accrued_interest = self._parse_decimal(row["accrued_interest"])
            if pd.notna(row.get("face_value")):
                transaction.face_value = self._parse_decimal(row["face_value"])

        return transaction

    def _parse_date(self, value: Any) -> date:
        """Parse date from various formats."""
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, pd.Timestamp):
            return value.date()
        if pd.isna(value):
            return date.today()
        return parse_date(value)

    def _parse_decimal(self, value: Any) -> Decimal:
        """Parse a value to Decimal."""
        if value is None or pd.isna(value):
            return Decimal("0")

        if isinstance(value, Decimal):
            return value

        if isinstance(value, str):
            value = value.replace(",", "").replace("$", "").replace("€", "").strip()
            if value == "":
                return Decimal("0")

        return Decimal(str(value))

    def _parse_value(self, value: Any) -> Decimal:
        """Parse any value to Decimal (alias for _parse_decimal)."""
        return self._parse_decimal(value)

    def get_expected_values(self) -> Dict[str, Decimal]:
        """Get loaded expected values for reconciliation."""
        return self.expected_values

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        """Get loaded position data."""
        return self.positions

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of loaded data."""
        return {
            "loaded": True,
            "transactions_count": len(self.transactions),
            "positions_count": len(self.positions),
            "expected_values_count": len(self.expected_values),
            "sheets_loaded": list(self.raw_data.keys()),
            "validation": {
                "is_valid": self.validation_result.is_valid if self.validation_result else None,
                "errors": self.validation_result.errors_count if self.validation_result else 0,
                "warnings": self.validation_result.warnings_count if self.validation_result else 0,
            },
        }
