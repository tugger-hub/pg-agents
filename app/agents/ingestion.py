"""Ingestion agent responsible for collecting and persisting market data."""
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Iterable, List, Optional

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

    - Fetches recent OHLCV data for a configured list of symbols.
    - Implements retry logic with exponential backoff for API calls.
    - Stores candles in PostgreSQL using idempotent bulk inserts.
    """

    def __init__(
        self,
        db_session: Session | Callable[[], Session],
        symbols: Iterable[str],
        exchange_id: str = "binance",
        exchange_client: Optional[ccxt.Exchange] = None,
        timeframe: str = "1m",
        ohlcv_limit: int = 200,
    ):
        if isinstance(db_session, Session):
            # Compatibility with legacy callers/tests that pass in a Session instance.
            self._session_factory: Callable[[], Session] = lambda: db_session
            self._manage_session = False
        else:
            # sessionmaker or a factory callable.
            self._session_factory = db_session  # type: ignore[assignment]
            self._manage_session = True

        self.symbols = list(symbols)
        self.exchange_id = exchange_id
        self.timeframe = timeframe
        self.ohlcv_limit = ohlcv_limit
        self.exchange = exchange_client or getattr(ccxt, self.exchange_id)()
        self.exchange.enableRateLimit = True
        self.logger = logging.getLogger(self.__class__.__name__)
        self._trading_rules_cache: dict[str, dict] = {}

    @contextmanager
    def _session_scope(self):
        session = self._session_factory()
        try:
            yield session
            if self._manage_session:
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            if self._manage_session:
                session.close()

    def run(self):
        """The main entry point for the agent's logic."""
        self.logger.info("IngestionAgent running for symbols: %s", self.symbols)
        self._cache_trading_rules()

        with self._session_scope() as session:
            for symbol in self.symbols:
                self.logger.info("Fetching market data for %s...", symbol)
                snapshots = self._fetch_ohlcv_with_retry(
                    symbol, timeframe=self.timeframe, limit=self.ohlcv_limit
                )
                if snapshots:
                    self._save_snapshots_to_db(session, snapshots, timeframe=self.timeframe)
                else:
                    self.logger.error(
                        "Failed to fetch market data for %s after multiple retries.", symbol
                    )

    def _save_snapshots_to_db(
        self, session: Session, snapshots: List[MarketSnapshot], timeframe: str
    ):
        """
        Saves a list of MarketSnapshot objects to the candles table.

        Uses a bulk insert with ON CONFLICT DO NOTHING to efficiently
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

        stmt = pg_insert(Candle).values(insert_values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["symbol", "timeframe", "timestamp"]
        )

        try:
            result = session.execute(stmt)
            if not self._manage_session:
                session.commit()
            self.logger.info(
                "Saved %s new candles to DB for symbol '%s' and timeframe '%s'.",
                result.rowcount,
                snapshots[0].symbol,
                timeframe,
            )
        except Exception as exc:
            self.logger.error("Database error while saving candles: %s", exc)
            session.rollback()

    def _cache_trading_rules(self):
        """
        Fetches and caches trading rules for the symbols.

        For now the data is cached in-memory and primarily used for logging.
        A future enhancement can persist the data to the exchange_instruments table
        so that database triggers have richer metadata.
        """
        try:
            markets = self.exchange.load_markets()
        except Exception as exc:  # pragma: no cover - network branch
            self.logger.warning("Unable to load markets for trading rules cache: %s", exc)
            return

        for symbol in self.symbols:
            market = markets.get(symbol)
            if not market:
                continue
            limits = market.get("limits", {}) or {}
            precision = market.get("precision", {}) or {}
            self._trading_rules_cache[symbol] = {
                "limits": limits,
                "precision": precision,
            }
        self.logger.debug("Cached trading rules for %s symbols", len(self._trading_rules_cache))

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
