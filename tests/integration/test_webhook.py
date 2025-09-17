import logging
import os
from unittest.mock import patch

import psycopg
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

# Set up logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Fixtures ---

@pytest.fixture(scope="module")
def postgres_container():
    """Module-scoped fixture for a PostgreSQL container."""
    with PostgresContainer("postgres:16-alpine") as container:
        logger.info("PostgreSQL container started for webhook tests.")
        yield container
    logger.info("PostgreSQL container stopped.")


@pytest.fixture(scope="module")
def db_connection(postgres_container):
    """
    Module-scoped fixture to establish a DB connection.
    Schema will be applied once per module.
    """
    conn_url = postgres_container.get_connection_url()
    test_db_url = conn_url.replace("postgresql+psycopg2://", "postgresql://")

    # We need to set the environment variable *before* the app and settings are loaded.
    # We will do this in the client fixture. For now, just create a connection.
    os.environ["DATABASE_URL_FOR_TESTS"] = test_db_url
    os.environ["WEBHOOK_SECRET_TOKEN_FOR_TESTS"] = "test_secret_token"

    with psycopg.connect(test_db_url) as connection:
        logger.info("Database connection established for module setup.")
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

        with open(os.path.join(project_root, 'db', 'schema_core.sql'), "r") as f:
            connection.execute(f.read())
        with open(os.path.join(project_root, 'db', 'schema_plus_options.sql'), "r") as f:
            connection.execute(f.read())

        connection.commit()
        logger.info("Both core and options schemas applied.")
        yield connection


@pytest.fixture(scope="function")
def test_db_and_client(db_connection, monkeypatch):
    """
    Function-scoped fixture to provide a clean DB and a configured test client.
    """
    # 1. Patch environment variables for settings
    monkeypatch.setenv("DATABASE_URL", os.environ["DATABASE_URL_FOR_TESTS"])
    monkeypatch.setenv("WEBHOOK_SECRET_TOKEN", os.environ["WEBHOOK_SECRET_TOKEN_FOR_TESTS"])

    # 2. Clear settings cache to force reload
    from app.config import get_settings
    get_settings.cache_clear()

    # 3. Truncate tables for test isolation
    with db_connection.cursor() as cursor:
        logger.info("Truncating tables for test isolation.")
        cursor.execute("""
            TRUNCATE TABLE
                inbound_alerts, inbound_dedupe_keys, orders, transactions, positions,
                exchange_instruments, instruments, accounts, users, notification_outbox,
                telegram_chats, exchanges
            RESTART IDENTITY CASCADE;
        """)

    # 4. Seed necessary data
    with db_connection.cursor() as cursor:
        cursor.execute("INSERT INTO users (username) VALUES ('testuser') RETURNING id;")
        user_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO accounts (user_id, name) VALUES (%s, 'test_account') RETURNING id;", (user_id,))
        cursor.execute("INSERT INTO exchanges (name) VALUES ('test_exchange');")
        cursor.execute("INSERT INTO instruments (symbol) VALUES ('BTC/USDT') RETURNING id;")
        instrument_id = cursor.fetchone()[0]
        cursor.execute("""
            INSERT INTO exchange_instruments (exchange_id, instrument_id, exchange_symbol)
            VALUES (1, %s, 'BTCUSDT');
        """, (instrument_id,))
        cursor.execute("UPDATE system_configuration SET is_trading_enabled = TRUE WHERE id = 1;")

    db_connection.commit()
    logger.info("Database seeded for test.")

    # 5. Create the test client
    from app.main import app
    with TestClient(app) as client:
        yield db_connection, client


# --- Helper Functions ---

def count_rows(db_conn, table_name) -> int:
    with db_conn.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
        return cursor.fetchone()[0]


# --- Tests ---

def test_webhook_success_creates_order(test_db_and_client):
    db_conn, client = test_db_and_client
    headers = {"X-Auth-Token": "test_secret_token"}
    payload = {
        "symbol": "BTC/USDT", "side": "buy", "qty": 0.01, "price": 65000.0,
        "ts": "2025-09-17T10:00:00Z", "strategy": "test_strategy_v1", "idempotency_key": "tv_unique_key_123"
    }

    response = client.post("/webhook/tradingview", headers=headers, json=payload)

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["status"] == "ok"
    assert response_data["key"] == "tv_unique_key_123"
    assert response_data["order_id"] is not None

    assert count_rows(db_conn, "orders") == 1
    assert count_rows(db_conn, "inbound_alerts") == 1
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT parsed, error FROM inbound_alerts WHERE dedupe_key = %s;", ("tv_unique_key_123",))
        parsed, error = cursor.fetchone()
        assert parsed is True
        assert error is None

def test_webhook_rejects_invalid_token(test_db_and_client):
    db_conn, client = test_db_and_client
    headers = {"X-Auth-Token": "wrong_token"}
    payload = {"symbol": "BTC/USDT", "side": "buy", "qty": 0.01, "price": 65000.0, "ts": "2025-09-17T10:00:00Z", "strategy": "s1", "idempotency_key": "key1"}
    response = client.post("/webhook/tradingview", headers=headers, json=payload)
    assert response.status_code == 401
    assert count_rows(db_conn, "orders") == 0

def test_webhook_handles_duplicate_event(test_db_and_client):
    db_conn, client = test_db_and_client
    headers = {"X-Auth-Token": "test_secret_token"}
    payload = {
        "symbol": "BTC/USDT", "side": "buy", "qty": 0.01, "price": 65000.0,
        "ts": "2025-09-17T10:00:00Z", "strategy": "s1", "idempotency_key": "duplicate_key"
    }
    response1 = client.post("/webhook/tradingview", headers=headers, json=payload)
    assert response1.status_code == 200
    assert count_rows(db_conn, "orders") == 1
    response2 = client.post("/webhook/tradingview", headers=headers, json=payload)
    assert response2.status_code == 200
    assert response2.json()["status"] == "duplicate"
    assert count_rows(db_conn, "orders") == 1

def test_webhook_rejects_invalid_payload(test_db_and_client):
    db_conn, client = test_db_and_client
    headers = {"X-Auth-Token": "test_secret_token"}
    payload = {
        "symbol": "BTC/USDT", "qty": 0.01, "price": 65000.0,
        "ts": "2025-09-17T10:00:00Z", "strategy": "s1", "idempotency_key": "invalid_payload_key"
    }
    response = client.post("/webhook/tradingview", headers=headers, json=payload)
    assert response.status_code == 422
    assert count_rows(db_conn, "orders") == 0
