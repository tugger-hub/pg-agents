"""
Data models for the trading application, using Pydantic for validation.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
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
    quantity: Optional[float] = Field(None, description="The quantity to trade. If None, a default is used.")
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


class OpsKpiSnapshot(BaseModel):
    """
    Represents a snapshot of operational KPIs.

    This model corresponds to the `ops_kpi_snapshots` table.
    """
    ts: datetime = Field(..., description="The timestamp of the KPI snapshot (UTC)")
    order_latency_p50_ms: Optional[int] = Field(None, description="p50 order latency in milliseconds")
    order_latency_p95_ms: Optional[int] = Field(None, description="p95 order latency in milliseconds")
    order_failure_rate: Optional[float] = Field(None, description="Ratio of failed orders")
    order_retry_rate: Optional[float] = Field(None, description="Ratio of retried orders")
    position_gross_exposure_usd: Optional[float] = Field(None, description="Gross exposure of all positions in USD")
    open_positions_count: Optional[int] = Field(None, description="Total number of open positions")
