"""Handler for fixed income (bond) assets."""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Any, Optional
import math

from models.transaction import Transaction
from models.lot import Lot
from models.enums import AssetType, TransactionType
from utils.date_utils import day_count_30_360, day_count_actual_365
from .base_handler import BaseAssetHandler, AssetValuation, AssetIncome


class BondHandler(BaseAssetHandler):
    """
    Handler for fixed income securities.

    Provides:
    - Clean and dirty price calculations
    - Accrued interest calculation (30/360 convention)
    - Yield to Maturity (YTM) calculation
    - Coupon income tracking
    """

    @property
    def asset_types(self) -> List[str]:
        return ["GOVERNMENT_BOND", "CORPORATE_BOND", "MUNICIPAL_BOND", "TREASURY_BILL", "ZERO_COUPON_BOND"]

    def calculate_valuation(
        self,
        lots: List[Lot],
        current_price: Decimal,
        valuation_date: date,
        fx_rate: Decimal = Decimal("1")
    ) -> AssetValuation:
        """
        Calculate bond valuation including accrued interest.

        Args:
            lots: Bond lots
            current_price: Clean price (as percentage of face value)
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

        # Aggregate quantities and cost basis
        total_face_value = sum(lot.face_value or lot.remaining_quantity for lot in lots)
        total_cost_basis = sum(lot.remaining_cost_basis for lot in lots)

        # Calculate accrued interest
        accrued_interest = self._calculate_total_accrued_interest(lots, valuation_date)

        # Clean price is percentage of face value
        clean_value = total_face_value * current_price / Decimal("100")

        # Dirty price = clean price + accrued interest
        dirty_value = clean_value + accrued_interest

        # Convert to base currency
        market_value = dirty_value * fx_rate
        cost_basis_base = total_cost_basis * fx_rate

        unrealized_pnl = market_value - cost_basis_base

        return AssetValuation(
            symbol=symbol,
            valuation_date=valuation_date,
            quantity=total_face_value,
            price=current_price,
            market_value=market_value,
            cost_basis=cost_basis_base,
            unrealized_pnl=unrealized_pnl,
            currency=currency,
            additional_fields={
                "clean_price": current_price,
                "clean_value": clean_value,
                "accrued_interest": accrued_interest,
                "dirty_value": dirty_value,
                "fx_rate": fx_rate,
            }
        )

    def calculate_unrealized_pnl(
        self,
        lots: List[Lot],
        current_price: Decimal,
        fx_rate: Decimal = Decimal("1")
    ) -> Decimal:
        """Calculate unrealized P&L for bond position."""
        total_pnl = Decimal("0")

        for lot in lots:
            if lot.remaining_quantity <= 0:
                continue

            face_value = lot.face_value or lot.remaining_quantity
            current_value = face_value * current_price / Decimal("100") * fx_rate
            cost_basis = lot.remaining_cost_basis * lot.acquisition_fx_rate

            total_pnl += current_value - cost_basis

        return total_pnl

    def process_transaction(
        self,
        transaction: Transaction
    ) -> Dict[str, Any]:
        """Process bond transaction."""
        result = {
            "symbol": transaction.symbol,
            "transaction_type": transaction.transaction_type.name,
            "face_value": float(transaction.face_value or transaction.quantity),
            "price": float(transaction.price),
        }

        if transaction.is_buy:
            result["action"] = "add_lot"
            result["cost_basis"] = float(transaction.net_amount)
            result["accrued_interest_paid"] = float(transaction.accrued_interest)

        elif transaction.is_sell:
            result["action"] = "dispose_fifo"
            result["proceeds"] = float(transaction.net_amount)
            result["accrued_interest_received"] = float(transaction.accrued_interest)

        elif transaction.transaction_type == TransactionType.COUPON:
            result["action"] = "record_income"
            result["income_type"] = "coupon"
            result["amount"] = float(transaction.net_amount)

        return result

    def calculate_accrued_interest(
        self,
        face_value: Decimal,
        coupon_rate: Decimal,
        last_coupon_date: date,
        settlement_date: date,
        frequency: int = 2,
        day_count_convention: str = "30_360"
    ) -> Decimal:
        """
        Calculate accrued interest on a bond.

        Args:
            face_value: Face value of bond
            coupon_rate: Annual coupon rate (as decimal, e.g., 0.05 for 5%)
            last_coupon_date: Date of last coupon payment
            settlement_date: Settlement date for calculation
            frequency: Coupon payments per year (1=annual, 2=semi-annual, 4=quarterly)
            day_count_convention: "30_360" or "actual_365"

        Returns:
            Accrued interest amount
        """
        # Calculate days since last coupon
        if day_count_convention == "30_360":
            days_accrued = day_count_30_360(last_coupon_date, settlement_date)
            days_in_period = 360 / frequency
        else:
            days_accrued = day_count_actual_365(last_coupon_date, settlement_date)
            days_in_period = 365 / frequency

        # Coupon amount per period
        coupon_per_period = face_value * coupon_rate / frequency

        # Accrued interest
        accrued = coupon_per_period * Decimal(str(days_accrued / days_in_period))

        return accrued

    def _calculate_total_accrued_interest(
        self,
        lots: List[Lot],
        valuation_date: date
    ) -> Decimal:
        """Calculate total accrued interest for all lots."""
        total_accrued = Decimal("0")

        for lot in lots:
            if lot.remaining_quantity <= 0:
                continue

            face_value = lot.face_value or lot.remaining_quantity
            coupon_rate = lot.coupon_rate or Decimal("0")

            if coupon_rate == 0:
                continue

            # Estimate last coupon date (semi-annual coupons assumed)
            # In production, this would come from bond reference data
            last_coupon = self._estimate_last_coupon_date(
                lot.acquisition_date, valuation_date, frequency=2
            )

            accrued = self.calculate_accrued_interest(
                face_value=face_value,
                coupon_rate=coupon_rate,
                last_coupon_date=last_coupon,
                settlement_date=valuation_date,
            )

            total_accrued += accrued

        return total_accrued

    def _estimate_last_coupon_date(
        self,
        acquisition_date: date,
        valuation_date: date,
        frequency: int = 2
    ) -> date:
        """Estimate the last coupon payment date."""
        # Simple estimation - in production use actual bond schedule
        months_per_coupon = 12 // frequency
        months_diff = (valuation_date.year - acquisition_date.year) * 12 + \
                      (valuation_date.month - acquisition_date.month)

        coupons_since = months_diff // months_per_coupon
        last_coupon_months = coupons_since * months_per_coupon

        year = acquisition_date.year + last_coupon_months // 12
        month = acquisition_date.month + last_coupon_months % 12
        if month > 12:
            year += 1
            month -= 12

        return date(year, month, acquisition_date.day)

    def calculate_ytm(
        self,
        clean_price: Decimal,
        face_value: Decimal,
        coupon_rate: Decimal,
        settlement_date: date,
        maturity_date: date,
        frequency: int = 2,
        max_iterations: int = 100,
        tolerance: float = 1e-8
    ) -> Optional[Decimal]:
        """
        Calculate Yield to Maturity using Newton-Raphson method.

        Args:
            clean_price: Clean price as percentage of face value
            face_value: Face value of bond
            coupon_rate: Annual coupon rate (as decimal)
            settlement_date: Settlement date
            maturity_date: Maturity date
            frequency: Coupon payments per year
            max_iterations: Max iterations for convergence
            tolerance: Convergence tolerance

        Returns:
            YTM as decimal or None if no solution
        """
        # Convert price to dollar amount
        price = face_value * clean_price / Decimal("100")

        # Calculate accrued interest
        # Simplified - assume last coupon was 0 days ago
        accrued = Decimal("0")

        # Dirty price
        dirty_price = float(price + accrued)

        # Coupon payment
        coupon = float(face_value * coupon_rate / frequency)

        # Time to maturity in periods
        days_to_maturity = (maturity_date - settlement_date).days
        years_to_maturity = days_to_maturity / 365
        periods_to_maturity = years_to_maturity * frequency

        if periods_to_maturity <= 0:
            return None

        # Newton-Raphson iteration
        ytm = float(coupon_rate)  # Initial guess

        for _ in range(max_iterations):
            # Calculate bond price at current YTM
            pv = 0
            pv_derivative = 0

            for t in range(1, int(periods_to_maturity) + 1):
                discount = (1 + ytm / frequency) ** t
                pv += coupon / discount
                pv_derivative -= t * coupon / (frequency * discount * (1 + ytm / frequency))

            # Add principal
            final_discount = (1 + ytm / frequency) ** periods_to_maturity
            pv += float(face_value) / final_discount
            pv_derivative -= periods_to_maturity * float(face_value) / (frequency * final_discount * (1 + ytm / frequency))

            # Newton-Raphson update
            f = pv - dirty_price
            if abs(pv_derivative) < 1e-12:
                break

            ytm_new = ytm - f / pv_derivative

            if abs(ytm_new - ytm) < tolerance:
                return Decimal(str(round(ytm_new, 8)))

            ytm = ytm_new

        return Decimal(str(round(ytm, 8)))

    def calculate_duration(
        self,
        clean_price: Decimal,
        face_value: Decimal,
        coupon_rate: Decimal,
        ytm: Decimal,
        settlement_date: date,
        maturity_date: date,
        frequency: int = 2
    ) -> Dict[str, Decimal]:
        """
        Calculate Macaulay and Modified duration.

        Returns:
            Dict with 'macaulay' and 'modified' duration
        """
        y = float(ytm)
        c = float(coupon_rate)
        n = frequency
        coupon = float(face_value) * c / n

        days_to_maturity = (maturity_date - settlement_date).days
        years_to_maturity = days_to_maturity / 365
        periods = years_to_maturity * n

        # Calculate weighted present values
        weighted_pv = 0
        total_pv = 0

        for t in range(1, int(periods) + 1):
            discount = (1 + y / n) ** t
            pv = coupon / discount
            weighted_pv += (t / n) * pv
            total_pv += pv

        # Add principal
        final_discount = (1 + y / n) ** periods
        principal_pv = float(face_value) / final_discount
        weighted_pv += years_to_maturity * principal_pv
        total_pv += principal_pv

        # Macaulay duration
        macaulay = weighted_pv / total_pv if total_pv > 0 else 0

        # Modified duration
        modified = macaulay / (1 + y / n)

        return {
            "macaulay": Decimal(str(round(macaulay, 4))),
            "modified": Decimal(str(round(modified, 4))),
        }

    def calculate_coupon_income(
        self,
        lots: List[Lot],
        coupon_date: date
    ) -> Optional[AssetIncome]:
        """
        Calculate coupon income for position.

        Args:
            lots: Bond lots
            coupon_date: Coupon payment date

        Returns:
            AssetIncome for coupon payment
        """
        total_income = Decimal("0")

        for lot in lots:
            if lot.remaining_quantity <= 0:
                continue

            if lot.acquisition_date > coupon_date:
                continue  # Didn't own on record date

            face_value = lot.face_value or lot.remaining_quantity
            coupon_rate = lot.coupon_rate or Decimal("0")

            # Semi-annual coupon
            coupon_amount = face_value * coupon_rate / Decimal("2")
            total_income += coupon_amount

        if total_income <= 0:
            return None

        return AssetIncome(
            symbol=lots[0].symbol if lots else "UNKNOWN",
            income_date=coupon_date,
            income_type="coupon",
            gross_amount=total_income,
            currency=lots[0].currency.value if lots else "USD",
        )
