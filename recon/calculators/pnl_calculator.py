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

    # Capital gains from selling securities (FIFO)
    realized_capital_gains: Decimal = Decimal("0")

    # Income breakdown
    gross_dividend_income: Decimal = Decimal("0")
    gross_interest_income: Decimal = Decimal("0")
    option_premium_received: Decimal = Decimal("0")  # Premium from selling options
    withholding_tax: Decimal = Decimal("0")
    interest_expense: Decimal = Decimal("0")
    other_fees: Decimal = Decimal("0")

    # Computed totals
    total_unrealized_pnl: Decimal = Decimal("0")
    total_cost_basis: Decimal = Decimal("0")
    total_market_value: Decimal = Decimal("0")

    @property
    def net_realized_income(self) -> Decimal:
        """Net income after taxes and expenses (includes option premium)."""
        return (
            self.gross_dividend_income +
            self.gross_interest_income +
            self.option_premium_received -
            self.withholding_tax -
            self.interest_expense -
            self.other_fees
        )

    @property
    def total_realized_pnl(self) -> Decimal:
        """Total realized P&L (capital gains + net income)."""
        return self.realized_capital_gains + self.net_realized_income

    @property
    def total_pnl(self) -> Decimal:
        """Total P&L including unrealized."""
        return self.realized_capital_gains + self.net_realized_income + self.total_unrealized_pnl

    # Legacy compatibility
    @property
    def dividend_income(self) -> Decimal:
        return self.gross_dividend_income

    @property
    def interest_income(self) -> Decimal:
        return self.gross_interest_income

    def add_position(self, position: PositionPnL) -> None:
        """Add a position and update totals."""
        self.positions[position.symbol] = position
        self.realized_capital_gains += position.realized_pnl
        self.total_unrealized_pnl += position.unrealized_pnl
        self.total_cost_basis += position.cost_basis
        self.total_market_value += position.market_value

    def finalize(self) -> None:
        """Finalize calculations (no-op, totals computed via properties)."""
        pass


