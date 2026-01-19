"""P&L Calculator with FIFO lot matching."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from models.transaction import Transaction
from models.lot import Lot, LotQueue
from models.enums import TransactionType, AssetType


@dataclass
class PositionPnL:
    """P&L breakdown for a single position."""
    symbol: str
    quantity: Decimal = Decimal("0")
    cost_basis: Decimal = Decimal("0")
    market_value: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    average_cost: Decimal = Decimal("0")
    current_price: Decimal = Decimal("0")
    lots: List[Lot] = field(default_factory=list)

    def __post_init__(self):
        """Calculate totals."""
        self.total_pnl = self.realized_pnl + self.unrealized_pnl


@dataclass
class PortfolioPnL:
    """Aggregate P&L for entire portfolio."""
    positions: Dict[str, PositionPnL] = field(default_factory=dict)
    total_realized_pnl: Decimal = Decimal("0")
    total_unrealized_pnl: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    total_cost_basis: Decimal = Decimal("0")
    total_market_value: Decimal = Decimal("0")
    dividend_income: Decimal = Decimal("0")
    interest_income: Decimal = Decimal("0")

    def add_position(self, position: PositionPnL) -> None:
        """Add a position and update totals."""
        self.positions[position.symbol] = position
        self.total_realized_pnl += position.realized_pnl
        self.total_unrealized_pnl += position.unrealized_pnl
        self.total_cost_basis += position.cost_basis
        self.total_market_value += position.market_value

    def finalize(self) -> None:
        """Calculate final totals."""
        self.total_pnl = (
            self.total_realized_pnl +
            self.total_unrealized_pnl +
            self.dividend_income +
            self.interest_income
        )


class PnLCalculator:
    """
    Calculate P&L using FIFO (First In, First Out) lot matching.

    Maintains lot queues per security and tracks:
    - Realized P&L on sales (matched against oldest lots first)
    - Unrealized P&L from remaining lots
    - Dividend and interest income
    """

    def __init__(self):
        """Initialize P&L calculator."""
        self._lot_queues: Dict[str, LotQueue] = {}
        self._income: Dict[str, Decimal] = defaultdict(Decimal)
        self._transactions: List[Transaction] = []

    def process_transactions(
        self,
        transactions: List[Transaction]
    ) -> PortfolioPnL:
        """
        Process all transactions and calculate P&L.

        Args:
            transactions: List of transactions sorted by date

        Returns:
            PortfolioPnL with all positions
        """
        # Sort transactions by date
        sorted_txns = sorted(transactions, key=lambda t: t.transaction_date)
        self._transactions = sorted_txns

        # Process each transaction
        for txn in sorted_txns:
            self._process_transaction(txn)

        # Build portfolio P&L (without prices - will be set later)
        return self._build_portfolio_pnl()

    def _process_transaction(self, txn: Transaction) -> None:
        """Process a single transaction."""
        symbol = txn.symbol

        # Initialize lot queue if needed
        if symbol not in self._lot_queues:
            self._lot_queues[symbol] = LotQueue(symbol)

        # Handle by transaction type
        if txn.is_buy:
            self._process_buy(txn)
        elif txn.is_sell:
            self._process_sell(txn)
        elif TransactionType.is_income(txn.transaction_type):
            self._process_income(txn)

    def _process_buy(self, txn: Transaction) -> None:
        """Process a buy transaction - create new lot."""
        lot = Lot(
            symbol=txn.symbol,
            asset_type=txn.asset_type,
            acquisition_date=txn.transaction_date,
            acquisition_price=txn.price,
            acquisition_quantity=txn.quantity,
            acquisition_cost=txn.net_amount,
            acquisition_fx_rate=txn.fx_rate,
            currency=txn.currency,
            allocated_fees=txn.total_fees,
            transaction_id=txn.transaction_id,
        )

        # Add option-specific fields
        if AssetType.is_option(txn.asset_type):
            lot.underlying_symbol = txn.underlying_symbol
            lot.strike_price = txn.strike_price
            lot.expiry_date = txn.expiry_date

        # Add bond-specific fields
        if AssetType.is_fixed_income(txn.asset_type):
            lot.face_value = txn.face_value
            lot.coupon_rate = txn.coupon_rate
            lot.maturity_date = txn.maturity_date

        self._lot_queues[txn.symbol].add_lot(lot)

    def _process_sell(self, txn: Transaction) -> None:
        """Process a sell transaction - dispose lots using FIFO."""
        queue = self._lot_queues.get(txn.symbol)
        if not queue:
            return

        # Dispose using FIFO
        queue.dispose_fifo(
            quantity=txn.quantity,
            sale_price=txn.price,
            sale_date=txn.transaction_date,
            sale_fx_rate=txn.fx_rate
        )

    def _process_income(self, txn: Transaction) -> None:
        """Process income transaction (dividend, interest, coupon)."""
        if txn.transaction_type == TransactionType.DIVIDEND:
            self._income["dividend"] += txn.net_amount
        elif txn.transaction_type in {TransactionType.INTEREST, TransactionType.COUPON}:
            self._income["interest"] += txn.net_amount

    def _build_portfolio_pnl(self) -> PortfolioPnL:
        """Build portfolio P&L from lot queues."""
        portfolio = PortfolioPnL()
        portfolio.dividend_income = self._income.get("dividend", Decimal("0"))
        portfolio.interest_income = self._income.get("interest", Decimal("0"))

        for symbol, queue in self._lot_queues.items():
            position = PositionPnL(
                symbol=symbol,
                quantity=queue.total_quantity,
                cost_basis=queue.total_cost_basis,
                realized_pnl=queue.realized_pnl,
                average_cost=queue.average_cost,
                lots=queue.lots,
            )
            portfolio.add_position(position)

        return portfolio

    def calculate_unrealized_pnl(
        self,
        current_prices: Dict[str, Decimal],
        fx_rates: Optional[Dict[str, Decimal]] = None
    ) -> PortfolioPnL:
        """
        Calculate unrealized P&L with current prices.

        Args:
            current_prices: Dict of symbol -> current price
            fx_rates: Optional dict of currency -> USD rate

        Returns:
            Updated PortfolioPnL
        """
        portfolio = self._build_portfolio_pnl()
        fx_rates = fx_rates or {}

        for symbol, position in portfolio.positions.items():
            price = current_prices.get(symbol, Decimal("0"))
            position.current_price = price

            # Get FX rate for this position's currency
            # Assume USD if not specified
            fx_rate = Decimal("1")

            queue = self._lot_queues.get(symbol)
            if queue:
                position.unrealized_pnl = queue.calculate_unrealized_pnl(price, fx_rate)
                position.market_value = position.quantity * price
                position.total_pnl = position.realized_pnl + position.unrealized_pnl

        # Recalculate totals
        portfolio.total_unrealized_pnl = sum(
            p.unrealized_pnl for p in portfolio.positions.values()
        )
        portfolio.total_market_value = sum(
            p.market_value for p in portfolio.positions.values()
        )
        portfolio.finalize()

        return portfolio

    def get_lot_details(self, symbol: str) -> List[Dict]:
        """
        Get detailed lot information for a symbol.

        Args:
            symbol: Security symbol

        Returns:
            List of lot details
        """
        queue = self._lot_queues.get(symbol)
        if not queue:
            return []

        return [
            {
                "lot_id": str(lot.lot_id),
                "acquisition_date": lot.acquisition_date.isoformat(),
                "acquisition_price": float(lot.acquisition_price),
                "acquisition_quantity": float(lot.acquisition_quantity),
                "remaining_quantity": float(lot.remaining_quantity),
                "cost_basis": float(lot.remaining_cost_basis),
                "cost_per_unit": float(lot.cost_per_unit),
                "holding_days": lot.holding_period_days,
                "is_long_term": lot.is_long_term,
            }
            for lot in queue.lots
        ]

    def get_disposal_history(self, symbol: str) -> List[Dict]:
        """
        Get disposal history for a symbol.

        Args:
            symbol: Security symbol

        Returns:
            List of disposal records
        """
        queue = self._lot_queues.get(symbol)
        if not queue:
            return []

        return queue.get_disposal_history()

    def get_tax_lot_report(self) -> List[Dict]:
        """
        Generate tax lot report for all positions.

        Returns:
            List of tax lot records
        """
        report = []

        for symbol, queue in self._lot_queues.items():
            for lot in queue.lots:
                report.append({
                    "symbol": symbol,
                    "lot_id": str(lot.lot_id),
                    "acquisition_date": lot.acquisition_date.isoformat(),
                    "acquisition_price": float(lot.acquisition_price),
                    "quantity": float(lot.remaining_quantity),
                    "cost_basis": float(lot.remaining_cost_basis),
                    "holding_period": "Long-term" if lot.is_long_term else "Short-term",
                    "days_held": lot.holding_period_days,
                })

        return report


def calculate_fifo_pnl(
    transactions: List[Transaction],
    current_prices: Dict[str, Decimal]
) -> PortfolioPnL:
    """
    Convenience function to calculate P&L.

    Args:
        transactions: List of transactions
        current_prices: Dict of symbol -> current price

    Returns:
        PortfolioPnL with realized and unrealized P&L
    """
    calculator = PnLCalculator()
    calculator.process_transactions(transactions)
    return calculator.calculate_unrealized_pnl(current_prices)
