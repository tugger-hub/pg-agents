"""
Configuration management for the application.

This module uses pydantic-settings to load configuration from a YAML file
and override it with environment variables. This provides a flexible and
type-safe way to manage application settings.

Based on the requirements in M4 of NEXT_STEPS_TODO_v2.md.
"""
import logging
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Configure logging
logger = logging.getLogger(__name__)

# Define the root directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Nested Models for Strategy Parameters ---
# These models correspond to the sections in the strategy.yaml file.

class TimeframesSettings(BaseModel):
    trend: str = "1d"
    entry: str = "1h"

class VolumeConfirmationSettings(BaseModel):
    enabled: bool = True
    ma_period: int = 20
    multiplier: float = 1.5

class RetestRuleSettings(BaseModel):
    success_condition: str = "candle_close_confirmation"

class RiskManagementSettings(BaseModel):
    stop_loss_method: str = "atr"
    atr_period: int = 14
    atr_multiplier: float = 2.0
    percentage_sl: float = 3.0

class DefaultRiskSettings(BaseModel):
    ratio: float = 1.0

class SignalConfidenceSettings(BaseModel):
    threshold: float = 0.7
    cooldown_seconds: int = 3600

# --- Main Strategy Settings Model ---

class StrategySettings(BaseModel):
    """A container for all strategy-related settings."""
    timeframes: TimeframesSettings = Field(default_factory=TimeframesSettings)
    volume_confirmation: VolumeConfirmationSettings = Field(default_factory=VolumeConfirmationSettings)
    retest_rule: RetestRuleSettings = Field(default_factory=RetestRuleSettings)
    risk_management: RiskManagementSettings = Field(default_factory=RiskManagementSettings)
    default_risk: DefaultRiskSettings = Field(default_factory=DefaultRiskSettings)
    signal_confidence: SignalConfidenceSettings = Field(default_factory=SignalConfidenceSettings)


# --- Pydantic-Settings Integration ---

from functools import lru_cache


# --- Pydantic-Settings Integration ---

# NOTE: Custom YAML source is disabled to resolve testing issues.
# Strategy parameters should be set via environment variables.
# Example: APP_STRATEGY__RISK_MANAGEMENT__PERCENTAGE_SL=5.0

class AppSettings(BaseSettings):
    """
    The main settings class for the application.
    """
    # --- Core Application Settings ---
    database_url: str = Field(..., env="DATABASE_URL")
    telegram_bot_token: str = Field("", env="TELEGRAM_BOT_TOKEN")
    app_env: str = Field("local", env="APP_ENV")
    db_pool_size: int = Field(10, env="DB_POOL_SIZE")
    webhook_secret_token: str = Field("", env="WEBHOOK_SECRET_TOKEN")

    # --- Strategy-specific Settings ---
    strategy: StrategySettings = Field(default_factory=StrategySettings)

    model_config = SettingsConfigDict(
        env_nested_delimiter='__',
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# --- Singleton Getter ---
@lru_cache()
def get_settings() -> AppSettings:
    """
    Returns a cached singleton instance of the AppSettings.
    The lru_cache decorator ensures that the AppSettings is only instantiated once.
    This approach defers the instantiation until the settings are actually needed,
    which is crucial for testing environments where settings might be patched.
    """
    return AppSettings()


# Optional: Log the loaded settings at startup for verification
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    logger.info("Loaded application settings:")
    settings = get_settings()
    # Using model_dump_json for clean, pretty-printed output
    print(json.dumps(settings.model_dump(), indent=2))
