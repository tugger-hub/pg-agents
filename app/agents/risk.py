"""
The RiskAgent is responsible for monitoring active positions and applying
risk management rules, such as trailing stops or partial profit taking.
"""
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional

import psycopg

from .base import Agent
from .execution import ExecutionAgent
from ..models import TradingDecision, TradeSide, SystemConfiguration
from ..services.system import get_system_configuration, set_trading_enabled
from ..kpi.services import get_daily_pnl, get_weekly_pnl

logger = logging.getLogger(__name__)


class RiskAgent(Agent):
    """
    Monitors open positions and executes risk management actions.

    This agent is responsible for:
    - Periodically fetching all active positions.
    - Evaluating each position against a set of risk management rules.
    - Executing risk management actions (e.g., creating a closing order).
    - Logging all actions to the `transactions` table.
    - Sending notifications for all actions taken.
    """

    def __init__(
        self,
        db_connection,
        execution_agent: ExecutionAgent,
        account_id: int = 1,
        price_timeframe: str = "1m",
        alert_chat_id: Optional[int] = None,
    ):
        """
        Initializes the RiskAgent with a database connection and an execution agent.

        Args:
            db_connection: An active psycopg3 database connection object.
            execution_agent: An instance of ExecutionAgent to submit orders.
            account_id: The account ID to monitor positions for.
        """
        self.db = db_connection
        self.execution_agent = execution_agent
        self.account_id = account_id
        self.price_timeframe = price_timeframe
        self.alert_chat_id = alert_chat_id or self._resolve_default_alert_chat()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._define_risk_rules()

    def _define_risk_rules(self):
        """
        Defines the risk management rules in a structured way.

        Example Rules:
        - rule_1: If profit > +1R, close 25% of the position.
        - rule_2: If profit > +2R, move Stop Loss to Break-Even.
        - rule_3: If profit > +3R, enable a trailing stop.
        """
        self.risk_rules = [
            {"name": "partial_profit_1R", "profit_r": 1.0, "action": "close_partial", "params": {"percentage": 0.25}},
            {"name": "breakeven_2R", "profit_r": 2.0, "action": "move_sl_to_be"},
            {"name": "trailing_stop_3R", "profit_r": 3.0, "action": "trail_sl"},
        ]
        self.logger.info(f"Loaded {len(self.risk_rules)} risk rules.")

    def _resolve_default_alert_chat(self) -> Optional[int]:
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT chat_id
                    FROM telegram_chats
                    WHERE enabled = TRUE
                    ORDER BY min_severity ASC
                    LIMIT 1;
                    """
                )
                row = cursor.fetchone()
                if row:
                    self.logger.info("Using chat_id %s for risk alerts", row[0])
                    return int(row[0])
        except psycopg.Error as exc:
            self.logger.warning("Could not resolve default alert chat id: %s", exc)
            self.db.rollback()
        return None

    def _get_active_positions(self) -> list[dict]:
        """
        Fetches all active positions (quantity != 0) for the agent's account.
        """
        query = """
        SELECT
            p.id,
            p.exchange_instrument_id,
            ei.exchange_symbol,
            i.symbol AS instrument_symbol,
            p.quantity,
            p.average_entry_price,
            p.initial_stop_loss
        FROM positions p
        JOIN exchange_instruments ei ON p.exchange_instrument_id = ei.id
        JOIN instruments i ON ei.instrument_id = i.id
        WHERE p.account_id = %s AND p.quantity != 0;
        """
        positions = []
        try:
            with self.db.cursor() as cursor:
                cursor.execute(query, (self.account_id,))
                results = cursor.fetchall()
                # Get column names from the cursor description
                columns = [desc[0] for desc in cursor.description]
                for row in results:
                    positions.append(dict(zip(columns, row)))
        except psycopg.Error as e:
            self.logger.error(f"Database error while fetching active positions: {e}")
            return [] # Return empty list on error

        self.logger.info(f"Found {len(positions)} active position(s).")
        return positions

    def _check_global_loss_limits(self):
        """
        M10 Guardrail: Checks daily and weekly PnL against configured loss limits.
        If a limit is breached, it activates the global kill switch and sends a CRITICAL alert.
        """
        # First, check if trading is already disabled. If so, do nothing.
        config = get_system_configuration(self.db)
        if not config or not config.is_trading_enabled:
            # No need to log here as the ExecutionAgent will log if it blocks trades.
            return

        # Get daily and weekly PnL
        daily_pnl = get_daily_pnl(self.db)
        weekly_pnl = get_weekly_pnl(self.db)
        self.logger.info(f"PnL Check - Daily: ${daily_pnl:.2f}, Weekly: ${weekly_pnl:.2f}")

        limit_breached = False
        breach_reason = ""

        # Loss limits are positive values, PnL is negative for a loss.
        if daily_pnl < -config.daily_loss_limit_usd:
            limit_breached = True
            breach_reason = f"Daily loss limit of ${config.daily_loss_limit_usd:.2f} breached (Today's PnL: ${daily_pnl:.2f})"
        elif weekly_pnl < -config.weekly_loss_limit_usd:
            limit_breached = True
            breach_reason = f"Weekly loss limit of ${config.weekly_loss_limit_usd:.2f} breached (This Week's PnL: ${weekly_pnl:.2f})"

        if limit_breached:
            self.logger.critical(f"LOSS LIMIT BREACHED: {breach_reason}")

            # 1. Activate the kill switch
            self.logger.info("Activating global kill switch due to loss limit breach.")
            set_trading_enabled(self.db, False)

            # 2. Send a CRITICAL notification
            self.logger.info("Sending CRITICAL notification for loss limit breach.")
            if not self.alert_chat_id:
                self.logger.warning("Loss limit breached but no alert_chat_id configured; notification skipped.")
                return

            try:
                with self.db.cursor() as cursor:
                    notify_sql = "SELECT enqueue_notification(%s, 'CRITICAL', %s, %s, %s);"
                    title = "!!! TRADING HALTED - LOSS LIMIT BREACHED !!!"
                    dedupe_key = f"loss-limit-breach-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
                    cursor.execute(notify_sql, (self.alert_chat_id, title, breach_reason, dedupe_key))
                    self.db.commit()
                    self.logger.info("Successfully enqueued CRITICAL notification.")
            except psycopg.Error as e:
                self.logger.error(f"Failed to enqueue CRITICAL notification for loss limit breach: {e}")
                self.db.rollback()


    def run(self):
        """
        The main entry point for the agent's logic.
        This method is called periodically by the scheduler.
        """
        self.logger.info("Running risk management cycle...")

        # --- M10 Guardrail: Global Loss Limit Check ---
        self._check_global_loss_limits()

        active_positions = self._get_active_positions()

        if not active_positions:
            self.logger.info("No active positions found. Ending cycle.")
            return

        for position in active_positions:
            self.logger.info(f"Evaluating position: {position}")
            self._evaluate_position_risk(position)

    def _get_current_market_price(self, symbol: str) -> float | None:
        """Fetches the most recent close price for the supplied symbol."""
        symbol_variants = [symbol]
        if "/" in symbol:
            symbol_variants.append(symbol.replace("/", ""))
        else:
            # naive conversion e.g. BTCUSDT -> BTC/USDT
            base = symbol[:-4]
            quote = symbol[-4:]
            symbol_variants.append(f"{base}/{quote}")

        for candidate in symbol_variants:
            try:
                with self.db.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT close
                        FROM candles
                        WHERE symbol = %s AND timeframe = %s
                        ORDER BY timestamp DESC
                        LIMIT 1;
                        """,
                        (candidate, self.price_timeframe),
                    )
                    row = cursor.fetchone()
                    if row:
                        return float(row[0])
            except psycopg.Error as exc:
                self.logger.error("Failed to fetch market price for %s: %s", symbol, exc)
                self.db.rollback()
                return None

        self.logger.warning("No recent candle found for %s", symbol)
        return None

    def _evaluate_position_risk(self, position: dict):
        """
        Calculates the position's current PnL and evaluates it against risk rules.
        """
        # Ensure all numeric values from the DB are treated as Decimals
        entry_price = Decimal(position['average_entry_price'])
        quantity = Decimal(position['quantity'])
        initial_sl = position.get('initial_stop_loss')

        if initial_sl is None:
            # This logic branch is for backward compatibility or missing data.
            # In our E2E test, we ensure initial_stop_loss is set.
            initial_sl = entry_price * Decimal('0.98')
            self.logger.warning(
                f"Position {position['id']} is missing 'initial_stop_loss'. "
                f"Simulating a 2% SL at {initial_sl}"
            )
        else:
            initial_sl = Decimal(initial_sl)

        current_price = self._get_current_market_price(position['exchange_symbol'])
        if current_price is None:
            self.logger.error(f"Could not fetch market price for {position['exchange_symbol']}. Skipping evaluation.")
            return

        current_price = Decimal(current_price)

        # --- R-Multiple Calculation ---
        # Determine the side of the trade for the calculation
        side = TradeSide.BUY if quantity > 0 else TradeSide.SELL

        r_multiple = calculate_r_multiple(
            entry_price=float(entry_price),
            current_price=float(current_price),
            stop_loss_price=float(initial_sl),
            side=side
        )

        if r_multiple is None:
            self.logger.warning(f"Initial risk is zero for position {position['id']}. Cannot calculate R-multiple.")
            return
        self.logger.info(f"Position {position['id']} ({position['exchange_symbol']}): Current R-multiple is {r_multiple:.2f}")

        # --- Rule Evaluation ---
        # Check rules in descending order of profit, so the highest-R rule triggers.
        for rule in sorted(self.risk_rules, key=lambda r: r['profit_r'], reverse=True):
            # For take-profit rules (profit_r > 0), we trigger if r_multiple is greater.
            # For stop-loss rules (profit_r < 0), we trigger if r_multiple is less.
            is_stop_loss_rule = rule['profit_r'] < 0
            triggered = False
            if is_stop_loss_rule:
                if r_multiple <= rule['profit_r']:
                    triggered = True
            else:  # Is a take-profit rule
                if r_multiple >= rule['profit_r']:
                    triggered = True

            if triggered:
                self.logger.info(f"TRIGGERED: Rule '{rule['name']}' for position {position['id']} at R={r_multiple:.2f}")
                # Add the calculated R-multiple to the position dict to pass to the action executor
                position['r_multiple'] = r_multiple
                # TODO: Add state to prevent re-triggering the same rule for the same position.
                # For now, we assume it's okay to re-evaluate every cycle.
                self._execute_risk_action(position, rule)
                # Stop checking after the first (highest) rule is triggered
                break

    def _execute_risk_action(self, position: dict, rule: dict):
        """
        Logs the risk action to the DB, queues a notification, and executes the trade.
        """
        action = rule.get("action")
        self.logger.info(f"Executing action '{action}' for position {position['id']}")

        # For now, we only implement 'close_partial'. Other actions are placeholders.
        position_qty = Decimal(position['quantity'])
        abs_position_qty = abs(position_qty)

        close_qty = None
        if action == "close_partial":
            percentage_str = str(rule.get("params", {}).get("percentage", "0.0"))
            percentage = Decimal(percentage_str)

            if not (Decimal("0") < percentage <= Decimal("1.0")):
                self.logger.error(
                    "Invalid percentage %s for close_partial. Must be between 0 and 1.",
                    percentage,
                )
                return

            close_qty = abs_position_qty * percentage
        elif action == "close_full":
            close_qty = abs_position_qty
        else:
            self.logger.warning(f"Action '{action}' is not yet implemented.")
            return

        if close_qty is None or close_qty <= 0:
            self.logger.warning("Computed close quantity is non-positive for position %s", position["id"])
            return

        close_side = TradeSide.SELL if position_qty > 0 else TradeSide.BUY
        decision_symbol = position.get("instrument_symbol") or position['exchange_symbol']

        decision = TradingDecision(
            symbol=decision_symbol,
            side=close_side,
            quantity=float(close_qty),
            stop_loss=0.0,
            take_profit=0.0,
            confidence=1.0,
        )

        order_id = self.execution_agent.run(decision)
        if order_id is None:
            self.logger.error(
                "Failed to create closing order for position %s (rule %s).",
                position['id'],
                rule['name'],
            )
            return

        try:
            with self.db.cursor() as cursor:
                tx_sql = """
                    INSERT INTO transactions (account_id, related_order_id, transaction_type, amount)
                    VALUES (%s, %s, %s, %s);
                    """
                tx_type = f"RISK_ACTION_{rule['name'].upper()}"
                cursor.execute(tx_sql, (self.account_id, order_id, tx_type, close_qty))
                self.db.commit()
                self.logger.info(
                    "Logged risk action to transactions table for order %s.", order_id
                )
        except psycopg.Error as e:
            self.logger.error(f"Failed to log risk action transaction: {e}")
            self.db.rollback()
            return

        if not self.alert_chat_id:
            return

        try:
            with self.db.cursor() as cursor:
                notify_sql = "SELECT enqueue_notification(%s, %s, %s, %s, %s);"
                severity = 'INFO'
                title = f"Risk Action: {rule['name']}"
                r_multiple = position.get('r_multiple', 0.0)
                message = (
                    f"Executed {rule['name']} for {decision_symbol}.\n"
                    f"Closed {float(close_qty):.4f} at R-multiple {r_multiple:.2f}."
                )
                dedupe_key = f"risk-action-{position['id']}-{rule['name']}-{order_id}"
                cursor.execute(
                    notify_sql,
                    (self.alert_chat_id, severity, title, message, dedupe_key),
                )
                self.db.commit()
                self.logger.info(
                    "Enqueued notification for risk action on position %s.", position['id']
                )
        except psycopg.Error as e:
            self.logger.error(f"Failed to enqueue notification: {e}")
            self.db.rollback()


def calculate_r_multiple(
    entry_price: float,
    current_price: float,
    stop_loss_price: float,
    side: TradeSide,
) -> float | None:
    """
    Calculates the current profit/loss of a potential or open trade
    in terms of "R" (initial risk multiple).

    This is a pure function, making it easy to unit test.

    Args:
        entry_price: The average entry price of the position.
        current_price: The current market price.
        stop_loss_price: The price at which the position would be stopped out.
        side: The side of the trade (BUY or SELL).

    Returns:
        The R-multiple as a float (e.g., 2.5 means 2.5x the initial risk in profit),
        or None if the initial risk is zero (cannot divide by zero).
    """
    initial_risk_per_unit = abs(entry_price - stop_loss_price)
    if initial_risk_per_unit == 0:
        return None

    if side == TradeSide.BUY:
        profit_per_unit = current_price - entry_price
    elif side == TradeSide.SELL:
        profit_per_unit = entry_price - current_price
    else:
        return None

    return profit_per_unit / initial_risk_per_unit
