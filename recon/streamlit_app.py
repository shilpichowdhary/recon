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
            help="CSV or Excel file with transaction history"
        )

        # Position file (contains PMS values and current prices)
        st.subheader("2. Positions (Required for Reconciliation)")
        positions_file = st.file_uploader(
            "Upload positions/holdings file",
            type=["csv", "xlsx", "xls"],
            help="Current holdings with market prices and PMS-calculated values"
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
                    positions_file if calc_mode == "Compare to PMS" else None,
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


def load_positions_file(positions_file):
    """Load positions file and extract PMS values and current prices."""
    if positions_file.name.endswith('.csv'):
        df = pd.read_csv(positions_file)
    else:
        df = pd.read_excel(positions_file)

    # Normalize column names
    df.columns = [str(c).lower().strip() for c in df.columns]

    current_prices = {}
    pms_positions = {}
    pms_totals = {
        'total_market_value': Decimal('0'),
        'total_cost_basis': Decimal('0'),
        'total_unrealized_pnl': Decimal('0'),
        'total_realized_pnl': Decimal('0'),
        'total_income': Decimal('0'),
        'total_pnl': Decimal('0'),
    }

    for _, row in df.iterrows():
        # Get symbol
        symbol = str(
            row.get('instrument id') or
            row.get('symbol') or
            row.get('ticker') or
            ''
        ).upper().strip()

        if not symbol:
            continue

        # Get market price
        market_price = row.get('market price', 0)
        if market_price and pd.notna(market_price):
            try:
                current_prices[symbol] = Decimal(str(market_price))
            except:
                pass

        # Get PMS values for this position
        quantity = Decimal(str(row.get('quantity', 0) or 0))
        cost_value = Decimal(str(row.get('cost value (base, eod fx)') or row.get('cost value (local)') or 0))
        market_value = Decimal(str(row.get('total market value (base)') or row.get('total market value (local)') or 0))
        unrealized_pnl = Decimal(str(row.get('total unrealised gain / loss (base)') or row.get('unrealised gain / loss (local)') or 0))
        realized_pnl = Decimal(str(row.get('total realised gain / loss (base)') or row.get('realised gain / loss (local)') or 0))
        income = Decimal(str(row.get('income (received, base)') or row.get('income (received, local)') or 0))
        total_pnl = Decimal(str(row.get('total p&l (base)') or row.get('total p&l (local)') or 0))
        xirr_pct = row.get('xirr (%)', None)

        pms_positions[symbol] = {
            'quantity': quantity,
            'cost_value': cost_value,
            'market_value': market_value,
            'unrealized_pnl': unrealized_pnl,
            'realized_pnl': realized_pnl,
            'income': income,
            'total_pnl': total_pnl,
            'xirr': Decimal(str(xirr_pct / 100)) if xirr_pct and pd.notna(xirr_pct) else None,
        }

        # Aggregate totals
        pms_totals['total_market_value'] += market_value
        pms_totals['total_cost_basis'] += cost_value
        pms_totals['total_unrealized_pnl'] += unrealized_pnl
        pms_totals['total_realized_pnl'] += realized_pnl
        pms_totals['total_income'] += income
        pms_totals['total_pnl'] += total_pnl

    return current_prices, pms_positions, pms_totals


def run_reconciliation(transactions_file, positions_file, portfolio_id, base_currency, valuation_date):
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

        # Load positions file (contains current prices AND PMS values)
        current_prices = {}
        pms_positions = {}
        pms_totals = {}

        if positions_file:
            current_prices, pms_positions, pms_totals = load_positions_file(positions_file)
            st.success(f"✅ Loaded {len(pms_positions)} positions with market prices")

        # Fallback: use last transaction price for missing symbols
        for txn in sorted(transactions, key=lambda t: t.transaction_date):
            if txn.symbol not in current_prices and txn.price and txn.price > 0:
                current_prices[txn.symbol] = txn.price

        # Build expected values from PMS totals for reconciliation
        expected_values = {
            'market_value': pms_totals.get('total_market_value', Decimal('0')),
            'cost_basis': pms_totals.get('total_cost_basis', Decimal('0')),
            'unrealized_pnl': pms_totals.get('total_unrealized_pnl', Decimal('0')),
            'realized_pnl': pms_totals.get('total_realized_pnl', Decimal('0')),
            'total_pnl': pms_totals.get('total_pnl', Decimal('0')),
        }

        # Run reconciliation
        recon_input = ReconciliationInput(
            transactions=transactions,
            current_prices=current_prices,
            expected_values=expected_values if positions_file else {},
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
            'pms_positions': pms_positions,
            'pms_totals': pms_totals,
            'current_prices': current_prices,
        }

    finally:
        tmp_path.unlink()


def display_results(result):
    """Display reconciliation results."""

    recon = result['reconciliation']
    pnl = result['portfolio_pnl']
    summary = recon.get_summary()
    calc_mode = result.get('calc_mode', 'Calculate Only')
    pms_totals = result.get('pms_totals', {})

    # Check if we have PMS data
    has_pms_data = bool(pms_totals)

    # Overall status based on mode
    if calc_mode == "Calculate Only":
        st.header("📊 Performance Calculation Results")
        st.success("✅ **Calculation Complete** - Compare these values against your PMS")
    else:
        st.header("📊 Reconciliation Results")
        if has_pms_data:
            st.info("📋 Comparing calculated values against PMS position data")
        else:
            st.warning("⚠️ **No positions file provided** - Upload a positions file to compare against PMS values.")

    # Show side-by-side comparison if we have PMS data
    if has_pms_data and calc_mode == "Compare to PMS":
        st.subheader("📊 Calculated vs PMS Comparison")

        comparison_data = []

        # Market Value
        calc_mv = float(pnl.total_market_value)
        pms_mv = float(pms_totals.get('total_market_value', 0))
        diff_mv = calc_mv - pms_mv
        comparison_data.append({
            'Metric': 'Total Market Value',
            'Calculated': f"${calc_mv:,.2f}",
            'PMS': f"${pms_mv:,.2f}",
            'Difference': f"${diff_mv:,.2f}",
            'Status': '✅' if abs(diff_mv) < 1 else '❌'
        })

        # Cost Basis
        calc_cost = float(pnl.total_cost_basis)
        pms_cost = float(pms_totals.get('total_cost_basis', 0))
        diff_cost = calc_cost - pms_cost
        comparison_data.append({
            'Metric': 'Total Cost Basis',
            'Calculated': f"${calc_cost:,.2f}",
            'PMS': f"${pms_cost:,.2f}",
            'Difference': f"${diff_cost:,.2f}",
            'Status': '✅' if abs(diff_cost) < 1 else '❌'
        })

        # Unrealized P&L
        calc_upnl = float(pnl.total_unrealized_pnl)
        pms_upnl = float(pms_totals.get('total_unrealized_pnl', 0))
        diff_upnl = calc_upnl - pms_upnl
        comparison_data.append({
            'Metric': 'Unrealized P&L',
            'Calculated': f"${calc_upnl:,.2f}",
            'PMS': f"${pms_upnl:,.2f}",
            'Difference': f"${diff_upnl:,.2f}",
            'Status': '✅' if abs(diff_upnl) < 1 else '❌'
        })

        # Realized P&L
        calc_rpnl = float(pnl.total_realized_pnl)
        pms_rpnl = float(pms_totals.get('total_realized_pnl', 0))
        diff_rpnl = calc_rpnl - pms_rpnl
        comparison_data.append({
            'Metric': 'Realized P&L',
            'Calculated': f"${calc_rpnl:,.2f}",
            'PMS': f"${pms_rpnl:,.2f}",
            'Difference': f"${diff_rpnl:,.2f}",
            'Status': '✅' if abs(diff_rpnl) < 1 else '❌'
        })

        # Total P&L
        calc_tpnl = float(pnl.total_pnl)
        pms_tpnl = float(pms_totals.get('total_pnl', 0))
        diff_tpnl = calc_tpnl - pms_tpnl
        comparison_data.append({
            'Metric': 'Total P&L',
            'Calculated': f"${calc_tpnl:,.2f}",
            'PMS': f"${pms_tpnl:,.2f}",
            'Difference': f"${diff_tpnl:,.2f}",
            'Status': '✅' if abs(diff_tpnl) < 1 else '❌'
        })

        # Income
        calc_inc = float(pnl.dividend_income + pnl.interest_income)
        pms_inc = float(pms_totals.get('total_income', 0))
        diff_inc = calc_inc - pms_inc
        comparison_data.append({
            'Metric': 'Total Income',
            'Calculated': f"${calc_inc:,.2f}",
            'PMS': f"${pms_inc:,.2f}",
            'Difference': f"${diff_inc:,.2f}",
            'Status': '✅' if abs(diff_inc) < 1 else '❌'
        })

        df_comparison = pd.DataFrame(comparison_data)
        st.dataframe(df_comparison, use_container_width=True, hide_index=True)

        # Count passes/fails
        passes = sum(1 for d in comparison_data if d['Status'] == '✅')
        fails = len(comparison_data) - passes

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Checks Passed", passes)
        with col2:
            st.metric("Checks Failed", fails)
        with col3:
            st.metric("Pass Rate", f"{passes/len(comparison_data)*100:.0f}%")

    else:
        # Just show calculated values
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total P&L", f"${float(pnl.total_pnl):,.2f}")
        with col2:
            st.metric("Realized P&L", f"${float(pnl.total_realized_pnl):,.2f}")
        with col3:
            st.metric("Unrealized P&L", f"${float(pnl.total_unrealized_pnl):,.2f}")
        with col4:
            st.metric("Positions", len(pnl.positions))

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
        display_performance_metrics(recon, pnl, has_pms_data, calc_mode)

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


def display_performance_metrics(recon, pnl, has_pms_data, calc_mode="Calculate Only"):
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
    if has_pms_data:
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
