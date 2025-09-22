"""
The StrategyAgent is responsible for analyzing market data and generating
TradingDecision objects based on a predefined trading strategy.
"""
from app.models import TradingDecision, MarketSnapshot, TradeSide

class StrategyAgent:
    """
    A simple strategy agent that generates trading signals.
    """
    def __init__(self, confidence_threshold: float = 0.5):
        self.confidence_threshold = confidence_threshold

    def analyze(self, snapshot: MarketSnapshot) -> list[TradingDecision]:
        """
        Analyzes a market snapshot and returns a list of trading decisions.

        This is a placeholder for the actual strategy logic.
        For unit testing, we will focus on more granular, pure functions.
        """
        # This is a dummy implementation.
        # Real logic would involve indicators (RSI, MAs, etc.)
        return []

def some_pure_strategy_function(price: float, moving_average: float) -> TradeSide | None:
    """
    An example of a pure function that could be part of the strategy logic.
    This is the type of function we will unit test.
    """
    if price > moving_average:
        return TradeSide.BUY
    elif price < moving_average:
        return TradeSide.SELL
    return None
