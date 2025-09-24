"""Main entry point that wires up agents and the scheduler."""
import logging
from typing import Optional

import ccxt
import psycopg
from apscheduler.schedulers.blocking import BlockingScheduler

from app.agents.execution import ExecutionAgent
from app.agents.ingestion import IngestionAgent
from app.agents.kpi import KpiAgent
from app.agents.notification import NotifyWorker
from app.agents.report import ReportAgent
from app.agents.risk import RiskAgent
from app.agents.strategy import StrategyAgent
from app.config import settings
from app.database import SessionLocal
from app.log_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def _build_exchange_client() -> Optional[ccxt.Exchange]:
    cfg = settings.exchange
    try:
        exchange_cls = getattr(ccxt, cfg.id)
    except AttributeError:
        logger.error("Unsupported exchange id '%s'", cfg.id)
        return None

    params = {"enableRateLimit": True}
    if cfg.api_key:
        params["apiKey"] = cfg.api_key
    if cfg.api_secret:
        params["secret"] = cfg.api_secret
    if cfg.api_password:
        params["password"] = cfg.api_password

    client = exchange_cls(params)
    if hasattr(client, "set_sandbox_mode"):
        client.set_sandbox_mode(cfg.sandbox_mode)
    client.enableRateLimit = True
    return client


def main():
    """Initializes and starts the agent scheduler."""
    logger.info("Bootstrapping scheduler and database connections...")

    try:
        db_connection = psycopg.connect(settings.database_url)
        logger.info("Primary database connection ready.")
    except psycopg.OperationalError as exc:
        logger.critical("Failed to connect to the database: %s", exc)
        return

    exchange_client = _build_exchange_client()
    if settings.exchange.enable_live_trading and not exchange_client:
        logger.warning(
            "Live trading requested but no exchange client could be constructed. "
            "Falling back to DB-only mode."
        )

    scheduler = BlockingScheduler()

    ingestion_agent = IngestionAgent(
        db_session=SessionLocal,
        symbols=settings.trading_symbols,
        exchange_id=settings.exchange.id,
        exchange_client=exchange_client,
        timeframe=settings.strategy.timeframes.entry,
    )
    strategy_agent = StrategyAgent(
        db_session=SessionLocal,
        symbols=settings.trading_symbols,
        timeframe=settings.strategy.timeframes.entry,
    )

    execution_agent = ExecutionAgent(
        db_connection=db_connection,
        account_id=1,
        exchange_client=exchange_client,
        submit_to_exchange=settings.exchange.enable_live_trading,
        default_order_size=settings.exchange.default_order_size,
    )
    risk_agent = RiskAgent(
        db_connection=db_connection,
        execution_agent=execution_agent,
        price_timeframe=settings.strategy.timeframes.entry,
        alert_chat_id=settings.notifications.alert_chat_id,
    )
    kpi_agent = KpiAgent(db_connection=db_connection)
    report_agent = ReportAgent(
        db_connection=db_connection,
        report_chat_id=settings.notifications.report_chat_id,
    )

    def trading_cycle():
        logger.debug("Running trading cycle")
        ingestion_agent.run()
        decisions = strategy_agent.run()
        for decision in decisions:
            execution_agent.run(decision)

    scheduler.add_job(trading_cycle, "interval", seconds=60, id="trading_cycle")
    scheduler.add_job(risk_agent.run, "interval", seconds=30, id="risk_agent")
    scheduler.add_job(kpi_agent.run, "interval", minutes=5, id="kpi_agent")
    scheduler.add_job(report_agent.run, "interval", hours=1, id="report_agent")

    if settings.telegram_bot_token:
        notify_worker = NotifyWorker(db_connection=db_connection)
        scheduler.add_job(notify_worker.run, "interval", seconds=5, id="notify_worker")
        logger.info("Notification worker scheduled.")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Notification worker disabled.")

    try:
        logger.info("Scheduler started. Press Ctrl+C to exit.")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by operator.")
    finally:
        logger.info("Shutting down scheduler and closing resources.")
        scheduler.shutdown(wait=False)
        db_connection.close()


if __name__ == "__main__":
    main()
