"""
Streamlit Frontend for PMS Reconciliation Testing Application

Run with: streamlit run streamlit_app.py
"""

import streamlit as st
import pandas as pd
from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
import io

from loaders.csv_loader import CSVLoader
from loaders.excel_loader import ExcelLoader
from services.reconciliation_service import ReconciliationService, ReconciliationInput
from calculators.pnl_calculator import PnLCalculator
from reports.excel_generator import ExcelReportGenerator


# Page configuration
st.set_page_config(
    page_title="PMS Reconciliation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E3A8A;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #64748B;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #F8FAFC;
        border-radius: 10px;
        padding: 1rem;
        border: 1px solid #E2E8F0;
    }
    .pass-status {
        color: #16A34A;
        font-weight: bold;
        font-size: 1.5rem;
    }
    .fail-status {
        color: #DC2626;
        font-weight: bold;
        font-size: 1.5rem;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """Main Streamlit application."""

    # Header
    st.markdown('<p class="main-header">📊 PMS Reconciliation Testing</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Validate PMS calculations against independently calculated metrics</p>', unsafe_allow_html=True)

    # Sidebar for inputs
    with st.sidebar:
        st.header("📁 Data Input")

        # Transaction file upload
        st.subheader("1. Transactions (Required)")
        transactions_file = st.file_uploader(
            "Upload transaction file",
            type=["csv", "xlsx", "xls"],
            help="CSV or Excel file with transaction data"
        )

        # PMS comparison file (optional)
        st.subheader("2. PMS Values (Optional)")
        pms_file = st.file_uploader(
            "Upload PMS comparison file",
            type=["csv", "xlsx", "xls"],
            help="Expected values from your PMS for comparison"
        )

        # Current prices file (optional)
        st.subheader("3. Current Prices (Optional)")
        prices_file = st.file_uploader(
            "Upload current prices",
            type=["csv", "xlsx", "xls"],
            help="CSV or Excel with columns: symbol, price"
        )

        st.divider()

        # Settings
        st.header("⚙️ Settings")

        # Mode selection
        calc_mode = st.radio(
            "Mode",
            ["Calculate Only", "Compare to PMS"],
            help="Calculate Only: Compute metrics independently. Compare to PMS: Upload expected values to reconcile."
        )

        portfolio_id = st.text_input("Portfolio ID", value="default")
        base_currency = st.selectbox("Base Currency", ["USD", "EUR", "GBP", "CHF", "JPY"], index=0)
        valuation_date = st.date_input("Valuation Date", value=date.today())

        st.divider()

        # Run button
        button_label = "🧮 Calculate Performance" if calc_mode == "Calculate Only" else "🚀 Run Reconciliation"
        run_button = st.button(button_label, type="primary", use_container_width=True)

    # Main content area
    if transactions_file is None:
        # Show instructions when no file uploaded
        st.info("👈 Upload a transaction file in the sidebar to get started")

        with st.expander("📖 Input File Format", expanded=True):
            st.markdown("""
            **Required CSV columns:**
            - `transaction_date` - Date of transaction (YYYY-MM-DD)
            - `transaction_type` - BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, etc.
            - `symbol` - Security symbol (e.g., AAPL, GOOGL)
            - `quantity` - Number of shares/units
            - `price` - Price per share
            - `currency` - Currency code (USD, EUR, etc.)

            **Optional columns:**
            - `settlement_date` - Settlement date
            - `asset_type` - EQUITY, ETF, BOND, CALL_OPTION, etc.
            - `commission`, `fees`, `taxes` - Transaction costs
            - `fx_rate` - FX rate to base currency
            """)

            # Sample data
            st.markdown("**Sample Data:**")
            sample_df = pd.DataFrame({
                "transaction_date": ["2024-01-15", "2024-02-01", "2024-03-01"],
                "transaction_type": ["BUY", "BUY", "SELL"],
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "quantity": [100, 50, 75],
                "price": [150.00, 155.00, 160.00],
                "currency": ["USD", "USD", "USD"],
                "commission": [5.00, 5.00, 5.00]
            })
            st.dataframe(sample_df, use_container_width=True)

        with st.expander("📊 Tolerance Thresholds"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("""
                | Metric | Tolerance |
                |--------|-----------|
                | IRR/XIRR | ±0.01% |
                | TWR | ±0.01% |
                | YTM | ±0.01% |
                """)
            with col2:
                st.markdown("""
                | Metric | Tolerance |
                |--------|-----------|
                | Realized P&L | ±$0.01 |
                | Unrealized P&L | ±$0.01 |
                | Total P&L (Portfolio) | ±$1.00 |
                """)

    elif run_button:
        # Run reconciliation
        spinner_text = "Calculating performance metrics..." if calc_mode == "Calculate Only" else "Running reconciliation..."
        with st.spinner(spinner_text):
            try:
                result = run_reconciliation(
                    transactions_file,
                    pms_file if calc_mode == "Compare to PMS" else None,  # Ignore PMS file in Calculate Only mode
                    prices_file,
                    portfolio_id,
                    base_currency,
                    valuation_date
                )

                if result:
                    result['calc_mode'] = calc_mode
                    display_results(result)

            except Exception as e:
                st.error(f"Error running reconciliation: {str(e)}")
                st.exception(e)

    elif transactions_file:
        # File uploaded but not yet run
        st.success(f"✅ File uploaded: {transactions_file.name}")

        # Preview the data
        try:
            if transactions_file.name.endswith('.csv'):
                df = pd.read_csv(transactions_file)
            else:
                df = pd.read_excel(transactions_file)

            transactions_file.seek(0)  # Reset file pointer

            st.subheader("📋 Data Preview")
            st.dataframe(df.head(10), use_container_width=True)

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Rows", len(df))
            with col2:
                st.metric("Columns", len(df.columns))
            with col3:
                if 'symbol' in df.columns:
                    st.metric("Unique Symbols", df['symbol'].nunique())

            st.info("👈 Click 'Run Reconciliation' in the sidebar to process")

        except Exception as e:
            st.error(f"Error reading file: {str(e)}")


def run_reconciliation(transactions_file, pms_file, prices_file, portfolio_id, base_currency, valuation_date):
    """Run the reconciliation process."""

    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(transactions_file.name).suffix) as tmp:
        tmp.write(transactions_file.getvalue())
        tmp_path = Path(tmp.name)

    try:
        # Load transactions
        if tmp_path.suffix.lower() == '.csv':
            loader = CSVLoader()
        else:
            loader = ExcelLoader()

        transactions, validation_result = loader.load(tmp_path)

        if not transactions:
            st.error("No transactions loaded. Please check your file format.")
            return None

        # Show validation warnings if any
        if validation_result.warnings_count > 0:
            with st.expander(f"⚠️ {validation_result.warnings_count} Validation Warnings"):
                for issue in validation_result.issues:
                    if issue.severity.value == "WARNING":
                        st.warning(f"{issue.field}: {issue.message}")

        # Load current prices
        current_prices = {}
        if prices_file:
            # Handle both CSV and Excel
            if prices_file.name.endswith('.csv'):
                prices_df = pd.read_csv(prices_file)
            else:
                prices_df = pd.read_excel(prices_file)

            # Normalize column names to lowercase
            prices_df.columns = [str(c).lower().strip() for c in prices_df.columns]

            for _, row in prices_df.iterrows():
                # Try various column names for symbol
                symbol = str(
                    row.get('symbol') or
                    row.get('instrument id') or
                    row.get('ticker') or
                    row.get('security') or
                    ''
                ).upper().strip()

                # Try various column names for price
                price = (
                    row.get('price') or
                    row.get('current price') or
                    row.get('market price') or
                    row.get('last price') or
                    0
                )

                if symbol and price:
                    try:
                        current_prices[symbol] = Decimal(str(price))
                    except:
                        pass

        # Use last transaction price as default for missing symbols
        for txn in sorted(transactions, key=lambda t: t.transaction_date):
            if txn.symbol not in current_prices and txn.price and txn.price > 0:
                current_prices[txn.symbol] = txn.price

        # Load PMS expected values
        expected_values = {}
        if pms_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(pms_file.name).suffix) as tmp_pms:
                tmp_pms.write(pms_file.getvalue())
                pms_path = Path(tmp_pms.name)

            try:
                if pms_path.suffix.lower() == '.csv':
                    pms_df = pd.read_csv(pms_path)
                    for _, row in pms_df.iterrows():
                        metric = str(row.get('metric', row.get('Metric', ''))).lower()
                        value = row.get('value', row.get('Value', 0))
                        if metric:
                            expected_values[metric] = Decimal(str(value))
                else:
                    pms_loader = ExcelLoader()
                    pms_loader.load(pms_path)
                    expected_values = pms_loader.get_expected_values()
            finally:
                pms_path.unlink()

        # Run reconciliation
        recon_input = ReconciliationInput(
            transactions=transactions,
            current_prices=current_prices,
            expected_values=expected_values,
            portfolio_id=portfolio_id,
            valuation_date=valuation_date,
            base_currency=base_currency,
        )

        recon_service = ReconciliationService()
        recon_result = recon_service.run_reconciliation(recon_input)

        # Calculate P&L for display
        pnl_calculator = PnLCalculator()
        pnl_calculator.process_transactions(transactions)
        portfolio_pnl = pnl_calculator.calculate_unrealized_pnl(current_prices)

        # Get additional data
        lot_details = recon_service.get_lot_details()
        cash_flow_summary = recon_service.get_cash_flow_summary(transactions)

        return {
            'reconciliation': recon_result,
            'transactions': transactions,
            'portfolio_pnl': portfolio_pnl,
            'lot_details': lot_details,
            'cash_flow_summary': cash_flow_summary,
            'loader_summary': loader.get_summary(),
        }

    finally:
        tmp_path.unlink()


