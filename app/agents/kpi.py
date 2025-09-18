"""
Agent responsible for calculating and storing KPI snapshots.
"""
import logging
import psycopg

from .base import Agent
from app.kpi.services import calculate_all_kpis

logger = logging.getLogger(__name__)

class KpiAgent(Agent):
    """
    This agent periodically calculates operational KPIs and saves them to the
    database.
    """

    def __init__(self, db_connection: psycopg.Connection):
        """
        Initializes the KpiAgent.

        Args:
            db_connection: An active psycopg connection to the database.
        """
        self.db_connection = db_connection
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self):
        """
        The main entry point for the agent's logic.

        It calculates KPIs and writes them to the `ops_kpi_snapshots` table.
        """
        self.logger.info("KpiAgent running...")
        try:
            # 1. Calculate KPIs using the service
            kpi_snapshot = calculate_all_kpis(self.db_connection)

            # 2. Save the snapshot to the database
            with self.db_connection.cursor() as cursor:
                insert_query = """
                    INSERT INTO ops_kpi_snapshots (
                        ts, order_latency_p50_ms, order_latency_p95_ms,
                        order_failure_rate, order_retry_rate,
                        position_gross_exposure_usd, open_positions_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ts) DO NOTHING;
                """
                cursor.execute(
                    insert_query,
                    (
                        kpi_snapshot.ts,
                        kpi_snapshot.order_latency_p50_ms,
                        kpi_snapshot.order_latency_p95_ms,
                        kpi_snapshot.order_failure_rate,
                        kpi_snapshot.order_retry_rate,
                        kpi_snapshot.position_gross_exposure_usd,
                        kpi_snapshot.open_positions_count,
                    ),
                )
                self.db_connection.commit()
                self.logger.info(f"Successfully saved KPI snapshot for ts: {kpi_snapshot.ts}")

        except Exception as e:
            self.logger.error(f"An error occurred during KPI processing: {e}", exc_info=True)
            # In a real app, you might want to rollback the transaction
            self.db_connection.rollback()
