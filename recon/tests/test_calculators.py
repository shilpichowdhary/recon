"""Tests for calculator modules."""

import pytest
from datetime import date
from decimal import Decimal

from calculators.irr_calculator import IRRCalculator, CashFlow, calculate_xirr
from calculators.twr_calculator import TWRCalculator, DailyValue, calculate_twr
from calculators.pnl_calculator import PnLCalculator, calculate_fifo_pnl
from calculators.fx_converter import FXConverter

from models.transaction import Transaction
from models.enums import TransactionType, AssetType, CurrencyCode


class TestIRRCalculator:
    """Tests for IRR/XIRR calculator."""

    def test_simple_xirr(self):
        """Test XIRR with simple investment scenario."""
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("-10000")),
            CashFlow(date=date(2024, 12, 31), amount=Decimal("11000")),
        ]

        calculator = IRRCalculator()
        xirr = calculator.calculate_xirr(cash_flows)

        assert xirr is not None
        # 10% return over 1 year
        assert abs(xirr - Decimal("0.10")) < Decimal("0.01")

    def test_xirr_with_dividends(self):
        """Test XIRR with intermediate cash flows."""
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("-10000")),
            CashFlow(date=date(2024, 6, 1), amount=Decimal("250")),
            CashFlow(date=date(2024, 12, 1), amount=Decimal("250")),
            CashFlow(date=date(2024, 12, 31), amount=Decimal("10500")),
        ]

        calculator = IRRCalculator()
        xirr = calculator.calculate_xirr(cash_flows)

        assert xirr is not None
        assert xirr > Decimal("0.05")  # Should be positive return

    def test_xirr_negative_return(self):
        """Test XIRR with loss scenario."""
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("-10000")),
            CashFlow(date=date(2024, 12, 31), amount=Decimal("9000")),
        ]

        calculator = IRRCalculator()
        xirr = calculator.calculate_xirr(cash_flows)

        assert xirr is not None
        assert xirr < Decimal("0")  # Negative return

    def test_xirr_no_sign_change(self):
        """Test XIRR returns None when no sign change in cash flows."""
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("1000")),
            CashFlow(date=date(2024, 12, 31), amount=Decimal("500")),
        ]

        calculator = IRRCalculator()
        xirr = calculator.calculate_xirr(cash_flows)

        assert xirr is None

    def test_calculate_npv(self):
        """Test NPV calculation."""
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("-10000")),
            CashFlow(date=date(2025, 1, 1), amount=Decimal("11000")),
        ]

        calculator = IRRCalculator()
        npv = calculator.calculate_npv(cash_flows, Decimal("0.05"))

        # NPV at 5% discount rate should be positive
        assert npv > Decimal("0")

    def test_convenience_function(self):
        """Test calculate_xirr convenience function."""
        dates = [date(2024, 1, 1), date(2024, 12, 31)]
        amounts = [Decimal("-10000"), Decimal("11000")]

        xirr = calculate_xirr(dates, amounts)

        assert xirr is not None
        assert abs(xirr - Decimal("0.10")) < Decimal("0.01")


