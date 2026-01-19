"""Data quality validation service."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional, Set
from collections import defaultdict

from models.transaction import Transaction
from models.enums import TransactionType, AssetType


@dataclass
class DataQualityIssue:
    """Single data quality issue."""
    severity: str  # "critical", "warning", "info"
    category: str
    message: str
    affected_records: List[str] = field(default_factory=list)
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "affected_records": self.affected_records,
            "suggestion": self.suggestion,
        }


@dataclass
class DataQualityReport:
    """Complete data quality report."""
    total_records: int = 0
    issues: List[DataQualityIssue] = field(default_factory=list)
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    def add_issue(self, issue: DataQualityIssue) -> None:
        """Add an issue and update counts."""
        self.issues.append(issue)
        if issue.severity == "critical":
            self.critical_count += 1
        elif issue.severity == "warning":
            self.warning_count += 1
        else:
            self.info_count += 1

    @property
    def has_critical_issues(self) -> bool:
        return self.critical_count > 0

    @property
    def is_clean(self) -> bool:
        return self.critical_count == 0 and self.warning_count == 0

    def to_dict(self) -> Dict:
        return {
            "total_records": self.total_records,
            "critical_issues": self.critical_count,
            "warning_issues": self.warning_count,
            "info_issues": self.info_count,
            "is_clean": self.is_clean,
            "issues": [i.to_dict() for i in self.issues],
        }


class DataQualityService:
    """
    Service for validating data quality of transactions and positions.

    Checks for:
    - Data completeness
    - Logical consistency
    - Anomalies and outliers
    - Reference data integrity
    """

    def __init__(self):
        """Initialize data quality service."""
        self._known_symbols: Set[str] = set()
        self._price_history: Dict[str, List[tuple]] = defaultdict(list)

    def validate_transactions(
        self,
        transactions: List[Transaction]
    ) -> DataQualityReport:
        """
        Run all data quality checks on transactions.

        Args:
            transactions: List of transactions to validate

        Returns:
            DataQualityReport with all issues found
        """
        report = DataQualityReport(total_records=len(transactions))

        if not transactions:
            report.add_issue(DataQualityIssue(
                severity="warning",
                category="completeness",
                message="No transactions provided",
            ))
            return report

        # Run all checks
        report = self._check_completeness(transactions, report)
        report = self._check_chronological_order(transactions, report)
        report = self._check_duplicate_transactions(transactions, report)
        report = self._check_negative_positions(transactions, report)
        report = self._check_price_anomalies(transactions, report)
        report = self._check_settlement_dates(transactions, report)
        report = self._check_fx_rates(transactions, report)
        report = self._check_option_fields(transactions, report)
        report = self._check_bond_fields(transactions, report)

        return report

    def _check_completeness(
        self,
        transactions: List[Transaction],
        report: DataQualityReport
    ) -> DataQualityReport:
        """Check for missing required data."""
        missing_symbol = []
        missing_price = []
        zero_quantity = []

        for i, txn in enumerate(transactions, 1):
            txn_id = f"Row {i}: {txn.transaction_date}"

            if not txn.symbol or txn.symbol.strip() == "":
                missing_symbol.append(txn_id)

            if txn.price is None or txn.price == Decimal("0"):
                # Zero price is OK for some transaction types
                if txn.transaction_type not in {
                    TransactionType.STOCK_SPLIT,
                    TransactionType.OPTION_EXPIRY,
                }:
                    missing_price.append(txn_id)

            if txn.quantity == Decimal("0"):
                zero_quantity.append(txn_id)

        if missing_symbol:
            report.add_issue(DataQualityIssue(
                severity="critical",
                category="completeness",
                message="Transactions with missing symbol",
                affected_records=missing_symbol[:10],  # Limit to first 10
                suggestion="Ensure all transactions have a valid symbol",
            ))

        if missing_price:
            report.add_issue(DataQualityIssue(
                severity="warning",
                category="completeness",
                message="Transactions with zero or missing price",
                affected_records=missing_price[:10],
            ))

        if zero_quantity:
            report.add_issue(DataQualityIssue(
                severity="warning",
                category="completeness",
                message="Transactions with zero quantity",
                affected_records=zero_quantity[:10],
            ))

        return report

    def _check_chronological_order(
        self,
        transactions: List[Transaction],
        report: DataQualityReport
    ) -> DataQualityReport:
        """Check if transactions are in chronological order."""
        out_of_order = []
        prev_date = None

        for i, txn in enumerate(transactions, 1):
            if prev_date and txn.transaction_date < prev_date:
                out_of_order.append(f"Row {i}: {txn.transaction_date} < {prev_date}")
            prev_date = txn.transaction_date

        if out_of_order:
            report.add_issue(DataQualityIssue(
                severity="info",
                category="consistency",
                message="Transactions not in chronological order",
                affected_records=out_of_order[:10],
                suggestion="Transactions should be sorted by date for accurate FIFO calculations",
            ))

        return report

    def _check_duplicate_transactions(
        self,
        transactions: List[Transaction],
        report: DataQualityReport
    ) -> DataQualityReport:
        """Check for potential duplicate transactions."""
        seen = defaultdict(list)

        for i, txn in enumerate(transactions, 1):
            key = (
                txn.transaction_date,
                txn.symbol,
                txn.transaction_type,
                txn.quantity,
                txn.price,
            )
            seen[key].append(i)

        duplicates = []
        for key, rows in seen.items():
            if len(rows) > 1:
                duplicates.append(f"Rows {rows}: {key[0]} {key[1]} {key[2].name}")

        if duplicates:
            report.add_issue(DataQualityIssue(
                severity="warning",
                category="consistency",
                message="Potential duplicate transactions detected",
                affected_records=duplicates[:10],
                suggestion="Review these transactions to ensure they are not duplicates",
            ))

        return report

    def _check_negative_positions(
        self,
        transactions: List[Transaction],
        report: DataQualityReport
    ) -> DataQualityReport:
        """Check for transactions that would result in negative positions."""
        positions: Dict[str, Decimal] = defaultdict(Decimal)
        negative_positions = []

        sorted_txns = sorted(transactions, key=lambda t: t.transaction_date)

        for i, txn in enumerate(sorted_txns, 1):
            if txn.is_buy:
                positions[txn.symbol] += txn.quantity
            elif txn.is_sell:
                positions[txn.symbol] -= txn.quantity

                if positions[txn.symbol] < 0:
                    negative_positions.append(
                        f"{txn.transaction_date} {txn.symbol}: "
                        f"selling {txn.quantity} but only have {positions[txn.symbol] + txn.quantity}"
                    )

        if negative_positions:
            report.add_issue(DataQualityIssue(
                severity="critical",
                category="consistency",
                message="Sell transactions exceed available quantity (short selling or missing buys)",
                affected_records=negative_positions[:10],
                suggestion="Check for missing buy transactions or incorrect quantities",
            ))

        return report

    def _check_price_anomalies(
        self,
        transactions: List[Transaction],
        report: DataQualityReport
    ) -> DataQualityReport:
        """Check for unusual price movements."""
        # Build price history by symbol
        prices_by_symbol: Dict[str, List[tuple]] = defaultdict(list)

        for txn in transactions:
            if txn.price > 0:
                prices_by_symbol[txn.symbol].append((txn.transaction_date, txn.price))

        anomalies = []

        for symbol, prices in prices_by_symbol.items():
            if len(prices) < 2:
                continue

            sorted_prices = sorted(prices, key=lambda x: x[0])

            for i in range(1, len(sorted_prices)):
                prev_date, prev_price = sorted_prices[i - 1]
                curr_date, curr_price = sorted_prices[i]

                if prev_price == 0:
                    continue

                # Calculate percentage change
                pct_change = abs((curr_price - prev_price) / prev_price)

                # Flag if price changed more than 50% between transactions
                if pct_change > Decimal("0.5"):
                    anomalies.append(
                        f"{symbol}: {prev_price} -> {curr_price} "
                        f"({float(pct_change * 100):.1f}% change) "
                        f"from {prev_date} to {curr_date}"
                    )

        if anomalies:
            report.add_issue(DataQualityIssue(
                severity="warning",
                category="anomaly",
                message="Large price changes detected (>50%)",
                affected_records=anomalies[:10],
                suggestion="Verify prices are correct; could indicate stock splits or data errors",
            ))

        return report

    def _check_settlement_dates(
        self,
        transactions: List[Transaction],
        report: DataQualityReport
    ) -> DataQualityReport:
        """Check settlement date consistency."""
        issues = []

        for i, txn in enumerate(transactions, 1):
            # Settlement before transaction
            if txn.settlement_date < txn.transaction_date:
                issues.append(
                    f"Row {i}: Settlement {txn.settlement_date} before trade {txn.transaction_date}"
                )

            # Settlement too far in future (more than T+5)
            days_diff = (txn.settlement_date - txn.transaction_date).days
            if days_diff > 5:
                issues.append(
                    f"Row {i}: Settlement T+{days_diff} for {txn.symbol}"
                )

        if issues:
            report.add_issue(DataQualityIssue(
                severity="warning",
                category="consistency",
                message="Settlement date anomalies",
                affected_records=issues[:10],
            ))

        return report

    def _check_fx_rates(
        self,
        transactions: List[Transaction],
        report: DataQualityReport
    ) -> DataQualityReport:
        """Check FX rates for validity."""
        issues = []

        for i, txn in enumerate(transactions, 1):
            if txn.fx_rate <= 0:
                issues.append(f"Row {i}: Invalid FX rate {txn.fx_rate}")
            elif txn.fx_rate > Decimal("1000") or txn.fx_rate < Decimal("0.001"):
                issues.append(f"Row {i}: Unusual FX rate {txn.fx_rate}")

        if issues:
            report.add_issue(DataQualityIssue(
                severity="warning",
                category="validity",
                message="FX rate anomalies",
                affected_records=issues[:10],
            ))

        return report

    def _check_option_fields(
        self,
        transactions: List[Transaction],
        report: DataQualityReport
    ) -> DataQualityReport:
        """Check option-specific fields."""
        issues = []

        for i, txn in enumerate(transactions, 1):
            if not AssetType.is_option(txn.asset_type):
                continue

            if txn.strike_price is None:
                issues.append(f"Row {i}: Option {txn.symbol} missing strike price")
            if txn.expiry_date is None:
                issues.append(f"Row {i}: Option {txn.symbol} missing expiry date")
            if txn.expiry_date and txn.expiry_date < txn.transaction_date:
                issues.append(f"Row {i}: Option {txn.symbol} expiry before transaction")

        if issues:
            report.add_issue(DataQualityIssue(
                severity="warning",
                category="completeness",
                message="Option transactions with missing/invalid fields",
                affected_records=issues[:10],
            ))

        return report

    def _check_bond_fields(
        self,
        transactions: List[Transaction],
        report: DataQualityReport
    ) -> DataQualityReport:
        """Check bond-specific fields."""
        issues = []

        for i, txn in enumerate(transactions, 1):
            if not AssetType.is_fixed_income(txn.asset_type):
                continue

            if txn.maturity_date is None:
                issues.append(f"Row {i}: Bond {txn.symbol} missing maturity date")
            if txn.maturity_date and txn.maturity_date < txn.transaction_date:
                issues.append(f"Row {i}: Bond {txn.symbol} maturity before transaction")
            if txn.coupon_rate is not None and txn.coupon_rate < 0:
                issues.append(f"Row {i}: Bond {txn.symbol} negative coupon rate")

        if issues:
            report.add_issue(DataQualityIssue(
                severity="warning",
                category="completeness",
                message="Bond transactions with missing/invalid fields",
                affected_records=issues[:10],
            ))

        return report
