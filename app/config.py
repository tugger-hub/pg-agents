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

def yaml_config_source(settings: BaseSettings) -> Dict[str, Any]:
    """
    A pydantic-settings source that loads settings from a YAML file.
    """
    config_path = BASE_DIR / "configs" / "strategy.yaml"
    if not config_path.is_file():
        logger.warning(f"YAML config file not found at: {config_path}")
        return {}

    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    except (IOError, yaml.YAMLError) as e:
        logger.error(f"Error reading or parsing YAML config: {e}")
        return {}


class AppSettings(BaseSettings):
    """
    The main settings class for the application.

    It loads settings from the following sources, in order of precedence:
    1. Environment variables (e.g., `STRATEGY_TIMEFRAMES_TREND=4h`).
    2. YAML file (`configs/strategy.yaml`).
    3. Default values defined in the models.
    """
    strategy: StrategySettings = Field(default_factory=StrategySettings)

    model_config = SettingsConfigDict(
        # For environment variables, use a prefix and nested delimiter
        env_prefix="APP_",
        env_nested_delimiter='__',
        # Allow case-insensitive env vars
        case_sensitive=False
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """
        Define the order of configuration sources.
        We place the YAML source after init_settings but before env_settings.
        """
        return (
            init_settings,
            env_settings,
            yaml_config_source, # Our custom YAML source
        )

# --- Singleton Instance ---
# Create a single instance of the settings to be used throughout the application.
settings = AppSettings()

# Optional: Log the loaded settings at startup for verification
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    logger.info("Loaded application settings:")
    # Using model_dump_json for clean, pretty-printed output
    print(json.dumps(settings.model_dump(), indent=2))
