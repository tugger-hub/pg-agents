"""
Skeleton implementations of the agents described in PG_Solo_Lite_AGENTS.md.

These are placeholders to be filled in with actual logic in later stages.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from .. import db_utils
from ccxt.base.errors import ExchangeError, NetworkError
from ccxt.async_support import Exchange as CCXTExchange
from ccxt.async_support import exchanges as ccxt_exchanges

from ..models import MarketSnapshot
from .base import Agent

logger = logging.getLogger(__name__)


class IngestionAgent(Agent):
    """
    Collects market data from a cryptocurrency exchange using ccxt.

    - Fetches recent 1-minute OHLCV data for a predefined list of symbols.
    - Implements retry logic with exponential backoff for API calls.
    - Caches trading rules for the symbols.
    """

    def __init__(self, symbols: List[str], exchange_id: str = "binance"):
        self.symbols = symbols
        self.exchange_id = exchange_id
        if self.exchange_id not in ccxt_exchanges:
            raise ValueError(f"Exchange {self.exchange_id} is not supported by ccxt.")

        exchange_class = getattr(
            __import__("ccxt.async_support", fromlist=[self.exchange_id]),
            self.exchange_id,
        )
        self.exchange: CCXTExchange = exchange_class()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._trading_rules_cache = {}

    async def run(self):
        """The main entry point for the agent's async logic."""
        self.logger.info(f"IngestionAgent running for symbols: {self.symbols}")
        try:
            await self._cache_trading_rules()

            for symbol in self.symbols:
                self.logger.info(f"Fetching market data for {symbol}...")
                snapshots = await self._fetch_ohlcv_with_retry(symbol)
                if snapshots:
                    self.logger.info(
                        f"Successfully fetched {len(snapshots)} snapshots for {symbol}."
                    )
                    # Store the snapshots in the database
                    try:
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None, db_utils.insert_candles, snapshots
                        )
                    except Exception as e:
                        self.logger.error(f"Failed to store candles for {symbol} in DB: {e}")
                else:
                    self.logger.error(
                        f"Failed to fetch market data for {symbol} after multiple retries."
                    )
        finally:
            self.logger.info("Closing exchange connection.")
            await self.exchange.close()

    async def _cache_trading_rules(self):
        """
        Fetches and caches trading rules from the database for the specified symbols.
        """
        self.logger.info("Fetching and caching trading rules from database...")
        loop = asyncio.get_running_loop()
        for symbol in self.symbols:
            try:
                # Run the synchronous DB call in a separate thread
                rules = await loop.run_in_executor(
                    None, db_utils.get_trading_rules, symbol
                )
                if rules:
                    self._trading_rules_cache[symbol] = rules
                    self.logger.info(f"Successfully cached trading rules for {symbol}.")
                    self.logger.debug(f"Rules for {symbol}: {rules}")
                else:
                    self.logger.warning(
                        f"Could not find trading rules for symbol {symbol} in the database."
                    )
            except Exception as e:
                self.logger.error(f"Failed to fetch trading rules for {symbol} from DB: {e}")
                # In a real system, we might want to raise this exception
                # or have a fallback mechanism. For now, we log and continue.

    async def _fetch_ohlcv_with_retry(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        max_retries: int = 3,
        initial_delay: int = 2,
    ) -> Optional[List[MarketSnapshot]]:
        """
        Fetches OHLCV data for a symbol with async exponential backoff retry logic.
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
                ohlcv_data = await self.exchange.fetch_ohlcv(
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
            except (NetworkError, ExchangeError) as e:
                self.logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed for {symbol}: {e}. Retrying in {delay}s..."
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    self.logger.error(f"All {max_retries} retries failed for {symbol}.")
                    return None
        return None

class StrategyAgent(Agent):
    """Generates trading decisions based on market data."""
    def run(self):
        logger.info("StrategyAgent running...")
        # In the future, this will analyze data and produce TradingDecision objects.
        pass

class ExecutionAgent(Agent):
    """Executes trades based on trading decisions."""
    def run(self):
        logger.info("ExecutionAgent running...")
        # In the future, this will place orders with the broker.
        pass

class RiskAgent(Agent):
    """Manages risk for open positions."""
    def run(self):
        logger.info("RiskAgent running...")
        # In the future, this will monitor positions and manage stop-losses, etc.
        pass

class ReportAgent(Agent):
    """Generates and sends reports."""
    def run(self):
        logger.info("ReportAgent running...")
        # In the future, this will generate performance reports.
        pass


if __name__ == "__main__":
    # This block is for temporary testing of the IngestionAgent.
    logging.basicConfig(
        level=logging.DEBUG,  # Use DEBUG to see the cached rules
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    async def main():
        # Test the IngestionAgent
        agent = IngestionAgent(symbols=["BTC/USDT", "ETH/USDT"], exchange_id="gateio")
        await agent.run()

    asyncio.run(main())
