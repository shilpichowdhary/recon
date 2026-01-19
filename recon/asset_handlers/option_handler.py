"""Handler for option assets."""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Any, Optional
from enum import Enum

from models.transaction import Transaction
from models.lot import Lot
from models.enums import AssetType, TransactionType
from .base_handler import BaseAssetHandler, AssetValuation


class OptionPosition(Enum):
    """Option position types."""
    LONG_CALL = "long_call"
    SHORT_CALL = "short_call"
    LONG_PUT = "long_put"
    SHORT_PUT = "short_put"


class OptionHandler(BaseAssetHandler):
    """
    Handler for options (calls and puts).

    Provides:
    - Premium accounting
    - Covered call / cash-secured put tracking
    - Exercise and expiry handling
    - Intrinsic and time value calculation
    """

    DEFAULT_MULTIPLIER = Decimal("100")  # Standard options contract size

    @property
    def asset_types(self) -> List[str]:
        return ["CALL_OPTION", "PUT_OPTION"]

    def calculate_valuation(
        self,
        lots: List[Lot],
        current_price: Decimal,
        valuation_date: date,
        fx_rate: Decimal = Decimal("1")
    ) -> AssetValuation:
        """
        Calculate option valuation.

        Args:
            lots: Option lots
            current_price: Current option premium
            valuation_date: Valuation date
            fx_rate: FX rate to base currency
        """
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

        # Aggregate contracts
        total_contracts = sum(lot.remaining_quantity for lot in lots)
        total_cost_basis = sum(lot.remaining_cost_basis for lot in lots)

        # Market value = contracts × premium × multiplier
        multiplier = self.DEFAULT_MULTIPLIER
        market_value_local = total_contracts * current_price * multiplier

        market_value = market_value_local * fx_rate
        cost_basis_base = total_cost_basis * fx_rate

        unrealized_pnl = market_value - cost_basis_base

        # Get option details from first lot
        strike_price = lots[0].strike_price if lots else None
        expiry_date = lots[0].expiry_date if lots else None
        underlying = lots[0].underlying_symbol if lots else None

        return AssetValuation(
            symbol=symbol,
            valuation_date=valuation_date,
            quantity=total_contracts,
            price=current_price,
            market_value=market_value,
            cost_basis=cost_basis_base,
            unrealized_pnl=unrealized_pnl,
            currency=currency,
            additional_fields={
                "strike_price": strike_price,
                "expiry_date": expiry_date.isoformat() if expiry_date else None,
                "underlying_symbol": underlying,
                "multiplier": multiplier,
                "notional_value": total_contracts * (strike_price or Decimal("0")) * multiplier,
            }
        )

    def calculate_unrealized_pnl(
        self,
        lots: List[Lot],
        current_price: Decimal,
        fx_rate: Decimal = Decimal("1")
    ) -> Decimal:
        """Calculate unrealized P&L for option position."""
        total_pnl = Decimal("0")
        multiplier = self.DEFAULT_MULTIPLIER

        for lot in lots:
            if lot.remaining_quantity <= 0:
                continue

            current_value = lot.remaining_quantity * current_price * multiplier * fx_rate
            cost_basis = lot.remaining_cost_basis * lot.acquisition_fx_rate

            total_pnl += current_value - cost_basis

        return total_pnl

    def process_transaction(
        self,
        transaction: Transaction
    ) -> Dict[str, Any]:
        """Process option transaction."""
        multiplier = transaction.contract_multiplier or self.DEFAULT_MULTIPLIER

        result = {
            "symbol": transaction.symbol,
            "transaction_type": transaction.transaction_type.name,
            "contracts": float(transaction.quantity),
            "premium": float(transaction.price),
            "multiplier": float(multiplier),
            "strike_price": float(transaction.strike_price) if transaction.strike_price else None,
            "expiry_date": transaction.expiry_date.isoformat() if transaction.expiry_date else None,
            "underlying": transaction.underlying_symbol,
        }

        if transaction.transaction_type in {TransactionType.BUY, TransactionType.OPTION_BUY}:
            result["action"] = "open_long"
            result["premium_paid"] = float(transaction.net_amount)

        elif transaction.transaction_type in {TransactionType.SELL, TransactionType.OPTION_SELL}:
            # Could be closing or opening short
            result["action"] = "close_or_open_short"
            result["premium_received"] = float(transaction.net_amount)

        elif transaction.transaction_type == TransactionType.OPTION_EXERCISE:
            result["action"] = "exercise"

        elif transaction.transaction_type == TransactionType.OPTION_ASSIGNMENT:
            result["action"] = "assignment"

        elif transaction.transaction_type == TransactionType.OPTION_EXPIRY:
            result["action"] = "expiry"
            result["pnl"] = float(-transaction.net_amount) if transaction.is_buy else float(transaction.net_amount)

        return result

    def calculate_intrinsic_value(
        self,
        is_call: bool,
        strike_price: Decimal,
        underlying_price: Decimal
    ) -> Decimal:
        """
        Calculate intrinsic value of option.

        Args:
            is_call: True for call, False for put
            strike_price: Option strike price
            underlying_price: Current price of underlying

        Returns:
            Intrinsic value (>= 0)
        """
        if is_call:
            intrinsic = underlying_price - strike_price
        else:
            intrinsic = strike_price - underlying_price

        return max(intrinsic, Decimal("0"))

    def calculate_time_value(
        self,
        option_price: Decimal,
        intrinsic_value: Decimal
    ) -> Decimal:
        """
        Calculate time value (extrinsic value) of option.

        Args:
            option_price: Current option premium
            intrinsic_value: Calculated intrinsic value

        Returns:
            Time value
        """
        return max(option_price - intrinsic_value, Decimal("0"))

    def calculate_moneyness(
        self,
        is_call: bool,
        strike_price: Decimal,
        underlying_price: Decimal
    ) -> str:
        """
        Determine option moneyness.

        Args:
            is_call: True for call, False for put
            strike_price: Option strike price
            underlying_price: Current price of underlying

        Returns:
            "ITM", "ATM", or "OTM"
        """
        # Consider ATM if within 1% of strike
        tolerance = strike_price * Decimal("0.01")

        if abs(underlying_price - strike_price) <= tolerance:
            return "ATM"

        if is_call:
            return "ITM" if underlying_price > strike_price else "OTM"
        else:
            return "ITM" if underlying_price < strike_price else "OTM"

    def process_exercise(
        self,
        lots: List[Lot],
        exercise_price: Decimal,
        underlying_price: Decimal,
        exercise_date: date
    ) -> Dict[str, Any]:
        """
        Process option exercise.

        Args:
            lots: Option lots being exercised
            exercise_price: Strike price
            underlying_price: Price of underlying at exercise
            exercise_date: Date of exercise

        Returns:
            Exercise processing result
        """
        total_contracts = sum(lot.remaining_quantity for lot in lots)
        multiplier = self.DEFAULT_MULTIPLIER

        # Calculate shares delivered/received
        shares = total_contracts * multiplier

        # Calculate cash settlement (if applicable)
        is_call = lots[0].asset_type == AssetType.CALL_OPTION if lots else True
        intrinsic = self.calculate_intrinsic_value(is_call, exercise_price, underlying_price)

        settlement_value = shares * intrinsic

        # Original premium paid/received
        total_premium = sum(lot.remaining_cost_basis for lot in lots)

        return {
            "action": "exercise",
            "exercise_date": exercise_date.isoformat(),
            "contracts": float(total_contracts),
            "shares": float(shares),
            "strike_price": float(exercise_price),
            "underlying_price": float(underlying_price),
            "intrinsic_value_per_share": float(intrinsic),
            "total_settlement": float(settlement_value),
            "original_premium": float(total_premium),
            "net_pnl": float(settlement_value - total_premium),
        }

    def process_expiry(
        self,
        lots: List[Lot],
        expiry_date: date,
        underlying_price: Decimal
    ) -> Dict[str, Any]:
        """
        Process option expiry (worthless or auto-exercise).

        Args:
            lots: Option lots expiring
            expiry_date: Expiry date
            underlying_price: Price of underlying at expiry

        Returns:
            Expiry processing result
        """
        total_contracts = sum(lot.remaining_quantity for lot in lots)
        total_premium = sum(lot.remaining_cost_basis for lot in lots)

        is_call = lots[0].asset_type == AssetType.CALL_OPTION if lots else True
        strike = lots[0].strike_price if lots else Decimal("0")

        intrinsic = self.calculate_intrinsic_value(is_call, strike, underlying_price)
        is_itm = intrinsic > 0

        if is_itm:
            # Would typically be auto-exercised
            return {
                "action": "auto_exercise",
                "expiry_date": expiry_date.isoformat(),
                "contracts": float(total_contracts),
                "in_the_money": True,
                "intrinsic_value": float(intrinsic),
                "note": "ITM options typically auto-exercise at expiry",
            }
        else:
            # Expires worthless
            return {
                "action": "expire_worthless",
                "expiry_date": expiry_date.isoformat(),
                "contracts": float(total_contracts),
                "in_the_money": False,
                "premium_lost": float(total_premium),  # For long positions
            }

    def identify_strategy(
        self,
        option_positions: List[Dict],
        underlying_position: Optional[Decimal] = None
    ) -> str:
        """
        Identify option strategy based on positions.

        Args:
            option_positions: List of option position dicts
            underlying_position: Number of shares of underlying held

        Returns:
            Strategy name
        """
        if not option_positions:
            return "No options"

        calls = [p for p in option_positions if p.get("is_call")]
        puts = [p for p in option_positions if not p.get("is_call")]

        # Covered call: long stock + short call
        if underlying_position and underlying_position > 0:
            short_calls = [c for c in calls if c.get("quantity", 0) < 0]
            if short_calls:
                return "Covered Call"

        # Cash-secured put: short put (with cash collateral)
        short_puts = [p for p in puts if p.get("quantity", 0) < 0]
        if short_puts and not calls:
            return "Cash-Secured Put"

        # Straddle: same strike, same expiry, call + put
        if len(calls) == 1 and len(puts) == 1:
            call = calls[0]
            put = puts[0]
            if call.get("strike") == put.get("strike") and call.get("expiry") == put.get("expiry"):
                if call.get("quantity", 0) > 0 and put.get("quantity", 0) > 0:
                    return "Long Straddle"
                elif call.get("quantity", 0) < 0 and put.get("quantity", 0) < 0:
                    return "Short Straddle"

        # Vertical spread: same expiry, different strikes
        if len(calls) == 2 and not puts:
            strikes = [c.get("strike") for c in calls]
            if strikes[0] != strikes[1]:
                return "Call Spread"

        if len(puts) == 2 and not calls:
            strikes = [p.get("strike") for p in puts]
            if strikes[0] != strikes[1]:
                return "Put Spread"

        return "Complex Strategy"
