"""
The RiskAgent is responsible for monitoring active positions and applying
risk management rules, such as trailing stops or partial profit taking.
"""
import logging
import psycopg
from decimal import Decimal

from .base import Agent
from .execution import ExecutionAgent
from ..models import TradingDecision, TradeSide

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

    def __init__(self, db_connection, execution_agent: ExecutionAgent, account_id: int = 1):
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

    def _get_active_positions(self) -> list[dict]:
        """
        Fetches all active positions (quantity != 0) for the agent's account.
        """
        query = """
        SELECT
            p.id,
            p.exchange_instrument_id,
            ei.exchange_symbol,
            p.quantity,
            p.average_entry_price,
            p.initial_stop_loss
        FROM positions p
        JOIN exchange_instruments ei ON p.exchange_instrument_id = ei.id
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

    def run(self):
        """
        The main entry point for the agent's logic.
        This method is called periodically by the scheduler.
        """
        self.logger.info("Running risk management cycle...")
        active_positions = self._get_active_positions()

        if not active_positions:
            self.logger.info("No active positions found. Ending cycle.")
            return

        for position in active_positions:
            self.logger.info(f"Evaluating position: {position}")
            self._evaluate_position_risk(position)

    def _get_current_market_price(self, symbol: str) -> float | None:
        """
        [PLACEHOLDER] Fetches the current market price for a symbol.

        TODO: This needs to be implemented to fetch data from the IngestionAgent's
        output (e.g., a 'candles' table or a shared in-memory snapshot).
        For now, we'll simulate a price for development.
        """
        self.logger.warning(f"Using placeholder market price for {symbol}")
        if "BTC" in symbol:
            return 70000.0  # Simulate a profitable move
        return 100.0

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
        initial_risk_per_unit = abs(entry_price - initial_sl)
        if initial_risk_per_unit == 0:
            self.logger.warning(f"Initial risk is zero for position {position['id']}. Cannot calculate R-multiple.")
            return

        # Profit is positive for long gains and short gains
        profit_per_unit = (current_price - entry_price) if quantity > 0 else (entry_price - current_price)

        r_multiple = profit_per_unit / initial_risk_per_unit
        self.logger.info(f"Position {position['id']} ({position['exchange_symbol']}): Current R-multiple is {r_multiple:.2f}")

        # --- Rule Evaluation ---
        # Check rules in descending order of profit, so the highest-R rule triggers.
        for rule in sorted(self.risk_rules, key=lambda r: r['profit_r'], reverse=True):
            if r_multiple >= rule['profit_r']:
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
        if action == "close_partial":
            percentage_str = str(rule.get("params", {}).get("percentage", "0.0"))
            percentage = Decimal(percentage_str)

            if not (Decimal('0') < percentage <= Decimal('1.0')):
                self.logger.error(f"Invalid percentage {percentage} for close_partial. Must be between 0 and 1.")
                return

            # 1. Determine order parameters
            position_qty = Decimal(position['quantity'])
            close_qty = position_qty * percentage
            # Side is the opposite of the current position
            close_side = TradeSide.SELL if position_qty > 0 else TradeSide.BUY

            # 2. Create a TradingDecision for the closing order
            decision = TradingDecision(
                symbol=position['exchange_symbol'],
                side=close_side,
                quantity=float(close_qty), # Pass the calculated quantity
                # SL/TP for a closing order is typically not needed. Pydantic requires them.
                sl=0,
                tp=0,
                confidence=1.0 # High confidence as it's a risk management action
            )

            # 3. Use ExecutionAgent to place the order and get its ID.
            # The ExecutionAgent's `run` method handles DB insertion and returns the order ID.
            # We assume the `run` method is adapted to return the ID for this use case.
            # NOTE: This is a conceptual adaptation. The current ExecutionAgent does not return the ID.
            # We will simulate this by calling its internal method for now, which is not ideal but necessary.
            order_id = self.execution_agent._execute_decision(decision)
            if order_id is None:
                self.logger.error(f"Failed to create closing order for position {position['id']}.")
                return

            # 4. Log the action to the 'transactions' table
            try:
                with self.db.cursor() as cursor:
                    tx_sql = """
                    INSERT INTO transactions (account_id, related_order_id, transaction_type, amount)
                    VALUES (%s, %s, %s, %s);
                    """
                    tx_type = f"RISK_ACTION_{rule['name'].upper()}"
                    # Amount is the quantity of the asset transacted
                    cursor.execute(tx_sql, (self.account_id, order_id, tx_type, close_qty))
                    self.db.commit()
                    self.logger.info(f"Logged risk action to transactions table for order {order_id}.")
            except psycopg.Error as e:
                self.logger.error(f"Failed to log risk action transaction: {e}")
                self.db.rollback()
                # If logging fails, we have an orphan order. This needs a robust reconciliation process.
                return

            # 5. Enqueue a notification
            try:
                with self.db.cursor() as cursor:
                    # The enqueue_notification function is defined in the DB schema
                    notify_sql = "SELECT enqueue_notification(%s, %s, %s, %s, %s);"
                    chat_id = -1 # Placeholder chat_id
                    severity = 'INFO'
                    title = f"Risk Action: {rule['name']}"
                    message = (f"Executed {rule['name']} for {position['exchange_symbol']}.\n"
                               f"Closed {close_qty:.4f} at R-multiple {position['r_multiple']:.2f}.")
                    dedupe_key = f"risk-action-{position['id']}-{rule['name']}-{order_id}"
                    cursor.execute(notify_sql, (chat_id, severity, title, message, dedupe_key))
                    self.db.commit()
                    self.logger.info(f"Enqueued notification for risk action on position {position['id']}.")
            except psycopg.Error as e:
                self.logger.error(f"Failed to enqueue notification: {e}")
                self.db.rollback()

        else:
            self.logger.warning(f"Action '{action}' is not yet implemented.")
