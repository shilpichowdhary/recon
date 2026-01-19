"""Tests for data loaders."""

import pytest
import tempfile
from pathlib import Path
from decimal import Decimal

from loaders.validators import DataValidator, ValidationResult
from loaders.csv_loader import CSVLoader


class TestDataValidator:
    """Tests for data validator."""

    def test_validate_schema_success(self):
        """Test schema validation with all required fields."""
        validator = DataValidator()
        columns = {
            "transaction_date", "transaction_type", "symbol",
            "quantity", "price", "currency"
        }

        result = validator.validate_schema(columns)

        assert result.is_valid
        assert result.errors_count == 0

    def test_validate_schema_missing_fields(self):
        """Test schema validation fails with missing fields."""
        validator = DataValidator()
        columns = {"transaction_date", "symbol", "quantity"}

        result = validator.validate_schema(columns)

        assert not result.is_valid
        assert result.errors_count > 0

    def test_validate_transaction_row(self):
        """Test row validation with valid data."""
        validator = DataValidator()
        row = {
            "transaction_date": "2024-01-15",
            "transaction_type": "BUY",
            "symbol": "AAPL",
            "quantity": "100",
            "price": "150.00",
            "currency": "USD",
        }

        result = validator.validate_transaction_row(row, 1)

        assert result.is_valid

    def test_validate_invalid_date(self):
        """Test validation catches invalid date."""
        validator = DataValidator()
        row = {
            "transaction_date": "invalid-date",
            "transaction_type": "BUY",
            "symbol": "AAPL",
            "quantity": "100",
            "price": "150.00",
            "currency": "USD",
        }

        result = validator.validate_transaction_row(row, 1)

        assert not result.is_valid

    def test_validate_invalid_numeric(self):
        """Test validation catches invalid numeric values."""
        validator = DataValidator()
        row = {
            "transaction_date": "2024-01-15",
            "transaction_type": "BUY",
            "symbol": "AAPL",
            "quantity": "not-a-number",
            "price": "150.00",
            "currency": "USD",
        }

        result = validator.validate_transaction_row(row, 1)

        assert not result.is_valid

    def test_validate_unknown_transaction_type(self):
        """Test validation catches unknown transaction type."""
        validator = DataValidator()
        row = {
            "transaction_date": "2024-01-15",
            "transaction_type": "UNKNOWN_TYPE",
            "symbol": "AAPL",
            "quantity": "100",
            "price": "150.00",
            "currency": "USD",
        }

        result = validator.validate_transaction_row(row, 1)

        assert not result.is_valid

    def test_parse_transaction_type(self):
        """Test transaction type parsing."""
        validator = DataValidator()

        from models.enums import TransactionType

        assert validator.parse_transaction_type("buy") == TransactionType.BUY
        assert validator.parse_transaction_type("SELL") == TransactionType.SELL
        assert validator.parse_transaction_type("dividend") == TransactionType.DIVIDEND

    def test_parse_asset_type(self):
        """Test asset type parsing."""
        validator = DataValidator()

        from models.enums import AssetType

        assert validator.parse_asset_type("equity") == AssetType.EQUITY
        assert validator.parse_asset_type("ETF") == AssetType.ETF
        assert validator.parse_asset_type("bond") == AssetType.CORPORATE_BOND


class TestCSVLoader:
    """Tests for CSV loader."""

    def test_load_valid_csv(self):
        """Test loading valid CSV file."""
        csv_content = """transaction_date,settlement_date,transaction_type,asset_type,symbol,quantity,price,currency,commission
2024-01-15,2024-01-17,BUY,EQUITY,AAPL,100,150.00,USD,5.00
2024-02-01,2024-02-03,SELL,EQUITY,AAPL,50,160.00,USD,5.00
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            loader = CSVLoader()
            transactions, result = loader.load(csv_path)

            assert result.is_valid
            assert len(transactions) == 2
            assert transactions[0].symbol == "AAPL"
            assert transactions[0].quantity == Decimal("100")
        finally:
            csv_path.unlink()

    def test_load_missing_file(self):
        """Test loading non-existent file."""
        loader = CSVLoader()
        transactions, result = loader.load("/nonexistent/path.csv")

        assert not result.is_valid
        assert len(transactions) == 0

    def test_load_with_fees(self):
        """Test loading CSV with fee columns."""
        csv_content = """transaction_date,transaction_type,symbol,quantity,price,currency,commission,fees,taxes
2024-01-15,BUY,AAPL,100,150.00,USD,5.00,2.00,1.00
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            loader = CSVLoader()
            transactions, result = loader.load(csv_path)

            assert len(transactions) == 1
            txn = transactions[0]
            assert txn.commission == Decimal("5.00")
            assert txn.fees == Decimal("2.00")
            assert txn.taxes == Decimal("1.00")
            assert txn.total_fees == Decimal("8.00")
        finally:
            csv_path.unlink()

    def test_get_summary(self):
        """Test loader summary statistics."""
        csv_content = """transaction_date,transaction_type,symbol,quantity,price,currency
2024-01-15,BUY,AAPL,100,150.00,USD
2024-01-20,BUY,GOOGL,50,140.00,USD
2024-02-01,SELL,AAPL,50,160.00,USD
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            loader = CSVLoader()
            loader.load(csv_path)
            summary = loader.get_summary()

            assert summary["loaded"]
            assert summary["count"] == 3
            assert summary["unique_symbols"] == 2
            assert "AAPL" in summary["symbols"]
            assert "GOOGL" in summary["symbols"]
        finally:
            csv_path.unlink()
