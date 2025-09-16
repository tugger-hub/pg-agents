import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.agents.ingestion_agent import IngestionAgent
from app.agents.strategy_agent import StrategyAgent
from app.agents.execution_agent import ExecutionAgent
from app.agents.risk_agent import RiskAgent
from app.agents.report_agent import ReportAgent

logger = logging.getLogger(__name__)

async def start_scheduler():
    """
    Initializes and runs the scheduler and agents.
    """
    logger.info("Initializing agents...")
    ingestion_agent = IngestionAgent()
    strategy_agent = StrategyAgent()
    execution_agent = ExecutionAgent()
    risk_agent = RiskAgent()
    report_agent = ReportAgent()

    scheduler = AsyncIOScheduler()

    logger.info("Scheduling agent jobs...")
    # These intervals are placeholders and should be configured properly later.
    scheduler.add_job(ingestion_agent.run, 'interval', seconds=10, id='ingestion_job')
    scheduler.add_job(strategy_agent.run, 'interval', seconds=15, id='strategy_job')
    scheduler.add_job(execution_agent.run, 'interval', seconds=20, id='execution_job')
    scheduler.add_job(risk_agent.run, 'interval', seconds=25, id='risk_job')
    scheduler.add_job(report_agent.run, 'interval', seconds=30, id='report_job')

    scheduler.start()
    logger.info("Scheduler started. Press Ctrl+C to exit.")

    # Keep the scheduler running in the foreground
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
        scheduler.shutdown()
