"""Data validation rules for PMS Reconciliation."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional, Set
from enum import Enum

from models.enums import TransactionType, AssetType, CurrencyCode
from utils.date_utils import parse_date


class ValidationSeverity(Enum):
    """Severity level of validation issues."""
    ERROR = "ERROR"      # Data cannot be processed
    WARNING = "WARNING"  # Data can be processed but may be incorrect
    INFO = "INFO"        # Informational, no action needed


@dataclass
class ValidationIssue:
    """Single validation issue."""
    field: str
    message: str
    severity: ValidationSeverity
    row_number: Optional[int] = None
    value: Optional[Any] = None

    def __str__(self) -> str:
        row_info = f" (row {self.row_number})" if self.row_number else ""
        return f"[{self.severity.value}]{row_info} {self.field}: {self.message}"


@dataclass
class ValidationResult:
    """Result of data validation."""
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    warnings_count: int = 0
    errors_count: int = 0

    def add_issue(self, issue: ValidationIssue) -> None:
        """Add a validation issue."""
        self.issues.append(issue)
        if issue.severity == ValidationSeverity.ERROR:
            self.errors_count += 1
            self.is_valid = False
        elif issue.severity == ValidationSeverity.WARNING:
            self.warnings_count += 1

    def add_error(self, field: str, message: str, row_number: Optional[int] = None, value: Any = None) -> None:
        """Convenience method to add an error."""
        self.add_issue(ValidationIssue(field, message, ValidationSeverity.ERROR, row_number, value))

    def add_warning(self, field: str, message: str, row_number: Optional[int] = None, value: Any = None) -> None:
        """Convenience method to add a warning."""
        self.add_issue(ValidationIssue(field, message, ValidationSeverity.WARNING, row_number, value))

    def merge(self, other: "ValidationResult") -> None:
        """Merge another validation result into this one."""
        self.issues.extend(other.issues)
        self.warnings_count += other.warnings_count
        self.errors_count += other.errors_count
        if other.errors_count > 0:
            self.is_valid = False


class DataValidator:
    """Validator for transaction and portfolio data."""

    # Required fields for transaction data
    REQUIRED_TRANSACTION_FIELDS = {
        "transaction_date",
        "transaction_type",
        "symbol",
        "quantity",
        "price",
        "currency",
    }

    # Optional fields with defaults
    OPTIONAL_TRANSACTION_FIELDS = {
        "settlement_date": None,
        "asset_type": "EQUITY",
        "commission": "0",
        "fees": "0",
        "taxes": "0",
        "fx_rate": "1",
        "account_id": None,
        "cusip": None,
        "isin": None,
        "description": None,
    }

    # Valid transaction type mappings (case-insensitive)
    TRANSACTION_TYPE_MAPPINGS = {
        "buy": TransactionType.BUY,
        "sell": TransactionType.SELL,
        "deposit": TransactionType.DEPOSIT,
        "withdrawal": TransactionType.WITHDRAWAL,
        "dividend": TransactionType.DIVIDEND,
        "interest": TransactionType.INTEREST,
        "coupon": TransactionType.COUPON,
        "fee": TransactionType.FEE,
        "commission": TransactionType.COMMISSION,
        "stock_split": TransactionType.STOCK_SPLIT,
        "option_buy": TransactionType.OPTION_BUY,
        "option_sell": TransactionType.OPTION_SELL,
        "option_exercise": TransactionType.OPTION_EXERCISE,
        "option_expiry": TransactionType.OPTION_EXPIRY,
        "transfer_in": TransactionType.TRANSFER_IN,
        "transfer_out": TransactionType.TRANSFER_OUT,
        "fx_trade": TransactionType.FX_TRADE,
    }

    # Valid asset type mappings
    ASSET_TYPE_MAPPINGS = {
        "cash": AssetType.CASH,
        "equity": AssetType.EQUITY,
        "stock": AssetType.EQUITY,
        "etf": AssetType.ETF,
        "mutual_fund": AssetType.MUTUAL_FUND,
        "bond": AssetType.CORPORATE_BOND,
        "corporate_bond": AssetType.CORPORATE_BOND,
        "government_bond": AssetType.GOVERNMENT_BOND,
        "treasury": AssetType.TREASURY_BILL,
        "call_option": AssetType.CALL_OPTION,
        "put_option": AssetType.PUT_OPTION,
        "call": AssetType.CALL_OPTION,
        "put": AssetType.PUT_OPTION,
        "structured": AssetType.STRUCTURED_NOTE,
        "structured_note": AssetType.STRUCTURED_NOTE,
    }

    def __init__(self):
        self.issues: List[ValidationIssue] = []

    def validate_schema(self, columns: Set[str]) -> ValidationResult:
        """
        Validate that required columns are present.

        Args:
            columns: Set of column names in data

        Returns:
            ValidationResult with any schema issues
        """
        result = ValidationResult(is_valid=True)

        # Normalize column names
        normalized_columns = {col.lower().strip().replace(" ", "_") for col in columns}

        # Check required fields
        missing_fields = self.REQUIRED_TRANSACTION_FIELDS - normalized_columns

        if missing_fields:
            result.add_error(
                "schema",
                f"Missing required columns: {', '.join(sorted(missing_fields))}"
            )

        return result

    def validate_transaction_row(self, row: Dict[str, Any], row_number: int) -> ValidationResult:
        """
        Validate a single transaction row.

        Args:
            row: Dictionary of field values
            row_number: Row number for error reporting

        Returns:
            ValidationResult with any row-level issues
        """
        result = ValidationResult(is_valid=True)

        # Normalize keys
        normalized_row = {k.lower().strip().replace(" ", "_"): v for k, v in row.items()}

        # Validate required fields are not empty
        for field in self.REQUIRED_TRANSACTION_FIELDS:
            value = normalized_row.get(field)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                result.add_error(field, f"Required field is empty", row_number)

        # Validate transaction_date
        if "transaction_date" in normalized_row:
            date_result = self._validate_date(
                normalized_row["transaction_date"], "transaction_date", row_number
            )
            result.merge(date_result)

        # Validate settlement_date if present
        if normalized_row.get("settlement_date"):
            date_result = self._validate_date(
                normalized_row["settlement_date"], "settlement_date", row_number
            )
            result.merge(date_result)

        # Validate transaction_type
        if "transaction_type" in normalized_row:
            type_result = self._validate_transaction_type(
                normalized_row["transaction_type"], row_number
            )
            result.merge(type_result)

        # Validate numeric fields
        numeric_fields = ["quantity", "price", "commission", "fees", "taxes", "fx_rate"]
        for field in numeric_fields:
            if field in normalized_row and normalized_row[field]:
                num_result = self._validate_numeric(
                    normalized_row[field], field, row_number
                )
                result.merge(num_result)

        # Validate currency
        if "currency" in normalized_row:
            currency_result = self._validate_currency(
                normalized_row["currency"], row_number
            )
            result.merge(currency_result)

        # Validate asset_type if present
        if normalized_row.get("asset_type"):
            asset_result = self._validate_asset_type(
                normalized_row["asset_type"], row_number
            )
            result.merge(asset_result)

        # Business logic validations
        result.merge(self._validate_business_rules(normalized_row, row_number))

        return result

    def _validate_date(self, value: Any, field: str, row_number: int) -> ValidationResult:
        """Validate a date field."""
        result = ValidationResult(is_valid=True)

        try:
            parsed_date = parse_date(value)

            # Check for future dates (warning only)
            if parsed_date > date.today():
                result.add_warning(field, f"Date is in the future: {value}", row_number, value)

            # Check for unreasonably old dates
            if parsed_date.year < 1900:
                result.add_error(field, f"Date appears invalid (before 1900): {value}", row_number, value)

        except Exception as e:
            result.add_error(field, f"Invalid date format: {value}", row_number, value)

        return result

    def _validate_numeric(self, value: Any, field: str, row_number: int) -> ValidationResult:
        """Validate a numeric field."""
        result = ValidationResult(is_valid=True)

        try:
            # Handle string with currency symbols or commas
            if isinstance(value, str):
                value = value.replace(",", "").replace("$", "").replace("€", "").strip()

            decimal_value = Decimal(str(value))

            # Field-specific validations
            if field == "quantity" and decimal_value == 0:
                result.add_warning(field, "Quantity is zero", row_number, value)

            if field == "price" and decimal_value < 0:
                result.add_error(field, "Price cannot be negative", row_number, value)

            if field == "fx_rate" and decimal_value <= 0:
                result.add_error(field, "FX rate must be positive", row_number, value)

        except (InvalidOperation, ValueError) as e:
            result.add_error(field, f"Invalid numeric value: {value}", row_number, value)

        return result

    def _validate_transaction_type(self, value: Any, row_number: int) -> ValidationResult:
        """Validate transaction type."""
        result = ValidationResult(is_valid=True)

        if value is None:
            result.add_error("transaction_type", "Transaction type is required", row_number)
            return result

        normalized = str(value).lower().strip().replace(" ", "_")

        if normalized not in self.TRANSACTION_TYPE_MAPPINGS:
            result.add_error(
                "transaction_type",
                f"Unknown transaction type: {value}. Valid types: {', '.join(self.TRANSACTION_TYPE_MAPPINGS.keys())}",
                row_number,
                value
            )

        return result

    def _validate_asset_type(self, value: Any, row_number: int) -> ValidationResult:
        """Validate asset type."""
        result = ValidationResult(is_valid=True)

        normalized = str(value).lower().strip().replace(" ", "_")

        if normalized not in self.ASSET_TYPE_MAPPINGS:
            result.add_warning(
                "asset_type",
                f"Unknown asset type: {value}, defaulting to EQUITY",
                row_number,
                value
            )

        return result

    def _validate_currency(self, value: Any, row_number: int) -> ValidationResult:
        """Validate currency code."""
        result = ValidationResult(is_valid=True)

        if value is None:
            result.add_error("currency", "Currency is required", row_number)
            return result

        try:
            CurrencyCode.from_string(str(value))
        except ValueError:
            result.add_warning(
                "currency",
                f"Unknown currency code: {value}",
                row_number,
                value
            )

        return result

    def _validate_business_rules(self, row: Dict[str, Any], row_number: int) -> ValidationResult:
        """Validate business rules across fields."""
        result = ValidationResult(is_valid=True)

        # Settlement date should be >= transaction date
        if row.get("settlement_date") and row.get("transaction_date"):
            try:
                txn_date = parse_date(row["transaction_date"])
                settle_date = parse_date(row["settlement_date"])

                if settle_date < txn_date:
                    result.add_warning(
                        "settlement_date",
                        "Settlement date is before transaction date",
                        row_number
                    )
            except Exception:
                pass  # Date parsing errors handled elsewhere

        # Options should have strike price and expiry
        txn_type = str(row.get("transaction_type", "")).lower()
        if "option" in txn_type:
            if not row.get("strike_price"):
                result.add_warning("strike_price", "Option transaction missing strike price", row_number)
            if not row.get("expiry_date"):
                result.add_warning("expiry_date", "Option transaction missing expiry date", row_number)

        return result

    def parse_transaction_type(self, value: str) -> TransactionType:
        """Parse transaction type string to enum."""
        normalized = str(value).lower().strip().replace(" ", "_")
        return self.TRANSACTION_TYPE_MAPPINGS.get(normalized, TransactionType.BUY)

    def parse_asset_type(self, value: str) -> AssetType:
        """Parse asset type string to enum."""
        normalized = str(value).lower().strip().replace(" ", "_")
        return self.ASSET_TYPE_MAPPINGS.get(normalized, AssetType.EQUITY)
