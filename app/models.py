from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class TradingDecision(BaseModel):
    """
    Represents a decision made by the StrategyAgent.
    """
    symbol: str
    side: str  # 'buy' or 'sell'
    sl: Optional[float] = None  # Stop Loss
    tp: Optional[float] = None  # Take Profit
    confidence: float


class MarketSnapshot(BaseModel):
    """
    Represents a snapshot of market data for a symbol at a point in time.
    """
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
