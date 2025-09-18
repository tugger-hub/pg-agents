"""
Agent responsible for generating and sending performance reports.
"""
import logging
import psycopg
from datetime import datetime

from .base import Agent
from app.models import OpsKpiSnapshot

logger = logging.getLogger(__name__)

# In a real application, this would come from a config or user settings in the DB
DEFAULT_REPORT_CHAT_ID = -1001234567890 # Placeholder Channel ID

class ReportAgent(Agent):
    """
    This agent generates a summary report based on the latest KPI snapshot
    and sends it as a notification.
    """

    def __init__(self, db_connection: psycopg.Connection):
        """
        Initializes the ReportAgent.

        Args:
            db_connection: An active psycopg connection to the database.
        """
        self.db_connection = db_connection
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self):
        """
        The main entry point for the agent's logic.

        It fetches the latest KPI data, formats a report, and enqueues it for
        sending via the notification worker.
        """
        self.logger.info("ReportAgent running...")
        try:
            snapshot = self._fetch_latest_kpi_snapshot()

            if not snapshot:
                self.logger.info("No KPI snapshot found. Skipping report generation.")
                return

            report_message = self._format_report(snapshot)
            self._enqueue_report(report_message)

        except Exception as e:
            self.logger.error(f"An error occurred during report generation: {e}", exc_info=True)

    def _fetch_latest_kpi_snapshot(self) -> OpsKpiSnapshot | None:
        """Fetches the most recent KPI snapshot from the database."""
        self.logger.info("Fetching latest KPI snapshot...")
        with self.db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT ts, order_latency_p50_ms, order_latency_p95_ms,
                       order_failure_rate, order_retry_rate,
                       position_gross_exposure_usd, open_positions_count
                FROM ops_kpi_snapshots
                ORDER BY ts DESC
                LIMIT 1;
            """)
            row = cursor.fetchone()
            if row:
                self.logger.info(f"Found KPI snapshot from: {row[0]}")
                return OpsKpiSnapshot(
                    ts=row[0],
                    order_latency_p50_ms=row[1],
                    order_latency_p95_ms=row[2],
                    order_failure_rate=row[3],
                    order_retry_rate=row[4],
                    position_gross_exposure_usd=row[5],
                    open_positions_count=row[6],
                )
        return None

    def _format_report(self, snapshot: OpsKpiSnapshot) -> str:
        """Formats the KPI data into a human-readable string."""
        self.logger.info("Formatting KPI report...")
        report_lines = [
            f"📊 *Operational Report* ({snapshot.ts.strftime('%Y-%m-%d %H:%M Z')})",
            "---------------------------",
            f"🚀 **Execution**",
            f"  - P50 Latency: {snapshot.order_latency_p50_ms} ms",
            f"  - P95 Latency: {snapshot.order_latency_p95_ms} ms",
            f"  - Failure Rate: {snapshot.order_failure_rate:.2%}",
            "",
            f"💼 **Portfolio**",
            f"  - Open Positions: {snapshot.open_positions_count}",
            f"  - Gross Exposure: ${snapshot.position_gross_exposure_usd:,.2f} USD",
        ]
        return "\n".join(report_lines)

    def _enqueue_report(self, message: str):
        """
        Enqueues the report message in the notification outbox.
        """
        self.logger.info(f"Enqueuing report for chat_id: {DEFAULT_REPORT_CHAT_ID}")
        with self.db_connection.cursor() as cursor:
            # Use the enqueue_notification function in the DB
            cursor.execute(
                "SELECT enqueue_notification(%s, %s, %s, %s, %s);",
                (
                    DEFAULT_REPORT_CHAT_ID,
                    'INFO', # severity
                    'Daily KPI Report', # title
                    message,
                    f"kpi-report-{datetime.utcnow().strftime('%Y-%m-%d')}" # dedupe_key
                ),
            )
            self.db_connection.commit()
            self.logger.info("Successfully enqueued report.")
