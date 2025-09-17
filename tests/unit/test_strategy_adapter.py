import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.models import TradingViewAlert, TradeSide
from app.config import StrategySettings
from app.strategy_adapter import adapt_alert_to_decision

@pytest.fixture
def sample_buy_alert():
    """A sample TradingViewAlert for a 'buy' signal."""
    return TradingViewAlert(
        symbol="BTC/USDT",
        side="buy",
        qty=0.1,
        price=50000.0,
        ts=datetime.utcnow(),
        strategy="test_strat_buy",
        idempotency_key="test_key_buy"
    )

@pytest.fixture
def sample_sell_alert():
    """A sample TradingViewAlert for a 'sell' signal."""
    return TradingViewAlert(
        symbol="ETH/USDT",
        side="sell",
        qty=1.5,
        price=3000.0,
        ts=datetime.utcnow(),
        strategy="test_strat_sell",
        idempotency_key="test_key_sell"
    )

@patch('app.strategy_adapter.get_settings')
def test_adapt_alert_to_decision_maps_fields_correctly(mock_get_settings, sample_buy_alert):
    """
    Tests that the basic fields from the alert are correctly mapped
    to the TradingDecision object.
    """
    # Create a mock settings object with default values
    mock_settings = MagicMock()
    mock_settings.strategy = StrategySettings() # Use default values from the model
    mock_get_settings.return_value = mock_settings

    decision = adapt_alert_to_decision(sample_buy_alert)

    assert decision.symbol == sample_buy_alert.symbol
    assert decision.side == TradeSide.BUY
    assert decision.quantity == sample_buy_alert.qty
    assert decision.confidence == mock_settings.strategy.signal_confidence.threshold

@patch('app.strategy_adapter.get_settings')
def test_stop_loss_calculation_for_buy_alert(mock_get_settings, sample_buy_alert):
    """
    Tests the stop-loss calculation for a buy alert using a mocked config.
    """
    mock_settings = MagicMock()
    mock_settings.strategy.risk_management.percentage_sl = 2.0
    mock_get_settings.return_value = mock_settings

    decision = adapt_alert_to_decision(sample_buy_alert)

    expected_sl = 50000.0 * (1 - 2.0 / 100) # 49000.0
    assert decision.stop_loss == pytest.approx(expected_sl)

@patch('app.strategy_adapter.get_settings')
def test_take_profit_calculation_for_buy_alert(mock_get_settings, sample_buy_alert):
    """
    Tests the take-profit calculation for a buy alert (assuming 1.5 R/R)
    using a mocked config.
    """
    mock_settings = MagicMock()
    mock_settings.strategy.risk_management.percentage_sl = 2.0
    mock_get_settings.return_value = mock_settings

    decision = adapt_alert_to_decision(sample_buy_alert)

    stop_loss = 50000.0 * (1 - 2.0 / 100)
    risk_amount = 50000.0 - stop_loss
    expected_tp = 50000.0 + (risk_amount * 1.5) # 51500.0
    assert decision.take_profit == pytest.approx(expected_tp)

@patch('app.strategy_adapter.get_settings')
def test_stop_loss_and_tp_calculation_for_sell_alert(mock_get_settings, sample_sell_alert):
    """
    Tests the stop-loss and take-profit calculations for a sell alert.
    """
    mock_settings = MagicMock()
    mock_settings.strategy.risk_management.percentage_sl = 5.0
    mock_get_settings.return_value = mock_settings

    decision = adapt_alert_to_decision(sample_sell_alert)

    # Stop loss for a sell is above the entry price
    expected_sl = 3000.0 * (1 + 5.0 / 100) # 3150.0
    assert decision.stop_loss == pytest.approx(expected_sl)

    # Take profit for a sell is below the entry price
    risk_amount = expected_sl - 3000.0
    expected_tp = 3000.0 - (risk_amount * 1.5) # 2775.0
    assert decision.take_profit == pytest.approx(expected_tp)
