"""
Data models for the trading application, using Pydantic for validation.
"""
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

class TradeSide(str, Enum):
    """Enumeration for trade sides."""
    BUY = "buy"
    SELL = "sell"

class TradingDecision(BaseModel):
    """
    Represents a decision made by a strategy agent.

    Based on `PG_Solo_Lite_AGENTS.md`, this model captures the output of a StrategyAgent.
    """
    symbol: str = Field(..., description="The trading symbol, e.g., 'BTC/USDT'")
    side: TradeSide = Field(..., description="The side of the trade, either 'buy' or 'sell'")
    stop_loss: float = Field(..., alias='sl', description="The price at which to cut losses")
    take_profit: float = Field(..., alias='tp', description="The price at which to take profit")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence level of the decision, from 0.0 to 1.0")

class MarketSnapshot(BaseModel):
    """
    Represents a snapshot of market data for a specific symbol at a point in time.

    This model is used by the IngestionAgent to pass data to other agents.
    """
    symbol: str = Field(..., description="The trading symbol, e.g., 'BTC/USDT'")
    timestamp: datetime = Field(..., description="The timestamp of the snapshot (UTC)")
    open: float = Field(..., description="The opening price of the candle")
    high: float = Field(..., description="The highest price of the candle")
    low: float = Field(..., description="The lowest price of the candle")
    close: float = Field(..., description="The closing price of the candle")
    volume: float = Field(..., description="The trading volume of the candle")
