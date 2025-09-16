"""
Integration tests for the ExecutionAgent, using a real PostgreSQL database
managed by testcontainers.
"""
import logging
import os
import pytest
import psycopg
from testcontainers.postgres import PostgresContainer

from app.agents.execution import ExecutionAgent
from app.models import TradingDecision, TradeSide

# Set up logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.fixture(scope="module")
def postgres_container():
    """
    Pytest fixture to manage a PostgreSQL container for the test module.
    The container is started once and torn down after all tests in the module run.
    """
    with PostgresContainer("postgres:16-alpine") as container:
        logger.info("PostgreSQL container started.")
        yield container
    logger.info("PostgreSQL container stopped.")

@pytest.fixture(scope="module")
def db_connection_and_schema(postgres_container):
    """
    Module-scoped fixture to set up the DB container and apply the schema once.
    """
    conn_info = postgres_container.get_connection_url()
    conn_str = conn_info.replace("postgresql+psycopg2://", "postgresql://")
    with psycopg.connect(conn_str) as connection:
        logger.info("Database connection established for module setup.")
        current_dir = os.path.dirname(__file__)
        project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
        schema_path = os.path.join(project_root, 'db', 'schema_core.sql')
        with open(schema_path, "r") as f:
            schema_sql = f.read()
            connection.execute(schema_sql)
        connection.commit()
        logger.info("Database schema applied for module.")
        yield connection

@pytest.fixture(scope="function")
def db_connection(db_connection_and_schema):
    """
    Function-scoped fixture to clean and seed the DB for each test.
    This ensures test isolation.
    """
    connection = db_connection_and_schema
    with connection.cursor() as cursor:
        # Truncate tables to ensure a clean state for each test.
        # CASCADE drops dependent objects and RESTART IDENTITY resets sequences.
        logger.info("Truncating tables for test isolation.")
        cursor.execute("""
            TRUNCATE TABLE
                orders, transactions, positions, exchange_instruments,
                instruments, accounts, users, notification_outbox, telegram_chats,
                exchanges
            RESTART IDENTITY CASCADE;
        """)
    connection.commit()

    # Seed the database with necessary data for this specific test
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO users (username) VALUES ('testuser') RETURNING id;")
        user_id = cursor.fetchone()[0]

        cursor.execute("INSERT INTO accounts (user_id, name) VALUES (%s, 'test_account') RETURNING id;", (user_id,))
        account_id = cursor.fetchone()[0]

        cursor.execute("INSERT INTO exchanges (name) VALUES ('test_exchange');")

        cursor.execute("INSERT INTO instruments (symbol) VALUES ('BTC/USDT') RETURNING id;")
        instrument_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO exchange_instruments (exchange_id, instrument_id, exchange_symbol)
            VALUES (1, %s, 'BTCUSDT');
        """, (instrument_id,))

    connection.commit()
    logger.info("Database seeded for test.")

    yield connection

        # Teardown (e.g., clearing tables) is handled by the function-level scope
        # of the fixture and the fresh container for each module.

def count_orders(db_connection) -> int:
    """Helper function to count the number of orders in the database."""
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM orders;")
        return cursor.fetchone()[0]

def test_execution_agent_inserts_first_order_successfully(db_connection):
    """
    Tests that the ExecutionAgent can successfully insert a new order when none exists.
    """
    # Arrange
    agent = ExecutionAgent(db_connection=db_connection, account_id=1)
    decision = TradingDecision(
        symbol="BTC/USDT",
        side=TradeSide.BUY,
        sl=60000.0,
        tp=70000.0,
        confidence=0.85,
    )

    # Act
    agent.run(decision)

    # Assert
    assert count_orders(db_connection) == 1

def test_duplicate_decision_is_suppressed_by_idempotency(db_connection, caplog):
    """
    Tests the core M5 requirement: a duplicate trading decision within the
    idempotency window does not create a second order.
    """
    # Arrange
    agent = ExecutionAgent(db_connection=db_connection, account_id=1)
    decision = TradingDecision(
        symbol="BTC/USDT",
        side=TradeSide.BUY,
        sl=60000.0,
        tp=70000.0,
        confidence=0.85,
    )

    # Act
    # First call - should succeed
    agent.run(decision)
    assert count_orders(db_connection) == 1, "The first order should be created."

    # Second call with the exact same decision - should be suppressed
    agent.run(decision)

    # Assert
    assert count_orders(db_connection) == 1, "The duplicate order should be suppressed."

    # Assert that the suppression was logged
    assert "Duplicate order detected" in caplog.text
    assert "The order has already been processed. Suppressing." in caplog.text

@pytest.fixture(scope="function")
def db_connection_with_failing_notional_check(db_connection):
    """
    Fixture that modifies the `meets_min_notional` function in the database
    to always return FALSE, simulating a failed notional value check.
    """
    with db_connection.cursor() as cursor:
        # Override the function for this test's transaction
        cursor.execute("""
        CREATE OR REPLACE FUNCTION meets_min_notional(p_exchange_instrument_id INT, p_price NUMERIC, p_quantity NUMERIC)
        RETURNS BOOLEAN AS $$
        BEGIN
            RETURN FALSE; -- Force failure
        END;
        $$ LANGUAGE plpgsql;
        """)
    db_connection.commit()
    logger.info("Database function `meets_min_notional` overridden to fail.")
    yield db_connection

def test_order_failing_min_notional_check_is_rejected(db_connection_with_failing_notional_check, caplog):
    """
    Tests that an order is rejected if the database trigger for minimum
    notional value fails.
    """
    # Arrange
    agent = ExecutionAgent(db_connection=db_connection_with_failing_notional_check, account_id=1)
    decision = TradingDecision(
        symbol="BTC/USDT",
        side=TradeSide.SELL,
        sl=70000.0,
        tp=60000.0,
        confidence=0.9,
    )

    # Act
    agent.run(decision)

    # Assert
    # Check that no order was created
    assert count_orders(db_connection_with_failing_notional_check) == 0

    # Check that the rejection was logged correctly
    assert "Order rejected by database trigger" in caplog.text
    # The specific error message from the trigger in schema_core.sql
    assert "min notional violation" in caplog.text
