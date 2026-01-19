"""Tests for data models."""

import pytest
from datetime import date
from decimal import Decimal

from models.enums import TransactionType, AssetType, CurrencyCode
from models.transaction import Transaction
from models.lot import Lot, LotQueue
from models.performance import ReconciliationResult, ReconciliationStatus


class TestEnums:
    """Tests for enumeration types."""

    def test_transaction_type_is_buy(self):
        """Test is_buy classification."""
        assert TransactionType.is_buy(TransactionType.BUY)
        assert TransactionType.is_buy(TransactionType.DEPOSIT)
        assert not TransactionType.is_buy(TransactionType.SELL)

    def test_transaction_type_is_sell(self):
        """Test is_sell classification."""
        assert TransactionType.is_sell(TransactionType.SELL)
        assert TransactionType.is_sell(TransactionType.WITHDRAWAL)
        assert not TransactionType.is_sell(TransactionType.BUY)

    def test_transaction_type_is_income(self):
        """Test is_income classification."""
        assert TransactionType.is_income(TransactionType.DIVIDEND)
        assert TransactionType.is_income(TransactionType.INTEREST)
        assert TransactionType.is_income(TransactionType.COUPON)
        assert not TransactionType.is_income(TransactionType.BUY)

    def test_asset_type_is_equity(self):
        """Test is_equity classification."""
        assert AssetType.is_equity(AssetType.EQUITY)
        assert AssetType.is_equity(AssetType.ETF)
        assert not AssetType.is_equity(AssetType.CORPORATE_BOND)

    def test_asset_type_is_fixed_income(self):
        """Test is_fixed_income classification."""
        assert AssetType.is_fixed_income(AssetType.CORPORATE_BOND)
        assert AssetType.is_fixed_income(AssetType.GOVERNMENT_BOND)
        assert not AssetType.is_fixed_income(AssetType.EQUITY)

    def test_asset_type_is_option(self):
        """Test is_option classification."""
        assert AssetType.is_option(AssetType.CALL_OPTION)
        assert AssetType.is_option(AssetType.PUT_OPTION)
        assert not AssetType.is_option(AssetType.EQUITY)

    def test_currency_from_string(self):
        """Test currency code parsing."""
        assert CurrencyCode.from_string("USD") == CurrencyCode.USD
        assert CurrencyCode.from_string("usd") == CurrencyCode.USD
        assert CurrencyCode.from_string("EUR") == CurrencyCode.EUR


class TestTransaction:
    """Tests for Transaction model."""

    def test_transaction_creation(self):
        """Test basic transaction creation."""
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

        assert txn.symbol == "AAPL"
        assert txn.quantity == Decimal("100")
        assert txn.is_buy
        assert not txn.is_sell

    def test_gross_amount_calculation(self):
        """Test automatic gross amount calculation."""
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

        assert txn.gross_amount == Decimal("15000.00")

    def test_net_amount_with_fees(self):
        """Test net amount includes fees."""
        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 17),
            transaction_type=TransactionType.BUY,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            currency=CurrencyCode.USD,
            commission=Decimal("5.00"),
            fees=Decimal("2.00"),
        )

        # Buy: net = gross + fees
        assert txn.net_amount == Decimal("15007.00")

    def test_sell_net_amount(self):
        """Test sell net amount subtracts fees."""
        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 17),
            transaction_type=TransactionType.SELL,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            currency=CurrencyCode.USD,
            commission=Decimal("5.00"),
        )

        # Sell: net = gross - fees
        assert txn.net_amount == Decimal("14995.00")

    def test_to_cash_flow(self):
        """Test cash flow conversion."""
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

        # Buys are negative cash flows
        assert buy_txn.to_cash_flow() < Decimal("0")

        sell_txn = Transaction(
            transaction_date=date(2024, 1, 15),
            settlement_date=date(2024, 1, 17),
            transaction_type=TransactionType.SELL,
            asset_type=AssetType.EQUITY,
            symbol="AAPL",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            currency=CurrencyCode.USD,
        )

        # Sells are positive cash flows
        assert sell_txn.to_cash_flow() > Decimal("0")


