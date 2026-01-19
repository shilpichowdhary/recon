"""Performance metric models."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict
from enum import Enum


class ReconciliationStatus(Enum):
    """Status of reconciliation check."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_APPLICABLE = "N/A"


@dataclass
class PerformanceMetrics:
    """Container for calculated performance metrics."""

    # Return metrics
    irr: Optional[Decimal] = None
    xirr: Optional[Decimal] = None
    twr: Optional[Decimal] = None
    twr_annualized: Optional[Decimal] = None

    # P&L metrics
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")

    # Income
    dividend_income: Decimal = Decimal("0")
    interest_income: Decimal = Decimal("0")
    total_income: Decimal = Decimal("0")

    # Position metrics
    total_cost_basis: Decimal = Decimal("0")
    total_market_value: Decimal = Decimal("0")

    # Period
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Additional metrics
    sharpe_ratio: Optional[Decimal] = None
    max_drawdown: Optional[Decimal] = None
    volatility: Optional[Decimal] = None

    def __post_init__(self):
        """Calculate derived fields."""
        self.total_pnl = self.realized_pnl + self.unrealized_pnl
        self.total_income = self.dividend_income + self.interest_income


@dataclass
class ReconciliationResult:
    """Result of a single reconciliation check."""

    metric_name: str
    calculated_value: Decimal
    expected_value: Decimal
    tolerance: Decimal
    difference: Decimal = field(init=False)
    status: ReconciliationStatus = field(init=False)

    # Additional context
    symbol: Optional[str] = None
    asset_type: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self):
        """Calculate difference and determine status."""
        self.difference = self.calculated_value - self.expected_value

        if abs(self.difference) <= self.tolerance:
            self.status = ReconciliationStatus.PASS
        else:
            self.status = ReconciliationStatus.FAIL

    @property
    def is_pass(self) -> bool:
        """Check if reconciliation passed."""
        return self.status == ReconciliationStatus.PASS

    @property
    def percentage_difference(self) -> Optional[Decimal]:
        """Calculate percentage difference if expected is non-zero."""
        if self.expected_value == Decimal("0"):
            return None
        return (self.difference / self.expected_value) * Decimal("100")

    def to_dict(self) -> dict:
        """Convert to dictionary for reporting."""
        return {
            "metric": self.metric_name,
            "calculated": float(self.calculated_value),
            "expected": float(self.expected_value),
            "difference": float(self.difference),
            "tolerance": float(self.tolerance),
            "status": self.status.value,
            "symbol": self.symbol,
            "notes": self.notes,
        }


@dataclass
class PortfolioReconciliation:
    """Container for full portfolio reconciliation results."""

    portfolio_id: str
    reconciliation_date: date
    base_currency: str = "USD"

    # Aggregated results
    results: List[ReconciliationResult] = field(default_factory=list)

    # Performance comparison
    calculated_metrics: Optional[PerformanceMetrics] = None
    expected_metrics: Optional[PerformanceMetrics] = None

    # Position-level results
    position_results: Dict[str, List[ReconciliationResult]] = field(default_factory=dict)

    # Data quality issues
    data_quality_issues: List[str] = field(default_factory=list)

    # Summary statistics
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    warning_checks: int = 0

    def add_result(self, result: ReconciliationResult) -> None:
        """Add a reconciliation result and update statistics."""
        self.results.append(result)
        self.total_checks += 1

        if result.status == ReconciliationStatus.PASS:
            self.passed_checks += 1
        elif result.status == ReconciliationStatus.FAIL:
            self.failed_checks += 1
        elif result.status == ReconciliationStatus.WARNING:
            self.warning_checks += 1

        # Add to position-level results if symbol is specified
        if result.symbol:
            if result.symbol not in self.position_results:
                self.position_results[result.symbol] = []
            self.position_results[result.symbol].append(result)

    def add_data_quality_issue(self, issue: str) -> None:
        """Add a data quality issue."""
        self.data_quality_issues.append(issue)

    @property
    def pass_rate(self) -> Decimal:
        """Calculate pass rate as percentage."""
        if self.total_checks == 0:
            return Decimal("100")
        return Decimal(str(self.passed_checks / self.total_checks * 100))

    @property
    def is_fully_reconciled(self) -> bool:
        """Check if all reconciliation checks passed."""
        return self.failed_checks == 0

    @property
    def failed_results(self) -> List[ReconciliationResult]:
        """Get list of failed reconciliation results."""
        return [r for r in self.results if r.status == ReconciliationStatus.FAIL]

    def get_summary(self) -> dict:
        """Get summary dictionary for reporting."""
        return {
            "portfolio_id": self.portfolio_id,
            "reconciliation_date": self.reconciliation_date.isoformat(),
            "base_currency": self.base_currency,
            "total_checks": self.total_checks,
            "passed": self.passed_checks,
            "failed": self.failed_checks,
            "warnings": self.warning_checks,
            "pass_rate": f"{self.pass_rate:.2f}%",
            "fully_reconciled": self.is_fully_reconciled,
            "data_quality_issues": len(self.data_quality_issues),
        }
