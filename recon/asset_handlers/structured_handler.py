"""Handler for structured products."""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Any, Optional
from enum import Enum

from models.transaction import Transaction
from models.lot import Lot
from models.enums import AssetType
from .base_handler import BaseAssetHandler, AssetValuation


class BarrierType(Enum):
    """Types of barrier options."""
    DOWN_AND_IN = "down_and_in"
    DOWN_AND_OUT = "down_and_out"
    UP_AND_IN = "up_and_in"
    UP_AND_OUT = "up_and_out"


class StructuredProductHandler(BaseAssetHandler):
    """
    Handler for structured products.

    Provides:
    - Barrier monitoring
    - Worst-of basket calculations
    - Autocallable monitoring
    - Coupon calculations
    """

    @property
    def asset_types(self) -> List[str]:
        return ["STRUCTURED_NOTE", "BARRIER_OPTION", "AUTOCALLABLE"]

    def calculate_valuation(
        self,
        lots: List[Lot],
        current_price: Decimal,
        valuation_date: date,
        fx_rate: Decimal = Decimal("1")
    ) -> AssetValuation:
        """
        Calculate structured product valuation.

        Note: Structured products often require model-based pricing.
        This provides a simplified mark-to-market valuation.
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

        # Aggregate
        total_notional = sum(lot.face_value or lot.remaining_quantity for lot in lots)
        total_cost_basis = sum(lot.remaining_cost_basis for lot in lots)

        # Current price as percentage of notional
        market_value_local = total_notional * current_price / Decimal("100")
        market_value = market_value_local * fx_rate
        cost_basis_base = total_cost_basis * fx_rate

        unrealized_pnl = market_value - cost_basis_base

        return AssetValuation(
            symbol=symbol,
            valuation_date=valuation_date,
            quantity=total_notional,
            price=current_price,
            market_value=market_value,
            cost_basis=cost_basis_base,
            unrealized_pnl=unrealized_pnl,
            currency=currency,
            additional_fields={
                "notional": total_notional,
                "fx_rate": fx_rate,
            }
        )

    def calculate_unrealized_pnl(
        self,
        lots: List[Lot],
        current_price: Decimal,
        fx_rate: Decimal = Decimal("1")
    ) -> Decimal:
        """Calculate unrealized P&L."""
        total_pnl = Decimal("0")

        for lot in lots:
            if lot.remaining_quantity <= 0:
                continue

            notional = lot.face_value or lot.remaining_quantity
            current_value = notional * current_price / Decimal("100") * fx_rate
            cost_basis = lot.remaining_cost_basis * lot.acquisition_fx_rate

            total_pnl += current_value - cost_basis

        return total_pnl

    def process_transaction(
        self,
        transaction: Transaction
    ) -> Dict[str, Any]:
        """Process structured product transaction."""
        result = {
            "symbol": transaction.symbol,
            "transaction_type": transaction.transaction_type.name,
            "notional": float(transaction.face_value or transaction.quantity),
            "price": float(transaction.price),
        }

        if transaction.is_buy:
            result["action"] = "add_position"
            result["cost"] = float(transaction.net_amount)

        elif transaction.is_sell:
            result["action"] = "close_position"
            result["proceeds"] = float(transaction.net_amount)

        return result

    def check_barrier(
        self,
        barrier_type: BarrierType,
        barrier_level: Decimal,
        current_price: Decimal,
        initial_price: Decimal
    ) -> Dict[str, Any]:
        """
        Check if barrier has been breached.

        Args:
            barrier_type: Type of barrier
            barrier_level: Barrier level as percentage of initial (e.g., 70 for 70%)
            current_price: Current underlying price
            initial_price: Initial underlying price

        Returns:
            Dict with barrier status
        """
        barrier_price = initial_price * barrier_level / Decimal("100")
        current_pct = current_price / initial_price * Decimal("100")

        result = {
            "barrier_type": barrier_type.value,
            "barrier_level": float(barrier_level),
            "barrier_price": float(barrier_price),
            "current_price": float(current_price),
            "current_level": float(current_pct),
            "breached": False,
        }

        if barrier_type in {BarrierType.DOWN_AND_IN, BarrierType.DOWN_AND_OUT}:
            result["breached"] = current_price <= barrier_price
            result["distance_to_barrier"] = float((current_price - barrier_price) / initial_price * 100)

        elif barrier_type in {BarrierType.UP_AND_IN, BarrierType.UP_AND_OUT}:
            result["breached"] = current_price >= barrier_price
            result["distance_to_barrier"] = float((barrier_price - current_price) / initial_price * 100)

        return result

    def calculate_worst_of(
        self,
        underlyings: Dict[str, Dict[str, Decimal]]
    ) -> Dict[str, Any]:
        """
        Calculate worst-of for a basket of underlyings.

        Args:
            underlyings: Dict of symbol -> {"initial": price, "current": price}

        Returns:
            Worst-of analysis
        """
        performances = []

        for symbol, prices in underlyings.items():
            initial = prices.get("initial", Decimal("1"))
            current = prices.get("current", Decimal("1"))

            if initial > 0:
                performance = (current - initial) / initial * Decimal("100")
            else:
                performance = Decimal("0")

            performances.append({
                "symbol": symbol,
                "initial_price": float(initial),
                "current_price": float(current),
                "performance": float(performance),
            })

        # Sort by performance (worst first)
        performances.sort(key=lambda x: x["performance"])

        worst = performances[0] if performances else None
        best = performances[-1] if performances else None

        return {
            "basket_size": len(underlyings),
            "performances": performances,
            "worst_of": worst,
            "best_of": best,
            "average_performance": sum(p["performance"] for p in performances) / len(performances) if performances else 0,
        }

    def check_autocall(
        self,
        observation_dates: List[date],
        autocall_level: Decimal,
        underlying_prices: Dict[date, Decimal],
        initial_price: Decimal
    ) -> Dict[str, Any]:
        """
        Check autocall trigger status.

        Args:
            observation_dates: List of autocall observation dates
            autocall_level: Autocall trigger level as percentage (e.g., 100)
            underlying_prices: Dict of date -> price
            initial_price: Initial underlying price

        Returns:
            Autocall status
        """
        autocall_price = initial_price * autocall_level / Decimal("100")

        observations = []
        called = False
        call_date = None

        for obs_date in sorted(observation_dates):
            price = underlying_prices.get(obs_date)

            if price is None:
                observations.append({
                    "date": obs_date.isoformat(),
                    "price": None,
                    "level": None,
                    "triggered": None,
                    "status": "pending",
                })
                continue

            level = price / initial_price * Decimal("100")
            triggered = price >= autocall_price

            observations.append({
                "date": obs_date.isoformat(),
                "price": float(price),
                "level": float(level),
                "triggered": triggered,
                "status": "called" if triggered else "not called",
            })

            if triggered and not called:
                called = True
                call_date = obs_date

        return {
            "autocall_level": float(autocall_level),
            "autocall_price": float(autocall_price),
            "initial_price": float(initial_price),
            "observations": observations,
            "is_called": called,
            "call_date": call_date.isoformat() if call_date else None,
        }

    def calculate_coupon(
        self,
        notional: Decimal,
        coupon_rate: Decimal,
        is_memory_coupon: bool = False,
        missed_coupons: int = 0
    ) -> Dict[str, Any]:
        """
        Calculate coupon payment.

        Args:
            notional: Notional amount
            coupon_rate: Coupon rate as percentage
            is_memory_coupon: If True, missed coupons are paid when conditions met
            missed_coupons: Number of previously missed coupons

        Returns:
            Coupon calculation result
        """
        base_coupon = notional * coupon_rate / Decimal("100")

        result = {
            "notional": float(notional),
            "coupon_rate": float(coupon_rate),
            "base_coupon": float(base_coupon),
            "is_memory_coupon": is_memory_coupon,
        }

        if is_memory_coupon and missed_coupons > 0:
            memory_payment = base_coupon * missed_coupons
            result["missed_coupons"] = missed_coupons
            result["memory_payment"] = float(memory_payment)
            result["total_payment"] = float(base_coupon + memory_payment)
        else:
            result["total_payment"] = float(base_coupon)

        return result

    def calculate_redemption(
        self,
        notional: Decimal,
        final_level: Decimal,
        barrier_level: Decimal,
        barrier_breached: bool,
        participation_rate: Decimal = Decimal("100")
    ) -> Dict[str, Any]:
        """
        Calculate redemption amount at maturity.

        Args:
            notional: Notional amount
            final_level: Final underlying level as percentage of initial
            barrier_level: Barrier level as percentage
            barrier_breached: Whether barrier was breached
            participation_rate: Participation in upside/downside

        Returns:
            Redemption calculation
        """
        result = {
            "notional": float(notional),
            "final_level": float(final_level),
            "barrier_level": float(barrier_level),
            "barrier_breached": barrier_breached,
            "participation_rate": float(participation_rate),
        }

        if not barrier_breached:
            # Protected - return notional
            result["redemption_amount"] = float(notional)
            result["redemption_type"] = "capital_protected"

        elif final_level >= Decimal("100"):
            # Above initial - could participate in upside
            upside = (final_level - Decimal("100")) / Decimal("100")
            bonus = notional * upside * participation_rate / Decimal("100")
            result["redemption_amount"] = float(notional + bonus)
            result["redemption_type"] = "above_initial"
            result["upside_participation"] = float(bonus)

        else:
            # Below initial and barrier breached - suffer loss
            loss_pct = (Decimal("100") - final_level) / Decimal("100")
            loss = notional * loss_pct
            result["redemption_amount"] = float(notional - loss)
            result["redemption_type"] = "barrier_breached"
            result["loss_amount"] = float(loss)

        return result