class TestLot:
    """Tests for Lot model."""

    def test_lot_creation(self):
        """Test basic lot creation."""
        lot = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 1, 15),
            acquisition_price=Decimal("150.00"),
            acquisition_quantity=Decimal("100"),
            acquisition_cost=Decimal("15005.00"),
            currency=CurrencyCode.USD,
        )

        assert lot.symbol == "AAPL"
        assert lot.remaining_quantity == Decimal("100")

    def test_cost_per_unit(self):
        """Test cost per unit calculation."""
        lot = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 1, 15),
            acquisition_price=Decimal("150.00"),
            acquisition_quantity=Decimal("100"),
            acquisition_cost=Decimal("15050.00"),  # Including fees
            currency=CurrencyCode.USD,
        )

        # Cost per unit = 15050 / 100 = 150.50
        assert lot.cost_per_unit == Decimal("150.50")

    def test_dispose(self):
        """Test lot disposal."""
        lot = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 1, 15),
            acquisition_price=Decimal("150.00"),
            acquisition_quantity=Decimal("100"),
            acquisition_cost=Decimal("15000.00"),
            currency=CurrencyCode.USD,
        )

        qty_disposed, realized_pnl = lot.dispose(
            quantity=Decimal("50"),
            sale_price=Decimal("160.00"),
            sale_date=date(2024, 3, 1),
        )

        assert qty_disposed == Decimal("50")
        # P&L = 50 * (160 - 150) = 500
        assert realized_pnl == Decimal("500")
        assert lot.remaining_quantity == Decimal("50")

    def test_unrealized_pnl(self):
        """Test unrealized P&L calculation."""
        lot = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 1, 15),
            acquisition_price=Decimal("150.00"),
            acquisition_quantity=Decimal("100"),
            acquisition_cost=Decimal("15000.00"),
            currency=CurrencyCode.USD,
        )

        unrealized = lot.calculate_unrealized_pnl(Decimal("160.00"))

        # Unrealized = 100 * (160 - 150) = 1000
        assert unrealized == Decimal("1000")

    def test_is_depleted(self):
        """Test is_depleted property."""
        lot = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 1, 15),
            acquisition_price=Decimal("150.00"),
            acquisition_quantity=Decimal("100"),
            acquisition_cost=Decimal("15000.00"),
            currency=CurrencyCode.USD,
        )

        assert not lot.is_depleted

        lot.dispose(Decimal("100"), Decimal("160.00"), date(2024, 3, 1))

        assert lot.is_depleted


class TestLotQueue:
    """Tests for LotQueue FIFO management."""

    def test_add_lot(self):
        """Test adding lots to queue."""
        queue = LotQueue("AAPL")

        lot = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 1, 15),
            acquisition_price=Decimal("150.00"),
            acquisition_quantity=Decimal("100"),
            acquisition_cost=Decimal("15000.00"),
            currency=CurrencyCode.USD,
        )

        queue.add_lot(lot)

        assert queue.total_quantity == Decimal("100")
        assert len(queue) == 1

    def test_fifo_disposal(self):
        """Test FIFO disposal order."""
        queue = LotQueue("AAPL")

        # Add first lot @ $150
        lot1 = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 1, 1),
            acquisition_price=Decimal("150.00"),
            acquisition_quantity=Decimal("100"),
            acquisition_cost=Decimal("15000.00"),
            currency=CurrencyCode.USD,
        )
        queue.add_lot(lot1)

        # Add second lot @ $160
        lot2 = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 2, 1),
            acquisition_price=Decimal("160.00"),
            acquisition_quantity=Decimal("50"),
            acquisition_cost=Decimal("8000.00"),
            currency=CurrencyCode.USD,
        )
        queue.add_lot(lot2)

        # Dispose 75 shares @ $170 (FIFO: use first lot first)
        realized = queue.dispose_fifo(
            Decimal("75"),
            Decimal("170.00"),
            date(2024, 3, 1)
        )

        # First 75 from lot1 @ $150: gain = 75 * (170 - 150) = 1500
        assert realized == Decimal("1500")

        # 25 remaining in lot1, 50 in lot2
        assert queue.total_quantity == Decimal("75")

    def test_average_cost(self):
        """Test weighted average cost calculation."""
        queue = LotQueue("AAPL")

        lot1 = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 1, 1),
            acquisition_price=Decimal("150.00"),
            acquisition_quantity=Decimal("100"),
            acquisition_cost=Decimal("15000.00"),
            currency=CurrencyCode.USD,
        )
        queue.add_lot(lot1)

        lot2 = Lot(
            symbol="AAPL",
            asset_type=AssetType.EQUITY,
            acquisition_date=date(2024, 2, 1),
            acquisition_price=Decimal("160.00"),
            acquisition_quantity=Decimal("100"),
            acquisition_cost=Decimal("16000.00"),
            currency=CurrencyCode.USD,
        )
        queue.add_lot(lot2)

        # Average cost = (15000 + 16000) / 200 = 155
        assert queue.average_cost == Decimal("155")


class TestReconciliationResult:
    """Tests for reconciliation result model."""

    def test_pass_within_tolerance(self):
        """Test result passes when within tolerance."""
        result = ReconciliationResult(
            metric_name="IRR",
            calculated_value=Decimal("0.1001"),
            expected_value=Decimal("0.1000"),
            tolerance=Decimal("0.0001"),
        )

        assert result.is_pass
        assert result.status == ReconciliationStatus.PASS

    def test_fail_outside_tolerance(self):
        """Test result fails when outside tolerance."""
        result = ReconciliationResult(
            metric_name="IRR",
            calculated_value=Decimal("0.1010"),
            expected_value=Decimal("0.1000"),
            tolerance=Decimal("0.0001"),
        )

        assert not result.is_pass
        assert result.status == ReconciliationStatus.FAIL

    def test_difference_calculation(self):
        """Test difference is calculated correctly."""
        result = ReconciliationResult(
            metric_name="P&L",
            calculated_value=Decimal("1005.00"),
            expected_value=Decimal("1000.00"),
            tolerance=Decimal("1.00"),
        )

        assert result.difference == Decimal("5.00")
