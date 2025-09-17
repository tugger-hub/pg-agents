import logging

from app.config import get_settings
from app.models import TradeSide, TradingDecision, TradingViewAlert

logger = logging.getLogger(__name__)


def adapt_alert_to_decision(alert: TradingViewAlert) -> TradingDecision:
    """
    Adapts a TradingView alert to an internal TradingDecision.

    This function converts a raw alert into a structured trading decision by
    applying risk management parameters from the application's configuration.
    It calculates stop-loss and take-profit levels based on the alert's
    entry price and the configured strategy.

    Args:
        alert: The validated TradingViewAlert object.

    Returns:
        A TradingDecision object ready to be processed by the execution agent.
    """
    settings = get_settings()
    logger.info(f"Adapting alert for {alert.symbol} with strategy {alert.strategy}")

    risk_params = settings.strategy.risk_management

    # The current implementation only supports percentage-based stop loss, as ATR
    # values are not available in the basic TradingView alert payload.
    # We'll use the 'percentage_sl' value from the config.
    if risk_params.stop_loss_method != "percentage":
        logger.warning(
            f"Strategy adapter currently only supports 'percentage' stop loss method, "
            f"but '{risk_params.stop_loss_method}' is configured. Falling back to using 'percentage_sl' value."
        )

    if alert.side == "buy":
        stop_loss = alert.price * (1 - risk_params.percentage_sl / 100)
        # Assume a simple 1:1.5 risk/reward ratio for take-profit as a placeholder
        take_profit = alert.price + (alert.price - stop_loss) * 1.5
    else:  # sell
        stop_loss = alert.price * (1 + risk_params.percentage_sl / 100)
        # Assume a simple 1:1.5 risk/reward ratio
        take_profit = alert.price - (stop_loss - alert.price) * 1.5

    # Create the TradingDecision object
    decision = TradingDecision(
        symbol=alert.symbol,
        side=TradeSide(alert.side),
        quantity=alert.qty,
        sl=stop_loss,
        tp=take_profit,
        # Use the default confidence threshold from settings
        confidence=settings.strategy.signal_confidence.threshold,
    )

    logger.info(f"Created TradingDecision: {decision.model_dump_json(indent=2)}")

    return decision
