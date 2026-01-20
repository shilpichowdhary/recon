"""Lot tracking service for FIFO position management."""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from models.transaction import Transaction
from models.lot import Lot, LotQueue
from models.enums import TransactionType, AssetType


class LotTrackingService:
    """
    Service for managing FIFO lot tracking across positions.

    Provides centralized lot management including:
    - Creating lots from buy transactions
    - FIFO disposal on sell transactions
    - Lot adjustment for corporate actions
    - Tax lot reporting
    """

    def __init__(self):
        """Initialize lot tracking service."""
        self._queues: Dict[str, LotQueue] = {}
        self._closed_lots: List[Dict] = []
        self._corporate_actions: List[Dict] = []

    def get_or_create_queue(self, symbol: str) -> LotQueue:
        """Get or create lot queue for a symbol."""
        if symbol not in self._queues:
            self._queues[symbol] = LotQueue(symbol)
        return self._queues[symbol]

    def process_transaction(self, transaction: Transaction) -> Optional[Dict]:
        """
        Process a transaction and update lot tracking.

        Args:
            transaction: Transaction to process

        Returns:
            Dict with transaction result details, or None
        """
        if transaction.is_buy:
            return self._process_buy(transaction)
        elif transaction.is_sell:
            return self._process_sell(transaction)
        elif transaction.transaction_type == TransactionType.STOCK_SPLIT:
            return self._process_stock_split(transaction)
        return None

    def _process_buy(self, txn: Transaction) -> Dict:
        """Process buy transaction - create new lot."""
        queue = self.get_or_create_queue(txn.symbol)

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

        # Copy asset-specific fields
        if AssetType.is_option(txn.asset_type):
            lot.underlying_symbol = txn.underlying_symbol
            lot.strike_price = txn.strike_price
            lot.expiry_date = txn.expiry_date

        if AssetType.is_fixed_income(txn.asset_type):
            lot.face_value = txn.face_value
            lot.coupon_rate = txn.coupon_rate
            lot.maturity_date = txn.maturity_date

        queue.add_lot(lot)

        return {
            "action": "lot_created",
            "lot_id": str(lot.lot_id),
            "symbol": txn.symbol,
            "quantity": float(txn.quantity),
            "cost_basis": float(txn.net_amount),
        }

    def _process_sell(self, txn: Transaction) -> Dict:
        """Process sell transaction - dispose lots using FIFO."""
        queue = self._queues.get(txn.symbol)

        if not queue:
            return {
                "action": "sell_error",
                "error": f"No lots found for {txn.symbol}",
            }

        if queue.total_quantity < txn.quantity:
            return {
                "action": "sell_warning",
                "warning": f"Selling more than held: {txn.quantity} > {queue.total_quantity}",
            }

        # Record lots before disposal for audit trail
        lots_before = [(str(l.lot_id), float(l.remaining_quantity)) for l in queue.lots]

        realized_pnl = queue.dispose_fifo(
            quantity=txn.quantity,
            sale_price=txn.price,
            sale_date=txn.transaction_date,
            sale_fx_rate=txn.fx_rate
        )

        # Get disposal details
        disposal_history = queue.get_disposal_history()

        return {
            "action": "lots_disposed",
            "symbol": txn.symbol,
            "quantity_sold": float(txn.quantity),
            "realized_pnl": float(realized_pnl),
            "lots_affected": lots_before,
            "remaining_quantity": float(queue.total_quantity),
        }

    def _process_stock_split(self, txn: Transaction) -> Dict:
        """Process stock split - adjust lot quantities.

        The split quantity (txn.quantity) represents the NEW shares received
        from the split, not a multiplier. For example, in a 10:1 split on 1 share:
        - You have 1 share before
        - You receive 9 additional shares (txn.quantity = 9)
        - You have 10 shares after
        """
        queue = self._queues.get(txn.symbol)

        if not queue:
            return {
                "action": "split_error",
                "error": f"No lots found for {txn.symbol}",
            }

        # txn.quantity is the number of NEW shares received from the split
        additional_shares = txn.quantity
        total_existing_shares = queue.total_quantity

        # Calculate the effective split ratio for price adjustment
        # If you had 10 shares and received 90 more, ratio is (10+90)/10 = 10
        if total_existing_shares > 0:
            effective_ratio = (total_existing_shares + additional_shares) / total_existing_shares
        else:
            # No existing shares - this shouldn't happen for a split
            return {
                "action": "split_error",
                "error": f"No existing shares to split for {txn.symbol}",
            }

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

        self._corporate_actions.append({
            "type": "stock_split",
            "symbol": txn.symbol,
            "date": txn.transaction_date.isoformat(),
            "additional_shares": float(additional_shares),
            "effective_ratio": float(effective_ratio),
        })

        return {
            "action": "split_processed",
            "symbol": txn.symbol,
            "additional_shares": float(additional_shares),
            "effective_ratio": float(effective_ratio),
            "lots_adjusted": len(queue.lots),
        }

    def get_position_summary(self, symbol: str) -> Optional[Dict]:
        """
        Get position summary for a symbol.

        Args:
            symbol: Security symbol

        Returns:
            Position summary dict or None
        """
        queue = self._queues.get(symbol)
        if not queue:
            return None

        return {
            "symbol": symbol,
            "total_quantity": float(queue.total_quantity),
            "total_cost_basis": float(queue.total_cost_basis),
            "average_cost": float(queue.average_cost),
            "realized_pnl": float(queue.realized_pnl),
            "lot_count": len(queue),
            "lots": [
                {
                    "lot_id": str(l.lot_id),
                    "acquisition_date": l.acquisition_date.isoformat(),
                    "quantity": float(l.remaining_quantity),
                    "cost_per_unit": float(l.cost_per_unit),
                    "holding_days": l.holding_period_days,
                    "term": "long" if l.is_long_term else "short",
                }
                for l in queue.lots
            ],
        }

    def get_all_positions(self) -> Dict[str, Dict]:
        """Get summary of all positions."""
        return {
            symbol: self.get_position_summary(symbol)
            for symbol in self._queues
            if self._queues[symbol].total_quantity > 0
        }

    def calculate_unrealized_pnl(
        self,
        symbol: str,
        current_price: Decimal,
        current_fx_rate: Decimal = Decimal("1")
    ) -> Optional[Decimal]:
        """
        Calculate unrealized P&L for a position.

        Args:
            symbol: Security symbol
            current_price: Current market price
            current_fx_rate: Current FX rate

        Returns:
            Unrealized P&L or None if no position
        """
        queue = self._queues.get(symbol)
        if not queue:
            return None

        return queue.calculate_unrealized_pnl(current_price, current_fx_rate)

    def get_tax_lot_report(self, as_of_date: Optional[date] = None) -> List[Dict]:
        """
        Generate tax lot report.

        Args:
            as_of_date: Optional date to calculate holding period (default: today)

        Returns:
            List of tax lot records
        """
        as_of = as_of_date or date.today()
        report = []

        for symbol, queue in self._queues.items():
            for lot in queue.lots:
                days_held = (as_of - lot.acquisition_date).days

                report.append({
                    "symbol": symbol,
                    "lot_id": str(lot.lot_id),
                    "acquisition_date": lot.acquisition_date.isoformat(),
                    "acquisition_price": float(lot.acquisition_price),
                    "quantity": float(lot.remaining_quantity),
                    "original_quantity": float(lot.acquisition_quantity),
                    "cost_basis": float(lot.remaining_cost_basis),
                    "cost_per_unit": float(lot.cost_per_unit),
                    "holding_period": "Long-term" if days_held > 365 else "Short-term",
                    "days_held": days_held,
                })

        return sorted(report, key=lambda x: (x["symbol"], x["acquisition_date"]))

    def get_realized_gains_report(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[Dict]:
        """
        Generate realized gains/losses report.

        Args:
            start_date: Start of period (optional)
            end_date: End of period (optional)

        Returns:
            List of realized gain/loss records
        """
        report = []

        for symbol, queue in self._queues.items():
            for disposal in queue.get_disposal_history():
                disposal_date = disposal.get("disposal_date")

                # Filter by date range if specified
                if start_date and disposal_date < start_date:
                    continue
                if end_date and disposal_date > end_date:
                    continue

                report.append({
                    "symbol": symbol,
                    **disposal,
                })

        return sorted(report, key=lambda x: x.get("disposal_date", date.min))

    def get_corporate_actions(self) -> List[Dict]:
        """Get list of processed corporate actions."""
        return self._corporate_actions.copy()

    def transfer_lots(
        self,
        from_symbol: str,
        to_symbol: str,
        quantity: Optional[Decimal] = None
    ) -> Dict:
        """
        Transfer lots from one symbol to another (e.g., ticker change).

        Args:
            from_symbol: Original symbol
            to_symbol: New symbol
            quantity: Optional quantity to transfer (default: all)

        Returns:
            Transfer result dict
        """
        from_queue = self._queues.get(from_symbol)
        if not from_queue:
            return {"error": f"No lots found for {from_symbol}"}

        to_queue = self.get_or_create_queue(to_symbol)
        transferred = 0

        for lot in list(from_queue._lots):
            if quantity and transferred >= quantity:
                break

            # Update symbol and move to new queue
            lot.symbol = to_symbol
            to_queue.add_lot(lot)
            from_queue._lots.remove(lot)
            transferred += lot.remaining_quantity

        return {
            "action": "lots_transferred",
            "from_symbol": from_symbol,
            "to_symbol": to_symbol,
            "quantity_transferred": float(transferred),
        }
