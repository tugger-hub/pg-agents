"""
Integration tests for the IngestionAgent.

This test suite uses a real PostgreSQL database managed by testcontainers
to verify that the IngestionAgent can correctly fetch data (from a mock exchange)
and save it to the database.
"""
import logging
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.agents.ingestion import IngestionAgent
from app.db_models import Candle
from testcontainers.postgres import PostgresContainer

# Set up logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def postgres_container():
    """Pytest fixture to manage a PostgreSQL container for the test module."""
    with PostgresContainer("postgres:16-alpine") as container:
        logger.info("PostgreSQL container started for IngestionAgent tests.")
        yield container
    logger.info("PostgreSQL container stopped.")


@pytest.fixture(scope="module")
def db_engine_and_schema(postgres_container):
    """
    Module-scoped fixture to set up the DB container, create an engine,
    and apply the schema once.
    """
    conn_str = postgres_container.get_connection_url()
    # The testcontainer for postgres returns a psycopg2-compatible URL by default.
    # We replace it to ensure it works with the modern psycopg v3 driver.
    if conn_str.startswith("postgresql+psycopg2://"):
        conn_str = conn_str.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    engine = create_engine(conn_str)

    # Apply the schema
    current_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
    schema_path = os.path.join(project_root, "db", "schema_core.sql")
    with open(schema_path, "r") as f:
        schema_sql = f.read()
        with engine.connect() as connection:
            connection.execute(text(schema_sql))
            connection.commit()

    logger.info("Database schema applied for module.")
    yield engine


@pytest.fixture(scope="function")
def db_session(db_engine_and_schema):
    """
    Function-scoped fixture to provide a clean database session for each test.
    It truncates the 'candles' table before each test.
    """
    engine = db_engine_and_schema
    connection = engine.connect()
    # Begin a transaction
    trans = connection.begin()

    # Truncate the table to ensure a clean state
    connection.execute(text("TRUNCATE TABLE candles RESTART IDENTITY;"))
    logger.info("Table 'candles' truncated for test isolation.")

    # Create a session
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    # Rollback the transaction and close the connection
    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture
def mock_ccxt_exchange(mocker):
    """Mocks the ccxt exchange object to return controlled data."""
    mock_exchange = MagicMock()
    mock_exchange.has = {"fetchOHLCV": True}

    # Sample OHLCV data: [timestamp_ms, open, high, low, close, volume]
    mock_ohlcv_data = [
        [1672531200000, 100, 110, 90, 105, 1000],  # 2023-01-01 00:00:00
        [1672531260000, 105, 115, 95, 110, 1200],  # 2023-01-01 00:01:00
    ]
    mock_exchange.fetch_ohlcv.return_value = mock_ohlcv_data

    mocker.patch("ccxt.binance", return_value=mock_exchange)
    return mock_exchange


def test_ingestion_agent_saves_candles_to_db(db_session, mock_ccxt_exchange):
    """
    Tests that the IngestionAgent can fetch data from the (mock) exchange
    and correctly save it to the database.
    """
    # Arrange
    agent = IngestionAgent(db_session=db_session, symbols=["BTC/USDT"])

    # Act
    agent.run()

    # Assert
    # Verify that the candles were inserted into the database
    candles_in_db = db_session.execute(select(Candle)).scalars().all()
    assert len(candles_in_db) == 2
    assert candles_in_db[0].symbol == "BTC/USDT"
    assert candles_in_db[0].timeframe == "1m"
    assert candles_in_db[0].open == 100
    assert candles_in_db[1].close == 110
    assert candles_in_db[1].timestamp == datetime(
        2023, 1, 1, 0, 1, 0, tzinfo=timezone.utc
    )


def test_ingestion_agent_is_idempotent(db_session, mock_ccxt_exchange):
    """
    Tests that running the agent multiple times with the same data does not
    create duplicate entries in the database.
    """
    # Arrange
    agent = IngestionAgent(db_session=db_session, symbols=["BTC/USDT"])

    # Act
    # Run the agent the first time
    agent.run()
    candles_after_first_run = db_session.execute(select(Candle)).scalars().all()
    assert len(candles_after_first_run) == 2, "Candles should be inserted on the first run."

    # Run the agent a second time with the exact same mock data
    agent.run()

    # Assert
    # The number of candles should not have changed
    candles_after_second_run = db_session.execute(select(Candle)).scalars().all()
    assert (
        len(candles_after_second_run) == 2
    ), "No new candles should be inserted on the second run."