class TestTWRCalculator:
    """Tests for Time-Weighted Return calculator."""

    def test_simple_twr(self):
        """Test TWR without cash flows."""
        start_value = Decimal("10000")
        end_value = Decimal("11000")

        twr = calculate_twr(
            start_value=start_value,
            end_value=end_value,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )

        assert twr is not None
        assert abs(twr - Decimal("0.10")) < Decimal("0.001")

    def test_twr_with_cash_flow(self):
        """Test TWR with deposit during period."""
        start_value = Decimal("10000")
        end_value = Decimal("21500")

        # Deposit of $10000 mid-year
        cash_flows = [(date(2024, 7, 1), Decimal("10000"))]

        twr = calculate_twr(
            start_value=start_value,
            end_value=end_value,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            cash_flows=cash_flows,
        )

        assert twr is not None
        # TWR removes impact of cash flows

    def test_twr_from_daily_values(self):
        """Test TWR calculation from daily values."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("10000")),
            DailyValue(date=date(2024, 1, 2), value=Decimal("10100")),
            DailyValue(date=date(2024, 1, 3), value=Decimal("10050")),
            DailyValue(date=date(2024, 1, 4), value=Decimal("10200")),
        ]

        calculator = TWRCalculator()
        twr = calculator.calculate_twr(daily_values)

        assert twr is not None
        # Overall gain from 10000 to 10200 = 2%
        assert abs(twr - Decimal("0.02")) < Decimal("0.001")

    def test_annualized_twr(self):
        """Test annualized TWR calculation."""
        calculator = TWRCalculator()

        # 5% return over 6 months
        twr = Decimal("0.05")
        annualized = calculator.calculate_annualized_twr(
            twr,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 7, 1),
        )

        # Annualized should be approximately 10.25%
        assert annualized > Decimal("0.10")


class TestPnLCalculator:
    """Tests for P&L calculator with FIFO lot matching."""

    def test_single_buy_unrealized_pnl(self):
        """Test unrealized P&L with single buy."""
        transactions = [
            Transaction(
                transaction_date=date(2024, 1, 1),
                settlement_date=date(2024, 1, 3),
                transaction_type=TransactionType.BUY,
                asset_type=AssetType.EQUITY,
                symbol="AAPL",
                quantity=Decimal("100"),
                price=Decimal("150.00"),
                currency=CurrencyCode.USD,
            ),
        ]

        current_prices = {"AAPL": Decimal("160.00")}

        pnl = calculate_fifo_pnl(transactions, current_prices)

        assert "AAPL" in pnl.positions
        position = pnl.positions["AAPL"]

        # Unrealized P&L = 100 * (160 - 150) = 1000
        assert position.unrealized_pnl == Decimal("1000")
        assert position.realized_pnl == Decimal("0")

    def test_fifo_matching(self):
        """Test FIFO lot matching on sales."""
        transactions = [
            # Buy 100 @ $150
            Transaction(
                transaction_date=date(2024, 1, 1),
                settlement_date=date(2024, 1, 3),
                transaction_type=TransactionType.BUY,
                asset_type=AssetType.EQUITY,
                symbol="AAPL",
                quantity=Decimal("100"),
                price=Decimal("150.00"),
                currency=CurrencyCode.USD,
            ),
            # Buy 50 @ $160
            Transaction(
                transaction_date=date(2024, 2, 1),
                settlement_date=date(2024, 2, 3),
                transaction_type=TransactionType.BUY,
                asset_type=AssetType.EQUITY,
                symbol="AAPL",
                quantity=Decimal("50"),
                price=Decimal("160.00"),
                currency=CurrencyCode.USD,
            ),
            # Sell 75 @ $170 (should use first lot @ $150)
            Transaction(
                transaction_date=date(2024, 3, 1),
                settlement_date=date(2024, 3, 3),
                transaction_type=TransactionType.SELL,
                asset_type=AssetType.EQUITY,
                symbol="AAPL",
                quantity=Decimal("75"),
                price=Decimal("170.00"),
                currency=CurrencyCode.USD,
            ),
        ]

        calculator = PnLCalculator()
        calculator.process_transactions(transactions)
        pnl = calculator.calculate_unrealized_pnl({"AAPL": Decimal("175.00")})

        position = pnl.positions["AAPL"]

        # Realized P&L = 75 * (170 - 150) = 1500
        assert position.realized_pnl == Decimal("1500")

        # Remaining: 25 @ $150 + 50 @ $160 = 75 shares
        assert position.quantity == Decimal("75")

    def test_dividend_income(self):
        """Test dividend income tracking."""
        transactions = [
            Transaction(
                transaction_date=date(2024, 1, 1),
                settlement_date=date(2024, 1, 3),
                transaction_type=TransactionType.BUY,
                asset_type=AssetType.EQUITY,
                symbol="AAPL",
                quantity=Decimal("100"),
                price=Decimal("150.00"),
                currency=CurrencyCode.USD,
            ),
            Transaction(
                transaction_date=date(2024, 3, 15),
                settlement_date=date(2024, 3, 15),
                transaction_type=TransactionType.DIVIDEND,
                asset_type=AssetType.EQUITY,
                symbol="AAPL",
                quantity=Decimal("100"),
                price=Decimal("0.24"),
                currency=CurrencyCode.USD,
            ),
        ]

        calculator = PnLCalculator()
        pnl = calculator.process_transactions(transactions)

        # Dividend = 100 * 0.24 = 24
        assert pnl.dividend_income == Decimal("24.00")


class TestFXConverter:
    """Tests for FX converter."""

    def test_set_and_get_rate(self):
        """Test setting and getting FX rate."""
        converter = FXConverter(base_currency="USD")
        converter.set_rate("EUR", date(2024, 1, 1), Decimal("0.92"))

        rate = converter.get_rate("EUR", date(2024, 1, 1))
        assert rate == Decimal("0.92")

    def test_same_currency(self):
        """Test conversion with same currency returns amount unchanged."""
        converter = FXConverter(base_currency="USD")

        result = converter.convert(
            Decimal("100"),
            "USD",
            "USD",
            date(2024, 1, 1)
        )

        assert result == Decimal("100")

    def test_convert_to_base(self):
        """Test conversion to base currency."""
        converter = FXConverter(base_currency="USD")
        converter.set_rate("EUR", date(2024, 1, 1), Decimal("0.92"))

        result = converter.convert_to_base(
            Decimal("100"),
            "EUR",
            date(2024, 1, 1)
        )

        # 100 EUR / 0.92 = ~108.70 USD
        assert result is not None
        assert result > Decimal("100")

    def test_fallback_to_previous_day(self):
        """Test rate lookup falls back to previous day."""
        converter = FXConverter(base_currency="USD")
        converter.set_rate("EUR", date(2024, 1, 1), Decimal("0.92"))

        # Query for Jan 2 should fall back to Jan 1
        rate = converter.get_rate("EUR", date(2024, 1, 2), fallback_to_previous=True)

        assert rate == Decimal("0.92")

    def test_cross_rate(self):
        """Test cross rate calculation."""
        converter = FXConverter(base_currency="USD")
        converter.set_rate("EUR", date(2024, 1, 1), Decimal("0.92"))
        converter.set_rate("GBP", date(2024, 1, 1), Decimal("0.79"))

        cross_rate = converter.get_cross_rate("EUR", "GBP", date(2024, 1, 1))

        # GBP/EUR = 0.79 / 0.92 ≈ 0.859
        assert cross_rate is not None
        assert abs(cross_rate - Decimal("0.859")) < Decimal("0.01")
