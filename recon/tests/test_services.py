"""Tests for services."""

import pytest
from datetime import date
from decimal import Decimal

from models.transaction import Transaction
from models.enums import TransactionType, AssetType, CurrencyCode
from services.data_quality_service import DataQualityService
from services.lot_tracking_service import LotTrackingService


class TestDataQualityService:
    """Tests for data quality service."""

    def test_validate_empty_transactions(self):
        """Test validation with empty transaction list."""
        service = DataQualityService()
        report = service.validate_transactions([])

        assert report.total_records == 0
        assert report.warning_count > 0  # Warning about no transactions

    def test_validate_valid_transactions(self):
        """Test validation with valid transactions."""
        transactions = [
            Transaction(
                transaction_date=date(2024, 1, 15),
                settlement_date=date(2024, 1, 17),
                transaction_type=TransactionType.BUY,
                asset_type=AssetType.EQUITY,
                symbol="AAPL",
                quantity=Decimal("100"),
                price=Decimal("150.00"),
                currency=CurrencyCode.USD,
            ),
        ]

        service = DataQualityService()
        report = service.validate_transactions(transactions)

        assert report.total_records == 1
        # Should have no critical issues for valid data
        assert not report.has_critical_issues

    def test_detect_negative_position(self):
        """Test detection of negative position (short sell without long)."""
        transactions = [
            Transaction(
                transaction_date=date(2024, 1, 15),
                settlement_date=date(2024, 1, 17),
                transaction_type=TransactionType.SELL,
                asset_type=AssetType.EQUITY,
                symbol="AAPL",
                quantity=Decimal("100"),
                price=Decimal("150.00"),
                currency=CurrencyCode.USD,
            ),
        ]

        service = DataQualityService()
        report = service.validate_transactions(transactions)

        # Should detect selling without owning
        assert report.has_critical_issues

    def test_detect_duplicate_transactions(self):
        """Test detection of potential duplicate transactions."""
        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 17),
            transaction_type=TransactionType.BUY,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            currency=CurrencyCode.USD,
        )

        # Same transaction twice
        transactions = [txn, txn]

        service = DataQualityService()
        report = service.validate_transactions(transactions)

        # Should detect duplicates (warning level)
        assert report.warning_count > 0


class TestLotTrackingService:
    """Tests for lot tracking service."""

    def test_process_buy_creates_lot(self):
        """Test that buy transaction creates a lot."""
        service = LotTrackingService()

        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 17),
            transaction_type=TransactionType.BUY,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            currency=CurrencyCode.USD,
        )

        result = service.process_transaction(txn)

        assert result["action"] == "lot_created"
        assert result["symbol"] == "AAPL"

        summary = service.get_position_summary("AAPL")
        assert summary is not None
        assert summary["total_quantity"] == 100

    def test_process_sell_disposes_lots(self):
        """Test that sell transaction disposes lots using FIFO."""
        service = LotTrackingService()

        # Buy first
        buy_txn = Transaction(
            transaction_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 17),
            transaction_type=TransactionType.BUY,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            currency=CurrencyCode.USD,
        )
        service.process_transaction(buy_txn)

        # Then sell
        sell_txn = Transaction(
            transaction_date=date(2024, 2, 15),
            settlement_date=date(2024, 2, 17),
            transaction_type=TransactionType.SELL,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("50"),
            price=Decimal("160.00"),
            currency=CurrencyCode.USD,
        )
        result = service.process_transaction(sell_txn)

        assert result["action"] == "lots_disposed"
        assert result["quantity_sold"] == 50
        assert result["remaining_quantity"] == 50

    def test_calculate_unrealized_pnl(self):
        """Test unrealized P&L calculation."""
        service = LotTrackingService()

        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 17),
            transaction_type=TransactionType.BUY,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            currency=CurrencyCode.USD,
        )
        service.process_transaction(txn)

        unrealized = service.calculate_unrealized_pnl("AAPL", Decimal("160.00"))

        # 100 * (160 - 150) = 1000
        assert unrealized == Decimal("1000")

    def test_get_tax_lot_report(self):
        """Test tax lot report generation."""
        service = LotTrackingService()

        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 17),
            transaction_type=TransactionType.BUY,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            currency=CurrencyCode.USD,
        )
        service.process_transaction(txn)

        report = service.get_tax_lot_report()

        assert len(report) == 1
        assert report[0]["symbol"] == "AAPL"
        assert report[0]["quantity"] == 100
        assert "holding_period" in report[0]

    def test_get_all_positions(self):
        """Test getting all positions."""
        service = LotTrackingService()

        for symbol, price in [("AAPL", 150), ("GOOGL", 140), ("MSFT", 380)]:
            txn = Transaction(
                transaction_date=date(2024, 1, 15),
                settlement_date=date(2024, 1, 17),
                transaction_type=TransactionType.BUY,
                asset_type=AssetType.EQUITY,
                symbol=symbol,
                quantity=Decimal("100"),
                price=Decimal(str(price)),
                currency=CurrencyCode.USD,
            )
            service.process_transaction(txn)

        positions = service.get_all_positions()

        assert len(positions) == 3
        assert "AAPL" in positions
        assert "GOOGL" in positions
        assert "MSFT" in positions
