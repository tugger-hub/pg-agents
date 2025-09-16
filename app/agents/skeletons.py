"""
Skeleton implementations of the agents described in PG_Solo_Lite_AGENTS.md.

These are placeholders to be filled in with actual logic in later stages.
"""
import logging
from .base import Agent

logger = logging.getLogger(__name__)

class IngestionAgent(Agent):
    """Collects market data."""
    def run(self):
        logger.info("IngestionAgent running...")
        # In the future, this will collect data from a broker API.
        pass

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
