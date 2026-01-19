"""Pytest configuration and fixtures."""

import pytest
from datetime import date
from decimal import Decimal
from pathlib import Path

from models.transaction import Transaction
from models.lot import Lot, LotQueue
from models.enums import TransactionType, AssetType, CurrencyCode


@pytest.fixture
def sample_transactions():
    """Create sample transactions for testing."""
    return [
        Transaction(
            transaction_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 17),
            transaction_type=TransactionType.BUY,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            currency=CurrencyCode.USD,
            commission=Decimal("5.00"),
        ),
        Transaction(
            transaction_date=date(2024, 2, 1),
            settlement_date=date(2024, 2, 3),
            transaction_type=TransactionType.BUY,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("50"),
            price=Decimal("155.00"),
            currency=CurrencyCode.USD,
            commission=Decimal("5.00"),
        ),
        Transaction(
            transaction_date=date(2024, 3, 1),
            settlement_date=date(2024, 3, 3),
            transaction_type=TransactionType.SELL,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("75"),
            price=Decimal("160.00"),
            currency=CurrencyCode.USD,
            commission=Decimal("5.00"),
        ),
        Transaction(
            transaction_date=date(2024, 3, 15),
            settlement_date=date(2024, 3, 15),
            transaction_type=TransactionType.DIVIDEND,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("75"),
            price=Decimal("0.24"),
            currency=CurrencyCode.USD,
        ),
    ]


@pytest.fixture
def sample_lot():
    """Create a sample lot for testing."""
    return Lot(
        symbol="AAPL",
        asset_type=AssetType.EQUITY,
        acquisition_date=date(2024, 1, 15),
        acquisition_price=Decimal("150.00"),
        acquisition_quantity=Decimal("100"),
        acquisition_cost=Decimal("15005.00"),
        currency=CurrencyCode.USD,
        allocated_fees=Decimal("5.00"),
    )


@pytest.fixture
def sample_lot_queue(sample_lot):
    """Create a sample lot queue for testing."""
    queue = LotQueue("AAPL")
    queue.add_lot(sample_lot)
    return queue


@pytest.fixture
def sample_cash_flows():
    """Create sample cash flows for IRR testing."""
    from calculators.irr_calculator import CashFlow
    return [
        CashFlow(date=date(2024, 1, 1), amount=Decimal("-10000")),  # Initial investment
        CashFlow(date=date(2024, 6, 1), amount=Decimal("500")),     # Dividend
        CashFlow(date=date(2024, 12, 31), amount=Decimal("11000")), # Final value
    ]


@pytest.fixture
def test_data_dir():
    """Get path to test data directory."""
    return Path(__file__).parent / "test_data"


@pytest.fixture
def sample_csv_content():
    """Sample CSV content for testing."""
    return """transaction_date,settlement_date,transaction_type,asset_type,symbol,quantity,price,currency,commission
2024-01-15,2024-01-17,BUY,EQUITY,AAPL,100,150.00,USD,5.00
2024-02-01,2024-02-03,BUY,EQUITY,AAPL,50,155.00,USD,5.00
2024-03-01,2024-03-03,SELL,EQUITY,AAPL,75,160.00,USD,5.00
2024-03-15,2024-03-15,DIVIDEND,EQUITY,AAPL,75,0.24,USD,0
"""


@pytest.fixture
def current_prices():
    """Sample current prices for testing."""
    return {
        "AAPL": Decimal("165.00"),
        "GOOGL": Decimal("140.00"),
        "MSFT": Decimal("380.00"),
    }
