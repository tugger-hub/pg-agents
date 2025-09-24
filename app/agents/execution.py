"""
The ExecutionAgent is responsible for converting TradingDecisions into actual
orders and submitting them to the database, ensuring idempotency and correctness.
"""
import logging
import hashlib
from datetime import datetime, timezone

# Assuming the use of psycopg, as it's a common choice mentioned in docs
import psycopg
import ccxt

from ..models import TradingDecision, TradeSide
from ..services.system import get_system_configuration
from .base import Agent

logger = logging.getLogger(__name__)


class ExecutionAgent(Agent):
    """
    Executes trades based on trading decisions by recording them in the database.

    This agent is responsible for:
    - Generating an idempotency key for each trading decision.
    - Inserting the order into the `orders` table.
    - Handling database errors gracefully (e.g., unique constraint violations
      for duplicate orders).
    """

    def __init__(
        self,
        db_connection,
        account_id: int = 1,
        exchange_client: ccxt.Exchange | None = None,
        submit_to_exchange: bool = False,
        default_order_size: float = 0.01,
    ):
        """
        Initializes the ExecutionAgent with a database connection.

        Args:
            db_connection: An active psycopg3 database connection object.
            account_id: The default account ID to use for placing orders.
        """
        self.db = db_connection
        self.account_id = account_id
        self.logger = logging.getLogger(self.__class__.__name__)
        self.exchange_client = exchange_client
        self.submit_to_exchange = submit_to_exchange and exchange_client is not None
        self.default_order_size = default_order_size

    def run(self, decision: TradingDecision):
        """
        The main entry point for the agent's logic.
        This method will be called by the scheduler with a trading decision.
        """
        self.logger.info(f"Received decision: {decision.model_dump_json()}")
        return self._execute_decision(decision)

    def _generate_idempotency_key(self, decision: TradingDecision) -> str:
        """
        Generates a deterministic idempotency key from a trading decision using SHA256.
        """
        # Using a rounded timestamp to create a time-window for idempotency
        # e.g., allowing a new, identical signal after 5 minutes.
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        key_data = (
            f"{self.account_id}-{decision.symbol}-{decision.side.value}-"
            f"{decision.stop_loss}-{decision.take_profit}-{ts}"
        )

        # Create a SHA256 hash of the key data for a uniform, fixed-length key
        return hashlib.sha256(key_data.encode("utf-8")).hexdigest()

    def _get_exchange_instrument_id(self, symbol: str) -> int | None:
        """
        Fetches the exchange_instrument_id from the database for a given symbol.
        """
        # This query robustly handles both generic symbols (e.g., 'BTC/USD') and
        # exchange-specific symbols (e.g., 'BTCUSD').
        query = """
        SELECT ei.id
        FROM exchange_instruments ei
        LEFT JOIN instruments i ON ei.instrument_id = i.id
        WHERE i.symbol = %s OR ei.exchange_symbol = %s;
        """
        try:
            with self.db.cursor() as cursor:
                # Pass the symbol for both WHERE clause conditions
                cursor.execute(query, (symbol, symbol))
                result = cursor.fetchone()
                if result:
                    self.logger.info(f"Found exchange_instrument_id: {result[0]} for symbol {symbol}")
                    return result[0]
                else:
                    self.logger.error(f"No exchange_instrument found for symbol: {symbol}")
                    return None
        except psycopg.Error as e:
            self.logger.error(f"Database error while fetching instrument ID for {symbol}: {e}")
            return None

    def _execute_decision(self, decision: TradingDecision) -> int | None:
        """
        Handles the database insertion of the order, ensuring idempotency.
        Returns the new order ID if successful, otherwise None.
        """
        # --- M10 Guardrail: Kill Switch Check ---
        system_config = get_system_configuration(self.db)
        if not system_config or not system_config.is_trading_enabled:
            self.logger.warning(
                "Trading is disabled (kill switch is ON or system config is missing). "
                f"Discarding decision: {decision.model_dump_json()}"
            )
            return None

        idempotency_key = self._generate_idempotency_key(decision)
        self.logger.info(f"Generated idempotency key: {idempotency_key}")

        exchange_instrument_id = self._get_exchange_instrument_id(decision.symbol)
        if exchange_instrument_id is None:
            return None # Error already logged in the helper method

        # We assume a 'market' order for now, as it's not in TradingDecision.
        # Price is NULL for market orders.
        # Use quantity from the decision if provided, otherwise use the placeholder default.
        quantity_to_use = decision.quantity if decision.quantity is not None else self.default_order_size

        order_to_insert = {
            "account_id": self.account_id,
            "exchange_instrument_id": exchange_instrument_id,
            "idempotency_key": idempotency_key,
            "client_order_id": idempotency_key[:100],
            "side": decision.side.value,
            "type": "market",
            "status": "NEW",
            "quantity": quantity_to_use,
            "price": None, # Market orders don't have a price
        }

        # The DB trigger will normalize quantity and check min_notional.
        # Let's assume a placeholder quantity that is likely to be valid.
        # In a real system, the StrategyAgent would suggest a quantity.

        sql = """
        INSERT INTO orders (account_id, exchange_instrument_id, idempotency_key, side, type, status, quantity, price)
        VALUES (%(account_id)s, %(exchange_instrument_id)s, %(idempotency_key)s, %(side)s, %(type)s, %(status)s, %(quantity)s, %(price)s)
        RETURNING id;
        """

        try:
            with self.db.cursor() as cursor:
                cursor.execute(sql, order_to_insert)
                order_id = cursor.fetchone()[0]
                self.db.commit()
                self.logger.info(
                    "Successfully inserted order with ID %s and idempotency_key %s",
                    order_id,
                    idempotency_key,
                )

            if self.submit_to_exchange:
                self._forward_to_exchange(decision, quantity_to_use, order_id, idempotency_key)

            return order_id

        except psycopg.errors.UniqueViolation:
            self.logger.warning(
                f"Duplicate order detected with idempotency_key: {idempotency_key}. "
                "The order has already been processed. Suppressing."
            )
            self.db.rollback()
            return None

        except psycopg.errors.RaiseException as e:
            # This is likely from our trg_orders_normalize trigger
            self.logger.error(f"Order rejected by database trigger: {e}")
            self.db.rollback()
            return None

        except psycopg.Error as e:
            self.logger.critical(f"An unexpected database error occurred: {e}")
            self.db.rollback()
            return None

    def _forward_to_exchange(
        self,
        decision: TradingDecision,
        quantity: float,
        order_id: int,
        idempotency_key: str,
    ) -> None:
        if not self.exchange_client:
            self.logger.warning("submit_to_exchange=True but no exchange client was provided.")
            return

        try:
            self.logger.info(
                "Submitting order %s to exchange %s", order_id, self.exchange_client.id
            )
            response = self.exchange_client.create_order(
                symbol=decision.symbol,
                type="market",
                side=decision.side.value,
                amount=quantity,
            )
            exchange_order_id = response.get("id") or response.get("orderId")
            if exchange_order_id:
                with self.db.cursor() as cursor:
                    cursor.execute(
                        "UPDATE orders SET exchange_order_id = %s WHERE id = %s",
                        (str(exchange_order_id), order_id),
                    )
                self.db.commit()
            self.logger.info(
                "Exchange accepted order %s (exchange_order_id=%s)",
                order_id,
                exchange_order_id,
            )
        except ccxt.BaseError as exc:  # pragma: no cover - network branch
            self.logger.error("Exchange order submission failed: %s", exc)
            self._mark_order_rejected(order_id, reason="EXCHANGE_ERROR")
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Unexpected error while submitting order to exchange: %s", exc)
            self._mark_order_rejected(order_id, reason="UNKNOWN_ERROR")

    def _mark_order_rejected(self, order_id: int, reason: str) -> None:
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    "UPDATE orders SET status = 'REJECTED', updated_at = NOW() WHERE id = %s",
                    (order_id,),
                )
            self.db.commit()
            self.logger.warning("Order %s marked as REJECTED (%s)", order_id, reason)
        except psycopg.Error as exc:
            self.logger.error("Failed to mark order %s as rejected: %s", order_id, exc)
            self.db.rollback()
