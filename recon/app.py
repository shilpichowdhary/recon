#!/usr/bin/env python3
"""
PMS Reconciliation Testing Application

A comprehensive Portfolio Management System (PMS) Reconciliation Testing application
that validates PMS calculations by comparing them against independently calculated metrics.

Usage:
    python app.py <transactions_file> [--pms <pms_file>] [--prices <prices_file>] [--output <output_file>]

Examples:
    python app.py transactions.csv
    python app.py transactions.xlsx --pms pms_values.xlsx --output report.xlsx
    python app.py transactions.csv --prices current_prices.csv
"""

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional

from config.settings import settings
from loaders.csv_loader import CSVLoader
from loaders.excel_loader import ExcelLoader
from services.reconciliation_service import ReconciliationService, ReconciliationInput
from services.data_quality_service import DataQualityService
from reports.excel_generator import ExcelReportGenerator


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="PMS Reconciliation Testing Application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s transactions.csv
    %(prog)s transactions.xlsx --pms pms_values.xlsx
    %(prog)s transactions.csv --prices prices.csv --output report.xlsx

Tolerance Thresholds:
    IRR/XIRR: ±0.01%% (1 basis point)
    TWR: ±0.01%%
    Realized P&L: ±$0.01
    Unrealized P&L: ±$0.01
    Total P&L (portfolio): ±$1.00
        """
    )

    parser.add_argument(
        "transactions_file",
        type=Path,
        help="Path to transactions file (CSV or Excel)"
    )

    parser.add_argument(
        "--pms", "-p",
        type=Path,
        dest="pms_file",
        help="Path to PMS values file for comparison (Excel)"
    )

    parser.add_argument(
        "--prices",
        type=Path,
        dest="prices_file",
        help="Path to current prices file (CSV: symbol,price)"
    )

    parser.add_argument(
        "--output", "-o",
        type=Path,
        dest="output_file",
        default=Path("reconciliation_report.xlsx"),
        help="Output report file path (default: reconciliation_report.xlsx)"
    )

    parser.add_argument(
        "--portfolio-id",
        type=str,
        default="default",
        help="Portfolio identifier"
    )

    parser.add_argument(
        "--base-currency",
        type=str,
        default="USD",
        help="Base currency for reporting (default: USD)"
    )

    parser.add_argument(
        "--valuation-date",
        type=str,
        help="Valuation date (YYYY-MM-DD, default: today)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    return parser.parse_args()


def load_transactions(file_path: Path, verbose: bool = False):
    """Load transactions from file."""
    if verbose:
        print(f"Loading transactions from: {file_path}")

    if file_path.suffix.lower() == ".csv":
        loader = CSVLoader()
    elif file_path.suffix.lower() in [".xlsx", ".xls", ".xlsm"]:
        loader = ExcelLoader()
    else:
        print(f"Error: Unsupported file format: {file_path.suffix}")
        sys.exit(1)

    transactions, validation_result = loader.load(file_path)

    if not validation_result.is_valid:
        print("Validation errors:")
        for issue in validation_result.issues:
            print(f"  - {issue}")

    if verbose:
        summary = loader.get_summary()
        print(f"  Loaded {summary.get('count', 0)} transactions")
        print(f"  Date range: {summary.get('date_range', {}).get('start')} to {summary.get('date_range', {}).get('end')}")
        print(f"  Symbols: {summary.get('unique_symbols', 0)}")

    return transactions, loader


def load_prices(file_path: Path, verbose: bool = False) -> Dict[str, Decimal]:
    """Load current prices from CSV file."""
    if verbose:
        print(f"Loading prices from: {file_path}")

    prices = {}

    try:
        import csv
        with open(file_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("symbol", row.get("Symbol", "")).upper()
                price_str = row.get("price", row.get("Price", "0"))
                price_str = price_str.replace(",", "").replace("$", "")
                prices[symbol] = Decimal(price_str)
    except Exception as e:
        print(f"Warning: Error loading prices: {e}")

    if verbose:
        print(f"  Loaded prices for {len(prices)} symbols")

    return prices


def load_pms_values(loader: ExcelLoader, verbose: bool = False) -> Dict[str, any]:
    """Load expected values from PMS file."""
    expected = {}

    # Get expected values from loader
    if hasattr(loader, 'get_expected_values'):
        expected = loader.get_expected_values()

    # Get positions
    if hasattr(loader, 'get_positions'):
        positions = loader.get_positions()
        if positions:
            expected["positions"] = positions

    if verbose and expected:
        print(f"  Loaded {len(expected)} expected metrics")

    return expected


def run_reconciliation(args):
    """Run the reconciliation process."""
    print("=" * 60)
    print("PMS Reconciliation Testing Application")
    print("=" * 60)
    print()

    # Load transactions
    transactions, loader = load_transactions(args.transactions_file, args.verbose)

    if not transactions:
        print("Error: No transactions loaded. Check input file.")
        sys.exit(1)

    # Load current prices
    if args.prices_file:
        current_prices = load_prices(args.prices_file, args.verbose)
    else:
        # Use last transaction price for each symbol as default
        current_prices = {}
        for txn in sorted(transactions, key=lambda t: t.transaction_date):
            current_prices[txn.symbol] = txn.price
        if args.verbose:
            print(f"Using transaction prices for {len(current_prices)} symbols")

    # Load PMS values for comparison
    expected_values = {}
    if args.pms_file:
        pms_loader = ExcelLoader()
        pms_loader.load(args.pms_file)
        expected_values = load_pms_values(pms_loader, args.verbose)
    elif isinstance(loader, ExcelLoader):
        expected_values = load_pms_values(loader, args.verbose)

    # Parse valuation date
    if args.valuation_date:
        from utils.date_utils import parse_date
        valuation_date = parse_date(args.valuation_date)
    else:
        valuation_date = date.today()

    print()
    print("Running reconciliation...")
    print()

    # Create reconciliation input
    recon_input = ReconciliationInput(
        transactions=transactions,
        current_prices=current_prices,
        expected_values=expected_values,
        portfolio_id=args.portfolio_id,
        valuation_date=valuation_date,
        base_currency=args.base_currency,
    )

    # Run reconciliation
    recon_service = ReconciliationService()
    recon_result = recon_service.run_reconciliation(recon_input)

    # Get additional data for report
    lot_details = recon_service.get_lot_details()
    cash_flow_summary = recon_service.get_cash_flow_summary(transactions)

    # Print summary
    summary = recon_result.get_summary()
    print("Reconciliation Results:")
    print("-" * 40)
    print(f"  Portfolio ID: {summary['portfolio_id']}")
    print(f"  Date: {summary['reconciliation_date']}")
    print(f"  Total Checks: {summary['total_checks']}")
    print(f"  Passed: {summary['passed']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Pass Rate: {summary['pass_rate']}")
    print()

    if recon_result.is_fully_reconciled:
        print("  STATUS: PASS - All reconciliation checks passed")
    else:
        print("  STATUS: FAIL - Some reconciliation checks failed")
        print()
        print("  Failed Items:")
        for result in recon_result.failed_results[:10]:
            print(f"    - {result.metric_name}: "
                  f"calculated={float(result.calculated_value):.4f}, "
                  f"expected={float(result.expected_value):.4f}, "
                  f"diff={float(result.difference):.4f}")

    print()

    # Generate Excel report
    print(f"Generating report: {args.output_file}")

    report_generator = ExcelReportGenerator(args.output_file)

    # Get portfolio P&L for report
    from calculators.pnl_calculator import PnLCalculator
    pnl_calc = PnLCalculator()
    pnl_calc.process_transactions(transactions)
    portfolio_pnl = pnl_calc.calculate_unrealized_pnl(current_prices)

    report_path = report_generator.generate_report(
        reconciliation=recon_result,
        transactions=transactions,
        portfolio_pnl=portfolio_pnl,
        lot_details=lot_details,
        cash_flow_summary=cash_flow_summary,
        data_quality_issues=recon_result.data_quality_issues,
    )

    print(f"Report generated: {report_path}")
    print()
    print("=" * 60)

    # Return exit code based on reconciliation result
    return 0 if recon_result.is_fully_reconciled else 1


def main():
    """Main entry point."""
    args = parse_args()

    try:
        exit_code = run_reconciliation(args)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nError: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
