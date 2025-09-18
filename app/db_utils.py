"""
Database utility functions for the trading application.
"""
import os
import psycopg2
import logging
from contextlib import contextmanager
from typing import List, Optional, Dict
from .models import MarketSnapshot
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

def get_db_connection_string():
    """
    Retrieves the database connection string from environment variables.
    """
    return os.environ.get("DATABASE_URL", "postgresql://user:password@localhost/dbname")

@contextmanager
def get_db_connection():
    """
    Provides a transactional database connection context.
    """
    conn = None
    try:
        conn = psycopg2.connect(get_db_connection_string())
        yield conn
    except psycopg2.OperationalError as e:
        logger.error(f"Database connection failed: {e}")
        raise
    finally:
        if conn:
            conn.close()

def get_trading_rules(symbol: str) -> Optional[dict]:
    """
    Fetches trading rules for a given symbol from the database.
    """
    logger.info(f"Fetching trading rules for {symbol} from database...")
    query = """
    SELECT ei.trading_rules
    FROM exchange_instruments ei
    JOIN instruments i ON ei.instrument_id = i.id
    WHERE i.symbol = %s;
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (symbol,))
            rules = cur.fetchone()
            if rules:
                return rules[0]
    return None

def get_exchange_instrument_ids(symbols: List[str], exchange_name: str = 'binance') -> Dict[str, int]:
    """
    Retrieves a mapping of symbols to exchange_instrument_ids.
    """
    if not symbols:
        return {}

    logger.debug(f"Fetching exchange_instrument_ids for {len(symbols)} symbols on {exchange_name}...")
    query = """
    SELECT i.symbol, ei.id
    FROM exchange_instruments ei
    JOIN exchanges e ON ei.exchange_id = e.id
    JOIN instruments i ON ei.instrument_id = i.id
    WHERE i.symbol = ANY(%s) AND e.name = %s;
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (symbols, exchange_name))
            return {row[0]: row[1] for row in cur.fetchall()}

def insert_candles(candles: List[MarketSnapshot], timeframe: str = "1m"):
    """
    Inserts a batch of market snapshots (candles) into the database.
    """
    if not candles:
        return

    logger.info(f"Preparing to insert {len(candles)} candles into the database.")
    exchange_name = 'binance'  # This should ideally come from the agent or a config

    # Fetch all instrument IDs in one go
    symbols = list(set(c.symbol for c in candles))
    instrument_id_map = get_exchange_instrument_ids(symbols, exchange_name)

    values_to_insert = []
    for candle in candles:
        instrument_id = instrument_id_map.get(candle.symbol)
        if instrument_id:
            values_to_insert.append((
                instrument_id,
                timeframe,
                candle.timestamp,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume
            ))
        else:
            logger.warning(f"Could not find exchange_instrument_id for {candle.symbol}, skipping candle insertion.")

    if values_to_insert:
        logger.info(f"Inserting {len(values_to_insert)} candles...")
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO candles (exchange_instrument_id, timeframe, timestamp, open, high, low, close, volume)
                    VALUES %s
                    ON CONFLICT (exchange_instrument_id, timeframe, timestamp) DO NOTHING;
                    """,
                    values_to_insert,
                    page_size=100
                )
                conn.commit()
                logger.info(f"Successfully inserted/updated {len(values_to_insert)} candles.")
    else:
        logger.info("No candles to insert after filtering.")