def display_results(result):
    """Display reconciliation results."""

    recon = result['reconciliation']
    pnl = result['portfolio_pnl']
    summary = recon.get_summary()
    calc_mode = result.get('calc_mode', 'Calculate Only')

    # Check if we have comparison data
    has_comparison = summary['total_checks'] > 0

    # Overall status based on mode
    if calc_mode == "Calculate Only":
        st.header("📊 Performance Calculation Results")
        st.success("✅ **Calculation Complete** - Use these values to compare against your PMS data")
    else:
        st.header("📊 Reconciliation Results")
        if not has_comparison:
            st.warning("⚠️ **No PMS comparison data provided** - Upload a PMS values file to compare.")
        elif recon.is_fully_reconciled:
            st.success(f"✅ **PASS** - All {summary['total_checks']} reconciliation checks passed")
        else:
            st.error(f"❌ **FAIL** - {summary['failed']} of {summary['total_checks']} check(s) failed")

    # Summary metrics - show calculated values prominently
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total P&L", f"${float(pnl.total_pnl):,.2f}")
    with col2:
        st.metric("Realized P&L", f"${float(pnl.total_realized_pnl):,.2f}")
    with col3:
        st.metric("Unrealized P&L", f"${float(pnl.total_unrealized_pnl):,.2f}")
    with col4:
        st.metric("Positions", len(pnl.positions))

    # Show reconciliation summary if in comparison mode with data
    if has_comparison and calc_mode == "Compare to PMS":
        st.divider()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Checks", summary['total_checks'])
        with col2:
            st.metric("Passed", summary['passed'], delta=None)
        with col3:
            st.metric("Failed", summary['failed'], delta=None, delta_color="inverse")
        with col4:
            st.metric("Pass Rate", summary['pass_rate'])

    st.divider()

    # Tabs for different views
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Performance",
        "💰 P&L Summary",
        "📈 Positions",
        "📦 FIFO Lots",
        "💵 Cash Flows",
        "📥 Download Report"
    ])

    with tab1:
        display_performance_metrics(recon, pnl, has_comparison, calc_mode)

    with tab2:
        display_pnl_summary(pnl, result['cash_flow_summary'])

    with tab3:
        display_positions(pnl)

    with tab4:
        display_lots(result['lot_details'])

    with tab5:
        display_cash_flows(result['transactions'], result['cash_flow_summary'])

    with tab6:
        generate_download(result)


