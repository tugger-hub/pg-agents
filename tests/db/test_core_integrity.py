"""
M1: Core DB Integrity Tests.
These tests verify the core database constraints and functions as defined in
the DB design documents (e.g., PG_Solo_Lite_Design_DB_v2.0.md).
"""
import os
import pytest
import psycopg
from testcontainers.postgres import PostgresContainer

# --- Test Fixtures ---

@pytest.fixture(scope="module")
def postgres_container():
    """
    Manages a PostgreSQL container for the test module.
    Schema is applied once per module.
    """
    with PostgresContainer("postgres:16-alpine") as container:
        yield container

@pytest.fixture(scope="module")
def db_connection(postgres_container):
    """
    Provides a connection to the test DB and applies the core schema.
    """
    conn_url = postgres_container.get_connection_url()
    with psycopg.connect(conn_url) as connection:
        # Load and apply the core database schema
        current_dir = os.path.dirname(__file__)
        project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
        schema_path = os.path.join(project_root, 'db', 'schema_core.sql')
        with open(schema_path, "r") as f:
            schema_sql = f.read()
            connection.execute(schema_sql)
        connection.commit()
        yield connection

@pytest.fixture(scope="function", autouse=True)
def clean_tables(db_connection):
    """
    Ensures each test function starts with a clean slate by truncating tables.
    """
    with db_connection.cursor() as cursor:
        cursor.execute("""
            TRUNCATE TABLE
                users, accounts, exchanges, instruments, exchange_instruments,
                orders, executions, positions, transactions
            RESTART IDENTITY CASCADE;
        """)
    db_connection.commit()
    yield


@pytest.fixture(scope="function")
def seed_basic_data(db_connection):
    """Seeds the database with a minimal set of data for integrity tests."""
    with db_connection.cursor() as cursor:
        cursor.execute("INSERT INTO users (username) VALUES ('test_user') RETURNING id;")
        user_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO accounts (user_id, name) VALUES (%s, 'test_account') RETURNING id;", (user_id,))
        account_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO exchanges (name) VALUES ('mock_exchange');")
        cursor.execute("INSERT INTO instruments (symbol) VALUES ('BTC/USD') RETURNING id;")
        instrument_id = cursor.fetchone()[0]
        # Seed with trading rules that the normalization trigger will use
        cursor.execute("""
            INSERT INTO exchange_instruments (exchange_id, instrument_id, exchange_symbol, trading_rules)
            VALUES (
                1, %s, 'BTCUSD',
                '{"min_order_size": 0.001, "price_precision": 2, "size_precision": 5, "min_notional_value": 10.0}'
            );
        """, (instrument_id,))
    db_connection.commit()
    return {"account_id": account_id, "exchange_instrument_id": 1}


# --- Integrity Tests ---

def test_transactions_table_is_append_only(db_connection, seed_basic_data):
    """
    Verifies that the `transactions` table cannot be updated or deleted from,
    enforcing the append-only rule via the `trg_transactions_block_ud` trigger.
    """
    # Arrange: Insert a transaction record
    account_id = seed_basic_data["account_id"]
    with db_connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO transactions (account_id, transaction_type, amount) VALUES (%s, 'DEPOSIT', 1000) RETURNING id;",
            (account_id,)
        )
        tx_id = cursor.fetchone()[0]
    db_connection.commit()

    # Act & Assert: Attempt to UPDATE the record and expect an exception
    with pytest.raises(psycopg.errors.RaiseException, match="transactions is append-only"):
        with db_connection.cursor() as cursor:
            cursor.execute("UPDATE transactions SET amount = 2000 WHERE id = %s;", (tx_id,))

    # Act & Assert: Attempt to DELETE the record and expect an exception
    with pytest.raises(psycopg.errors.RaiseException, match="transactions is append-only"):
        with db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM transactions WHERE id = %s;", (tx_id,))


def test_orders_active_idempotency_check(db_connection, seed_basic_data):
    """
    Verifies that the `ux_orders_idem_active` partial unique index prevents
    inserting duplicate active orders with the same idempotency key.
    """
    # Arrange: Common data for the orders
    account_id = seed_basic_data["account_id"]
    exchange_instrument_id = seed_basic_data["exchange_instrument_id"]
    idempotency_key = "test-idem-key-123"
    order_sql = """
    INSERT INTO orders (account_id, exchange_instrument_id, idempotency_key, side, quantity, price, status)
    VALUES (%s, %s, %s, 'buy', 0.01, 50000, 'NEW');
    """

    # Act 1: Insert the first order, which should succeed
    with db_connection.cursor() as cursor:
        cursor.execute(order_sql, (account_id, exchange_instrument_id, idempotency_key))
    db_connection.commit()

    # Act 2 & Assert: Attempt to insert the exact same active order, expecting a unique violation
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db_connection.cursor() as cursor:
            cursor.execute(order_sql, (account_id, exchange_instrument_id, idempotency_key))
    db_connection.rollback() # Rollback the failed transaction

    # Assert that a completed order with the same key CAN be inserted
    completed_order_sql = """
    INSERT INTO orders (account_id, exchange_instrument_id, idempotency_key, side, quantity, price, status)
    VALUES (%s, %s, %s, 'buy', 0.01, 50000, 'FILLED');
    """
    try:
        with db_connection.cursor() as cursor:
            # First, cancel the original active order to avoid other issues
            cursor.execute("UPDATE orders SET status = 'CANCELLED' WHERE idempotency_key = %s;", (idempotency_key,))
            # Now, insert a new, completed order with the same key
            cursor.execute(completed_order_sql, (account_id, exchange_instrument_id, idempotency_key))
        db_connection.commit()
    except psycopg.Error as e:
        pytest.fail(f"Inserting a completed order with a duplicate idempotency key failed unexpectedly: {e}")


def test_order_normalization_and_min_notional_trigger(db_connection, seed_basic_data):
    """
    Verifies that the `trg_orders_normalize` trigger correctly normalizes
    price and size, and rejects orders that don't meet the minimum notional value.
    """
    # Arrange
    account_id = seed_basic_data["account_id"]
    exchange_instrument_id = seed_basic_data["exchange_instrument_id"]
    order_sql = """
    INSERT INTO orders (account_id, exchange_instrument_id, side, quantity, price, status)
    VALUES (%s, %s, 'buy', %s, %s, 'NEW') RETURNING id, price, quantity;
    """

    # --- Test 1: Normalization ---
    # Price has too many decimal places (55123.4567 -> 55123.46)
    # Size has too many decimal places (0.12345678 -> 0.12346)
    with db_connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
        cursor.execute(order_sql, (account_id, exchange_instrument_id, 0.12345678, 55123.4567))
        result = cursor.fetchone()
        db_connection.commit()

    assert result["price"] == pytest.approx(55123.46)
    assert result["quantity"] == pytest.approx(0.12346)


    # --- Test 2: Minimum Notional Value Violation ---
    # The minimum notional is 10.0. This order's notional is ~1.23, so it should fail.
    with pytest.raises(psycopg.errors.RaiseException, match="min notional violation"):
        with db_connection.cursor() as cursor:
            cursor.execute(order_sql, (account_id, exchange_instrument_id, 0.001, 1.23))
    db_connection.rollback()

    # --- Test 3: Minimum Notional Value Success ---
    # This order's notional is ~12.3, which is > 10.0, so it should succeed.
    try:
        with db_connection.cursor() as cursor:
            cursor.execute(order_sql, (account_id, exchange_instrument_id, 0.001, 12300.0))
        db_connection.commit()
    except psycopg.Error as e:
        pytest.fail(f"Order that meets minimum notional failed unexpectedly: {e}")
