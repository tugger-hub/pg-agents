"""
Configuration management for the application.

This module uses pydantic-settings to load configuration from a YAML file
and override it with environment variables. This provides a flexible and
type-safe way to manage application settings.

The configuration layout aligns with the Solo-Lite design docs and exposes
only the knobs that a single-operator setup should need.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    atr_take_profit_r_multiple: float = 2.0
    percentage_sl: float = 3.0
    account_equity_usd: float = 10_000.0

class DefaultRiskSettings(BaseModel):
    ratio: float = 1.0  # percentage of capital to risk per trade

class SignalConfidenceSettings(BaseModel):
    threshold: float = 0.7
    cooldown_seconds: int = 3600

class MovingAverageSettings(BaseModel):
    fast_period: int = 9
    slow_period: int = 21
    trend_period: int = 200

class MacdSettings(BaseModel):
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9

class VolumeBreakoutSettings(BaseModel):
    lookback: int = 20
    volume_ma_period: int = 20
    volume_multiplier: float = 2.0
    breakout_buffer_pct: float = 0.001

class DivergenceSettings(BaseModel):
    rsi_period: int = 14
    window: int = 20
    bullish_rsi_floor: float = 30.0
    bearish_rsi_ceiling: float = 70.0
    min_price_change_pct: float = 0.003
    min_rsi_change: float = 3.0

class RetestSettings(BaseModel):
    lookback: int = 30
    tolerance_pct: float = 0.002
    confirmation_bars: int = 3

class StrategySwitches(BaseModel):
    ema_trend_pullback: bool = True
    volume_breakout: bool = True
    rsi_divergence: bool = True
    breakout_retest: bool = True
    macd_crossover: bool = False

class PositionSizingSettings(BaseModel):
    account_equity_usd: float = 10_000.0
    risk_per_trade_percent: float = 1.0
    max_position_notional_usd: Optional[float] = None
    min_position_notional_usd: Optional[float] = None

class StrategySettings(BaseModel):
    """A container for all strategy-related settings."""

    timeframes: TimeframesSettings = Field(default_factory=TimeframesSettings)
    volume_confirmation: VolumeConfirmationSettings = Field(default_factory=VolumeConfirmationSettings)
    retest_rule: RetestRuleSettings = Field(default_factory=RetestRuleSettings)
    risk_management: RiskManagementSettings = Field(default_factory=RiskManagementSettings)
    default_risk: DefaultRiskSettings = Field(default_factory=DefaultRiskSettings)
    signal_confidence: SignalConfidenceSettings = Field(default_factory=SignalConfidenceSettings)
    moving_average: MovingAverageSettings = Field(default_factory=MovingAverageSettings)
    macd: MacdSettings = Field(default_factory=MacdSettings)
    volume_breakout: VolumeBreakoutSettings = Field(default_factory=VolumeBreakoutSettings)
    divergence: DivergenceSettings = Field(default_factory=DivergenceSettings)
    retest: RetestSettings = Field(default_factory=RetestSettings)
    switches: StrategySwitches = Field(default_factory=StrategySwitches)
    position_sizing: PositionSizingSettings = Field(default_factory=PositionSizingSettings)

class ExchangeSettings(BaseModel):
    id: str = "binance"
    api_key: str = ""
    api_secret: str = ""
    api_password: str = ""
    sandbox_mode: bool = True
    enable_live_trading: bool = False
    default_order_size: float = 0.01

class NotificationSettings(BaseModel):
    alert_chat_id: Optional[int] = None
    report_chat_id: Optional[int] = None

# --- Pydantic-Settings Integration ---

class YamlConfigSource(PydanticBaseSettingsSource):
    """
    A pydantic-settings source that loads settings from a YAML file.
    """

    def get_field_value(self, field, field_name):  # type: ignore[override]
        # This source is not field-based, so we leave this method empty.
        return None, None

    def __call__(self) -> Dict[str, Any]:  # type: ignore[override]
        config_path = BASE_DIR / "configs" / "strategy.yaml"
        if not config_path.is_file():
            logger.warning("YAML config file not found at %s", config_path)
            return {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                if not isinstance(data, dict):
                    logger.error("YAML config root must be a mapping. Got %s", type(data))
                    return {}
                return data
        except (OSError, yaml.YAMLError) as exc:
            logger.error("Error reading or parsing YAML config: %s", exc)
            return {}

class AppSettings(BaseSettings):
    """
    The main settings class for the application.

    Load order (lowest precedence first):
        1. YAML file (`configs/strategy.yaml`).
        2. .env file (if present).
        3. Environment variables.
        4. Explicit init kwargs.
    """

    # --- Core Application Settings ---
    database_url: str = Field(
        "postgresql://postgres:postgres@localhost:5432/pg_agents",
        env="DATABASE_URL",
    )
    telegram_bot_token: str = Field("", env="TELEGRAM_BOT_TOKEN")
    app_env: str = Field("local", env="APP_ENV")
    db_pool_size: int = Field(10, env="DB_POOL_SIZE")

    # --- Domain Specific Settings ---
    trading_symbols: List[str] = Field(default_factory=lambda: ["BTC/USDT"], alias="symbols")
    strategy: StrategySettings = Field(default_factory=StrategySettings)
    exchange: ExchangeSettings = Field(default_factory=ExchangeSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
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
        YAML is loaded first so that env vars can override selectively.
        """

        return (
            YamlConfigSource(settings_cls),
            dotenv_settings,
            env_settings,
            init_settings,
        )

# --- Singleton Instance ---
# Create a single instance of the settings to be used throughout the application.
settings = AppSettings()

if __name__ == "__main__":  # pragma: no cover
    import json

    logging.basicConfig(level=logging.INFO)
    logger.info("Loaded application settings:")
    print(json.dumps(settings.model_dump(mode="json"), indent=2))
