"""
Main entry point for the application.

This script initializes and runs the scheduler, which in turn triggers the agents.
"""
import logging
import time

import psycopg
from apscheduler.schedulers.blocking import BlockingScheduler

from app.log_config import setup_logging
from app.config import settings
# Import the REAL agents, not the skeletons
from app.agents.execution import ExecutionAgent
from app.agents.risk import RiskAgent
# Skeletons can be used for agents not yet implemented
from app.agents.skeletons import IngestionAgent, StrategyAgent, ReportAgent
from app.agents.notification import NotifyWorker

# Configure logging
setup_logging()
logger = logging.getLogger(__name__)

def main():
    """
    Initializes and starts the agent scheduler.
    """
    logger.info("Initializing scheduler and database connection...")

    try:
        # Establish database connection
        # In a real app, a connection pool would be better.
        db_connection = psycopg.connect(settings.database_url)
        logger.info("Database connection successful.")
    except psycopg.OperationalError as e:
        logger.critical(f"Failed to connect to the database: {e}")
        return

    scheduler = BlockingScheduler()

    # Instantiate agents with db connection and dependencies
    # Note: Using placeholder skeletons for non-implemented agents
    ingestion_agent = IngestionAgent(symbols=["BTC/USDT"]) # Example symbol
    strategy_agent = StrategyAgent()

    # Instantiate the real, functional agents
    execution_agent = ExecutionAgent(db_connection=db_connection)
    risk_agent = RiskAgent(db_connection=db_connection, execution_agent=execution_agent)

    report_agent = ReportAgent()

    # Instantiate the notification worker
    if settings.telegram_bot_token:
        notify_worker = NotifyWorker(db_connection=db_connection)
        scheduler.add_job(notify_worker.run, 'interval', seconds=5, id='notify_worker')
        logger.info("Notification worker has been scheduled.")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Notification worker will not run.")


    # Schedule agents to run periodically
    # Note: The `execution_agent.run` expects a `TradingDecision`, so scheduling it
    # to run on an interval like this is not correct. It should be triggered.
    # We will leave it commented out as per the original design.
    scheduler.add_job(ingestion_agent.run, 'interval', seconds=60, id='ingestion_agent')
    scheduler.add_job(strategy_agent.run, 'interval', seconds=60, id='strategy_agent')
    # scheduler.add_job(execution_agent.run, 'interval', seconds=20, id='execution_agent')
    scheduler.add_job(risk_agent.run, 'interval', seconds=30, id='risk_agent')
    scheduler.add_job(report_agent.run, 'interval', seconds=120, id='report_agent')

    try:
        logger.info("Scheduler started. Press Ctrl+C to exit.")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
        scheduler.shutdown()

if __name__ == "__main__":
    main()
