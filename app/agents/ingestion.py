"""
The IngestionAgent is responsible for collecting market data from exchanges.
"""
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import ccxt
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..db_models import Candle
from ..models import MarketSnapshot
from .base import Agent

logger = logging.getLogger(__name__)


class IngestionAgent(Agent):
    """
    Collects market data from a cryptocurrency exchange using ccxt.

    - Fetches recent 1-minute OHLCV data for a predefined list of symbols.
    - Implements retry logic with exponential backoff for API calls.
    - Caches trading rules for the symbols (placeholder).
    """

    def __init__(
        self, db_session: Session, symbols: List[str], exchange_id: str = "binance"
    ):
        self.db_session = db_session
        self.symbols = symbols
        self.exchange_id = exchange_id
        self.exchange = getattr(ccxt, self.exchange_id)()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._trading_rules_cache = {}

    def run(self):
        """The main entry point for the agent's logic."""
        self.logger.info(f"IngestionAgent running for symbols: {self.symbols}")
        self._cache_trading_rules()

        for symbol in self.symbols:
            self.logger.info(f"Fetching market data for {symbol}...")
            snapshots = self._fetch_ohlcv_with_retry(symbol, timeframe="1m", limit=200)
            if snapshots:
                self._save_snapshots_to_db(snapshots, timeframe="1m")
            else:
                self.logger.error(
                    f"Failed to fetch market data for {symbol} after multiple retries."
                )

    def _save_snapshots_to_db(
        self, snapshots: List[MarketSnapshot], timeframe: str
    ):
        """
        Saves a list of MarketSnapshot objects to the candles table.

        This method uses a bulk insert with ON CONFLICT DO NOTHING to efficiently
        insert new candles while ignoring duplicates.
        """
        if not snapshots:
            return

        insert_values = [
            {
                "symbol": s.symbol,
                "timeframe": timeframe,
                "timestamp": s.timestamp,
                "open": s.open,
                "high": s.high,
                "low": s.low,
                "close": s.close,
                "volume": s.volume,
            }
            for s in snapshots
        ]

        # Use PostgreSQL's ON CONFLICT DO NOTHING for idempotent inserts
        stmt = pg_insert(Candle).values(insert_values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["symbol", "timeframe", "timestamp"]
        )

        try:
            result = self.db_session.execute(stmt)
            self.db_session.commit()
            # The number of rows actually inserted might be useful.
            # result.rowcount gives the number of rows affected.
            self.logger.info(
                f"Saved {result.rowcount} new candles to DB for symbol "
                f"'{snapshots[0].symbol}' and timeframe '{timeframe}'."
            )
        except Exception as e:
            self.logger.error(f"Database error while saving candles: {e}")
            self.db_session.rollback()

    def _cache_trading_rules(self):
        """
        Fetches and caches trading rules for the symbols.

        Placeholder as per M3 requirements. In a real implementation, this would
        fetch rules from the exchange and store them, potentially in the
        `exchange_instruments` table or an in-memory cache.
        """
        self.logger.info("Caching trading rules (placeholder)...")
        # Example: self._trading_rules_cache = self.exchange.load_markets()
        pass

    def _fetch_ohlcv_with_retry(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 10,
        max_retries: int = 3,
        initial_delay: int = 2,
    ) -> Optional[List[MarketSnapshot]]:
        """
        Fetches OHLCV data for a symbol with exponential backoff retry logic.
        """
        delay = initial_delay
        for attempt in range(max_retries):
            try:
                if not self.exchange.has["fetchOHLCV"]:
                    self.logger.warning(
                        f"Exchange {self.exchange_id} does not support fetchOHLCV."
                    )
                    return None

                # Fetch OHLCV data: [timestamp, open, high, low, close, volume]
                ohlcv_data = self.exchange.fetch_ohlcv(
                    symbol, timeframe=timeframe, limit=limit
                )

                snapshots = [
                    MarketSnapshot(
                        symbol=symbol,
                        timestamp=datetime.fromtimestamp(data[0] / 1000, tz=timezone.utc),
                        open=data[1],
                        high=data[2],
                        low=data[3],
                        close=data[4],
                        volume=data[5],
                    )
                    for data in ohlcv_data
                ]
                return snapshots
            except (ccxt.NetworkError, ccxt.ExchangeError) as e:
                self.logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed for {symbol}: {e}. Retrying in {delay}s..."
                )
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    self.logger.error(f"All {max_retries} retries failed for {symbol}.")
                    return None
        return None
