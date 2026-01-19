"""Core reconciliation service."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Dict, Optional, Any

from config.tolerances import tolerances, Tolerances
from models.transaction import Transaction
from models.performance import (
    PerformanceMetrics,
    ReconciliationResult,
    ReconciliationStatus,
    PortfolioReconciliation,
)
from models.enums import AssetType
from calculators.irr_calculator import IRRCalculator, CashFlow
from calculators.twr_calculator import TWRCalculator
from calculators.pnl_calculator import PnLCalculator, PortfolioPnL
from services.lot_tracking_service import LotTrackingService
from services.data_quality_service import DataQualityService, DataQualityReport


@dataclass
class ReconciliationInput:
    """Input data for reconciliation."""
    transactions: List[Transaction]
    current_prices: Dict[str, Decimal]
    expected_values: Dict[str, Any] = field(default_factory=dict)
    portfolio_id: str = "default"
    valuation_date: date = field(default_factory=date.today)
    base_currency: str = "USD"
    fx_rates: Dict[str, Decimal] = field(default_factory=dict)


class ReconciliationService:
    """
    Core reconciliation service.

    Orchestrates all calculations and compares against expected values
    from PMS to generate pass/fail results.
    """

    def __init__(self, tolerances_config: Optional[Tolerances] = None):
        """
        Initialize reconciliation service.

        Args:
            tolerances_config: Custom tolerances (uses defaults if None)
        """
        self.tolerances = tolerances_config or tolerances
        self.irr_calculator = IRRCalculator()
        self.twr_calculator = TWRCalculator()
        self.pnl_calculator = PnLCalculator()
        self.lot_service = LotTrackingService()
        self.data_quality_service = DataQualityService()

    def run_reconciliation(
        self,
        input_data: ReconciliationInput
    ) -> PortfolioReconciliation:
        """
        Run full portfolio reconciliation.

        Args:
            input_data: ReconciliationInput with all required data

        Returns:
            PortfolioReconciliation with all results
        """
        recon = PortfolioReconciliation(
            portfolio_id=input_data.portfolio_id,
            reconciliation_date=input_data.valuation_date,
            base_currency=input_data.base_currency,
        )

        # Step 1: Data quality checks
        dq_report = self.data_quality_service.validate_transactions(input_data.transactions)
        for issue in dq_report.issues:
            recon.add_data_quality_issue(str(issue))

        if dq_report.has_critical_issues:
            recon.add_result(ReconciliationResult(
                metric_name="data_quality",
                calculated_value=Decimal(str(dq_report.critical_count)),
                expected_value=Decimal("0"),
                tolerance=Decimal("0"),
                notes="Critical data quality issues found",
            ))
            # Continue with reconciliation but flag issues

        # Step 2: Calculate P&L using FIFO
        portfolio_pnl = self._calculate_pnl(
            input_data.transactions,
            input_data.current_prices,
            input_data.fx_rates,
        )

        # Step 3: Calculate performance metrics
        calculated_metrics = self._calculate_performance(
            input_data.transactions,
            portfolio_pnl,
            input_data.valuation_date,
        )

        recon.calculated_metrics = calculated_metrics

        # Step 4: Reconcile against expected values
        expected = input_data.expected_values

        # Reconcile IRR/XIRR
        if "irr" in expected or "xirr" in expected:
            expected_irr = Decimal(str(expected.get("xirr", expected.get("irr", 0))))
            if calculated_metrics.xirr is not None:
                recon.add_result(ReconciliationResult(
                    metric_name="XIRR",
                    calculated_value=calculated_metrics.xirr,
                    expected_value=expected_irr,
                    tolerance=self.tolerances.xirr,
                ))

        # Reconcile TWR
        if "twr" in expected:
            expected_twr = Decimal(str(expected["twr"]))
            if calculated_metrics.twr is not None:
                recon.add_result(ReconciliationResult(
                    metric_name="TWR",
                    calculated_value=calculated_metrics.twr,
                    expected_value=expected_twr,
                    tolerance=self.tolerances.twr,
                ))

        # Reconcile realized P&L
        if "realized_pnl" in expected:
            recon.add_result(ReconciliationResult(
                metric_name="Realized P&L",
                calculated_value=calculated_metrics.realized_pnl,
                expected_value=Decimal(str(expected["realized_pnl"])),
                tolerance=self.tolerances.realized_pnl,
            ))

        # Reconcile unrealized P&L
        if "unrealized_pnl" in expected:
            recon.add_result(ReconciliationResult(
                metric_name="Unrealized P&L",
                calculated_value=calculated_metrics.unrealized_pnl,
                expected_value=Decimal(str(expected["unrealized_pnl"])),
                tolerance=self.tolerances.unrealized_pnl,
            ))

        # Reconcile total P&L
        if "total_pnl" in expected:
            recon.add_result(ReconciliationResult(
                metric_name="Total P&L",
                calculated_value=calculated_metrics.total_pnl,
                expected_value=Decimal(str(expected["total_pnl"])),
                tolerance=self.tolerances.total_pnl_portfolio,
            ))

        # Reconcile market value
        if "market_value" in expected:
            recon.add_result(ReconciliationResult(
                metric_name="Market Value",
                calculated_value=calculated_metrics.total_market_value,
                expected_value=Decimal(str(expected["market_value"])),
                tolerance=self.tolerances.market_value,
            ))

        # Reconcile cost basis
        if "cost_basis" in expected:
            recon.add_result(ReconciliationResult(
                metric_name="Cost Basis",
                calculated_value=calculated_metrics.total_cost_basis,
                expected_value=Decimal(str(expected["cost_basis"])),
                tolerance=self.tolerances.market_value,
            ))

        # Position-level reconciliation
        self._reconcile_positions(recon, portfolio_pnl, expected)

        return recon

    def _calculate_pnl(
        self,
        transactions: List[Transaction],
        current_prices: Dict[str, Decimal],
        fx_rates: Dict[str, Decimal],
    ) -> PortfolioPnL:
        """Calculate P&L using FIFO lot matching."""
        self.pnl_calculator = PnLCalculator()
        self.pnl_calculator.process_transactions(transactions)
        return self.pnl_calculator.calculate_unrealized_pnl(current_prices, fx_rates)

    def _calculate_performance(
        self,
        transactions: List[Transaction],
        portfolio_pnl: PortfolioPnL,
        valuation_date: date,
    ) -> PerformanceMetrics:
        """Calculate all performance metrics."""
        metrics = PerformanceMetrics(
            realized_pnl=portfolio_pnl.total_realized_pnl,
            unrealized_pnl=portfolio_pnl.total_unrealized_pnl,
            total_pnl=portfolio_pnl.total_pnl,
            dividend_income=portfolio_pnl.dividend_income,
            interest_income=portfolio_pnl.interest_income,
            total_cost_basis=portfolio_pnl.total_cost_basis,
            total_market_value=portfolio_pnl.total_market_value,
            end_date=valuation_date,
        )

        # Calculate XIRR from cash flows
        cash_flows = self._build_cash_flows(transactions, portfolio_pnl, valuation_date)
        if cash_flows and len(cash_flows) >= 2:
            metrics.xirr = self.irr_calculator.calculate_xirr(cash_flows)
            metrics.irr = metrics.xirr

        # Calculate TWR
        if transactions:
            sorted_txns = sorted(transactions, key=lambda t: t.transaction_date)
            start_date = sorted_txns[0].transaction_date
            metrics.start_date = start_date

            # Build cash flow list for TWR
            twr_cash_flows = [
                (t.transaction_date, t.to_cash_flow())
                for t in sorted_txns
                if t.to_cash_flow() != Decimal("0")
            ]

            # Need starting and ending values
            # Simplified: use deposits as starting value
            start_value = sum(
                t.net_amount for t in sorted_txns
                if t.transaction_type.name == "DEPOSIT"
            )

            if start_value > 0:
                metrics.twr = self.twr_calculator.calculate_twr_from_transactions(
                    start_value=start_value,
                    end_value=portfolio_pnl.total_market_value + portfolio_pnl.total_realized_pnl,
                    start_date=start_date,
                    end_date=valuation_date,
                    cash_flows=twr_cash_flows,
                )

                if metrics.twr is not None:
                    metrics.twr_annualized = self.twr_calculator.calculate_annualized_twr(
                        metrics.twr, start_date, valuation_date
                    )

        return metrics

    def _build_cash_flows(
        self,
        transactions: List[Transaction],
        portfolio_pnl: PortfolioPnL,
        valuation_date: date,
    ) -> List[CashFlow]:
        """Build cash flow list for IRR calculation."""
        cash_flows = []

        for txn in transactions:
            cf_amount = txn.to_cash_flow()
            if cf_amount != Decimal("0"):
                cash_flows.append(CashFlow(
                    date=txn.transaction_date,
                    amount=cf_amount,
                ))

        # Add terminal value (current portfolio value)
        if portfolio_pnl.total_market_value > 0:
            cash_flows.append(CashFlow(
                date=valuation_date,
                amount=portfolio_pnl.total_market_value,
            ))

        return cash_flows

    def _reconcile_positions(
        self,
        recon: PortfolioReconciliation,
        portfolio_pnl: PortfolioPnL,
        expected: Dict[str, Any],
    ) -> None:
        """Reconcile individual position values."""
        expected_positions = expected.get("positions", {})

        for symbol, position in portfolio_pnl.positions.items():
            exp_pos = expected_positions.get(symbol, {})

            if not exp_pos:
                continue

            # Reconcile quantity
            if "quantity" in exp_pos:
                recon.add_result(ReconciliationResult(
                    metric_name="Quantity",
                    calculated_value=position.quantity,
                    expected_value=Decimal(str(exp_pos["quantity"])),
                    tolerance=self.tolerances.quantity,
                    symbol=symbol,
                ))

            # Reconcile cost basis
            if "cost_basis" in exp_pos:
                recon.add_result(ReconciliationResult(
                    metric_name="Cost Basis",
                    calculated_value=position.cost_basis,
                    expected_value=Decimal(str(exp_pos["cost_basis"])),
                    tolerance=self.tolerances.market_value,
                    symbol=symbol,
                ))

            # Reconcile market value
            if "market_value" in exp_pos:
                recon.add_result(ReconciliationResult(
                    metric_name="Market Value",
                    calculated_value=position.market_value,
                    expected_value=Decimal(str(exp_pos["market_value"])),
                    tolerance=self.tolerances.market_value,
                    symbol=symbol,
                ))

            # Reconcile unrealized P&L
            if "unrealized_pnl" in exp_pos:
                recon.add_result(ReconciliationResult(
                    metric_name="Unrealized P&L",
                    calculated_value=position.unrealized_pnl,
                    expected_value=Decimal(str(exp_pos["unrealized_pnl"])),
                    tolerance=self.tolerances.unrealized_pnl,
                    symbol=symbol,
                ))

    def get_lot_details(self) -> Dict[str, List[Dict]]:
        """Get detailed lot information for all positions."""
        result = {}
        for symbol in self.pnl_calculator._lot_queues:
            result[symbol] = self.pnl_calculator.get_lot_details(symbol)
        return result

    def get_disposal_history(self) -> Dict[str, List[Dict]]:
        """Get disposal history for all positions."""
        result = {}
        for symbol in self.pnl_calculator._lot_queues:
            history = self.pnl_calculator.get_disposal_history(symbol)
            if history:
                result[symbol] = history
        return result

    def get_cash_flow_summary(
        self,
        transactions: List[Transaction]
    ) -> Dict[str, Any]:
        """Generate cash flow summary."""
        inflows = Decimal("0")
        outflows = Decimal("0")
        income = Decimal("0")

        for txn in transactions:
            cf = txn.to_cash_flow()
            if cf > 0:
                if txn.transaction_type.name in {"DIVIDEND", "INTEREST", "COUPON"}:
                    income += cf
                else:
                    inflows += cf
            elif cf < 0:
                outflows += abs(cf)

        return {
            "total_inflows": float(inflows),
            "total_outflows": float(outflows),
            "total_income": float(income),
            "net_cash_flow": float(inflows - outflows + income),
            "transaction_count": len(transactions),
        }