def display_performance_metrics(recon, pnl, has_comparison, calc_mode="Calculate Only"):
    """Display performance metrics (XIRR, TWR, P&L)."""

    if calc_mode == "Calculate Only":
        st.subheader("📋 Independent Calculation Results")
        st.info("Compare these calculated values against your PMS to identify discrepancies")
    else:
        st.subheader("Calculated Performance Metrics")

    metrics = recon.calculated_metrics

    # Performance returns
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Investment Returns**")
        xirr_val = f"{float(metrics.xirr) * 100:.2f}%" if metrics.xirr else "N/A"
        twr_val = f"{float(metrics.twr) * 100:.2f}%" if metrics.twr else "N/A"
        twr_ann = f"{float(metrics.twr_annualized) * 100:.2f}%" if metrics.twr_annualized else "N/A"

        returns_df = pd.DataFrame({
            'Metric': ['XIRR (Money-Weighted)', 'TWR (Time-Weighted)', 'TWR Annualized'],
            'Value': [xirr_val, twr_val, twr_ann]
        })
        st.dataframe(returns_df, use_container_width=True, hide_index=True)

    with col2:
        st.markdown("**P&L Summary**")
        pnl_df = pd.DataFrame({
            'Metric': ['Realized P&L', 'Unrealized P&L', 'Total P&L'],
            'Value': [
                f"${float(metrics.realized_pnl):,.2f}",
                f"${float(metrics.unrealized_pnl):,.2f}",
                f"${float(metrics.total_pnl):,.2f}",
            ]
        })
        st.dataframe(pnl_df, use_container_width=True, hide_index=True)

    with col3:
        st.markdown("**Income**")
        income_df = pd.DataFrame({
            'Metric': ['Dividend Income', 'Interest Income', 'Total Income'],
            'Value': [
                f"${float(metrics.dividend_income):,.2f}",
                f"${float(metrics.interest_income):,.2f}",
                f"${float(metrics.total_income):,.2f}",
            ]
        })
        st.dataframe(income_df, use_container_width=True, hide_index=True)

    # Show comparison results if available
    if has_comparison:
        st.divider()
        st.subheader("Reconciliation Details")

        recon_data = []
        for r in recon.results:
            recon_data.append({
                'Metric': r.metric_name,
                'Symbol': r.symbol or 'Portfolio',
                'Calculated': float(r.calculated_value),
                'Expected': float(r.expected_value),
                'Difference': float(r.difference),
                'Tolerance': float(r.tolerance),
                'Status': '✅ PASS' if r.is_pass else '❌ FAIL',
            })

        if recon_data:
            df = pd.DataFrame(recon_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No reconciliation checks to display")


def display_pnl_summary(pnl, cash_summary):
    """Display P&L summary."""

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("P&L Breakdown")

        metrics_df = pd.DataFrame({
            'Metric': ['Realized P&L', 'Unrealized P&L', 'Total P&L', 'Dividend Income', 'Interest Income'],
            'Value': [
                f"${float(pnl.total_realized_pnl):,.2f}",
                f"${float(pnl.total_unrealized_pnl):,.2f}",
                f"${float(pnl.total_pnl):,.2f}",
                f"${float(pnl.dividend_income):,.2f}",
                f"${float(pnl.interest_income):,.2f}",
            ]
        })
        st.dataframe(metrics_df, use_container_width=True, hide_index=True)

    with col2:
        st.subheader("Portfolio Summary")

        summary_df = pd.DataFrame({
            'Metric': ['Total Cost Basis', 'Total Market Value', 'Total Positions'],
            'Value': [
                f"${float(pnl.total_cost_basis):,.2f}",
                f"${float(pnl.total_market_value):,.2f}",
                len(pnl.positions)
            ]
        })
        st.dataframe(summary_df, use_container_width=True, hide_index=True)


def display_positions(pnl):
    """Display position details."""

    st.subheader("Position Details")

    if not pnl.positions:
        st.info("No positions to display")
        return

    positions_data = []
    for symbol, pos in pnl.positions.items():
        positions_data.append({
            'Symbol': symbol,
            'Quantity': float(pos.quantity),
            'Avg Cost': float(pos.average_cost),
            'Current Price': float(pos.current_price),
            'Cost Basis': float(pos.cost_basis),
            'Market Value': float(pos.market_value),
            'Realized P&L': float(pos.realized_pnl),
            'Unrealized P&L': float(pos.unrealized_pnl),
            'Total P&L': float(pos.total_pnl),
        })

    df = pd.DataFrame(positions_data)

    # Format currency columns
    currency_cols = ['Avg Cost', 'Current Price', 'Cost Basis', 'Market Value', 'Realized P&L', 'Unrealized P&L', 'Total P&L']

    st.dataframe(
        df.style.format({col: "${:,.2f}" for col in currency_cols}),
        use_container_width=True,
        hide_index=True
    )


def display_lots(lot_details):
    """Display FIFO lot details."""

    st.subheader("FIFO Lot Details")

    if not lot_details:
        st.info("No lots to display")
        return

    all_lots = []
    for symbol, lots in lot_details.items():
        for lot in lots:
            all_lots.append({
                'Symbol': symbol,
                'Lot ID': lot.get('lot_id', '')[:8],
                'Acquisition Date': lot.get('acquisition_date', ''),
                'Acquisition Price': lot.get('acquisition_price', 0),
                'Remaining Qty': lot.get('remaining_quantity', 0),
                'Cost Basis': lot.get('cost_basis', 0),
                'Cost/Unit': lot.get('cost_per_unit', 0),
                'Days Held': lot.get('holding_days', 0),
                'Term': lot.get('holding_period', ''),
            })

    if all_lots:
        df = pd.DataFrame(all_lots)
        st.dataframe(df, use_container_width=True, hide_index=True)


def display_cash_flows(transactions, cash_summary):
    """Display cash flow analysis."""

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Cash Flow Summary")

        cf_df = pd.DataFrame({
            'Category': ['Total Inflows', 'Total Outflows', 'Total Income', 'Net Cash Flow'],
            'Amount': [
                f"${cash_summary.get('total_inflows', 0):,.2f}",
                f"${cash_summary.get('total_outflows', 0):,.2f}",
                f"${cash_summary.get('total_income', 0):,.2f}",
                f"${cash_summary.get('net_cash_flow', 0):,.2f}",
            ]
        })
        st.dataframe(cf_df, use_container_width=True, hide_index=True)

    with col2:
        st.subheader("Transaction Count by Type")

        type_counts = {}
        for txn in transactions:
            t = txn.transaction_type.name
            type_counts[t] = type_counts.get(t, 0) + 1

        type_df = pd.DataFrame({
            'Type': list(type_counts.keys()),
            'Count': list(type_counts.values())
        })
        st.dataframe(type_df, use_container_width=True, hide_index=True)

    # Transaction list
    st.subheader("Transaction History")

    txn_data = []
    for txn in sorted(transactions, key=lambda t: t.transaction_date):
        txn_data.append({
            'Date': txn.transaction_date.isoformat(),
            'Type': txn.transaction_type.name,
            'Symbol': txn.symbol,
            'Quantity': float(txn.quantity),
            'Price': float(txn.price),
            'Gross Amount': float(txn.gross_amount),
            'Fees': float(txn.total_fees),
            'Net Amount': float(txn.net_amount),
        })

    df = pd.DataFrame(txn_data)
    st.dataframe(df, use_container_width=True, hide_index=True)


def generate_download(result):
    """Generate downloadable Excel report."""

    st.subheader("📥 Download Full Report")

    st.markdown("""
    The Excel report includes 7 sheets:
    - **Executive Summary** - Overall reconciliation status
    - **Performance Reconciliation** - IRR, TWR metrics
    - **P&L Reconciliation** - Realized/unrealized P&L
    - **Position Detail** - All FIFO lots
    - **Cash Flows** - Transaction history
    - **Data Quality** - Data validation issues
    - **Audit Trail** - Complete reconciliation log
    """)

    # Generate report to bytes
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp_path = Path(tmp.name)

    try:
        report_generator = ExcelReportGenerator(tmp_path)
        report_generator.generate_report(
            reconciliation=result['reconciliation'],
            transactions=result['transactions'],
            portfolio_pnl=result['portfolio_pnl'],
            lot_details=result['lot_details'],
            cash_flow_summary=result['cash_flow_summary'],
            data_quality_issues=result['reconciliation'].data_quality_issues,
        )

        with open(tmp_path, 'rb') as f:
            excel_data = f.read()

        st.download_button(
            label="📥 Download Excel Report",
            data=excel_data,
            file_name=f"reconciliation_report_{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True
        )

    finally:
        if tmp_path.exists():
            tmp_path.unlink()


if __name__ == "__main__":
    main()
