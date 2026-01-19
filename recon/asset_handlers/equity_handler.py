"""Handler for equity and ETF assets."""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Any, Optional

from models.transaction import Transaction
from models.lot import Lot
from models.enums import AssetType, TransactionType
from .base_handler import BaseAssetHandler, AssetValuation, AssetIncome


class EquityHandler(BaseAssetHandler):
    """
    Handler for equities, ETFs, mutual funds, and ADRs.

    Provides:
    - Standard valuation (quantity × price)
    - Dividend income calculation
    - Stock split adjustments
    - Cost basis tracking
    """

    @property
    def asset_types(self) -> List[str]:
        return ["EQUITY", "ETF", "MUTUAL_FUND", "ADR"]

    def calculate_valuation(
        self,
        lots: List[Lot],
        current_price: Decimal,
        valuation_date: date,
        fx_rate: Decimal = Decimal("1")
    ) -> AssetValuation:
        """Calculate equity valuation."""
        if not lots:
            return AssetValuation(
                symbol="UNKNOWN",
                valuation_date=valuation_date,
                quantity=Decimal("0"),
                price=current_price,
                market_value=Decimal("0"),
                cost_basis=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                currency="USD",
            )

        symbol = lots[0].symbol
        currency = lots[0].currency.value

        # Aggregate from lots
        total_quantity = sum(lot.remaining_quantity for lot in lots)
        total_cost_basis = sum(lot.remaining_cost_basis for lot in lots)

        # Market value in local currency
        market_value_local = total_quantity * current_price

        # Convert to base currency
        market_value = market_value_local * fx_rate
        cost_basis = total_cost_basis * lots[0].acquisition_fx_rate if lots else Decimal("0")

        unrealized_pnl = market_value - cost_basis

        return AssetValuation(
            symbol=symbol,
            valuation_date=valuation_date,
            quantity=total_quantity,
            price=current_price,
            market_value=market_value,
            cost_basis=cost_basis,
            unrealized_pnl=unrealized_pnl,
            currency=currency,
            additional_fields={
                "fx_rate": fx_rate,
                "market_value_local": market_value_local,
                "average_cost": total_cost_basis / total_quantity if total_quantity else Decimal("0"),
            }
        )

    def calculate_unrealized_pnl(
        self,
        lots: List[Lot],
        current_price: Decimal,
        fx_rate: Decimal = Decimal("1")
    ) -> Decimal:
        """Calculate unrealized P&L for equity position."""
        total_pnl = Decimal("0")

        for lot in lots:
            if lot.remaining_quantity <= 0:
                continue

            current_value = lot.remaining_quantity * current_price * fx_rate
            cost_basis = lot.remaining_cost_basis * lot.acquisition_fx_rate

            total_pnl += current_value - cost_basis

        return total_pnl

    def process_transaction(
        self,
        transaction: Transaction
    ) -> Dict[str, Any]:
        """Process equity transaction."""
        result = {
            "symbol": transaction.symbol,
            "transaction_type": transaction.transaction_type.name,
            "quantity": float(transaction.quantity),
            "price": float(transaction.price),
        }

        if transaction.is_buy:
            result["action"] = "add_lot"
            result["cost_basis"] = float(transaction.net_amount)

        elif transaction.is_sell:
            result["action"] = "dispose_fifo"
            result["proceeds"] = float(transaction.net_amount)

        elif transaction.transaction_type == TransactionType.DIVIDEND:
            result["action"] = "record_income"
            result["income_type"] = "dividend"
            result["amount"] = float(transaction.net_amount)

        elif transaction.transaction_type == TransactionType.STOCK_SPLIT:
            result["action"] = "adjust_lots"
            result["split_ratio"] = float(transaction.quantity)

        return result

    def calculate_dividend_income(
        self,
        lots: List[Lot],
        ex_date: date,
        dividend_per_share: Decimal,
        withholding_rate: Decimal = Decimal("0")
    ) -> Optional[AssetIncome]:
        """
        Calculate dividend income for position on ex-date.

        Args:
            lots: Position lots
            ex_date: Ex-dividend date
            dividend_per_share: Dividend amount per share
            withholding_rate: Withholding tax rate (0-1)

        Returns:
            AssetIncome if position exists
        """
        # Only count lots acquired before ex-date
        eligible_quantity = sum(
            lot.remaining_quantity
            for lot in lots
            if lot.acquisition_date < ex_date
        )

        if eligible_quantity <= 0:
            return None

        gross_amount = eligible_quantity * dividend_per_share
        withholding = gross_amount * withholding_rate

        return AssetIncome(
            symbol=lots[0].symbol if lots else "UNKNOWN",
            income_date=ex_date,
            income_type="dividend",
            gross_amount=gross_amount,
            withholding_tax=withholding,
            currency=lots[0].currency.value if lots else "USD",
        )

    def process_stock_split(
        self,
        lots: List[Lot],
        split_ratio: Decimal,
        split_date: date
    ) -> Dict[str, Any]:
        """
        Process stock split for all lots.

        For a 2:1 split (split_ratio=2), quantity doubles, price halves.

        Args:
            lots: Lots to adjust
            split_ratio: New shares per old share (e.g., 2 for 2:1 split)
            split_date: Date of split

        Returns:
            Summary of adjustments
        """
        adjusted_lots = []

        for lot in lots:
            old_qty = lot.remaining_quantity
            old_price = lot.acquisition_price

            # Adjust quantities and prices
            lot.remaining_quantity = old_qty * split_ratio
            lot.acquisition_quantity = lot.acquisition_quantity * split_ratio
            lot.acquisition_price = old_price / split_ratio
            # Cost basis stays the same

            adjusted_lots.append({
                "lot_id": str(lot.lot_id),
                "old_quantity": float(old_qty),
                "new_quantity": float(lot.remaining_quantity),
                "old_price": float(old_price),
                "new_price": float(lot.acquisition_price),
            })

        return {
            "action": "stock_split",
            "split_ratio": float(split_ratio),
            "split_date": split_date.isoformat(),
            "lots_adjusted": len(adjusted_lots),
            "details": adjusted_lots,
        }

    def calculate_tax_lots(
        self,
        lots: List[Lot],
        current_price: Decimal,
        as_of_date: date = None
    ) -> List[Dict]:
        """
        Generate tax lot report for position.

        Args:
            lots: Position lots
            current_price: Current market price
            as_of_date: Reference date for holding period

        Returns:
            List of tax lot details
        """
        as_of = as_of_date or date.today()
        report = []

        for lot in lots:
            if lot.remaining_quantity <= 0:
                continue

            current_value = lot.remaining_quantity * current_price
            unrealized_gain = current_value - lot.remaining_cost_basis
            holding_days = (as_of - lot.acquisition_date).days

            report.append({
                "lot_id": str(lot.lot_id),
                "acquisition_date": lot.acquisition_date.isoformat(),
                "quantity": float(lot.remaining_quantity),
                "cost_per_share": float(lot.cost_per_unit),
                "cost_basis": float(lot.remaining_cost_basis),
                "current_price": float(current_price),
                "current_value": float(current_value),
                "unrealized_gain": float(unrealized_gain),
                "holding_days": holding_days,
                "holding_period": "Long-term" if holding_days > 365 else "Short-term",
                "gain_type": "gain" if unrealized_gain > 0 else "loss",
            })

        return sorted(report, key=lambda x: x["acquisition_date"])
