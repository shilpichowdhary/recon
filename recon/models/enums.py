"""Enumeration types for PMS Reconciliation."""

from enum import Enum, auto


class TransactionType(Enum):
    """Types of portfolio transactions."""

    # Cash transactions
    DEPOSIT = auto()
    WITHDRAWAL = auto()

    # Security transactions
    BUY = auto()
    SELL = auto()

    # Income
    DIVIDEND = auto()
    INTEREST = auto()
    COUPON = auto()

    # Corporate actions
    STOCK_SPLIT = auto()
    REVERSE_SPLIT = auto()
    SPIN_OFF = auto()
    MERGER = auto()

    # Options
    OPTION_BUY = auto()
    OPTION_SELL = auto()
    OPTION_EXERCISE = auto()
    OPTION_ASSIGNMENT = auto()
    OPTION_EXPIRY = auto()

    # Fees
    FEE = auto()
    COMMISSION = auto()

    # Transfers
    TRANSFER_IN = auto()
    TRANSFER_OUT = auto()

    # FX
    FX_TRADE = auto()

    @classmethod
    def is_buy(cls, txn_type: "TransactionType") -> bool:
        """Check if transaction type is a buy-side transaction."""
        return txn_type in {cls.BUY, cls.OPTION_BUY, cls.DEPOSIT, cls.TRANSFER_IN}

    @classmethod
    def is_sell(cls, txn_type: "TransactionType") -> bool:
        """Check if transaction type is a sell-side transaction."""
        return txn_type in {cls.SELL, cls.OPTION_SELL, cls.WITHDRAWAL, cls.TRANSFER_OUT}

    @classmethod
    def is_income(cls, txn_type: "TransactionType") -> bool:
        """Check if transaction type is income."""
        return txn_type in {cls.DIVIDEND, cls.INTEREST, cls.COUPON}


class AssetType(Enum):
    """Types of assets in portfolio."""

    # Cash
    CASH = auto()

    # Equities
    EQUITY = auto()
    ETF = auto()
    MUTUAL_FUND = auto()
    ADR = auto()

    # Fixed Income
    GOVERNMENT_BOND = auto()
    CORPORATE_BOND = auto()
    MUNICIPAL_BOND = auto()
    TREASURY_BILL = auto()
    ZERO_COUPON_BOND = auto()

    # Options
    CALL_OPTION = auto()
    PUT_OPTION = auto()

    # Structured Products
    STRUCTURED_NOTE = auto()
    BARRIER_OPTION = auto()
    AUTOCALLABLE = auto()

    # Other
    FUTURE = auto()
    FORWARD = auto()
    SWAP = auto()

    @classmethod
    def is_equity(cls, asset_type: "AssetType") -> bool:
        """Check if asset type is equity-like."""
        return asset_type in {cls.EQUITY, cls.ETF, cls.MUTUAL_FUND, cls.ADR}

    @classmethod
    def is_fixed_income(cls, asset_type: "AssetType") -> bool:
        """Check if asset type is fixed income."""
        return asset_type in {
            cls.GOVERNMENT_BOND, cls.CORPORATE_BOND, cls.MUNICIPAL_BOND,
            cls.TREASURY_BILL, cls.ZERO_COUPON_BOND
        }

    @classmethod
    def is_option(cls, asset_type: "AssetType") -> bool:
        """Check if asset type is an option."""
        return asset_type in {cls.CALL_OPTION, cls.PUT_OPTION}

    @classmethod
    def is_structured(cls, asset_type: "AssetType") -> bool:
        """Check if asset type is a structured product."""
        return asset_type in {cls.STRUCTURED_NOTE, cls.BARRIER_OPTION, cls.AUTOCALLABLE}


class CurrencyCode(Enum):
    """ISO 4217 currency codes."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CHF = "CHF"
    JPY = "JPY"
    CAD = "CAD"
    AUD = "AUD"
    NZD = "NZD"
    HKD = "HKD"
    SGD = "SGD"
    CNY = "CNY"
    INR = "INR"

    @classmethod
    def from_string(cls, currency_str: str) -> "CurrencyCode":
        """Convert string to CurrencyCode."""
        try:
            return cls(currency_str.upper())
        except ValueError:
            raise ValueError(f"Unknown currency code: {currency_str}")
