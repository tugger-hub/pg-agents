"""
Main entry point for the application.

This script initializes and runs the scheduler, which in turn triggers the agents.
"""
import logging
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from app.log_config import setup_logging
from app.agents.skeletons import (
    IngestionAgent,
    StrategyAgent,
    ExecutionAgent,
    RiskAgent,
    ReportAgent,
)

# Configure logging
setup_logging()
logger = logging.getLogger(__name__)

def main():
    """
    Initializes and starts the agent scheduler.
    """
    logger.info("Initializing scheduler...")
    scheduler = BlockingScheduler()

    # Instantiate agents
    ingestion_agent = IngestionAgent()
    strategy_agent = StrategyAgent()
    execution_agent = ExecutionAgent()
    risk_agent = RiskAgent()
    report_agent = ReportAgent()

    # Schedule agents to run periodically
    # Using a short interval for demonstration purposes
    scheduler.add_job(ingestion_agent.run, 'interval', seconds=10, id='ingestion_agent')
    scheduler.add_job(strategy_agent.run, 'interval', seconds=15, id='strategy_agent')
    scheduler.add_job(execution_agent.run, 'interval', seconds=20, id='execution_agent')
    scheduler.add_job(risk_agent.run, 'interval', seconds=25, id='risk_agent')
    scheduler.add_job(report_agent.run, 'interval', seconds=30, id='report_agent')

    try:
        logger.info("Scheduler started. Press Ctrl+C to exit.")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
        scheduler.shutdown()

if __name__ == "__main__":
    main()