class PnLCalculator:
    """
    Calculate P&L using FIFO (First In, First Out) lot matching.

    Maintains lot queues per security and tracks:
    - Realized P&L on sales (matched against oldest lots first)
    - Unrealized P&L from remaining lots
    - Dividend and interest income
    """

    # Currency codes that should be treated as cash (not tracked via FIFO lots)
    CASH_SYMBOLS = {
        'USD', 'EUR', 'GBP', 'CHF', 'JPY', 'CAD', 'AUD', 'NZD', 'HKD', 'SGD',
        'CNY', 'CNH', 'INR', 'KRW', 'TWD', 'THB', 'MYR', 'IDR', 'PHP', 'VND',
        'SEK', 'NOK', 'DKK', 'PLN', 'CZK', 'HUF', 'TRY', 'ZAR', 'MXN', 'BRL',
        'ARS', 'CLP', 'COP', 'PEN', 'ILS', 'AED', 'SAR', 'KWD', 'BHD', 'QAR',
    }

    def __init__(self):
        """Initialize P&L calculator."""
        self._lot_queues: Dict[str, LotQueue] = {}
        self._income: Dict[str, Decimal] = defaultdict(Decimal)
        self._transactions: List[Transaction] = []
        self._cash_balances: Dict[str, Decimal] = defaultdict(Decimal)  # Track cash separately

    def _is_cash_symbol(self, symbol: str) -> bool:
        """Check if symbol is a cash/currency position."""
        if not symbol:
            return False
        return symbol.upper() in self.CASH_SYMBOLS

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
        is_cash = self._is_cash_symbol(symbol)

        # Always process income and fees regardless of whether it's a cash symbol
        if TransactionType.is_income(txn.transaction_type):
            self._process_income(txn)
            return
        elif txn.transaction_type in {TransactionType.FEE, TransactionType.COMMISSION}:
            self._process_fee(txn)
            return

        # Skip cash symbols from lot tracking (buys, sells, splits)
        if is_cash:
            return

        # Initialize lot queue if needed
        if symbol not in self._lot_queues:
            self._lot_queues[symbol] = LotQueue(symbol)

        # Handle by transaction type
        if txn.is_buy:
            self._process_buy(txn)
        elif txn.is_sell:
            # Check if this is an option sale (STO) - record premium as income
            if self._is_option_symbol(symbol) and txn.net_amount and txn.net_amount > 0:
                self._process_option_premium(txn)
            else:
                self._process_sell(txn)
        elif txn.transaction_type == TransactionType.STOCK_SPLIT:
            self._process_stock_split(txn)

    def _is_option_symbol(self, symbol: str) -> bool:
        """Check if symbol is an option."""
        if not symbol:
            return False
        symbol_upper = symbol.upper()
        # Common option suffixes: _OPQ (options exchange)
        # Format like QQQO3126C375000_OPQ or SPYX1925C450000_OPQ
        return '_OPQ' in symbol_upper

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
            self._income["gross_dividend"] += txn.net_amount
        elif txn.transaction_type in {TransactionType.INTEREST, TransactionType.COUPON}:
            self._income["gross_interest"] += txn.net_amount

    def _process_fee(self, txn: Transaction) -> None:
        """Process fee/expense transaction (withholding tax, interest paid, etc.)."""
        # Use absolute value since fees are often stored as negative
        amount = abs(txn.net_amount) if txn.net_amount else abs(txn.gross_amount)

        # Categorize by description or symbol pattern
        symbol_lower = txn.symbol.lower() if txn.symbol else ""
        desc_lower = (txn.description or "").lower()

        # Check if it's withholding tax (WTAX transaction type or tax-related)
        if "wtax" in symbol_lower or "tax" in desc_lower or "withhold" in desc_lower:
            self._income["withholding_tax"] += amount
        # Check if it's interest expense (INTPAID)
        elif "intpaid" in symbol_lower or "interest paid" in desc_lower:
            self._income["interest_expense"] += amount
        else:
            # Other fees (custody, management, etc.)
            self._income["other_fees"] += amount

    def _process_option_premium(self, txn: Transaction) -> None:
        """Process option premium from selling (writing) options."""
        # Premium received from selling options
        if txn.net_amount and txn.net_amount > 0:
            self._income["option_premium"] += txn.net_amount
        elif txn.gross_amount and txn.gross_amount > 0:
            self._income["option_premium"] += txn.gross_amount

    def _process_stock_split(self, txn: Transaction) -> None:
        """Process stock split - adjust lot quantities.

        The split quantity (txn.quantity) represents the NEW shares received
        from the split, not a multiplier. For example, in a 10:1 split on 1 share:
        - You have 1 share before
        - You receive 9 additional shares (txn.quantity = 9)
        - You have 10 shares after
        """
        queue = self._lot_queues.get(txn.symbol)
        if not queue or queue.total_quantity == 0:
            return

        # txn.quantity is the number of NEW shares received from the split
        additional_shares = txn.quantity
        total_existing_shares = queue.total_quantity

        # Calculate the effective split ratio for price adjustment
        effective_ratio = (total_existing_shares + additional_shares) / total_existing_shares

        # Distribute additional shares proportionally across lots
        for lot in queue._lots:
            old_qty = lot.remaining_quantity
            old_price = lot.acquisition_price

            # Each lot gets proportional additional shares
            lot_additional = additional_shares * (old_qty / total_existing_shares)

            # Adjust quantity: add the additional shares
            lot.remaining_quantity = old_qty + lot_additional
            lot.acquisition_quantity = lot.acquisition_quantity * effective_ratio

            # Adjust price: divide by the effective ratio to maintain cost basis
            lot.acquisition_price = old_price / effective_ratio

    def _build_portfolio_pnl(self) -> PortfolioPnL:
        """Build portfolio P&L from lot queues."""
        portfolio = PortfolioPnL()

        # Set income breakdown
        portfolio.gross_dividend_income = self._income.get("gross_dividend", Decimal("0"))
        portfolio.gross_interest_income = self._income.get("gross_interest", Decimal("0"))
        portfolio.option_premium_received = self._income.get("option_premium", Decimal("0"))
        portfolio.withholding_tax = self._income.get("withholding_tax", Decimal("0"))
        portfolio.interest_expense = self._income.get("interest_expense", Decimal("0"))
        portfolio.other_fees = self._income.get("other_fees", Decimal("0"))

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
            current_prices: Dict of symbol -> current price (in local currency)
            fx_rates: Optional dict of symbol -> FX rate to convert local to base currency

        Returns:
            Updated PortfolioPnL with values in base currency
        """
        portfolio = self._build_portfolio_pnl()
        fx_rates = fx_rates or {}

        for symbol, position in portfolio.positions.items():
            price = current_prices.get(symbol, Decimal("0"))
            position.current_price = price

            # Get FX rate for this symbol
            # FX rate converts local currency to base currency (e.g., HKD/USD = 0.128)
            fx_rate = fx_rates.get(symbol, Decimal("1"))

            queue = self._lot_queues.get(symbol)
            if queue:
                # Calculate unrealized P&L in base currency
                position.unrealized_pnl = queue.calculate_unrealized_pnl(price, fx_rate)
                # Market value in base currency = qty * local_price * fx_rate
                position.market_value = position.quantity * price * fx_rate
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
