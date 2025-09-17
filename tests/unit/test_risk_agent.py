import pytest
from app.agents.risk import calculate_r_multiple
from app.models import TradeSide

@pytest.mark.parametrize(
    "entry, current, sl, side, expected_r",
    [
        # Long positions
        (100, 110, 90, TradeSide.BUY, 1.0),      # Profit = 1R
        (100, 125, 90, TradeSide.BUY, 2.5),      # Profit = 2.5R
        (100, 95, 90, TradeSide.BUY, -0.5),     # Loss = -0.5R
        (100, 90, 90, TradeSide.BUY, -1.0),      # At stop-loss, R should be -1.0
        (100, 100, 90, TradeSide.BUY, 0.0),      # At entry, R = 0
        # Short positions
        (100, 90, 110, TradeSide.SELL, 1.0),     # Profit = 1R
        (100, 75, 110, TradeSide.SELL, 2.5),     # Profit = 2.5R
        (100, 105, 110, TradeSide.SELL, -0.5),    # Loss = -0.5R
        (100, 110, 110, TradeSide.SELL, -1.0),   # At stop-loss, R should be -1.0
        (100, 100, 110, TradeSide.SELL, 0.0),     # At entry, R = 0
    ],
)
def test_calculate_r_multiple_scenarios(entry, current, sl, side, expected_r):
    """
    Tests various scenarios for the R-multiple calculation.
    """
    r_multiple = calculate_r_multiple(
        entry_price=float(entry),
        current_price=float(current),
        stop_loss_price=float(sl),
        side=side,
    )
    assert r_multiple == pytest.approx(expected_r)

def test_calculate_r_multiple_zero_risk():
    """
    Tests the edge case where the initial risk is zero.
    The function should return None to avoid division by zero.
    """
    # Entry price is the same as stop-loss price
    r_multiple = calculate_r_multiple(
        entry_price=100.0,
        current_price=110.0,
        stop_loss_price=100.0,
        side=TradeSide.BUY,
    )
    assert r_multiple is None
