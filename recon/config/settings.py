"""Application configuration settings."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Settings:
    """Application settings for PMS Reconciliation."""

    # FX Configuration
    ecb_api_url: str = "https://data-api.ecb.europa.eu/service/data/EXR"
    fx_cache_hours: int = 24
    base_currency: str = "USD"

    # Calculation Settings
    irr_max_iterations: int = 100
    irr_initial_guess: float = 0.1
    newton_raphson_precision: float = 1e-10

    # Date Settings
    date_format: str = "%Y-%m-%d"
    business_day_convention: str = "following"

    # Output Settings
    output_directory: Path = field(default_factory=lambda: Path("./output"))
    report_filename: str = "reconciliation_report.xlsx"

    # Logging
    log_level: str = "INFO"

    def __post_init__(self):
        """Ensure output directory exists."""
        self.output_directory = Path(self.output_directory)
        self.output_directory.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
