import pytest
from app.agents.strategy import some_pure_strategy_function
from app.models import TradeSide

def test_some_pure_strategy_function():
    """
    Tests the some_pure_strategy_function logic.
    """
    # Test case 1: Price is above the moving average, should return BUY
    assert some_pure_strategy_function(price=110, moving_average=100) == TradeSide.BUY

    # Test case 2: Price is below the moving average, should return SELL
    assert some_pure_strategy_function(price=90, moving_average=100) == TradeSide.SELL

    # Test case 3: Price is equal to the moving average, should return None
    assert some_pure_strategy_function(price=100, moving_average=100) is None

    # Test case 4: Edge case with zero values
    assert some_pure_strategy_function(price=0, moving_average=0) is None

    # Test case 5: Negative values
    assert some_pure_strategy_function(price=-10, moving_average=-20) == TradeSide.BUY
